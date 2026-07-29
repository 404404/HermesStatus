package main

import (
	"errors"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

const MaxDeviceClockSkew = 5 * time.Minute

var (
	errDeviceNotRegistered = errors.New("device is not registered")
	errDeviceDisabled      = errors.New("device is disabled")
	errInactiveOwner       = errors.New("protocol is not the active ingestion owner")
	errStaleGeneration     = errors.New("generation is not newer")
	errDeviceClockSkew     = errors.New("collected_at exceeds clock-skew limit")
	errDeviceIdentity      = errors.New("device identity evidence was rejected")
	errInactiveConnection  = errors.New("connection generation is inactive")
)

type deviceIngestRequest struct {
	DeviceID         string
	ProtocolMode     string
	CollectedAt      time.Time
	FlatStats        []byte
	Generation       uint64
	ConnectionID     uint64
	ReportedName     *string
	ReportedFQDN     *string
	ReportedHostname *string
}

// ingestDeviceUpdate is the single decoder-and-state entry point shared by
// protocol adapters. Authentication remains outside this method.
func (a *App) ingestDeviceUpdate(
	authenticatedDeviceID string,
	protocolMode string,
	collectedAt time.Time,
	flatStats []byte,
	generation uint64,
) ([]extensionDecodeIssue, error) {
	return a.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID:     authenticatedDeviceID,
		ProtocolMode: protocolMode,
		CollectedAt:  collectedAt,
		FlatStats:    flatStats,
		Generation:   generation,
	}, time.Now())
}

func (a *App) ingestDeviceUpdateAt(
	request deviceIngestRequest,
	now time.Time,
) ([]extensionDecodeIssue, error) {
	if request.CollectedAt.IsZero() {
		request.CollectedAt = now
	}
	if request.CollectedAt.Sub(now) > MaxDeviceClockSkew {
		return nil, errDeviceClockSkew
	}

	a.nodeMu.RLock()
	node := a.nodes[request.DeviceID]
	if err := a.validateIngestLocked(node, request, now); err != nil {
		a.nodeMu.RUnlock()
		return nil, err
	}
	expectedFQDN := cloneStringPointer(node.ExpectedFQDN)
	a.nodeMu.RUnlock()

	identityStatus, identityErr := evaluateIdentity(
		expectedFQDN, request.ReportedFQDN, request.ProtocolMode,
	)
	if identityErr != nil {
		a.markIdentityError(request, identityStatus, now)
		return nil, identityErr
	}

	stats, extension, issues, err := decodeAgentUpdate(request.FlatStats)
	if err != nil {
		return nil, err
	}

	a.nodeMu.Lock()
	node = a.nodes[request.DeviceID]
	if err := a.validateIngestLocked(node, request, now); err != nil {
		a.nodeMu.Unlock()
		return nil, err
	}
	if stats.Online4 != nil {
		node.Online4 = *stats.Online4
	}
	if stats.Online6 != nil {
		node.Online6 = *stats.Online6
	}
	node.Stats = stats
	node.Extension = extensionSnapshotAt(extension, now)
	node.HasUpdate = true
	node.LastUpdate = now
	node.LastSeen = now
	node.CollectedAt = request.CollectedAt
	node.LastAcceptedGeneration = request.Generation
	node.ProtocolMode = request.ProtocolMode
	node.IdentityStatus = identityStatus
	node.ReportedName = cloneStringPointer(request.ReportedName)
	node.ReportedFQDN = cloneStringPointer(request.ReportedFQDN)
	node.ReportedHostname = cloneStringPointer(request.ReportedHostname)
	node.Restored = false
	node.IdentityError = false
	node.Degraded = len(issues) > 0 || extensionHasBusinessError(extension)
	a.nodeMu.Unlock()
	a.wakeStatsWriter()
	return issues, nil
}

func (a *App) validateIngestLocked(
	node *NodeState,
	request deviceIngestRequest,
	now time.Time,
) error {
	if node == nil {
		return errDeviceNotRegistered
	}
	if !node.Enabled {
		return errDeviceDisabled
	}
	if a.ownershipFailClosed {
		return errInactiveOwner
	}
	if a.registry != nil && !contracts.OwnershipAllows(node.Ownership, request.ProtocolMode, now) {
		return errInactiveOwner
	}
	if a.registry == nil && request.ProtocolMode != "legacy_single_device" {
		return errInactiveOwner
	}
	if request.Generation == 0 || request.Generation <= node.LastAcceptedGeneration {
		return errStaleGeneration
	}
	if request.ConnectionID != 0 &&
		(!node.Connected || node.ConnectionID != request.ConnectionID) {
		return errInactiveConnection
	}
	return nil
}

func evaluateIdentity(
	expectedFQDN *string,
	reportedFQDN *string,
	protocolMode string,
) (string, error) {
	if expectedFQDN == nil {
		return "unknown", nil
	}
	if reportedFQDN == nil || *reportedFQDN == "" {
		if protocolMode == "legacy_single_device" {
			return "missing_fqdn", nil
		}
		return "missing_fqdn", errDeviceIdentity
	}
	normalized, err := contracts.NormalizeFQDN(*reportedFQDN)
	if err != nil || normalized != *expectedFQDN {
		return "fqdn_mismatch", errDeviceIdentity
	}
	return "matched", nil
}

