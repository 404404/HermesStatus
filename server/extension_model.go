package main

const (
	ExtensionSchemaVersion = "1.0-draft"
	HiddenDockerCommand    = "[hidden]"
	RedactedValue          = "[redacted]"

	MaxExtensionVersionLength = 32
	MaxTimestampLength        = 40
	MaxSafeInteger            = int64(9007199254740991)
	MinTemperatureCelsius     = -100.0
	MaxTemperatureCelsius     = 250.0

	MaxErrorCodeLength    = 64
	MaxErrorMessageLength = 256
	MaxErrorSourceLength  = 64
	MinHTTPStatus         = 100
	MaxHTTPStatus         = 599

	MaxCPUModelLength          = 128
	MaxTemperatureSourceLength = 128
	MaxDiskDeviceLength        = 128
	MaxDiskSmartSourceLength   = 64

	MaxDockerContainers    = 256
	MaxDockerCount         = 100000
	MaxDockerIDLength      = 64
	MaxDockerNameLength    = 256
	MaxDockerStatusLength  = 128
	MaxDockerCreatedLength = 64
	MaxDockerImageLength   = 256
	MaxDockerCommandLength = 512
	MaxDockerPortsLength   = 512

	MaxHermesProfiles        = 64
	MaxProfileNameLength     = 64
	MaxAgentVersionLength    = 64
	MaxServiceStatusLength   = 64
	MaxGatewayServiceLength  = 64
	MaxManagerModeLength     = 96
	MaxProviderLength        = 128
	MaxModelLength           = 256
	MaxHermesCounter         = int64(1000000000)
	MaxDockerVolumes         = 64
	MaxDockerVolumeLength    = 512
	MaxAuxiliaryModels       = 32
	MaxAuxiliaryNameLength   = 64
	MaxBaseURLLength         = 256
	MaxReasoningEffortLength = 64
	MaxMOATools              = 64
	MaxMOANameLength         = 128
	MaxMOADescriptionLength  = 512

	MaxLegacyHardwareJSONBytes = 4 * 1024
	MaxLegacyDockerJSONBytes   = 32 * 1024
	MaxLegacyHermesJSONBytes   = 32 * 1024

	MaxExtensionPayloadBytes = 1 << 20
	MaxHardwarePayloadBytes  = 8 * 1024
	MaxDockerPayloadBytes    = 512 * 1024
	MaxHermesPayloadBytes    = 1 << 20
)

type DiskSMARTStatus string

const (
	DiskSMARTPassed  DiskSMARTStatus = "passed"
	DiskSMARTFailed  DiskSMARTStatus = "failed"
	DiskSMARTUnknown DiskSMARTStatus = "unknown"
)

type DockerContainerState string

const (
	DockerStateCreated    DockerContainerState = "created"
	DockerStateRunning    DockerContainerState = "running"
	DockerStatePaused     DockerContainerState = "paused"
	DockerStateRestarting DockerContainerState = "restarting"
	DockerStateRemoving   DockerContainerState = "removing"
	DockerStateExited     DockerContainerState = "exited"
	DockerStateDead       DockerContainerState = "dead"
	DockerStateUnknown    DockerContainerState = "unknown"
)

type HermesAPIStatus string

const (
	HermesAPIOK           HermesAPIStatus = "ok"
	HermesAPIHealthy      HermesAPIStatus = "healthy"
	HermesAPIUnauthorized HermesAPIStatus = "unauthorized"
	HermesAPITimeout      HermesAPIStatus = "timeout"
	HermesAPIUnavailable  HermesAPIStatus = "unavailable"
	HermesAPIError        HermesAPIStatus = "error"
	HermesAPIUnknown      HermesAPIStatus = "unknown"
)

type HermesUsageMode string

const (
	HermesUsageAPI          HermesUsageMode = "api"
	HermesUsageAuthProvider HermesUsageMode = "auth_provider"
	HermesUsageUnknown      HermesUsageMode = "unknown"
)

type TokenUsageSource string

const (
	TokenSourceHermesAPI         TokenUsageSource = "hermes_api_payload"
	TokenSourceLocalSessionState TokenUsageSource = "local_session_state"
	TokenSourceLocalLogs         TokenUsageSource = "local_logs"
	TokenSourceUnavailable       TokenUsageSource = "unavailable"
)

