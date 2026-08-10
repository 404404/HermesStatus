package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"sort"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
	"golang.org/x/sys/unix"
)

const maxPersistenceBytes = 8 << 20

var errOrphanLimitExceeded = errors.New("orphan_limit_exceeded")

func writePersistenceV2(path string, snapshot contracts.PersistenceV2) error {
	if err := contracts.ValidatePersistenceV2(&snapshot); err != nil {
		return errors.New("multi-device state is invalid")
	}
	data, err := marshalIndented(snapshot)
	if err != nil {
		return err
	}
	if len(data) > maxPersistenceBytes {
		return errors.New("multi-device state exceeds size limit")
	}
	paths, err := openPersistencePaths(path, path+"~", true)
	if err != nil {
		return err
	}
	defer paths.close()
	if previous, err := paths.readBounded(paths.primaryName, maxPersistenceBytes); err == nil {
		if previousSnapshot, decodeErr := contracts.DecodePersistenceV2(previous); decodeErr == nil {
			if _, err := paths.validateEntry(paths.backupName); err != nil {
				return err
			}
			if err := paths.atomicWrite(paths.backupName, previous, 0o600); err != nil {
				return err
			}
			comparison := snapshot
			comparison.GeneratedAt = previousSnapshot.GeneratedAt
			previousCanonical, previousErr := marshalIndented(previousSnapshot)
			comparisonCanonical, comparisonErr := marshalIndented(comparison)
			if previousErr == nil && comparisonErr == nil &&
				bytes.Equal(previousCanonical, comparisonCanonical) {
				return nil
			}
		}
	}
	if _, err := paths.validateEntry(paths.primaryName); err != nil {
		return err
	}
	return paths.atomicWrite(paths.primaryName, data, 0o600)
}

func (a *App) snapshotPersistenceV2(now time.Time) (contracts.PersistenceV2, error) {
	a.nodeMu.RLock()
	defer a.nodeMu.RUnlock()
	return a.snapshotPersistenceV2Locked(now)
}

// snapshotPersistenceV2Locked requires nodeMu to be held. Device HTTP commits
// use it to build the durable snapshot in the same critical section as replay
// classification and NodeState mutation.
func (a *App) snapshotPersistenceV2Locked(now time.Time) (contracts.PersistenceV2, error) {
	snapshot := contracts.PersistenceV2{
		Version:         2,
		GeneratedAt:     now.UTC().Format(time.RFC3339),
		Devices:         make([]contracts.PersistedDevice, 0, len(a.nodes)),
		OrphanedDevices: nil,
	}
	for _, device := range sortedRegistryDevices(a.registry) {
		node := a.nodes[device.ID]
		if node == nil {
			continue
		}
		persisted, err := persistedDeviceFromNode(a, node, now)
		if err != nil {
			return contracts.PersistenceV2{}, err
		}
		snapshot.Devices = append(snapshot.Devices, persisted)
	}
	snapshot.OrphanedDevices = append(
		[]contracts.OrphanedDevice(nil), a.orphans...,
	)
	if err := contracts.ValidatePersistenceV2(&snapshot); err != nil {
		return contracts.PersistenceV2{}, errors.New("multi-device state is invalid")
	}
	return snapshot, nil
}

func persistedDeviceFromNode(
	a *App,
	node *NodeState,
	now time.Time,
) (contracts.PersistedDevice, error) {
	observations := make(map[string]json.RawMessage)
	if node.HasUpdate {
		stats, err := rawJSON(node.Stats)
		if err != nil {
			return contracts.PersistedDevice{}, err
		}
		observations["stats"] = stats
	}
	for key, value := range map[string]any{
		"last_network_in":   node.LastNetworkIn,
		"last_network_out":  node.LastNetworkOut,
		"extension_version": node.Extension.ExtensionVersion,
		"received_at":       node.Extension.ReceivedAt,
		"identity_status":   node.IdentityStatus,
		"reported_name":     node.ReportedName,
		"reported_fqdn":     node.ReportedFQDN,
		"reported_hostname": node.ReportedHostname,
		"degraded":          node.Degraded,
	} {
		raw, err := rawJSON(value)
		if err != nil {
			return contracts.PersistedDevice{}, err
		}
		observations[key] = raw
	}
	if node.HasLastRequestDigest {
		raw, err := rawJSON(hex.EncodeToString(node.LastRequestDigest[:]))
		if err != nil {
			return contracts.PersistedDevice{}, err
		}
		observations["last_request_digest"] = raw
	}
	domains := make(map[string]json.RawMessage, 5)
	for key, value := range map[string]any{
		"hardware": node.Extension.Hardware,
		"docker":   node.Extension.Docker,
		"hermes":   node.Extension.Hermes,
		"lucky":    node.Extension.Lucky,
		"easytier": node.Extension.EasyTier,
	} {
		raw, err := rawJSON(value)
		if err != nil {
			return contracts.PersistedDevice{}, err
		}
		domains[key] = raw
	}
	return contracts.PersistedDevice{
		DeviceID:               node.DeviceID,
		LastAcceptedGeneration: node.LastAcceptedGeneration,
		LastSeen:               timeStringPointer(node.LastSeen),
		CollectedAt:            timeStringPointer(node.CollectedAt),
		ProtocolMode:           node.ProtocolMode,
		StatusAtSnapshot:       a.deviceStatusAt(node, now),
		RuntimeObservations:    observations,
		Domains:                domains,
	}, nil
}

