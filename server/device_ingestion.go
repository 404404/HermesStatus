package main

import (
	"errors"
	"sync"
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
	errStaleReport         = errors.New("collected_at is older than the last accepted report")
	errReportConflict      = errors.New("collected_at conflicts with the last accepted report")
	errIdempotentReplay    = errors.New("report was already accepted")
	errDeviceIdentity      = errors.New("device identity evidence was rejected")
	errInactiveConnection  = errors.New("connection generation is inactive")
)

type deviceIngestRequest struct {
	DeviceID           string
	ProtocolMode       string
	CollectedAt        time.Time
	FlatStats          []byte
	Generation         uint64
	ConnectionID       uint64
	ReportedName       *string
	ReportedFQDN       *string
	ReportedHostname   *string
	RequestDigest      [32]byte
	HasRequestDigest   bool
	IdentityClass      string
	IdentityRejected   bool
	IdentityClassified bool
	AssignGeneration   bool
	PersistBeforeAck   bool
}

type deviceReplayClass string

const (
	replayNoBoundary    deviceReplayClass = "no_boundary"
	replayStrictlyNewer deviceReplayClass = "strictly_newer"
	replayStale         deviceReplayClass = "stale"
	replayIdempotent    deviceReplayClass = "idempotent"
	replayConflict      deviceReplayClass = "conflict"
)

// DeviceUpdateDecision is the mutation-free result of applying ownership,
// replay, identity, generation, and connection policy to one device update.
// Only ShouldIngest authorizes the commit phase to change NodeState.
type DeviceUpdateDecision struct {
	Outcome                     string
	ReplayClass                 deviceReplayClass
	IdentityClass               string
	ShouldIngest                bool
	ShouldRecordIdentityFailure bool
	IsIdempotent                bool
	Err                         error
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
	if err := validateDeviceCollectedAt(request.CollectedAt, now); err != nil {
		return nil, errDeviceClockSkew
	}

	stats, extension, issues, err := decodeAgentUpdate(request.FlatStats)
	if err != nil {
		return nil, err
	}

	deviceLock := a.deviceIngestLock(request.DeviceID)
	deviceLock.Lock()
	defer deviceLock.Unlock()
	if request.PersistBeforeAck {
		a.persistMu.Lock()
		defer a.persistMu.Unlock()
	}

	a.nodeMu.Lock()
	node := a.nodes[request.DeviceID]
	decision := a.decideDeviceUpdateLocked(node, request, now)
	if decision.Err != nil {
		a.nodeMu.Unlock()
		return nil, decision.Err
	}
	if !decision.ShouldIngest {
		a.nodeMu.Unlock()
		return nil, errors.New("device update decision did not authorize ingestion")
	}
	if request.PersistBeforeAck {
		paths, pathErr := openPersistencePaths(
			a.opts.PersistencePath,
			a.opts.PersistencePath+"~",
			true,
		)
		if pathErr != nil {
			a.nodeMu.Unlock()
			return nil, errors.New("device update persistence failed")
		}
		paths.close()
	}
	previousUpdateID := uint64(0)
	if request.AssignGeneration {
		request.Generation = a.updateID.Add(1)
		previousUpdateID = request.Generation - 1
	}
	if request.Generation == 0 || request.Generation <= node.LastAcceptedGeneration {
		a.nodeMu.Unlock()
		return nil, errStaleGeneration
	}
	before := *node
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
	if request.HasRequestDigest {
		node.LastRequestDigest = request.RequestDigest
		node.HasLastRequestDigest = true
	}
	node.ProtocolMode = request.ProtocolMode
	node.IdentityStatus = decision.IdentityClass
	node.ReportedName = cloneStringPointer(request.ReportedName)
	node.ReportedFQDN = cloneStringPointer(request.ReportedFQDN)
	node.ReportedHostname = cloneStringPointer(request.ReportedHostname)
	node.Restored = false
	node.IdentityError = false
	node.Degraded = len(issues) > 0 || extensionHasBusinessError(extension)
	if request.PersistBeforeAck {
		snapshot, snapshotErr := a.snapshotPersistenceV2Locked(now)
		if snapshotErr == nil {
			snapshotErr = writePersistenceV2(a.opts.PersistencePath, snapshot)
		}
		if snapshotErr != nil {
			*node = before
			if request.AssignGeneration {
				a.updateID.CompareAndSwap(request.Generation, previousUpdateID)
			}
			a.nodeMu.Unlock()
			return nil, errors.New("device update persistence failed")
		}
	}
	a.nodeMu.Unlock()
	a.wakeStatsWriter()
	return issues, nil
}

