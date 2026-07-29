package contracts

import (
	"crypto/sha256"
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

type LegacyPersistenceBinding struct {
	Source   map[string]any `json:"source"`
	DeviceID string         `json:"device_id"`
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

func DecodePersistenceV1(data []byte) (*LegacyPersistenceV1, error) {
	var snapshot LegacyPersistenceV1
	if err := decodeStrict(data, &snapshot); err != nil {
		return nil, err
	}
	if len(snapshot.Servers) > MaxDevices {
		return nil, contractError("servers", "must contain at most 16 entries")
	}
	for index, server := range snapshot.Servers {
		if server == nil {
			return nil, contractError(fmt.Sprintf("servers[%d]", index), "must be an object")
		}
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
		return contractError("devices", "must contain at most 16 entries")
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
		if len(device.RuntimeObservations) > 128 {
			return contractError(prefix+".runtime_observations", "contains too many fields")
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
			if !rawJSONObject(device.Domains[domain]) {
				return contractError(prefix+".domains."+domain, "must be an object")
			}
		}
	}
	if len(snapshot.OrphanedDevices) > MaxOrphanedDevices {
		return contractError("orphaned_devices", "must contain at most 64 entries")
	}
	orphanIDs := map[string]bool{}
	reasons := map[string]bool{
		"unmatched_v1": true, "ambiguous_v1": true, "removed_device": true,
		"unknown_v2": true, "corrupt_entry": true,
	}
	for index, orphan := range snapshot.OrphanedDevices {
		prefix := fmt.Sprintf("orphaned_devices[%d]", index)
		if len(orphan.OrphanID) < 1 || len(orphan.OrphanID) > 128 || orphanIDs[orphan.OrphanID] {
			return contractError(prefix+".orphan_id", "is invalid or duplicated")
		}
		orphanIDs[orphan.OrphanID] = true
		if orphan.DeviceID != nil && !ValidateDeviceID(*orphan.DeviceID) {
			return contractError(prefix+".device_id", "is invalid")
		}
		if !reasons[orphan.Reason] {
			return contractError(prefix+".reason", "is invalid")
		}
		if orphan.SourceVersion < 1 || orphan.SourceVersion > 2 ||
			!rawJSONObject(orphan.Snapshot) {
			return contractError(prefix, "must retain source version and snapshot")
		}
	}
	return nil
}

func rawJSONObject(data json.RawMessage) bool {
	var value map[string]json.RawMessage
	return json.Unmarshal(data, &value) == nil && value != nil
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

// MigratePersistenceV1 converts only entries whose complete legacy source
// object is present in an explicit binding table. It never uses array order,
// hostname/FQDN inference, or username promotion.
func MigratePersistenceV1(
	legacy LegacyPersistenceV1,
	bindings []LegacyPersistenceBinding,
	registry DeviceRegistry,
	generatedAt time.Time,
) (PersistenceV2, error) {
	if len(legacy.Servers) > MaxDevices {
		return PersistenceV2{}, contractError("servers", "must contain at most 16 entries")
	}
	if err := ValidateRegistry(&registry, generatedAt); err != nil {
		return PersistenceV2{}, contractError("registry", "is invalid")
	}
	registryDevices := map[string]RegistryDevice{}
	for _, device := range registry.Devices {
		registryDevices[device.ID] = device
	}
	usedDevices := map[string]bool{}
	boundSources := make(map[string]string, len(bindings))
	for _, binding := range bindings {
		sourceKey, err := legacySourceKey(binding.Source)
		if err != nil || !ValidateDeviceID(binding.DeviceID) {
			return PersistenceV2{}, contractError("bindings", "contains an invalid source or device_id")
		}
		if _, exists := boundSources[sourceKey]; exists || usedDevices[binding.DeviceID] {
			return PersistenceV2{}, contractError("bindings", "contains an ambiguous device collision")
		}
		boundSources[sourceKey] = binding.DeviceID
		usedDevices[binding.DeviceID] = true
	}

	result := PersistenceV2{
		Version: 2, GeneratedAt: generatedAt.UTC().Format(time.RFC3339),
		Devices: []PersistedDevice{}, OrphanedDevices: []OrphanedDevice{},
	}
	seenSources := map[string]bool{}
	orphanIDs := map[string]int{}
	for _, legacyServer := range legacy.Servers {
		encoded, err := json.Marshal(legacyServer)
		if err != nil {
			return PersistenceV2{}, contractError("legacy", "cannot serialize source entry")
		}
		sourceKey, err := legacySourceKey(legacyServer)
		if err != nil {
			return PersistenceV2{}, contractError("legacy", "cannot identify source entry")
		}
		deviceID, bound := boundSources[sourceKey]
		if bound && seenSources[sourceKey] {
			return PersistenceV2{}, contractError("bindings", "matches more than one source entry")
		}
		seenSources[sourceKey] = true
		registryDevice, registered := registryDevices[deviceID]
		if !bound || !registered {
			reason := "unmatched_v1"
			var optionalID *string
			if bound {
				reason = "removed_device"
				value := deviceID
				optionalID = &value
			}
			digest := sha256.Sum256(encoded)
			orphanBase := fmt.Sprintf("v1-%x", digest[:6])
			orphanIDs[orphanBase]++
			orphanID := orphanBase
			if orphanIDs[orphanBase] > 1 {
				orphanID = fmt.Sprintf("%s-%d", orphanBase, orphanIDs[orphanBase])
			}
			result.OrphanedDevices = append(result.OrphanedDevices, OrphanedDevice{
				OrphanID: orphanID, DeviceID: optionalID,
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
	for sourceKey := range boundSources {
		if !seenSources[sourceKey] {
			return PersistenceV2{}, contractError("bindings", "contains a source not present in v1")
		}
	}
	sort.Slice(result.Devices, func(i, j int) bool {
		return result.Devices[i].DeviceID < result.Devices[j].DeviceID
	})
	return result, nil
}

// MigratePersistenceV1Mock remains as a compatibility name for Stage A
// callers. It delegates to the same production-safe pure conversion.
func MigratePersistenceV1Mock(
	legacy LegacyPersistenceV1,
	bindings []LegacyPersistenceBinding,
	registry DeviceRegistry,
	generatedAt time.Time,
) (PersistenceV2, error) {
	return MigratePersistenceV1(legacy, bindings, registry, generatedAt)
}

func legacySourceKey(source map[string]any) (string, error) {
	if source == nil {
		return "", contractError("source", "must be an object")
	}
	encoded, err := json.Marshal(source)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(encoded)
	return fmt.Sprintf("%x", digest[:]), nil
}