func timeStringPointer(value time.Time) *string {
	if value.IsZero() {
		return nil
	}
	formatted := value.UTC().Format(time.RFC3339Nano)
	return &formatted
}

func (a *App) restorePersistenceV2() error {
	data, err := readPersistenceWithBackup(a.opts.PersistencePath)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		a.logger.Printf("read multi-device state: %s", persistenceReadErrorCode(err))
		return errors.New("multi-device state is unavailable")
	}
	snapshot, err := contracts.DecodePersistenceV2(data)
	if err != nil {
		backup, backupErr := readPersistenceBackup(a.opts.PersistencePath)
		if backupErr != nil {
			a.logger.Printf("read multi-device state: invalid_json")
			return errors.New("multi-device state is invalid")
		}
		snapshot, err = contracts.DecodePersistenceV2(backup)
		if err != nil {
			a.logger.Printf("read multi-device state: invalid_json")
			return errors.New("multi-device state is invalid")
		}
	}

	a.nodeMu.Lock()
	defer a.nodeMu.Unlock()
	candidates := make(map[string]*NodeState, len(a.nodes))
	for deviceID, node := range a.nodes {
		candidate := *node
		candidates[deviceID] = &candidate
	}
	registered := make(map[string]bool, len(a.nodes))
	for deviceID := range a.nodes {
		registered[deviceID] = true
	}
	restored := make(map[string]bool, len(snapshot.Devices))
	orphans := make([]contracts.OrphanedDevice, 0, len(snapshot.OrphanedDevices))
	maxGeneration := uint64(0)
	for _, persisted := range snapshot.Devices {
		node := candidates[persisted.DeviceID]
		if node == nil {
			orphans = append(orphans, orphanFromPersisted(
				persisted, "unknown_v2", orphans,
			))
			continue
		}
		if err := restorePersistedDevice(node, persisted); err != nil {
			orphans = append(orphans, sanitizedCorruptOrphan(
				persisted, snapshot.GeneratedAt, orphans,
			))
			continue
		}
		restored[persisted.DeviceID] = true
		if persisted.LastAcceptedGeneration > maxGeneration {
			maxGeneration = persisted.LastAcceptedGeneration
		}
	}
	for _, orphan := range snapshot.OrphanedDevices {
		if orphan.DeviceID != nil && registered[*orphan.DeviceID] &&
			!restored[*orphan.DeviceID] && orphan.SourceVersion == 2 {
			var persisted contracts.PersistedDevice
			if decodeStrictRuntime(orphan.Snapshot, &persisted) == nil &&
				persisted.DeviceID == *orphan.DeviceID &&
				restorePersistedDevice(candidates[persisted.DeviceID], persisted) == nil {
				restored[persisted.DeviceID] = true
				if persisted.LastAcceptedGeneration > maxGeneration {
					maxGeneration = persisted.LastAcceptedGeneration
				}
				continue
			}
		}
		orphans = append(orphans, orphan)
	}
	orphans = deduplicateOrphans(orphans)
	if len(orphans) > contracts.MaxOrphanedDevices {
		return errOrphanLimitExceeded
	}
	for deviceID, candidate := range candidates {
		*a.nodes[deviceID] = *candidate
	}
	a.orphans = orphans
	a.updateID.Store(maxGeneration)
	return nil
}

func sanitizedCorruptOrphan(
	persisted contracts.PersistedDevice,
	observedAt string,
	existing []contracts.OrphanedDevice,
) contracts.OrphanedDevice {
	encoded, _ := json.Marshal(persisted)
	digest := sha256.Sum256(encoded)
	referenceDigest := sha256.Sum256([]byte(persisted.DeviceID))
	snapshot, _ := json.Marshal(map[string]any{
		"entry_reference": fmt.Sprintf("device-%x", referenceDigest[:6]),
		"sha256":          fmt.Sprintf("%x", digest[:]),
		"error_code":      "invalid_persisted_device",
		"observed_at":     observedAt,
	})
	return contracts.OrphanedDevice{
		OrphanID:      uniqueOrphanID(fmt.Sprintf("corrupt-%x", referenceDigest[:6]), existing),
		DeviceID:      nil,
		Reason:        "corrupt_entry",
		SourceVersion: 2,
		Snapshot:      snapshot,
	}
}

