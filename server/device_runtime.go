package main

import (
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
	"golang.org/x/sys/unix"
)

const maxRuntimeConfigBytes = 1 << 20

// loadMultiDeviceRuntime is deliberately startup-only for the first 2.2
// implementation. Both read-only documents must validate atomically before
// any multi-device behavior is enabled.
func (a *App) loadMultiDeviceRuntime(runtime RuntimeConfig) {
	a.registry = nil
	a.ownershipFailClosed = false
	a.legacyMap = make(map[string]string)
	a.deviceUsers = make(map[string]string)
	if a.opts.RegistryPath == "" {
		return
	}

	registryData, err := readBoundedFile(a.opts.RegistryPath, maxRuntimeConfigBytes)
	if err != nil {
		a.logger.Printf("multi-device configuration: registry_unavailable")
		return
	}
	registry, err := contracts.DecodeRegistry(registryData, time.Now())
	if err != nil {
		if strings.Contains(err.Error(), "cutover window expired") {
			a.ownershipFailClosed = true
		}
		a.logger.Printf("multi-device configuration: registry_invalid")
		return
	}
	if a.opts.LegacyMappingPath == "" {
		a.logger.Printf("multi-device configuration: legacy_mapping_unavailable")
		return
	}
	mappingData, err := readBoundedFile(a.opts.LegacyMappingPath, maxRuntimeConfigBytes)
	if err != nil {
		a.logger.Printf("multi-device configuration: legacy_mapping_unavailable")
		return
	}
	mappings, err := contracts.DecodeLegacyMappings(mappingData, registry, time.Now())
	if err != nil || !legacyMappingsMatchRuntime(mappings, runtime) {
		a.logger.Printf("multi-device configuration: legacy_mapping_invalid")
		return
	}

	legacyMap := make(map[string]string, len(mappings.Mappings))
	deviceUsers := make(map[string]string, len(mappings.Mappings))
	for _, mapping := range mappings.Mappings {
		legacyMap[mapping.Username] = mapping.DeviceID
		deviceUsers[mapping.DeviceID] = mapping.Username
	}
	a.registry = registry
	a.legacyMap = legacyMap
	a.deviceUsers = deviceUsers
	if a.opts.PersistencePath == "" {
		a.opts.PersistencePath = a.opts.StatsPath + ".state-v2"
	}
}

func readBoundedFile(path string, limit int64) ([]byte, error) {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return nil, errors.New("document unavailable")
	}
	fileFD, err := unix.Open(
		path,
		unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW,
		0,
	)
	if err != nil {
		return nil, errors.New("document unavailable")
	}
	file := os.NewFile(uintptr(fileFD), "multi-device-document")
	if file == nil {
		_ = unix.Close(fileFD)
		return nil, errors.New("document unavailable")
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > limit {
		return nil, errors.New("document unavailable")
	}
	data, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil || int64(len(data)) > limit {
		return nil, errors.New("document unavailable")
	}
	return data, nil
}

func legacyMappingsMatchRuntime(mappings *contracts.LegacyMappingDocument, runtime RuntimeConfig) bool {
	configured := make(map[string]ServerConfig, len(runtime.Servers))
	for _, server := range runtime.Servers {
		configured[server.Username] = server
	}
	for _, mapping := range mappings.Mappings {
		server, exists := configured[mapping.Username]
		if !exists || server.Disabled {
			return false
		}
	}
	return true
}

func (a *App) multiDeviceEnabled() bool {
	return a.registry != nil
}

func (a *App) rebuildNodesLocked(
	runtime RuntimeConfig,
	oldNodes map[string]*NodeState,
	disconnect bool,
	now time.Time,
) map[string]*NodeState {
	if a.registry == nil {
		return rebuildLegacyNodes(runtime, oldNodes, disconnect, now)
	}

	configured := make(map[string]ServerConfig, len(runtime.Servers))
	for _, server := range runtime.Servers {
		configured[server.Username] = server
	}
	nodes := make(map[string]*NodeState, len(a.registry.Devices))
	for _, device := range a.registry.Devices {
		enabled := device.Enabled != nil && *device.Enabled
		server := ServerConfig{
			Username:   a.deviceUsers[device.ID],
			Name:       device.DisplayName,
			Type:       "device",
			MonthStart: 1,
			Disabled:   !enabled,
		}
		if username := a.deviceUsers[device.ID]; username != "" {
			if legacy, exists := configured[username]; exists {
				server = legacy
				server.Name = device.DisplayName
				server.Disabled = !enabled
			}
		}
		node := &NodeState{
			DeviceID:       device.ID,
			LegacyUsername: a.deviceUsers[device.ID],
			DisplayName:    device.DisplayName,
			ExpectedFQDN:   cloneStringPointer(device.ExpectedFQDN),
			Enabled:        enabled,
			Order:          device.Order,
			Ownership:      device.Ingestion,
			Config:         server,
			Extension:      newNotReportedExtensionSnapshot(now),
			IdentityStatus: "unknown",
			ProtocolMode:   "none",
		}
		if old := oldNodes[device.ID]; old != nil {
			copyNodeRuntime(node, old, disconnect)
		}
		nodes[device.ID] = node
	}
	return nodes
}

