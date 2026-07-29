package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

const maxPersistenceBytes = 8 << 20

func writePersistenceV2(path string, snapshot contracts.PersistenceV2) error {
	data, err := marshalIndented(snapshot)
	if err != nil {
		return err
	}
	if len(data) > maxPersistenceBytes {
		return errors.New("multi-device state exceeds size limit")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	if previous, err := readBoundedFile(path, maxPersistenceBytes); err == nil {
		if _, decodeErr := contracts.DecodePersistenceV2(previous); decodeErr == nil {
			if err := atomicWrite(path+"~", previous, 0o600, false); err != nil {
				return err
			}
		}
	}
	return atomicWrite(path, data, 0o600, false)
}

func (a *App) snapshotPersistenceV2(now time.Time) (contracts.PersistenceV2, error) {
	snapshot := contracts.PersistenceV2{
		Version:         2,
		GeneratedAt:     now.UTC().Format(time.RFC3339),
		Devices:         make([]contracts.PersistedDevice, 0, len(a.nodes)),
		OrphanedDevices: nil,
	}
	a.nodeMu.RLock()
	defer a.nodeMu.RUnlock()
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
	domains := make(map[string]json.RawMessage, 4)
	for key, value := range map[string]any{
		"hardware": node.Extension.Hardware,
		"docker":   node.Extension.Docker,
		"hermes":   node.Extension.Hermes,
		"lucky":    node.Extension.Lucky,
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
	formatted := value.UTC().Format(time.RFC3339)
	return &formatted
}

func (a *App) restorePersistenceV2() {
	data, err := readPersistenceWithBackup(a.opts.PersistencePath)
	if err != nil {
		if !errors.Is(err, os.ErrNotExist) {
			a.logger.Printf("read multi-device state: %s", persistenceReadErrorCode(err))
		}
		return
	}
	snapshot, err := contracts.DecodePersistenceV2(data)
	if err != nil {
		backup, backupErr := readBoundedFile(a.opts.PersistencePath+"~", maxPersistenceBytes)
		if backupErr != nil {
			a.logger.Printf("read multi-device state: invalid_json")
			return
		}
		snapshot, err = contracts.DecodePersistenceV2(backup)
		if err != nil {
			a.logger.Printf("read multi-device state: invalid_json")
			return
		}
	}

	a.nodeMu.Lock()
	defer a.nodeMu.Unlock()
	registered := make(map[string]bool, len(a.nodes))
	for deviceID := range a.nodes {
		registered[deviceID] = true
	}
	restored := make(map[string]bool, len(snapshot.Devices))
	orphans := make([]contracts.OrphanedDevice, 0, len(snapshot.OrphanedDevices))
	maxGeneration := uint64(0)
	for _, persisted := range snapshot.Devices {
		node := a.nodes[persisted.DeviceID]
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
				restorePersistedDevice(a.nodes[persisted.DeviceID], persisted) == nil {
				restored[persisted.DeviceID] = true
				if persisted.LastAcceptedGeneration > maxGeneration {
					maxGeneration = persisted.LastAcceptedGeneration
				}
				continue
			}
		}
		orphans = append(orphans, orphan)
	}
	a.orphans = deduplicateOrphans(orphans)
	a.updateID.Store(maxGeneration)
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
	data, err := readBoundedFile(path, maxPersistenceBytes)
	if err == nil {
		return data, nil
	}
	primaryErr := err
	data, err = readBoundedFile(path+"~", maxPersistenceBytes)
	if err == nil {
		return data, nil
	}
	if errors.Is(primaryErr, os.ErrNotExist) && errors.Is(err, os.ErrNotExist) {
		return nil, os.ErrNotExist
	}
	return nil, primaryErr
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
