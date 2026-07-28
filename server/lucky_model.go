package main

const (
	MaxLuckyPayloadBytes    = 512 * 1024
	MaxLuckyItems           = 256
	MaxLuckyNameLength      = 128
	MaxLuckyTextLength      = 256
	MaxLuckyVersionLength   = 64
	MaxLuckyBuildInfoLength = 128
	MaxLuckyStatusLength    = 32
	MaxLuckyProtocolLength  = 16
	MaxLuckyProviderLength  = 64
	MaxLuckyCertificateDays = int64(365000)
)

type LuckyStatus string

const (
	LuckyStatusOK            LuckyStatus = "ok"
	LuckyStatusDegraded      LuckyStatus = "degraded"
	LuckyStatusError         LuckyStatus = "error"
	LuckyStatusNotConfigured LuckyStatus = "not_configured"
	LuckyStatusUnavailable   LuckyStatus = "unavailable"
	LuckyStatusStale         LuckyStatus = "stale"
	LuckyStatusUnknown       LuckyStatus = "unknown"
)

type LuckySource string

const (
	LuckySourceAPI         LuckySource = "api"
	LuckySourceLocalAPI    LuckySource = "local_api"
	LuckySourceConfig      LuckySource = "config"
	LuckySourceCLI         LuckySource = "cli"
	LuckySourceWebFallback LuckySource = "web_fallback"
	LuckySourceUnavailable LuckySource = "unavailable"
)

type LuckyStats struct {
	Status       LuckyStatus            `json:"status"`
	Source       LuckySource            `json:"source"`
	Service      LuckyServiceStats      `json:"service"`
	Version      LuckyVersionStats      `json:"version"`
	IPResolution LuckyIPResolutionStats `json:"ip_resolution"`
	DynamicDNS   LuckyDynamicDNSStats   `json:"dynamic_dns"`
	WebServices  LuckyWebServicesStats  `json:"web_services"`
	PortForwards LuckyPortForwardsStats `json:"port_forwards"`
	Certificates LuckyCertificatesStats `json:"certificates"`
	UpdatedAt    *string                `json:"updated_at"`
	Stale        bool                   `json:"stale"`
	Error        *ExtensionError        `json:"error"`
}

type LuckyServiceStats struct {
	State          string          `json:"state"`
	ProcessRunning *bool           `json:"process_running"`
	ProcessPID     *int64          `json:"process_pid"`
	UptimeSeconds  *int64          `json:"uptime_seconds"`
	APIReachable   bool            `json:"api_reachable"`
	WebReachable   bool            `json:"web_reachable"`
	Error          *ExtensionError `json:"error"`
}

type LuckyVersionStats struct {
	Current         *string         `json:"current"`
	Latest          *string         `json:"latest"`
	UpdateAvailable *bool           `json:"update_available"`
	BuildInfo       *string         `json:"build_info"`
	CheckedAt       *string         `json:"checked_at"`
	Stale           bool            `json:"stale"`
	Error           *ExtensionError `json:"error"`
}

type LuckyIPResolutionStats struct {
	Mode            *string         `json:"mode"`
	ResolvedIPCount int             `json:"resolved_ip_count"`
	IPv4Count       int             `json:"ipv4_count"`
	IPv6Count       int             `json:"ipv6_count"`
	Status          LuckyStatus     `json:"status"`
	UpdatedAt       *string         `json:"updated_at"`
	Stale           bool            `json:"stale"`
	Error           *ExtensionError `json:"error"`
}

type LuckyDynamicDNSStats struct {
	Total      int               `json:"total"`
	Enabled    int               `json:"enabled"`
	Disabled   int               `json:"disabled"`
	Healthy    int               `json:"healthy"`
	ErrorCount int               `json:"error_count"`
	Records    []LuckyDDNSRecord `json:"records"`
	Status     LuckyStatus       `json:"status"`
	UpdatedAt  *string           `json:"updated_at"`
	Stale      bool              `json:"stale"`
	Error      *ExtensionError   `json:"error"`
}

type LuckyDDNSRecord struct {
	ID                      string          `json:"id"`
	DisplayName             string          `json:"display_name"`
	Provider                *string         `json:"provider"`
	AddressMethod           *string         `json:"address_method"`
	LocalRecordChangeStatus *string         `json:"local_record_change_status"`
	UpdatedRecords          *int64          `json:"updated_records"`
	TotalRecords            *int64          `json:"total_records"`
	Enabled                 bool            `json:"enabled"`
	Status                  string          `json:"status"`
	RecordType              *string         `json:"record_type"`
	LastUpdateAt            *string         `json:"last_update_at"`
	NextSyncAt              *string         `json:"next_sync_at"`
	LastSuccessAt           *string         `json:"last_success_at"`
	Error                   *ExtensionError `json:"error"`
}

