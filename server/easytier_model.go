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
// carry the EasyTier configuration, RPC endpoint, peer endpoint, credentials,
// STUN results, command text, or stderr.
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
	State        string  `json:"state"`
	InstanceName *string `json:"instance_name"`
	NetworkName  *string `json:"network_name"`
	Version      *string `json:"version"`
	PeerID       *string `json:"peer_id"`
}

type EasyTierPeerStats struct {
	Total       int `json:"total"`
	Direct      int `json:"direct"`
	Relay       int `json:"relay"`
	UnknownPath int `json:"unknown_path"`
}

type EasyTierRouteStats struct {
	Total int `json:"total"`
}

type EasyTierConnectorStats struct {
	Total         int  `json:"total"`
	TCPConfigured bool `json:"tcp_configured"`
	TCPActive     bool `json:"tcp_active"`
}

type EasyTierTrafficStats struct {
	BytesRX        int64 `json:"bytes_rx"`
	BytesTX        int64 `json:"bytes_tx"`
	BytesForwarded int64 `json:"bytes_forwarded"`
}

type EasyTierCommandStatus struct {
	Status EasyTierStatus  `json:"status"`
	Error  *ExtensionError `json:"error"`
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
