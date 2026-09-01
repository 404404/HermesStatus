package main

const (
	ExtensionSchemaVersion = "1.0-draft"
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
	MaxCPUTextLength           = 128
	MaxCPUCount                = 65536
	MaxCPUFrequencyMHz         = 1000000.0
	MaxTemperatureSourceLength = 128
	MaxDiskDeviceLength        = 128
	MaxDiskSmartSourceLength   = 64
	MaxPhysicalDisks           = 64
	MaxFilesystems             = 128
	MaxFilesystemBackingDisks  = 16
	MaxDiskModelLength         = 256
	MaxFilesystemSourceLength  = 256
	MaxMountpointLength        = 512
	MaxFilesystemTypeLength    = 64
	MaxStorageStackTypeLength  = 32
	MaxSystemIdentityLength    = 256
	MaxBuildVersionLength      = 64
	MaxBuildRevisionLength     = 64
	MaxDeploymentLength        = 32

	MaxDockerContainers   = 256
	MaxDockerCount        = 100000
	MaxDockerNameLength   = 256
	MaxDockerStatusLength = 128
	MaxDockerImageLength  = 256
	MaxDockerPortsLength  = 512

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
	// Storage inventory is bounded independently (64 physical disks and 128
	// filesystems), so the former single-disk hardware limit is too small.
	MaxHardwarePayloadBytes     = 256 * 1024
	MaxDockerPayloadBytes       = 512 * 1024
	MaxHermesPayloadBytes       = 1 << 20
	MaxEasyTierPayloadBytes     = 64 * 1024
	MaxUniFiPayloadBytes        = 64 * 1024
	MaxEasyTierTextLength       = 128
	MaxUniFiTextLength          = 128
	MaxUniFiFans                = 8
	MaxUniFiPowerSupplies       = 4
	MaxUniFiPowerProfiles       = 16
	MaxUniFiIgnoredObservations = 8
	MaxUniFiAPIEndpoints        = 24
	MaxUniFiAPIWans             = 16
	MaxUniFiAPIUplinks          = 32
	MaxUniFiAPITemperatures     = 16
	MaxUniFiPortRoles           = 4
	// Per-device limits cover one physical port table or static PoE map.
	MaxUniFiPortsPerDevice = 64
	// Site-wide API telemetry is the bounded union of all device observations.
	// 256 accepts the qualified 97-port site with margin while remaining bounded;
	// the existing whole-domain payload limit still applies independently.
	MaxUniFiSitePortObservations = 256
	MaxUniFiAPILags              = 16
	MaxUniFiAPITopologyLinks     = 32
	MaxUniFiAPIAnomalyTypes      = 4
)

type DiskSMARTStatus string

const (
	DiskSMARTPassed  DiskSMARTStatus = "passed"
	DiskSMARTFailed  DiskSMARTStatus = "failed"
	DiskSMARTUnknown DiskSMARTStatus = "unknown"
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
	Lucky            *LuckyStats    `json:"lucky,omitempty"`
	EasyTier         *EasyTierStats `json:"easytier,omitempty"`
	UniFi            *UniFiStats    `json:"unifi,omitempty"`
	// ClientBuild is an optional build provenance report. It is not an
	// identity input and is intentionally absent for older clients.
	ClientBuild *ClientBuildInfo `json:"client_build,omitempty"`
}

type ExtensionSnapshot struct {
	ExtensionVersion string           `json:"extension_version"`
	ReceivedAt       string           `json:"received_at"`
	Hardware         *HardwareStats   `json:"hardware"`
	Docker           *DockerStats     `json:"docker"`
	Hermes           *HermesStats     `json:"hermes"`
	Lucky            *LuckyStats      `json:"lucky"`
	EasyTier         *EasyTierStats   `json:"easytier"`
	UniFi            *UniFiStats      `json:"unifi"`
	ClientBuild      *ClientBuildInfo `json:"client_build,omitempty"`
}

