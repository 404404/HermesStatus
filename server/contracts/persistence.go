package contracts

import (
	"encoding/json"
	"fmt"
	"sort"
	"time"
)

type PersistedDevice struct {
	DeviceID               string                     `json:"device_id"`
	LastAcceptedGeneration uint64                     `json:"last_accepted_generation"`
	LastSeen               *string                    `json:"last_seen"`
	CollectedAt            *string                    `json:"collected_at"`
	ProtocolMode           string                     `json:"protocol_mode"`
	StatusAtSnapshot       string                     `json:"status_at_snapshot"`
	RuntimeObservations    map[string]json.RawMessage `json:"runtime_observations"`
	Domains                map[string]json.RawMessage `json:"domains"`
}

type OrphanedDevice struct {
	OrphanID      string          `json:"orphan_id"`
	DeviceID      *string         `json:"device_id"`
	Reason        string          `json:"reason"`
	SourceVersion int             `json:"source_version"`
	Snapshot      json.RawMessage `json:"snapshot"`
}

type PersistenceV2 struct {
	Version         int               `json:"version"`
	GeneratedAt     string            `json:"generated_at"`
	Devices         []PersistedDevice `json:"devices"`
	OrphanedDevices []OrphanedDevice  `json:"orphaned_devices"`
}

type RestoredDevice struct {
	DeviceID               string
	LastAcceptedGeneration uint64
	LastSeen               *string
	CollectedAt            *string
	ProtocolMode           string
	Status                 string
	Stale                  bool
	Domains                map[string]json.RawMessage
}

type LegacyPersistenceV1 struct {
	Servers []map[string]any `json:"servers"`
}

func DecodePersistenceV2(data []byte) (*PersistenceV2, error) {
	var snapshot PersistenceV2
	if err := decodeStrict(data, &snapshot); err != nil {
		return nil, err
	}
	if err := ValidatePersistenceV2(&snapshot); err != nil {
		return nil, err
	}
	return &snapshot, nil
}

func ValidatePersistenceV2(snapshot *PersistenceV2) error {
	if snapshot == nil || snapshot.Version != 2 {
		return contractError("version", "must equal 2")
	}
	if _, err := parseRFC3339UTC(snapshot.GeneratedAt); err != nil {
		return contractError("generated_at", "must be RFC3339 UTC")
	}
	if len(snapshot.Devices) > MaxDevices {
		return contractError("devices", "must contain at most 128 entries")
	}
	seen := map[string]bool{}
	for index, device := range snapshot.Devices {
		prefix := fmt.Sprintf("devices[%d]", index)
		if !ValidateDeviceID(device.DeviceID) || seen[device.DeviceID] {
			return contractError(prefix+".device_id", "is invalid or duplicated")
		}
		seen[device.DeviceID] = true
		if !protocolModeSet[device.ProtocolMode] || !deviceStatusSet[device.StatusAtSnapshot] {
			return contractError(prefix, "contains an invalid enum")
		}
		if device.LastSeen != nil {
			if _, err := parseRFC3339UTC(*device.LastSeen); err != nil {
				return contractError(prefix+".last_seen", "must be RFC3339 UTC or null")
			}
		}
		if device.CollectedAt != nil {
			if _, err := parseRFC3339UTC(*device.CollectedAt); err != nil {
				return contractError(prefix+".collected_at", "must be RFC3339 UTC or null")
			}
		}
		for domain := range device.Domains {
			if domain != "hardware" && domain != "docker" && domain != "hermes" && domain != "lucky" {
				return contractError(prefix+".domains", "contains an unknown domain")
			}
		}
	}
	orphanIDs := map[string]bool{}
	for index, orphan := range snapshot.OrphanedDevices {
		prefix := fmt.Sprintf("orphaned_devices[%d]", index)
		if len(orphan.OrphanID) < 1 || len(orphan.OrphanID) > 128 || orphanIDs[orphan.OrphanID] {
			return contractError(prefix+".orphan_id", "is invalid or duplicated")
		}
		orphanIDs[orphan.OrphanID] = true
		if orphan.DeviceID != nil && !ValidateDeviceID(*orphan.DeviceID) {
			return contractError(prefix+".device_id", "is invalid")
		}
		if orphan.SourceVersion < 1 || len(orphan.Snapshot) == 0 {
			return contractError(prefix, "must retain source version and snapshot")
		}
	}
	return nil
}

