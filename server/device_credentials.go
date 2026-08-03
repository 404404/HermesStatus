package main

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
	"golang.org/x/sys/unix"
)

const (
	maxCredentialFileBytes            = 64 << 10
	deviceTokenBytes                  = 43
	maxDeviceAuthorizationHeaderBytes = 512
	fixedDeviceCredentialCompareSlots = 2
)

var dummyDeviceCredentialDigest = sha256.Sum256(
	[]byte("HermesStatus fixed dummy device credential digest"),
)

type deviceCredentialSlot struct {
	ID        string
	Digest    [sha256.Size]byte
	NotBefore time.Time
	NotAfter  time.Time
}

type deviceCredentialSet struct {
	DeviceID string
	Slots    []deviceCredentialSlot
}

type authenticatedDevice struct {
	DeviceID string
	SlotID   string
}

func (a *App) configureDeviceEndpoint() error {
	a.deviceEndpointEnabled = false
	a.deviceCredentials = make(map[string]deviceCredentialSet)

	prefixes, err := parseTrustedProxyPrefixes(a.opts.TrustedProxyMode, a.opts.TrustedProxyCIDRs)
	if err != nil {
		return errors.New("device endpoint trusted proxy configuration is invalid")
	}
	a.trustedProxyPrefixes = prefixes

	preAuthLimit := a.opts.PreAuthRateLimit
	if preAuthLimit <= 0 {
		preAuthLimit = 120
	}
	deviceLimit := a.opts.DeviceRateLimit
	if deviceLimit <= 0 {
		deviceLimit = 120
	}
	a.preAuthLimiter = newBoundedRateLimiter(2048, preAuthLimit, time.Minute, 10*time.Minute)
	a.deviceLimiter = newBoundedRateLimiter(contracts.MaxDevices, deviceLimit, time.Minute, 10*time.Minute)

	if a.opts.DeviceCredentialsDir == "" {
		if a.opts.DeviceEndpointEnabled {
			return errors.New("device endpoint credential configuration is unavailable")
		}
		return nil
	}
	if a.registry == nil {
		return errors.New("device endpoint registry configuration is unavailable")
	}
	credentials, err := loadDeviceCredentialDirectory(a.opts.DeviceCredentialsDir, a.registry)
	if err != nil {
		return errors.New("device endpoint credential configuration is invalid")
	}
	if a.opts.DeviceEndpointEnabled {
		if err := validateRequiredDeviceCredentials(credentials, a.registry, time.Now()); err != nil {
			return errors.New("device endpoint credential configuration is incomplete")
		}
	}
	a.deviceCredentials = credentials
	a.deviceEndpointEnabled = a.opts.DeviceEndpointEnabled
	return nil
}

func loadDeviceCredentialDirectory(
	directoryPath string,
	registry *contracts.DeviceRegistry,
) (map[string]deviceCredentialSet, error) {
	return loadDeviceCredentialDirectoryWithHooks(directoryPath, registry, nil)
}