func restorePersistedDevice(node *NodeState, persisted contracts.PersistedDevice) error {
	candidate := *node
	if err := restorePersistedDeviceFields(&candidate, persisted); err != nil {
		return err
	}
	*node = candidate
	return nil
}

func restorePersistedDeviceFields(node *NodeState, persisted contracts.PersistedDevice) error {
	if persisted.LastSeen != nil {
		value, err := time.Parse(time.RFC3339, *persisted.LastSeen)
		if err != nil {
			return err
		}
		node.LastSeen = value
	}
	if persisted.CollectedAt != nil {
		value, err := time.Parse(time.RFC3339, *persisted.CollectedAt)
		if err != nil {
			return err
		}
		node.CollectedAt = value
	}
	node.LastAcceptedGeneration = persisted.LastAcceptedGeneration
	node.ProtocolMode = persisted.ProtocolMode
	node.Restored = true
	node.Connected = false
	node.Connection = nil
	node.Online4 = false
	node.Online6 = false

	if raw, exists := persisted.RuntimeObservations["stats"]; exists {
		if err := decodeStrictRuntime(raw, &node.Stats); err != nil {
			return err
		}
		node.HasUpdate = true
	}
	if err := decodeOptionalObservation(
		persisted.RuntimeObservations, "last_network_in", &node.LastNetworkIn,
	); err != nil {
		return err
	}
	if err := decodeOptionalObservation(
		persisted.RuntimeObservations, "last_network_out", &node.LastNetworkOut,
	); err != nil {
		return err
	}
	if raw, exists := persisted.RuntimeObservations["last_request_digest"]; exists {
		var value string
		if err := decodeStrictRuntime(raw, &value); err != nil || len(value) != 64 {
			return errors.New("last request digest is invalid")
		}
		decoded, err := hex.DecodeString(value)
		if err != nil || len(decoded) != sha256.Size {
			return errors.New("last request digest is invalid")
		}
		copy(node.LastRequestDigest[:], decoded)
		node.HasLastRequestDigest = true
	}
	_ = decodeOptionalObservation(
		persisted.RuntimeObservations, "identity_status", &node.IdentityStatus,
	)
	_ = decodeOptionalObservation(
		persisted.RuntimeObservations, "reported_name", &node.ReportedName,
	)
	_ = decodeOptionalObservation(
		persisted.RuntimeObservations, "reported_fqdn", &node.ReportedFQDN,
	)
	_ = decodeOptionalObservation(
		persisted.RuntimeObservations, "reported_hostname", &node.ReportedHostname,
	)
	_ = decodeOptionalObservation(
		persisted.RuntimeObservations, "degraded", &node.Degraded,
	)
	_ = decodeOptionalObservation(
		persisted.RuntimeObservations, "extension_version", &node.Extension.ExtensionVersion,
	)
	_ = decodeOptionalObservation(
		persisted.RuntimeObservations, "received_at", &node.Extension.ReceivedAt,
	)

	if raw, exists := persisted.Domains["hardware"]; exists {
		var value HardwareStats
		if err := decodeStrictRuntime(raw, &value); err != nil {
			return err
		}
		node.Extension.Hardware = &value
	}
	if raw, exists := persisted.Domains["docker"]; exists {
		var value DockerStats
		if err := decodeStrictRuntime(raw, &value); err != nil {
			return err
		}
		node.Extension.Docker = &value
	}
	if raw, exists := persisted.Domains["hermes"]; exists {
		var value HermesStats
		if err := decodeStrictRuntime(raw, &value); err != nil {
			return err
		}
		node.Extension.Hermes = &value
	}
	if raw, exists := persisted.Domains["lucky"]; exists {
		var value LuckyStats
		if err := decodeStrictRuntime(raw, &value); err != nil {
			return err
		}
		node.Extension.Lucky = &value
	}
	if raw, exists := persisted.Domains["easytier"]; exists {
		var value EasyTierStats
		if err := decodeStrictRuntime(raw, &value); err != nil {
			return err
		}
		node.Extension.EasyTier = &value
	}
	return nil
}

func decodeOptionalObservation(
	observations map[string]json.RawMessage,
	key string,
	target any,
) error {
	raw, exists := observations[key]
	if !exists {
		return nil
	}
	return decodeStrictRuntime(raw, target)
}

func decodeStrictRuntime(data []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return errors.New("multiple JSON values")
	}
	return nil
}