func (a *App) deviceIngestLock(deviceID string) *sync.Mutex {
	value, _ := a.deviceIngestLocks.LoadOrStore(deviceID, &sync.Mutex{})
	return value.(*sync.Mutex)
}

func (a *App) decideDeviceUpdateLocked(
	node *NodeState,
	request deviceIngestRequest,
	now time.Time,
) DeviceUpdateDecision {
	decision := DeviceUpdateDecision{
		Outcome:       "rejected",
		ReplayClass:   replayNoBoundary,
		IdentityClass: "unknown",
	}
	if request.IdentityClassified {
		decision.IdentityClass = request.IdentityClass
	}
	if node == nil {
		decision.Err = errDeviceNotRegistered
		return decision
	}
	if !node.Enabled {
		decision.Err = errDeviceDisabled
		return decision
	}
	if a.ownershipFailClosed {
		decision.Err = errInactiveOwner
		return decision
	}
	if a.registry != nil && !contracts.OwnershipAllows(node.Ownership, request.ProtocolMode, now) {
		decision.Err = errInactiveOwner
		return decision
	}
	if a.registry == nil && request.ProtocolMode != "legacy_single_device" {
		decision.Err = errInactiveOwner
		return decision
	}

	if request.ProtocolMode == "device_v2" {
		decision.ReplayClass = replayStrictlyNewer
		if !node.CollectedAt.IsZero() {
			switch {
			case request.CollectedAt.Before(node.CollectedAt):
				decision.Outcome = "stale_report"
				decision.ReplayClass = replayStale
				decision.Err = errStaleReport
				return decision
			case request.CollectedAt.Equal(node.CollectedAt):
				if request.HasRequestDigest && node.HasLastRequestDigest &&
					request.RequestDigest == node.LastRequestDigest {
					decision.Outcome = "idempotent"
					decision.ReplayClass = replayIdempotent
					decision.IsIdempotent = true
					decision.Err = errIdempotentReplay
					return decision
				}
				decision.Outcome = "report_conflict"
				decision.ReplayClass = replayConflict
				decision.Err = errReportConflict
				return decision
			}
		}
	}

	identityRejected := request.IdentityRejected
	if !request.IdentityClassified {
		identityStatus, identityErr := evaluateIdentity(
			node.ExpectedFQDN, request.ReportedFQDN, request.ProtocolMode,
		)
		decision.IdentityClass = identityStatus
		identityRejected = identityErr != nil
	}
	if identityRejected {
		decision.Outcome = "identity_mismatch"
		decision.ShouldRecordIdentityFailure = false
		decision.Err = errDeviceIdentity
		return decision
	}
	if !request.AssignGeneration &&
		(request.Generation == 0 || request.Generation <= node.LastAcceptedGeneration) {
		decision.Err = errStaleGeneration
		return decision
	}
	if request.ConnectionID != 0 &&
		(!node.Connected || node.ConnectionID != request.ConnectionID) {
		decision.Err = errInactiveConnection
		return decision
	}
	decision.Outcome = "accepted"
	decision.ShouldIngest = true
	return decision
}

func validateDeviceCollectedAt(collectedAt, now time.Time) error {
	if collectedAt.IsZero() ||
		collectedAt.Before(now.Add(-MaxDeviceClockSkew)) ||
		collectedAt.After(now.Add(MaxDeviceClockSkew)) {
		return errDeviceClockSkew
	}
	return nil
}

func (a *App) validateIngestLocked(
	node *NodeState,
	request deviceIngestRequest,
	now time.Time,
) error {
	return a.decideDeviceUpdateLocked(node, request, now).Err
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
	if extension.EasyTier != nil {
		extensionErrors = append(extensionErrors, extension.EasyTier.Error)
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
	if extension.EasyTier != nil {
		value := *extension.EasyTier
		extension.EasyTier = &value
		extension.EasyTier.Stale = true
		extension.EasyTier.Status = EasyTierStale
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
