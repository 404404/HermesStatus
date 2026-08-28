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
	API           *UniFiAPIStats      `json:"api,omitempty"`
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

type UniFiAPIStats struct {
	Enabled     bool               `json:"enabled"`
	Status      string             `json:"status"`
	LastAttempt *string            `json:"last_attempt"`
	LastSuccess *string            `json:"last_success"`
	Endpoints   []UniFiAPIEndpoint `json:"endpoints"`
	Summary     *UniFiAPISummary   `json:"summary"`
	Telemetry   *UniFiAPITelemetry `json:"telemetry"`
	Error       *ExtensionError    `json:"error"`
}

type UniFiAPIEndpoint struct {
	Name       string          `json:"name"`
	Status     string          `json:"status"`
	HTTPStatus *int            `json:"http_status"`
	Error      *ExtensionError `json:"error"`
}

type UniFiAPISummary struct {
	Model              *string `json:"model,omitempty"`
	Firmware           *string `json:"firmware,omitempty"`
	ApplicationVersion *string `json:"application_version,omitempty"`
}

type UniFiAPITelemetry struct {
	Identity     *UniFiAPIIdentity       `json:"identity"`
	Controller   *UniFiAPIController     `json:"controller"`
	WANs         []UniFiAPIWAN           `json:"wans"`
	Uplinks      []UniFiAPIUplink        `json:"uplinks"`
	Temperatures []UniFiAPITemperature   `json:"temperatures"`
	Clients      *UniFiAPIClientSummary  `json:"clients"`
	Devices      *UniFiAPIDeviceSummary  `json:"devices"`
	Networks     *UniFiAPINetworkSummary `json:"networks"`
	Ports        []UniFiAPIPort          `json:"ports"`
	PortSummary  *UniFiAPIPortSummary    `json:"port_summary"`
	LAGs         []UniFiAPILAG           `json:"lags"`
	Topology     *UniFiAPITopology       `json:"topology"`
	Anomalies    *UniFiAPIAnomalies      `json:"anomalies"`
}

type UniFiAPIIdentity struct {
	Model         *string  `json:"model,omitempty"`
	DisplayName   *string  `json:"display_name,omitempty"`
	Firmware      *string  `json:"firmware,omitempty"`
	Status        *string  `json:"status,omitempty"`
	UptimeSeconds *float64 `json:"uptime_seconds,omitempty"`
}

type UniFiAPIController struct {
	ApplicationVersion *string `json:"application_version,omitempty"`
	Build              *string `json:"build,omitempty"`
	UpdateAvailable    *bool   `json:"update_available,omitempty"`
	State              *string `json:"state,omitempty"`
}

type UniFiAPIWAN struct {
	ID                      *string  `json:"id,omitempty"`
	Name                    *string  `json:"name,omitempty"`
	Interface               *string  `json:"interface,omitempty"`
	ISP                     *string  `json:"isp,omitempty"`
	LinkState               *string  `json:"link_state,omitempty"`
	Online                  *bool    `json:"online,omitempty"`
	Active                  *bool    `json:"active,omitempty"`
	Standby                 *bool    `json:"standby,omitempty"`
	UptimeSeconds           *float64 `json:"uptime_seconds,omitempty"`
	DowntimeSeconds         *float64 `json:"downtime_seconds,omitempty"`
	LatencyMs               *float64 `json:"latency_ms,omitempty"`
	PacketLossPercent       *float64 `json:"packet_loss_percent,omitempty"`
	RxBPS                   *int64   `json:"rx_bps,omitempty"`
	TxBPS                   *int64   `json:"tx_bps,omitempty"`
	RxBytes                 *int64   `json:"rx_bytes,omitempty"`
	TxBytes                 *int64   `json:"tx_bytes,omitempty"`
	ConfiguredUpstreamBPS   *int64   `json:"configured_upstream_bps,omitempty"`
	ConfiguredDownstreamBPS *int64   `json:"configured_downstream_bps,omitempty"`
	FailoverState           *string  `json:"failover_state,omitempty"`
	LoadBalancingState      *string  `json:"load_balancing_state,omitempty"`
}

type UniFiAPIUplink struct {
	Name      *string  `json:"name,omitempty"`
	LinkState *string  `json:"link_state,omitempty"`
	SpeedMbps *float64 `json:"speed_mbps,omitempty"`
	Duplex    *string  `json:"duplex,omitempty"`
	WANID     *string  `json:"wan_id,omitempty"`
}

type UniFiAPITemperature struct {
	ID      string  `json:"id"`
	Label   string  `json:"label"`
	Celsius float64 `json:"celsius"`
	Source  string  `json:"source"`
}