func rebuildLegacyNodes(
	runtime RuntimeConfig,
	oldNodes map[string]*NodeState,
	disconnect bool,
	now time.Time,
) map[string]*NodeState {
	nodes := make(map[string]*NodeState, len(runtime.Servers))
	for index, server := range runtime.Servers {
		node := &NodeState{
			DeviceID:       server.Username,
			LegacyUsername: server.Username,
			DisplayName:    server.Name,
			Enabled:        !server.Disabled,
			Order:          index,
			Config:         server,
			Extension:      newNotReportedExtensionSnapshot(now),
			IdentityStatus: "unknown",
			ProtocolMode:   "none",
		}
		if old := oldNodes[server.Username]; old != nil && sameServerIdentity(old.Config, server) {
			node.LastNetworkIn = old.LastNetworkIn
			node.LastNetworkOut = old.LastNetworkOut
			node.Stats = old.Stats
			node.HasUpdate = old.HasUpdate
			if !disconnect {
				copyNodeRuntime(node, old, false)
			}
		}
		nodes[server.Username] = node
	}
	return nodes
}

func copyNodeRuntime(target, source *NodeState, disconnect bool) {
	target.Stats = source.Stats
	target.Extension = source.Extension
	target.HasUpdate = source.HasUpdate
	target.LastNetworkIn = source.LastNetworkIn
	target.LastNetworkOut = source.LastNetworkOut
	target.LastUpdate = source.LastUpdate
	target.IdentityStatus = source.IdentityStatus
	target.ProtocolMode = source.ProtocolMode
	target.ReportedName = cloneStringPointer(source.ReportedName)
	target.ReportedFQDN = cloneStringPointer(source.ReportedFQDN)
	target.ReportedHostname = cloneStringPointer(source.ReportedHostname)
	target.LastSeen = source.LastSeen
	target.CollectedAt = source.CollectedAt
	target.LastAcceptedGeneration = source.LastAcceptedGeneration
	target.Restored = source.Restored
	target.IdentityError = source.IdentityError
	target.Degraded = source.Degraded
	if disconnect {
		return
	}
	target.Connected = source.Connected
	target.Connection = source.Connection
	target.ConnectionID = source.ConnectionID
	target.Family = source.Family
	target.Online4 = source.Online4
	target.Online6 = source.Online6
	target.Pong = source.Pong
}

func cloneStringPointer(value *string) *string {
	if value == nil {
		return nil
	}
	copy := *value
	return &copy
}

func (a *App) deviceIDForUsername(username string) (string, bool) {
	if a.registry == nil {
		_, exists := a.nodes[username]
		return username, exists
	}
	deviceID, exists := a.legacyMap[username]
	return deviceID, exists
}

func (a *App) resolveNodeKey(identity string) string {
	if _, exists := a.nodes[identity]; exists {
		return identity
	}
	if deviceID, exists := a.deviceIDForUsername(identity); exists {
		return deviceID
	}
	return identity
}

func sortedRegistryDevices(registry *contracts.DeviceRegistry) []contracts.RegistryDevice {
	if registry == nil {
		return nil
	}
	devices := append([]contracts.RegistryDevice(nil), registry.Devices...)
	sort.SliceStable(devices, func(i, j int) bool {
		if devices[i].Order == devices[j].Order {
			return devices[i].ID < devices[j].ID
		}
		return devices[i].Order < devices[j].Order
	})
	return devices
}

func rawJSON(value any) (json.RawMessage, error) {
	data, err := json.Marshal(value)
	return json.RawMessage(data), err
}