func loadDeviceCredentialDirectoryWithHooks(
	directoryPath string,
	registry *contracts.DeviceRegistry,
	hooks *securePathTraversalHooks,
) (map[string]deviceCredentialSet, error) {
	if registry == nil || !filepath.IsAbs(directoryPath) ||
		filepath.Clean(directoryPath) != directoryPath {
		return nil, errors.New("credential directory is invalid")
	}
	directoryFD, err := openDirectoryWithoutSymlinksWithHooks(
		directoryPath,
		hooks,
	)
	if err != nil {
		return nil, errors.New("credential directory is unavailable")
	}
	directory := os.NewFile(uintptr(directoryFD), "device-credentials")
	if directory == nil {
		_ = unix.Close(directoryFD)
		return nil, errors.New("credential directory is unavailable")
	}
	defer directory.Close()

	entries, err := directory.ReadDir(-1)
	if err != nil {
		return nil, errors.New("credential directory is unavailable")
	}
	if len(entries) > contracts.MaxRegisteredDevices {
		return nil, errors.New("credential directory exceeds the registered device limit")
	}
	registryDevices := make(map[string]contracts.RegistryDevice, len(registry.Devices))
	for _, device := range registry.Devices {
		registryDevices[device.ID] = device
	}
	loaded := make(map[string]deviceCredentialSet, len(entries))
	for _, entry := range entries {
		name := entry.Name()
		if name == "" || name == "." || name == ".." || strings.ContainsAny(name, `/\`) ||
			!strings.HasSuffix(name, ".json") {
			return nil, errors.New("credential directory contains an invalid entry")
		}
		deviceID := strings.TrimSuffix(name, ".json")
		if !contracts.ValidateDeviceID(deviceID) || name != deviceID+".json" {
			return nil, errors.New("credential file name is invalid")
		}
		if _, exists := registryDevices[deviceID]; !exists {
			return nil, errors.New("credential identifies an unknown device")
		}
		if _, duplicate := loaded[deviceID]; duplicate {
			return nil, errors.New("credential file is duplicated")
		}
		if entry.Type()&os.ModeSymlink != 0 || entry.IsDir() {
			return nil, errors.New("credential entry is not a regular file")
		}
		data, err := readCredentialAt(directoryFD, name)
		if err != nil {
			return nil, err
		}
		record, err := contracts.DecodeCredentialRecord(data)
		if err != nil || record.DeviceID != deviceID {
			return nil, errors.New("credential record is invalid")
		}
		credentialSet, err := compileCredentialRecord(*record)
		if err != nil {
			return nil, err
		}
		loaded[deviceID] = credentialSet
	}
	return loaded, nil
}

func readCredentialAt(directoryFD int, name string) ([]byte, error) {
	fileFD, err := unix.Openat(
		directoryFD,
		name,
		unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW|unix.O_NONBLOCK,
		0,
	)
	if err != nil {
		return nil, errors.New("credential file is unavailable")
	}
	file := os.NewFile(uintptr(fileFD), "device-credential")
	if file == nil {
		_ = unix.Close(fileFD)
		return nil, errors.New("credential file is unavailable")
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() ||
		info.Mode().Perm()&0o022 != 0 ||
		info.Size() > maxCredentialFileBytes {
		return nil, errors.New("credential file is invalid")
	}
	data, err := io.ReadAll(io.LimitReader(file, maxCredentialFileBytes+1))
	if err != nil || len(data) > maxCredentialFileBytes {
		return nil, errors.New("credential file is invalid")
	}
	return data, nil
}

func compileCredentialRecord(record contracts.CredentialRecord) (deviceCredentialSet, error) {
	result := deviceCredentialSet{
		DeviceID: record.DeviceID,
		Slots:    make([]deviceCredentialSlot, 0, len(record.Credentials)),
	}
	seenDigests := make(map[[sha256.Size]byte]bool, len(record.Credentials))
	for _, credential := range record.Credentials {
		digestBytes, err := hex.DecodeString(credential.Digest)
		if err != nil || len(digestBytes) != sha256.Size {
			return deviceCredentialSet{}, errors.New("credential digest is invalid")
		}
		var digest [sha256.Size]byte
		copy(digest[:], digestBytes)
		if seenDigests[digest] {
			return deviceCredentialSet{}, errors.New("credential digest is duplicated")
		}
		seenDigests[digest] = true
		notBefore, beforeErr := time.Parse(time.RFC3339, credential.NotBefore)
		notAfter, afterErr := time.Parse(time.RFC3339, credential.NotAfter)
		if beforeErr != nil || afterErr != nil {
			return deviceCredentialSet{}, errors.New("credential time is invalid")
		}
		result.Slots = append(result.Slots, deviceCredentialSlot{
			ID: credential.ID, Digest: digest,
			NotBefore: notBefore, NotAfter: notAfter,
		})
	}
	return result, nil
}

func validateRequiredDeviceCredentials(
	credentials map[string]deviceCredentialSet,
	registry *contracts.DeviceRegistry,
	now time.Time,
) error {
	for _, device := range registry.Devices {
		if device.Enabled == nil || !*device.Enabled ||
			!contracts.OwnershipAllows(device.Ingestion, "device_v2", now) {
			continue
		}
		if !validDeviceHeaderID(device.ID) {
			return errors.New("required device identity is unavailable")
		}
		credentialSet, exists := credentials[device.ID]
		if !exists || !credentialSetHasActiveSlot(credentialSet, now) {
			return errors.New("required credential is unavailable")
		}
	}
	return nil
}

func validDeviceHeaderID(value string) bool {
	return contracts.ValidateDeviceID(value) && net.ParseIP(value) == nil
}

func credentialSetHasActiveSlot(credentials deviceCredentialSet, now time.Time) bool {
	for _, slot := range credentials.Slots {
		if !now.Before(slot.NotBefore) && now.Before(slot.NotAfter) {
			return true
		}
	}
	return false
}

func authenticateDeviceBearer(
	headerValues []string,
	credentials deviceCredentialSet,
	now time.Time,
) (authenticatedDevice, bool) {
	authenticated, ok, _ := authenticateDeviceBearerWithCompareCount(
		headerValues, credentials, now,
	)
	return authenticated, ok
}

func authenticateDeviceBearerWithCompareCount(
	headerValues []string,
	credentials deviceCredentialSet,
	now time.Time,
) (authenticatedDevice, bool, int) {
	token, ok := parseDeviceBearer(headerValues)
	if !ok {
		return authenticatedDevice{}, false, 0
	}
	digest := sha256.Sum256([]byte(token))
	matched := 0
	slotID := ""
	for index := 0; index < fixedDeviceCredentialCompareSlots; index++ {
		candidateDigest := dummyDeviceCredentialDigest
		activeInt := 0
		candidateSlotID := ""
		if index < len(credentials.Slots) {
			slot := credentials.Slots[index]
			candidateDigest = slot.Digest
			candidateSlotID = slot.ID
			if !now.Before(slot.NotBefore) && now.Before(slot.NotAfter) {
				activeInt = 1
			}
		}
		equal := subtle.ConstantTimeCompare(digest[:], candidateDigest[:])
		slotMatch := equal & activeInt
		matched |= slotMatch
		if slotMatch == 1 {
			slotID = candidateSlotID
		}
	}
	if matched != 1 {
		return authenticatedDevice{}, false, fixedDeviceCredentialCompareSlots
	}
	return authenticatedDevice{
		DeviceID: credentials.DeviceID,
		SlotID:   slotID,
	}, true, fixedDeviceCredentialCompareSlots
}

func parseDeviceBearer(headerValues []string) (string, bool) {
	totalBytes := 0
	for _, value := range headerValues {
		totalBytes += len(value)
		if totalBytes > maxDeviceAuthorizationHeaderBytes {
			return "", false
		}
	}
	if len(headerValues) != 1 {
		return "", false
	}
	value := headerValues[0]
	if len(value) > maxDeviceAuthorizationHeaderBytes ||
		len(value) != len("Bearer ")+deviceTokenBytes {
		return "", false
	}
	separator := strings.IndexByte(value, ' ')
	if separator != len("Bearer") || !strings.EqualFold(value[:separator], "Bearer") {
		return "", false
	}
	token := value[separator+1:]
	if len(token) != deviceTokenBytes {
		return "", false
	}
	for index := 0; index < len(token); index++ {
		character := token[index]
		if !((character >= 'A' && character <= 'Z') ||
			(character >= 'a' && character <= 'z') ||
			(character >= '0' && character <= '9') ||
			character == '_' || character == '-') {
			return "", false
		}
	}
	return token, true
}

func parseTrustedProxyPrefixes(enabled bool, value string) ([]netip.Prefix, error) {
	if !enabled {
		if strings.TrimSpace(value) != "" {
			return nil, errors.New("trusted proxy list requires trusted proxy mode")
		}
		return nil, nil
	}
	parts := strings.Split(value, ",")
	if len(parts) == 0 || len(parts) > 64 {
		return nil, errors.New("trusted proxy list is invalid")
	}
	prefixes := make([]netip.Prefix, 0, len(parts))
	for _, raw := range parts {
		item := strings.TrimSpace(raw)
		if item == "" {
			return nil, errors.New("trusted proxy list is invalid")
		}
		if address, err := netip.ParseAddr(item); err == nil {
			address = address.Unmap()
			bits := 32
			if address.Is6() {
				bits = 128
			}
			prefixes = append(prefixes, netip.PrefixFrom(address, bits))
			continue
		}
		prefix, err := netip.ParsePrefix(item)
		if err != nil {
			return nil, fmt.Errorf("trusted proxy list is invalid")
		}
		prefixes = append(prefixes, prefix.Masked())
	}
	return prefixes, nil
}