type ExtensionStats struct {
	ExtensionVersion string         `json:"extension_version"`
	Hardware         *HardwareStats `json:"hardware"`
	Docker           *DockerStats   `json:"docker"`
	Hermes           *HermesStats   `json:"hermes"`
}

type ExtensionSnapshot struct {
	ExtensionVersion string         `json:"extension_version"`
	ReceivedAt       string         `json:"received_at"`
	Hardware         *HardwareStats `json:"hardware"`
	Docker           *DockerStats   `json:"docker"`
	Hermes           *HermesStats   `json:"hermes"`
}

type HardwareStats struct {
	CPUModel         *string               `json:"cpu_model"`
	CPUTemperature   *TemperatureReading   `json:"cpu_temperature"`
	DiskTemperature  *DiskTemperatureStats `json:"disk_temperature"`
	DiskSMARTStatus  DiskSMARTStatus       `json:"disk_smart_status"`
	DiskPowerOnHours *int64                `json:"disk_power_on_hours"`
	DiskWrittenBytes *int64                `json:"disk_written_bytes"`
	DiskReadBytes    *int64                `json:"disk_read_bytes"`
	DiskDevice       *string               `json:"disk_device"`
	DiskSMARTSource  *string               `json:"disk_smart_source"`
	UpdatedAt        *string               `json:"updated_at"`
	Stale            bool                  `json:"stale"`
	Error            *ExtensionError       `json:"error"`
}

type TemperatureReading struct {
	Value  float64 `json:"value"`
	Unit   string  `json:"unit"`
	Source *string `json:"source"`
}

type DiskTemperatureStats struct {
	Current *float64 `json:"current"`
	Highest *float64 `json:"highest"`
	Lowest  *float64 `json:"lowest"`
	Unit    string   `json:"unit"`
	Source  *string  `json:"source"`
}

type DockerStats struct {
	Running    int                    `json:"running"`
	Total      int                    `json:"total"`
	Limit      int                    `json:"limit"`
	Truncated  bool                   `json:"truncated"`
	Containers []DockerContainerStats `json:"containers"`
	UpdatedAt  *string                `json:"updated_at"`
	Stale      bool                   `json:"stale"`
	Error      *ExtensionError        `json:"error"`
}

type DockerContainerStats struct {
	ID      string               `json:"id"`
	Names   string               `json:"names"`
	State   DockerContainerState `json:"state"`
	Status  string               `json:"status"`
	Created string               `json:"created"`
	Image   string               `json:"image"`
	Command string               `json:"command"`
	Ports   string               `json:"ports"`
}

type HermesStats struct {
	Profiles  []HermesProfileStats `json:"profiles"`
	UpdatedAt *string              `json:"updated_at"`
	Stale     bool                 `json:"stale"`
	Error     *ExtensionError      `json:"error"`
}

type HermesProfileStats struct {
	Profile             string                  `json:"profile"`
	AgentVersion        *string                 `json:"agent_version"`
	APIStatus           HermesAPIStatus         `json:"api_status"`
	ServiceStatus       *string                 `json:"service_status"`
	GatewayService      *string                 `json:"gateway_service"`
	ManagerMode         *string                 `json:"manager_mode"`
	UsageMode           *HermesUsageMode        `json:"usage_mode"`
	Provider            *string                 `json:"provider"`
	Model               *string                 `json:"model"`
	AuthRefreshedAt     *string                 `json:"auth_refreshed_at"`
	ScheduledJobsActive *int64                  `json:"scheduled_jobs_active"`
	ScheduledJobsTotal  *int64                  `json:"scheduled_jobs_total"`
	SessionsActive      *int64                  `json:"sessions_active"`
	SessionsTotal       *int64                  `json:"sessions_total"`
	SessionsHasMore     bool                    `json:"sessions_has_more"`
	Usage               TokenUsageStats         `json:"usage"`
	ConfigSummary       *SanitizedConfigSummary `json:"config_summary"`
	MixtureOfAgents     *MixtureOfAgentsStats   `json:"mixture_of_agents"`
	UpdatedAt           *string                 `json:"updated_at"`
	ReceivedAt          *string                 `json:"received_at"`
	Stale               bool                    `json:"stale"`
	Error               *ExtensionError         `json:"error"`
}