func (a *App) markIdentityError(
	request deviceIngestRequest,
	identityStatus string,
	now time.Time,
) {
	a.nodeMu.Lock()
	node := a.nodes[request.DeviceID]
	if node == nil || !node.Enabled ||
		(request.Generation != 0 && request.Generation <= node.LastAcceptedGeneration) {
		a.nodeMu.Unlock()
		return
	}
	if a.registry != nil && !contracts.OwnershipAllows(node.Ownership, request.ProtocolMode, now) {
		a.nodeMu.Unlock()
		return
	}
	node.IdentityStatus = identityStatus
	node.IdentityError = true
	a.nodeMu.Unlock()
	a.wakeStatsWriter()
}

func extensionHasBusinessError(extension ExtensionStats) bool {
	var extensionErrors []*ExtensionError
	if extension.Hardware != nil {
		extensionErrors = append(extensionErrors, extension.Hardware.Error)
	}
	if extension.Docker != nil {
		extensionErrors = append(extensionErrors, extension.Docker.Error)
	}
	if extension.Hermes != nil {
		extensionErrors = append(extensionErrors, extension.Hermes.Error)
	}
	if extension.Lucky != nil {
		extensionErrors = append(extensionErrors, extension.Lucky.Error)
	}
	for _, extensionError := range extensionErrors {
		if extensionError != nil &&
			extensionError.Code != "not_reported" &&
			extensionError.Code != "not_configured" {
			return true
		}
	}
	return false
}

func (a *App) deviceStatusAt(node *NodeState, now time.Time) string {
	if !node.Enabled {
		return "disabled"
	}
	if node.LastSeen.IsZero() && !node.Restored {
		return "never_seen"
	}
	if node.IdentityError {
		return "identity_error"
	}
	if node.Restored {
		return "offline"
	}
	if node.ProtocolMode == "legacy_single_device" && !node.Connected {
		return "offline"
	}
	if node.LastSeen.IsZero() {
		return "offline"
	}
	age := now.Sub(node.LastSeen)
	if age > time.Duration(a.registry.Defaults.OfflineSeconds)*time.Second {
		return "offline"
	}
	if age > time.Duration(a.registry.Defaults.StaleSeconds)*time.Second {
		return "stale"
	}
	if node.Degraded {
		return "degraded"
	}
	return "online"
}

func (a *App) deviceIsStaleAt(node *NodeState, now time.Time) bool {
	if !node.Enabled || node.Restored || node.LastSeen.IsZero() {
		return true
	}
	return now.Sub(node.LastSeen) > time.Duration(a.registry.Defaults.StaleSeconds)*time.Second
}

func nullableTime(value time.Time) any {
	if value.IsZero() {
		return nil
	}
	return value.UTC().Format(time.RFC3339)
}

func forceExtensionStale(extension *ExtensionSnapshot) {
	if extension.Hardware != nil {
		value := *extension.Hardware
		extension.Hardware = &value
		extension.Hardware.Stale = true
	}
	if extension.Docker != nil {
		value := *extension.Docker
		extension.Docker = &value
		extension.Docker.Stale = true
	}
	if extension.Hermes != nil {
		value := *extension.Hermes
		value.Profiles = append([]HermesProfileStats(nil), extension.Hermes.Profiles...)
		extension.Hermes = &value
		extension.Hermes.Stale = true
		for index := range extension.Hermes.Profiles {
			extension.Hermes.Profiles[index].Stale = true
		}
	}
	if extension.Lucky != nil {
		value := *extension.Lucky
		extension.Lucky = &value
		extension.Lucky.Stale = true
		extension.Lucky.IPResolution.Stale = true
		extension.Lucky.DynamicDNS.Stale = true
		extension.Lucky.WebServices.Stale = true
		extension.Lucky.PortForwards.Stale = true
		extension.Lucky.Certificates.Stale = true
		extension.Lucky.Version.Stale = true
	}
}

func (a *App) updateAgent(
	identity string,
	connectionID uint64,
	update AgentStats,
	extension ExtensionStats,
) bool {
	now := time.Now()
	generation := a.updateID.Add(1)
	a.nodeMu.Lock()
	deviceID := a.resolveNodeKey(identity)
	node := a.nodes[deviceID]
	request := deviceIngestRequest{
		DeviceID:     deviceID,
		ProtocolMode: "legacy_single_device",
		CollectedAt:  now,
		Generation:   generation,
		ConnectionID: connectionID,
	}
	if err := a.validateIngestLocked(node, request, now); err != nil {
		a.nodeMu.Unlock()
		return false
	}
	if update.Online4 != nil {
		node.Online4 = *update.Online4
	}
	if update.Online6 != nil {
		node.Online6 = *update.Online6
	}
	node.Stats = update
	node.Extension = extensionSnapshotAt(extension, now)
	node.HasUpdate = true
	node.LastUpdate = now
	node.LastSeen = now
	node.CollectedAt = now
	node.LastAcceptedGeneration = generation
	node.ProtocolMode = "legacy_single_device"
	if node.ExpectedFQDN != nil {
		node.IdentityStatus = "missing_fqdn"
	} else {
		node.IdentityStatus = "unknown"
	}
	node.Restored = false
	node.IdentityError = false
	node.Degraded = extensionHasBusinessError(extension)
	a.nodeMu.Unlock()
	a.wakeStatsWriter()
	return true
}