type HardwareStats struct {
	CPUModel         *string               `json:"cpu_model"`
	CPUDetails       *CPUDetails           `json:"cpu_details,omitempty"`
	MemoryDetails    *MemoryDetails        `json:"memory_details,omitempty"`
	CPUTemperature   *TemperatureReading   `json:"cpu_temperature"`
	DiskTemperature  *DiskTemperatureStats `json:"disk_temperature"`
	DiskSMARTStatus  DiskSMARTStatus       `json:"disk_smart_status"`
	DiskPowerOnHours *int64                `json:"disk_power_on_hours"`
	DiskWrittenBytes *int64                `json:"disk_written_bytes"`
	DiskReadBytes    *int64                `json:"disk_read_bytes"`
	DiskDevice       *string               `json:"disk_device"`
	DiskSMARTSource  *string               `json:"disk_smart_source"`
	// Storage separates physical disks from mounted filesystems. It remains
	// optional so existing single-disk and older clients stay compatible.
	Storage        *StorageStats   `json:"storage,omitempty"`
	SystemIdentity *SystemIdentity `json:"system_identity,omitempty"`
	UpdatedAt      *string         `json:"updated_at"`
	Stale          bool            `json:"stale"`
	Error          *ExtensionError `json:"error"`
}

// CPUDetails is a bounded allowlist of host CPU topology fields. It is not a
// raw lscpu payload: capability flags, firmware strings, and arbitrary command
// output are intentionally excluded.
type CPUDetails struct {
	Architecture    *string        `json:"architecture"`
	Vendor          *string        `json:"vendor"`
	Family          *string        `json:"family"`
	ModelID         *string        `json:"model_id"`
	ModelName       *string        `json:"model_name"`
	Stepping        *string        `json:"stepping"`
	Virtualization  *string        `json:"virtualization"`
	L1DCache        *string        `json:"l1d_cache"`
	L1ICache        *string        `json:"l1i_cache"`
	L2Cache         *string        `json:"l2_cache"`
	L3Cache         *string        `json:"l3_cache"`
	LogicalCPUs     *int           `json:"logical_cpus"`
	Sockets         *int           `json:"sockets"`
	CoresPerSocket  *int           `json:"cores_per_socket"`
	ThreadsPerCore  *int           `json:"threads_per_core"`
	MaxMHz          *float64       `json:"max_mhz"`
	MinMHz          *float64       `json:"min_mhz"`
	CurrentMHz      *float64       `json:"current_mhz"`
	InstructionSets *string        `json:"instruction_sets"`
	Usage           *CPUUsageStats `json:"usage"`
}

// CPUUsageStats is a short sampling-window share of aggregate CPU time.
// IOWait is separate from idle so operators can distinguish storage pressure.
type CPUUsageStats struct {
	UserPercent    *float64 `json:"user_percent"`
	NicePercent    *float64 `json:"nice_percent"`
	SystemPercent  *float64 `json:"system_percent"`
	IdlePercent    *float64 `json:"idle_percent"`
	IOWaitPercent  *float64 `json:"iowait_percent"`
	IRQPercent     *float64 `json:"irq_percent"`
	SoftIRQPercent *float64 `json:"softirq_percent"`
	StealPercent   *float64 `json:"steal_percent"`
	TotalPercent   *float64 `json:"total_percent"`
}

// MemoryDetails provides host memory accounting from a bounded /proc/meminfo
// allowlist. It does not include process-level memory or page contents.
type MemoryDetails struct {
	TotalBytes       *int64 `json:"total_bytes"`
	UsedBytes        *int64 `json:"used_bytes"`
	AvailableBytes   *int64 `json:"available_bytes"`
	FreeBytes        *int64 `json:"free_bytes"`
	BuffersBytes     *int64 `json:"buffers_bytes"`
	CachedBytes      *int64 `json:"cached_bytes"`
	ReclaimableBytes *int64 `json:"reclaimable_bytes"`
	ActiveBytes      *int64 `json:"active_bytes"`
	InactiveBytes    *int64 `json:"inactive_bytes"`
	DirtyBytes       *int64 `json:"dirty_bytes"`
	WritebackBytes   *int64 `json:"writeback_bytes"`
	SlabBytes        *int64 `json:"slab_bytes"`
	SwapTotalBytes   *int64 `json:"swap_total_bytes"`
	SwapUsedBytes    *int64 `json:"swap_used_bytes"`
	SwapFreeBytes    *int64 `json:"swap_free_bytes"`
	SwapCachedBytes  *int64 `json:"swap_cached_bytes"`
}