type UniFiAPIPort struct {
	DeviceID         string       `json:"device_id"`
	PortIndex        int          `json:"port_idx"`
	Name             *string      `json:"name,omitempty"`
	Media            *string      `json:"media,omitempty"`
	Enabled          *bool        `json:"enabled,omitempty"`
	Up               *bool        `json:"up,omitempty"`
	SpeedMbps        *float64     `json:"speed_mbps,omitempty"`
	Duplex           *bool        `json:"duplex,omitempty"`
	Autoneg          *bool        `json:"autoneg,omitempty"`
	Uplink           *bool        `json:"uplink,omitempty"`
	RxBytes          *int64       `json:"rx_bytes,omitempty"`
	TxBytes          *int64       `json:"tx_bytes,omitempty"`
	RxPackets        *int64       `json:"rx_packets,omitempty"`
	TxPackets        *int64       `json:"tx_packets,omitempty"`
	RxErrors         *int64       `json:"rx_errors,omitempty"`
	TxErrors         *int64       `json:"tx_errors,omitempty"`
	RxDropped        *int64       `json:"rx_dropped,omitempty"`
	TxDropped        *int64       `json:"tx_dropped,omitempty"`
	RxMulticast      *int64       `json:"rx_multicast,omitempty"`
	TxMulticast      *int64       `json:"tx_multicast,omitempty"`
	RxBroadcast      *int64       `json:"rx_broadcast,omitempty"`
	TxBroadcast      *int64       `json:"tx_broadcast,omitempty"`
	RxBPS            *int64       `json:"rx_bps,omitempty"`
	TxBPS            *int64       `json:"tx_bps,omitempty"`
	RxUtilizationPct *float64     `json:"rx_utilization_pct,omitempty"`
	TxUtilizationPct *float64     `json:"tx_utilization_pct,omitempty"`
	PoE              *UniFiAPIPoE `json:"poe,omitempty"`
	PeerCount        *int         `json:"peer_count,omitempty"`
}

type UniFiAPIPoE struct {
	Supported *bool    `json:"supported,omitempty"`
	Enabled   *bool    `json:"enabled,omitempty"`
	Active    *bool    `json:"active,omitempty"`
	State     *string  `json:"state,omitempty"`
	Mode      *string  `json:"mode,omitempty"`
	Class     *string  `json:"class,omitempty"`
	PowerW    *float64 `json:"power_w,omitempty"`
	VoltageV  *float64 `json:"voltage_v,omitempty"`
	CurrentMA *float64 `json:"current_ma,omitempty"`
	Good      *bool    `json:"good,omitempty"`
}

type UniFiAPIPortSummary struct {
	Total          int      `json:"total"`
	Up             int      `json:"up"`
	Down           int      `json:"down"`
	PoEActive      int      `json:"poe_active"`
	PoETotalPowerW *float64 `json:"poe_total_power_w,omitempty"`
}

type UniFiAPILAG struct {
	LAGID  string `json:"lag_id"`
	Member string `json:"lag_member"`
}

type UniFiAPITopologyLink struct {
	SourceDeviceID *string `json:"source_device_id,omitempty"`
	TargetDeviceID *string `json:"target_device_id,omitempty"`
	State          *string `json:"state,omitempty"`
}

type UniFiAPITopology struct {
	LinkCount int                    `json:"link_count"`
	Links     []UniFiAPITopologyLink `json:"links"`
}

type UniFiAPIAnomalies struct {
	AnomalyCount      int      `json:"anomaly_count"`
	AffectedPortCount int      `json:"affected_port_count"`
	RecentTypes       []string `json:"recent_types"`
}

type UniFiAPIClientSummary struct {
	Total    int  `json:"total"`
	Wired    *int `json:"wired"`
	Wireless *int `json:"wireless"`
	Observed bool `json:"observed"`
}

type UniFiAPIDeviceSummary struct {
	Total   int            `json:"total"`
	Online  int            `json:"online"`
	Offline int            `json:"offline"`
	ByType  map[string]int `json:"by_type"`
}

type UniFiAPINetworkSummary struct {
	Total int `json:"total"`
	VLAN  int `json:"vlan"`
}

type UniFiSystemStats struct {
	CPUModel        *string           `json:"cpu_model"`
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
	NVMe UniFiStorageCapability  `json:"nvme"`
	SATA *UniFiStorageCapability `json:"sata_ssd,omitempty"`
	TF   *UniFiStorageCapability `json:"tf,omitempty"`
}

type UniFiStorageCapability struct {
	Supported     UniFiCapabilityState `json:"supported"`
	Present       UniFiPresenceState   `json:"present"`
	Observed      bool                 `json:"observed"`
	CapacityBytes *int64               `json:"capacity_bytes,omitempty"`
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