func RestorePersistenceMock(snapshot PersistenceV2, registry DeviceRegistry) map[string]RestoredDevice {
	registered := map[string]RegistryDevice{}
	for _, device := range registry.Devices {
		registered[device.ID] = device
	}
	result := map[string]RestoredDevice{}
	for _, persisted := range snapshot.Devices {
		device, exists := registered[persisted.DeviceID]
		if !exists {
			continue
		}
		status := "offline"
		if device.Enabled != nil && !*device.Enabled {
			status = "disabled"
		}
		result[persisted.DeviceID] = RestoredDevice{
			DeviceID:               persisted.DeviceID,
			LastAcceptedGeneration: persisted.LastAcceptedGeneration,
			LastSeen:               persisted.LastSeen,
			CollectedAt:            persisted.CollectedAt,
			ProtocolMode:           persisted.ProtocolMode,
			Status:                 status,
			Stale:                  true,
			Domains:                persisted.Domains,
		}
	}
	return result
}

// MigratePersistenceV1Mock converts only explicitly bound array entries. The
// binding key is the v1 array index, avoiding hostname/FQDN guessing.
func MigratePersistenceV1Mock(
	legacy LegacyPersistenceV1,
	bindings map[int]string,
	registry DeviceRegistry,
	generatedAt time.Time,
) (PersistenceV2, error) {
	registryDevices := map[string]RegistryDevice{}
	for _, device := range registry.Devices {
		registryDevices[device.ID] = device
	}
	usedDevices := map[string]bool{}
	for index, deviceID := range bindings {
		if index < 0 || index >= len(legacy.Servers) || !ValidateDeviceID(deviceID) {
			return PersistenceV2{}, contractError("bindings", "contains an invalid source index or device_id")
		}
		if usedDevices[deviceID] {
			return PersistenceV2{}, contractError("bindings", "contains an ambiguous device collision")
		}
		usedDevices[deviceID] = true
	}

	result := PersistenceV2{
		Version: 2, GeneratedAt: generatedAt.UTC().Format(time.RFC3339),
		Devices: []PersistedDevice{}, OrphanedDevices: []OrphanedDevice{},
	}
	for index, legacyServer := range legacy.Servers {
		encoded, err := json.Marshal(legacyServer)
		if err != nil {
			return PersistenceV2{}, contractError("legacy", "cannot serialize source entry")
		}
		deviceID, bound := bindings[index]
		registryDevice, registered := registryDevices[deviceID]
		if !bound || !registered {
			reason := "unmatched_v1"
			var optionalID *string
			if bound {
				reason = "removed_device"
				value := deviceID
				optionalID = &value
			}
			result.OrphanedDevices = append(result.OrphanedDevices, OrphanedDevice{
				OrphanID: fmt.Sprintf("v1-index-%d", index), DeviceID: optionalID,
				Reason: reason, SourceVersion: 1, Snapshot: encoded,
			})
			continue
		}
		status := "offline"
		if registryDevice.Enabled != nil && !*registryDevice.Enabled {
			status = "disabled"
		}
		result.Devices = append(result.Devices, PersistedDevice{
			DeviceID: deviceID, LastAcceptedGeneration: 0,
			LastSeen: nil, CollectedAt: nil, ProtocolMode: "legacy_single_device",
			StatusAtSnapshot:    status,
			RuntimeObservations: map[string]json.RawMessage{"legacy_snapshot": encoded},
			Domains:             map[string]json.RawMessage{},
		})
	}
	sort.Slice(result.Devices, func(i, j int) bool {
		return result.Devices[i].DeviceID < result.Devices[j].DeviceID
	})
	return result, nil
}
