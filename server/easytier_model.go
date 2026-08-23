package main

type EasyTierStatus string

const (
	EasyTierHealthy            EasyTierStatus = "healthy"
	EasyTierDegraded           EasyTierStatus = "degraded"
	EasyTierUnavailable        EasyTierStatus = "unavailable"
	EasyTierStale              EasyTierStatus = "stale"
	EasyTierNotConfigured      EasyTierStatus = "not_configured"
	EasyTierUnsupportedVersion EasyTierStatus = "unsupported_version"
	EasyTierInvalidData        EasyTierStatus = "invalid_data"
)

type EasyTierSource string

const (
	EasyTierSourceCLI         EasyTierSource = "easytier_cli"
	EasyTierSourceUnavailable EasyTierSource = "unavailable"
)

// EasyTierStats is intentionally a small monitoring projection. It must never
// carry the EasyTier configuration, RPC endpoint, credentials, command text,
// or stderr. Retained endpoints and STUN values are bounded observations only.
type EasyTierStats struct {
	Status        EasyTierStatus          `json:"status"`
	Source        EasyTierSource          `json:"source"`
	Node          EasyTierNodeStats       `json:"node"`
	Peers         EasyTierPeerStats       `json:"peers"`
	Routes        EasyTierRouteStats      `json:"routes"`
	Connectors    EasyTierConnectorStats  `json:"connectors"`
	Traffic       EasyTierTrafficStats    `json:"traffic"`
	CommandStatus EasyTierCommandStatuses `json:"command_status"`
	UpdatedAt     *string                 `json:"updated_at"`
	Stale         bool                    `json:"stale"`
	Error         *ExtensionError         `json:"error"`
}

type EasyTierNodeStats struct {
	State               string           `json:"state"`
	InstanceName        *string          `json:"instance_name"`
	NetworkName         *string          `json:"network_name"`
	Version             *string          `json:"version"`
	PeerID              *string          `json:"peer_id"`
	OverlayIPv4         *string          `json:"overlay_ipv4,omitempty"`
	ProxyCIDRs          []string         `json:"proxy_cidrs,omitempty"`
	AdministrativeRole  *string          `json:"administrative_role,omitempty"`
	Hostname            *string          `json:"hostname,omitempty"`
	InstanceID          *string          `json:"inst_id,omitempty"`
	Listeners           []string         `json:"listeners,omitempty"`
	STUNInfo            EasyTierSTUNInfo `json:"stun_info,omitempty"`
	SchemaCompatibility string           `json:"schema_compatibility,omitempty"`
}

// EasyTierSTUNInfo contains only topology facts from the node response. It
// deliberately excludes raw STUN server configuration and any credential.
type EasyTierSTUNInfo struct {
	UDPNATType     *string  `json:"udp_nat_type,omitempty"`
	TCPNATType     *string  `json:"tcp_nat_type,omitempty"`
	PublicIPs      []string `json:"public_ips,omitempty"`
	LastUpdateTime *string  `json:"last_update_time,omitempty"`
}

type EasyTierPeerStats struct {
	Total         int            `json:"total"`
	Direct        int            `json:"direct"`
	Relay         int            `json:"relay"`
	UnknownPath   int            `json:"unknown_path"`
	IPv6UDPDirect *bool          `json:"ipv6_udp_direct"`
	Items         []EasyTierPeer `json:"items,omitempty"`
}

type EasyTierPeer struct {
	PeerID             *string  `json:"peer_id"`
	OverlayIPv4        *string  `json:"overlay_ipv4"`
	Hostname           *string  `json:"hostname"`
	Version            *string  `json:"version"`
	PathState          string   `json:"path_state"`
	Transport          string   `json:"transport"`
	AddressFamily      string   `json:"address_family"`
	LocallyInitiated   bool     `json:"locally_initiated"`
	LatencyMS          *float64 `json:"latency_ms"`
	LossRate           *float64 `json:"loss_rate"`
	RXBytes            int64    `json:"rx_bytes"`
	TXBytes            int64    `json:"tx_bytes"`
	RXPackets          int64    `json:"rx_packets"`
	TXPackets          int64    `json:"tx_packets"`
	Closed             bool     `json:"closed"`
	Cost               *string  `json:"cost,omitempty"`
	EstablishedTunnels []string `json:"established_tunnels,omitempty"`
	NATType            *string  `json:"nat_type,omitempty"`
	RXDisplay          *string  `json:"rx_display,omitempty"`
	TXDisplay          *string  `json:"tx_display,omitempty"`
}

type EasyTierRouteStats struct {
	Total int             `json:"total"`
	Items []EasyTierRoute `json:"items,omitempty"`
}

