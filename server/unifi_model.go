package main

// UniFi telemetry is an optional, profile-selected remote observation domain.
// It never participates in Device v2 identity or device online/offline status.
type UniFiTransportStatus string

const (
	UniFiTransportDisabled     UniFiTransportStatus = "disabled"
	UniFiTransportNotCollected UniFiTransportStatus = "not_collected"
	UniFiTransportAvailable    UniFiTransportStatus = "available"
	UniFiTransportUnavailable  UniFiTransportStatus = "unavailable"
)

type UniFiCapabilityState string

const (
	UniFiCapabilitySupported   UniFiCapabilityState = "supported"
	UniFiCapabilityUnknown     UniFiCapabilityState = "unknown"
	UniFiCapabilityUnsupported UniFiCapabilityState = "unsupported"
)

type UniFiPresenceState string

const (
	UniFiPresencePresent      UniFiPresenceState = "present"
	UniFiPresenceNotPresent   UniFiPresenceState = "not_present"
	UniFiPresenceNotPopulated UniFiPresenceState = "not_populated"
	UniFiPresenceUnknown      UniFiPresenceState = "unknown"
)

type UniFiObservationState string

const (
	UniFiObservationNotObserved     UniFiObservationState = "not_observed"
	UniFiObservationObserved        UniFiObservationState = "observed"
	UniFiObservationObservedZeroRPM UniFiObservationState = "observed_zero_rpm"
	UniFiObservationUnknown         UniFiObservationState = "unknown"
)

type UniFiStats struct {
	Configured    bool                `json:"configured"`
	Profile       *string             `json:"profile"`
	Transport     UniFiTransportStats `json:"transport"`
	System        *UniFiSystemStats   `json:"system"`
	Fans          []UniFiFanStats     `json:"fans"`
	PowerSupplies []UniFiPowerStats   `json:"power_supplies"`
	Storage       UniFiStorageStats   `json:"storage"`
	Diagnostics   UniFiDiagnostics    `json:"diagnostics"`
	UpdatedAt     *string             `json:"updated_at"`
	Stale         bool                `json:"stale"`
	Error         *ExtensionError     `json:"error"`
}

type UniFiTransportStats struct {
	Status      UniFiTransportStatus `json:"status"`
	LastAttempt *string              `json:"last_attempt"`
	LastSuccess *string              `json:"last_success"`
}

type UniFiSystemStats struct {
	CPUUsagePercent *float64          `json:"cpu_usage_percent"`
	CPUUsageReason  *string           `json:"cpu_usage_reason"`
	CPUTemperatureC *float64          `json:"cpu_temperature_c"`
	Memory          *UniFiMemoryStats `json:"memory"`
	UptimeSeconds   *float64          `json:"uptime_seconds"`
	LoadAverage     *UniFiLoadAverage `json:"load_average"`
}

type UniFiMemoryStats struct {
	TotalBytes      *int64   `json:"total_bytes"`
	AvailableBytes  *int64   `json:"available_bytes"`
	FreeBytes       *int64   `json:"free_bytes"`
	BuffersBytes    *int64   `json:"buffers_bytes"`
	CachedBytes     *int64   `json:"cached_bytes"`
	SwapTotalBytes  *int64   `json:"swap_total_bytes"`
	SwapFreeBytes   *int64   `json:"swap_free_bytes"`
	UsedBytes       *int64   `json:"used_bytes"`
	UsedPercent     *float64 `json:"used_percent"`
	AvailableSource string   `json:"available_source"`
}

type UniFiLoadAverage struct {
	OneMinute      *float64 `json:"one_minute"`
	FiveMinutes    *float64 `json:"five_minutes"`
	FifteenMinutes *float64 `json:"fifteen_minutes"`
}

type UniFiFanStats struct {
	ID        string                `json:"id"`
	Supported UniFiCapabilityState  `json:"supported"`
	Present   UniFiPresenceState    `json:"present"`
	Observed  bool                  `json:"observed"`
	RPM       *int                  `json:"rpm"`
	State     UniFiObservationState `json:"state"`
	Error     *ExtensionError       `json:"error"`
}

type UniFiPowerStats struct {
	ID        string                `json:"id"`
	Supported UniFiCapabilityState  `json:"supported"`
	Present   UniFiPresenceState    `json:"present"`
	Observed  bool                  `json:"observed"`
	State     UniFiObservationState `json:"state"`
	Error     *ExtensionError       `json:"error"`
}

type UniFiStorageStats struct {
	NVMe UniFiStorageCapability `json:"nvme"`
}

type UniFiStorageCapability struct {
	Supported UniFiCapabilityState `json:"supported"`
	Present   UniFiPresenceState   `json:"present"`
	Observed  bool                 `json:"observed"`
}

type UniFiDiagnostics struct {
	CollectionStatus string                    `json:"collection_status"`
	Ignored          []UniFiIgnoredObservation `json:"ignored_observations"`
}

type UniFiIgnoredObservation struct {
	ID     string `json:"id"`
	Reason string `json:"reason"`
}

func NewNotReportedUniFiStats() UniFiStats {
	return UniFiStats{
		Configured:    false,
		Transport:     UniFiTransportStats{Status: UniFiTransportDisabled},
		Fans:          make([]UniFiFanStats, 0),
		PowerSupplies: make([]UniFiPowerStats, 0),
		Storage: UniFiStorageStats{NVMe: UniFiStorageCapability{
			Supported: UniFiCapabilityUnknown,
			Present:   UniFiPresenceUnknown,
			Observed:  false,
		}},
		Diagnostics: UniFiDiagnostics{CollectionStatus: "not_collected", Ignored: make([]UniFiIgnoredObservation, 0)},
	}
}

func newDegradedUniFiStats(code string) *UniFiStats {
	stats := NewNotReportedUniFiStats()
	profile := "unknown"
	stats.Configured = true
	stats.Profile = &profile
	stats.Transport.Status = UniFiTransportUnavailable
	stats.Stale = true
	stats.Error = newPipelineError("unifi", code)
	return &stats
}