type LuckyWebServicesStats struct {
	Total      int               `json:"total"`
	Enabled    int               `json:"enabled"`
	Disabled   int               `json:"disabled"`
	Healthy    int               `json:"healthy"`
	ErrorCount int               `json:"error_count"`
	Services   []LuckyWebService `json:"services"`
	Status     LuckyStatus       `json:"status"`
	UpdatedAt  *string           `json:"updated_at"`
	Stale      bool              `json:"stale"`
	Error      *ExtensionError   `json:"error"`
}

type LuckyWebService struct {
	ID              string          `json:"id"`
	DisplayName     string          `json:"display_name"`
	Enabled         bool            `json:"enabled"`
	Status          string          `json:"status"`
	Protocol        string          `json:"protocol"`
	ListenPort      *int            `json:"listen_port"`
	UpstreamType    *string         `json:"upstream_type"`
	TLSEnabled      bool            `json:"tls_enabled"`
	CertificateRef  *string         `json:"certificate_ref"`
	ConnectionCount *int64          `json:"connection_count"`
	EnabledSubrules *int64          `json:"enabled_subrules"`
	TotalSubrules   *int64          `json:"total_subrules"`
	Error           *ExtensionError `json:"error"`
}

type LuckyPortForwardsStats struct {
	Total      int                `json:"total"`
	Enabled    int                `json:"enabled"`
	Disabled   int                `json:"disabled"`
	Healthy    int                `json:"healthy"`
	ErrorCount int                `json:"error_count"`
	Rules      []LuckyPortForward `json:"rules"`
	Status     LuckyStatus        `json:"status"`
	UpdatedAt  *string            `json:"updated_at"`
	Stale      bool               `json:"stale"`
	Error      *ExtensionError    `json:"error"`
}

type LuckyPortForward struct {
	ID              string          `json:"id"`
	DisplayName     string          `json:"display_name"`
	Enabled         bool            `json:"enabled"`
	Status          string          `json:"status"`
	Protocol        string          `json:"protocol"`
	ListenPort      *int            `json:"listen_port"`
	TargetType      *string         `json:"target_type"`
	ConnectionCount *int64          `json:"connection_count"`
	Error           *ExtensionError `json:"error"`
}

type LuckyCertificatesStats struct {
	Total       int                `json:"total"`
	Valid       int                `json:"valid"`
	Expiring    int                `json:"expiring"`
	Expired     int                `json:"expired"`
	NotYetValid int                `json:"not_yet_valid"`
	Invalid     int                `json:"invalid"`
	Unknown     int                `json:"unknown"`
	Items       []LuckyCertificate `json:"items"`
	Status      LuckyStatus        `json:"status"`
	UpdatedAt   *string            `json:"updated_at"`
	Stale       bool               `json:"stale"`
	Error       *ExtensionError    `json:"error"`
}

type LuckyCertificate struct {
	ID            string          `json:"id"`
	DisplayName   string          `json:"display_name"`
	SANCount      int             `json:"san_count"`
	Issuer        *string         `json:"issuer"`
	Source        string          `json:"source"`
	NotBefore     *string         `json:"not_before"`
	NotAfter      *string         `json:"not_after"`
	RemainingDays *int64          `json:"remaining_days"`
	Status        string          `json:"status"`
	AutoRenew     *bool           `json:"auto_renew"`
	LastRenewAt   *string         `json:"last_renew_at"`
	NextRenewAt   *string         `json:"next_renew_at"`
	Error         *ExtensionError `json:"error"`
}

func NewNotReportedLuckyStats() LuckyStats {
	errorValue := newNotReportedError("lucky")
	return newEmptyLuckyStats(LuckyStatusUnknown, LuckySourceUnavailable, errorValue)
}

func newEmptyLuckyStats(status LuckyStatus, source LuckySource, errorValue *ExtensionError) LuckyStats {
	return LuckyStats{
		Status:       status,
		Source:       source,
		Service:      LuckyServiceStats{State: "unknown", Error: errorValue},
		Version:      LuckyVersionStats{Stale: true, Error: errorValue},
		IPResolution: LuckyIPResolutionStats{Status: status, Stale: true, Error: errorValue},
		DynamicDNS:   LuckyDynamicDNSStats{Records: make([]LuckyDDNSRecord, 0), Status: status, Stale: true, Error: errorValue},
		WebServices:  LuckyWebServicesStats{Services: make([]LuckyWebService, 0), Status: status, Stale: true, Error: errorValue},
		PortForwards: LuckyPortForwardsStats{Rules: make([]LuckyPortForward, 0), Status: status, Stale: true, Error: errorValue},
		Certificates: LuckyCertificatesStats{Items: make([]LuckyCertificate, 0), Status: status, Stale: true, Error: errorValue},
		Stale:        true,
		Error:        errorValue,
	}
}