type EasyTierRoute struct {
	PeerID        *string  `json:"peer_id"`
	OverlayIPv4   *string  `json:"overlay_ipv4"`
	Hostname      *string  `json:"hostname"`
	Version       *string  `json:"version"`
	NextHopPeerID *string  `json:"next_hop_peer_id"`
	Cost          *int     `json:"cost"`
	PathLatencyMS *float64 `json:"path_latency_ms"`
	ProxyCIDRs    []string `json:"proxy_cidrs"`
	PathState     string   `json:"path_state"`
	IsLocal       bool     `json:"is_local"`
}

type EasyTierConnectorStats struct {
	Total                int                 `json:"total"`
	TCPConfigured        bool                `json:"tcp_configured"`
	TCPActive            bool                `json:"tcp_active"`
	TCPListenerAvailable *bool               `json:"tcp_listener_available,omitempty"`
	Items                []EasyTierConnector `json:"items,omitempty"`
}

type EasyTierConnector struct {
	URL           *string `json:"url,omitempty"`
	Endpoint      *string `json:"endpoint,omitempty"`
	Transport     string  `json:"transport"`
	AddressFamily string  `json:"address_family"`
	Port          *int    `json:"port"`
	RawStatus     *int    `json:"raw_status,omitempty"`
	Status        string  `json:"status"`
}

type EasyTierTrafficStats struct {
	BytesRX        int64                     `json:"bytes_rx"`
	BytesTX        int64                     `json:"bytes_tx"`
	BytesForwarded int64                     `json:"bytes_forwarded"`
	PacketsRX      int64                     `json:"packets_rx,omitempty"`
	PacketsTX      int64                     `json:"packets_tx,omitempty"`
	RXBPS          *float64                  `json:"rx_bps,omitempty"`
	TXBPS          *float64                  `json:"tx_bps,omitempty"`
	ByInstance     []EasyTierInstanceTraffic `json:"by_instance,omitempty"`
	Samples        []EasyTierMetricSample    `json:"samples,omitempty"`
}

// EasyTierInstanceTraffic retains the label relationship supplied by the CLI;
// it does not infer remote device identity from an EasyTier instance ID.
type EasyTierInstanceTraffic struct {
	NetworkName    *string `json:"network_name,omitempty"`
	FromInstanceID *string `json:"from_instance_id,omitempty"`
	ToInstanceID   *string `json:"to_instance_id,omitempty"`
	BytesRX        *int64  `json:"bytes_rx,omitempty"`
	BytesTX        *int64  `json:"bytes_tx,omitempty"`
	PacketsRX      *int64  `json:"packets_rx,omitempty"`
	PacketsTX      *int64  `json:"packets_tx,omitempty"`
}

// EasyTierMetricSample uses name + labels as its identity. It contains bounded
// raw counters only, never EasyTier configuration or RPC payloads.
type EasyTierMetricSample struct {
	Name   string            `json:"name"`
	Value  int64             `json:"value"`
	Labels map[string]string `json:"labels"`
}

type EasyTierCommandStatus struct {
	Status        EasyTierStatus  `json:"status"`
	LastSuccessAt *string         `json:"last_success_at,omitempty"`
	CollectedAt   *string         `json:"collected_at,omitempty"`
	DurationMS    *int            `json:"duration_ms,omitempty"`
	Error         *ExtensionError `json:"error"`
}

type EasyTierCommandStatuses struct {
	NodeInfo      EasyTierCommandStatus `json:"node_info"`
	PeerList      EasyTierCommandStatus `json:"peer_list"`
	RouteList     EasyTierCommandStatus `json:"route_list"`
	ConnectorList EasyTierCommandStatus `json:"connector_list"`
	StatsShow     EasyTierCommandStatus `json:"stats_show"`
}

func NewNotReportedEasyTierStats() EasyTierStats {
	errorValue := newNotReportedError("easytier")
	return newEmptyEasyTierStats(EasyTierNotConfigured, EasyTierSourceUnavailable, errorValue)
}

func newEmptyEasyTierStats(status EasyTierStatus, source EasyTierSource, errorValue *ExtensionError) EasyTierStats {
	command := EasyTierCommandStatus{Status: status, Error: errorValue}
	return EasyTierStats{
		Status: status, Source: source,
		Node:  EasyTierNodeStats{State: "unknown"},
		Peers: EasyTierPeerStats{}, Routes: EasyTierRouteStats{},
		Connectors: EasyTierConnectorStats{}, Traffic: EasyTierTrafficStats{},
		CommandStatus: EasyTierCommandStatuses{command, command, command, command, command},
		Stale:         true, Error: errorValue,
	}
}