type TokenUsageStats struct {
	InputTokens  *int64           `json:"input_tokens"`
	OutputTokens *int64           `json:"output_tokens"`
	TotalTokens  *int64           `json:"total_tokens"`
	Estimated    bool             `json:"estimated"`
	Source       TokenUsageSource `json:"source"`
	WindowStart  *string          `json:"window_start"`
	WindowEnd    *string          `json:"window_end"`
}

type ExtensionError struct {
	Code       string `json:"code"`
	Message    string `json:"message"`
	Source     string `json:"source"`
	Retryable  bool   `json:"retryable"`
	HTTPStatus *int   `json:"http_status"`
}

type SanitizedConfigSummary struct {
	ConfigFound     bool                    `json:"config_found"`
	MainModel       ConfigModelSummary      `json:"main_model"`
	AuxiliaryModels []AuxiliaryModelSummary `json:"auxiliary_models"`
	Delegation      DelegationSummary       `json:"delegation"`
	DockerVolumes   []string                `json:"docker_volumes"`
}

type ConfigModelSummary struct {
	Provider       string   `json:"provider"`
	Model          string   `json:"model"`
	BaseURL        string   `json:"base_url"`
	Concurrency    *int64   `json:"concurrency"`
	TimeoutSeconds *float64 `json:"timeout_seconds"`
}

type AuxiliaryModelSummary struct {
	Name                   string   `json:"name"`
	Provider               string   `json:"provider"`
	Model                  string   `json:"model"`
	EffectiveProvider      string   `json:"effective_provider"`
	EffectiveModel         string   `json:"effective_model"`
	Source                 string   `json:"source"`
	BaseURLDisplay         string   `json:"base_url_display"`
	TimeoutSeconds         *float64 `json:"timeout_seconds"`
	DownloadTimeoutSeconds *float64 `json:"download_timeout_seconds"`
	MaxConcurrency         *int64   `json:"max_concurrency"`
	Language               string   `json:"language"`
	ExtraBodyConfigured    bool     `json:"extra_body_configured"`
	CredentialConfigured   bool     `json:"credential_configured"`
}

type DelegationSummary struct {
	Provider              string   `json:"provider"`
	Model                 string   `json:"model"`
	BaseURL               string   `json:"base_url"`
	ReasoningEffort       string   `json:"reasoning_effort"`
	MaxConcurrentChildren *int64   `json:"max_concurrent_children"`
	MaxSpawnDepth         *int64   `json:"max_spawn_depth"`
	ChildTimeoutSeconds   *float64 `json:"child_timeout_seconds"`
}

type MixtureOfAgentsStats struct {
	Source      string   `json:"source"`
	Available   bool     `json:"available"`
	Name        string   `json:"name"`
	Label       string   `json:"label"`
	Description string   `json:"description"`
	Enabled     *bool    `json:"enabled"`
	Configured  *bool    `json:"configured"`
	Tools       []string `json:"tools"`
	Error       *string  `json:"error"`
}

// legacyExtensionWire exists only for the B2 transition decoder. It is not
// embedded in any normal stats type and cannot be serialized accidentally.
type legacyExtensionWire struct {
	HardwareJSON string `json:"hardware_json,omitempty"`
	DockerJSON   string `json:"docker_json,omitempty"`
	HermesJSON   string `json:"hermes_json,omitempty"`
}

func NewNotReportedHardwareStats() HardwareStats {
	return HardwareStats{
		DiskSMARTStatus: DiskSMARTUnknown,
		Stale:           true,
		Error:           newNotReportedError("hardware"),
	}
}

func NewNotReportedDockerStats() DockerStats {
	return DockerStats{
		Containers: make([]DockerContainerStats, 0),
		Stale:      true,
		Error:      newNotReportedError("docker"),
	}
}

func NewNotReportedHermesStats() HermesStats {
	return HermesStats{
		Profiles: make([]HermesProfileStats, 0),
		Stale:    true,
		Error:    newNotReportedError("hermes"),
	}
}

func NewUnavailableTokenUsageStats() TokenUsageStats {
	return TokenUsageStats{
		Estimated: true,
		Source:    TokenSourceUnavailable,
	}
}

func newNotReportedError(source string) *ExtensionError {
	return &ExtensionError{
		Code:      "not_reported",
		Message:   "Extension data was not reported",
		Source:    source,
		Retryable: false,
	}
}