func readPersistenceWithBackup(path string) ([]byte, error) {
	paths, err := openPersistencePaths(path, path+"~", true)
	if err != nil {
		return nil, err
	}
	defer paths.close()
	data, err := paths.readBounded(paths.primaryName, maxPersistenceBytes)
	if err == nil {
		return data, nil
	}
	primaryErr := err
	data, err = paths.readBounded(paths.backupName, maxPersistenceBytes)
	if err == nil {
		return data, nil
	}
	if errors.Is(primaryErr, os.ErrNotExist) && errors.Is(err, os.ErrNotExist) {
		return nil, os.ErrNotExist
	}
	return nil, primaryErr
}

func readPersistenceBackup(path string) ([]byte, error) {
	paths, err := openPersistencePaths(path, path+"~", true)
	if err != nil {
		return nil, err
	}
	defer paths.close()
	return paths.readBounded(paths.backupName, maxPersistenceBytes)
}

func (paths *openedPersistencePaths) readBounded(
	name string,
	limit int64,
) ([]byte, error) {
	if _, err := paths.validateEntry(name); err != nil {
		return nil, err
	}
	fileFD, err := unix.Openat(
		paths.directoryFD,
		name,
		unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW|unix.O_NONBLOCK,
		0,
	)
	if err != nil {
		if errors.Is(err, unix.ENOENT) {
			return nil, os.ErrNotExist
		}
		return nil, err
	}
	file := os.NewFile(uintptr(fileFD), "multi-device-state")
	if file == nil {
		_ = unix.Close(fileFD)
		return nil, errors.New("multi-device state is unavailable")
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > limit {
		return nil, errors.New("multi-device state is unavailable")
	}
	data, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil || int64(len(data)) > limit {
		return nil, errors.New("multi-device state is unavailable")
	}
	return data, nil
}

func (paths *openedPersistencePaths) atomicWrite(
	name string,
	data []byte,
	mode os.FileMode,
) error {
	tmpName, err := randomPersistenceName(".hermesstatus-state-", ".tmp")
	if err != nil {
		return err
	}
	fileFD, err := unix.Openat(
		paths.directoryFD,
		tmpName,
		unix.O_WRONLY|unix.O_CREAT|unix.O_EXCL|unix.O_CLOEXEC|unix.O_NOFOLLOW,
		uint32(mode.Perm()),
	)
	if err != nil {
		return err
	}
	cleanup := true
	defer func() {
		if cleanup {
			_ = unix.Unlinkat(paths.directoryFD, tmpName, 0)
		}
	}()
	file := os.NewFile(uintptr(fileFD), "multi-device-state-temporary")
	if file == nil {
		_ = unix.Close(fileFD)
		return errors.New("multi-device state is unavailable")
	}
	if err := file.Chmod(mode); err != nil {
		_ = file.Close()
		return err
	}
	if _, err := file.Write(data); err != nil {
		_ = file.Close()
		return err
	}
	if err := file.Sync(); err != nil {
		_ = file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	if err := unix.Renameat(
		paths.directoryFD,
		tmpName,
		paths.directoryFD,
		name,
	); err != nil {
		return err
	}
	cleanup = false
	return unix.Fsync(paths.directoryFD)
}

func persistenceReadErrorCode(err error) string {
	if errors.Is(err, os.ErrPermission) {
		return "permission_denied"
	}
	return "unavailable"
}

func orphanFromPersisted(
	persisted contracts.PersistedDevice,
	reason string,
	existing []contracts.OrphanedDevice,
) contracts.OrphanedDevice {
	raw, _ := json.Marshal(persisted)
	base := "v2-" + persisted.DeviceID
	orphanID := uniqueOrphanID(base, existing)
	deviceID := persisted.DeviceID
	return contracts.OrphanedDevice{
		OrphanID:      orphanID,
		DeviceID:      &deviceID,
		Reason:        reason,
		SourceVersion: 2,
		Snapshot:      raw,
	}
}

func uniqueOrphanID(base string, existing []contracts.OrphanedDevice) string {
	used := make(map[string]bool, len(existing))
	for _, orphan := range existing {
		used[orphan.OrphanID] = true
	}
	if !used[base] {
		return base
	}
	for suffix := 2; ; suffix++ {
		candidate := fmt.Sprintf("%s-%d", base, suffix)
		if !used[candidate] {
			return candidate
		}
	}
}

func deduplicateOrphans(input []contracts.OrphanedDevice) []contracts.OrphanedDevice {
	result := make([]contracts.OrphanedDevice, 0, len(input))
	seen := make(map[string]bool, len(input))
	for _, orphan := range input {
		if seen[orphan.OrphanID] {
			orphan.OrphanID = uniqueOrphanID(orphan.OrphanID, result)
		}
		seen[orphan.OrphanID] = true
		result = append(result, orphan)
	}
	sort.SliceStable(result, func(i, j int) bool {
		return result[i].OrphanID < result[j].OrphanID
	})
	return result
}