// StorageStats is a bounded, read-only storage inventory. Physical disks and
// filesystems intentionally do not have a one-to-one relationship: LVM, MD
// RAID, device mapper, and Btrfs stacks can map a filesystem to many disks.
type StorageStats struct {
	PhysicalDisks []PhysicalDiskStats `json:"physical_disks"`
	Filesystems   []FilesystemStats   `json:"filesystems"`
	Summary       StorageSummary      `json:"summary"`
	UpdatedAt     *string             `json:"updated_at"`
	Stale         bool                `json:"stale"`
	Error         *ExtensionError     `json:"error"`
}

// PhysicalDiskStats deliberately omits serials, WWNs, UUIDs, SMART raw JSON,
// and SMART attribute tables. ID is a runtime kernel device identifier only.
type PhysicalDiskStats struct {
	ID               string          `json:"id"`
	Device           string          `json:"device"`
	Model            *string         `json:"model"`
	CapacityBytes    *int64          `json:"capacity_bytes"`
	TemperatureC     *float64        `json:"temperature_c"`
	SMARTStatus      DiskSMARTStatus `json:"smart_status"`
	PowerOnHours     *int64          `json:"power_on_hours"`
	WrittenBytes     *int64          `json:"written_bytes"`
	ReadBytes        *int64          `json:"read_bytes"`
	SMARTSource      *string         `json:"smart_source"`
	Completeness     *string         `json:"completeness"`
	HealthSource     *string         `json:"health_source"`
	NativeStatus     *string         `json:"native_status"`
	CollectionStatus string          `json:"collection_status"`
	Error            *ExtensionError `json:"error"`
}

type FilesystemStats struct {
	Source           *string         `json:"source"`
	Mountpoint       string          `json:"mountpoint"`
	FSType           *string         `json:"fs_type"`
	TotalBytes       *int64          `json:"total_bytes"`
	UsedBytes        *int64          `json:"used_bytes"`
	AvailableBytes   *int64          `json:"available_bytes"`
	UsagePercent     *float64        `json:"usage_percent"`
	BackingDiskIDs   []string        `json:"backing_disk_ids"`
	StackType        string          `json:"stack_type"`
	CollectionStatus string          `json:"collection_status"`
	Error            *ExtensionError `json:"error"`
}

type StorageSummary struct {
	PhysicalDiskCount int      `json:"physical_disk_count"`
	SMARTPassed       int      `json:"smart_passed"`
	SMARTFailed       int      `json:"smart_failed"`
	SMARTUnknown      int      `json:"smart_unknown"`
	TemperatureMinC   *float64 `json:"temperature_min_c"`
	TemperatureMaxC   *float64 `json:"temperature_max_c"`
	FilesystemCount   int      `json:"filesystem_count"`
}

// SystemIdentity carries only operating-system facts, never a hostname,
// FQDN, device identifier, or authentication evidence.
type SystemIdentity struct {
	Distribution   *string `json:"distribution"`
	ReleaseVersion *string `json:"release_version"`
	PrettyName     *string `json:"pretty_name"`
	KernelRelease  *string `json:"kernel_release"`
	Architecture   *string `json:"architecture"`
	Source         string  `json:"source"`
}

// ClientBuildInfo is image/build provenance reported by a Device v2 client.
// Revision must be a complete Git object ID when the optional object is sent.
type ClientBuildInfo struct {
	Version   string  `json:"version"`
	Revision  string  `json:"revision"`
	BuildTime *string `json:"build_time"`
	Protocol  string  `json:"protocol"`
}

// ServerBuildInfo is server-owned metadata. It is populated exclusively from
// build-time linker variables and a tightly allowlisted deployment setting;
// it never executes Git at runtime.
type ServerBuildInfo struct {
	Version    string  `json:"version"`
	Revision   string  `json:"revision"`
	BuildTime  *string `json:"build_time"`
	Deployment string  `json:"deployment"`
}

type TemperatureReading struct {
	Value  float64 `json:"value"`
	Unit   string  `json:"unit"`
	Source *string `json:"source"`
	Label  *string `json:"label,omitempty"`
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
	Names  string `json:"names"`
	Image  string `json:"image"`
	Status string `json:"status"`
	Ports  string `json:"ports"`
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
