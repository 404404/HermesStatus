package main

func statsResponse() map[string]any {
	return map[string]any{
		"200": jsonResponse("WebUI 状态数据", schemaRef("StatsDocument")),
		"4XX": jsonResponse("请求错误", schemaRef("Error")),
	}
}

func extensionOpenAPISchemas() map[string]any {
	nullableString := func(maxLength int, description string) map[string]any {
		return map[string]any{"type": []string{"string", "null"}, "maxLength": maxLength, "description": description}
	}
	nullableInteger := func(maximum int64, description string) map[string]any {
		return map[string]any{"type": []string{"integer", "null"}, "minimum": 0, "maximum": maximum, "description": description}
	}
	nullableNumber := func(description string) map[string]any {
		return map[string]any{"type": []string{"number", "null"}, "minimum": MinTemperatureCelsius, "maximum": MaxTemperatureCelsius, "description": description}
	}
	nullableDuration := func(description string) map[string]any {
		return map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 86400, "description": description}
	}
	nullableRef := func(name string) map[string]any {
		return map[string]any{"anyOf": []any{schemaRef(name), map[string]any{"type": "null"}}}
	}
	requiredObject := func(required []string, properties map[string]any) map[string]any {
		return map[string]any{
			"type":                 "object",
			"required":             required,
			"properties":           properties,
			"additionalProperties": false,
		}
	}

	extensionError := requiredObject(
		[]string{"code", "message", "source", "retryable", "http_status"},
		map[string]any{
			"code":        map[string]any{"type": "string", "maxLength": MaxErrorCodeLength, "pattern": "^[a-z0-9_]+$"},
			"message":     map[string]any{"type": "string", "maxLength": MaxErrorMessageLength},
			"source":      map[string]any{"type": "string", "maxLength": MaxErrorSourceLength, "pattern": "^[A-Za-z0-9_.-]+$"},
			"retryable":   map[string]any{"type": "boolean"},
			"http_status": map[string]any{"type": []string{"integer", "null"}, "minimum": MinHTTPStatus, "maximum": MaxHTTPStatus},
		},
	)
	temperature := requiredObject(
		[]string{"value", "unit", "source"},
		map[string]any{
			"value":  map[string]any{"type": "number", "minimum": MinTemperatureCelsius, "maximum": MaxTemperatureCelsius},
			"unit":   map[string]any{"type": "string", "const": "C"},
			"source": nullableString(MaxTemperatureSourceLength, "Sanitized sensor label"),
			"label":  nullableString(MaxTemperatureSourceLength, "Sanitized CPU sensor label"),
		},
	)
	diskTemperature := requiredObject(
		[]string{"current", "highest", "lowest", "unit", "source"},
		map[string]any{
			"current": nullableNumber("Current disk temperature in Celsius"),
			"highest": nullableNumber("Highest observed disk temperature in Celsius"),
			"lowest":  nullableNumber("Lowest observed disk temperature in Celsius"),
			"unit":    map[string]any{"type": "string", "const": "C"},
			"source":  nullableString(MaxTemperatureSourceLength, "Sanitized SMART source label"),
		},
	)
	physicalDisk := requiredObject(
		[]string{"id", "device", "model", "capacity_bytes", "temperature_c", "smart_status", "power_on_hours", "written_bytes", "read_bytes", "smart_source", "collection_status"},
		map[string]any{
			"id":                map[string]any{"type": "string", "maxLength": MaxDiskDeviceLength, "pattern": "^[A-Za-z0-9][A-Za-z0-9_.+-]*$"},
			"device":            map[string]any{"type": "string", "maxLength": MaxDiskDeviceLength, "pattern": "^/dev/[A-Za-z0-9._+/-]+$"},
			"model":             nullableString(MaxDiskModelLength, "Sanitized disk model without serial or WWN"),
			"capacity_bytes":    nullableInteger(MaxSafeInteger, "Physical device capacity"),
			"temperature_c":     nullableNumber("Physical disk temperature in Celsius"),
			"smart_status":      map[string]any{"type": "string", "enum": []string{"passed", "failed", "unknown"}},
			"power_on_hours":    nullableInteger(MaxSafeInteger, "SMART power-on hours"),
			"written_bytes":     nullableInteger(MaxSafeInteger, "SMART lifetime bytes written"),
			"read_bytes":        nullableInteger(MaxSafeInteger, "SMART lifetime bytes read"),
			"smart_source":      nullableString(MaxDiskSmartSourceLength, "Safe SMART collector source label"),
			"completeness":      map[string]any{"type": []string{"string", "null"}, "enum": []any{"complete", "partial", "unavailable", nil}},
			"health_source":     map[string]any{"type": []string{"string", "null"}, "enum": []any{"native_status", "attribute_check", "unknown", nil}},
			"native_status":     map[string]any{"type": []string{"string", "null"}, "enum": []any{"available", "unavailable", "unknown", nil}},
			"collection_status": map[string]any{"type": "string", "enum": []string{"healthy", "partial", "unavailable", "unsupported", "permission_denied", "invalid_data"}},
			"error":             nullableRef("ExtensionError"),
		},
	)
	filesystem := requiredObject(
		[]string{"source", "mountpoint", "fs_type", "total_bytes", "used_bytes", "available_bytes", "usage_percent", "backing_disk_ids", "stack_type", "collection_status"},
		map[string]any{
			"source":            nullableString(MaxFilesystemSourceLength, "Sanitized backing block-device path when observed"),
			"mountpoint":        map[string]any{"type": "string", "maxLength": MaxMountpointLength, "pattern": "^/.*$", "description": "Absolute display path; control characters and parent traversal are rejected"},
			"fs_type":           nullableString(MaxFilesystemTypeLength, "Filesystem type when observed"),
			"total_bytes":       nullableInteger(MaxSafeInteger, "Filesystem capacity"),
			"used_bytes":        nullableInteger(MaxSafeInteger, "Filesystem used bytes"),
			"available_bytes":   nullableInteger(MaxSafeInteger, "Filesystem available bytes"),
			"usage_percent":     map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100},
			"backing_disk_ids":  map[string]any{"type": "array", "maxItems": MaxFilesystemBackingDisks, "items": map[string]any{"type": "string", "maxLength": MaxDiskDeviceLength, "pattern": "^[A-Za-z0-9][A-Za-z0-9_.+-]*$"}, "default": []any{}},
			"stack_type":        map[string]any{"type": "string", "enum": []string{"plain", "lvm", "mdraid", "device_mapper", "btrfs", "unknown"}},
			"collection_status": map[string]any{"type": "string", "enum": []string{"healthy", "unavailable", "unsupported", "permission_denied", "invalid_data"}},
			"error":             nullableRef("ExtensionError"),
		},
	)
	storageSummary := requiredObject(
		[]string{"physical_disk_count", "smart_passed", "smart_failed", "smart_unknown", "temperature_min_c", "temperature_max_c", "filesystem_count"},
		map[string]any{
			"physical_disk_count": integerOpenAPISchema(), "smart_passed": integerOpenAPISchema(), "smart_failed": integerOpenAPISchema(), "smart_unknown": integerOpenAPISchema(),
			"temperature_min_c": nullableNumber("Lowest observed physical disk temperature"), "temperature_max_c": nullableNumber("Highest observed physical disk temperature"), "filesystem_count": integerOpenAPISchema(),
		},
	)
	storageStats := requiredObject(
		[]string{"physical_disks", "filesystems", "summary", "updated_at", "stale", "error"},
		map[string]any{
			"physical_disks": map[string]any{"type": "array", "maxItems": MaxPhysicalDisks, "items": schemaRef("PhysicalDiskStats"), "default": []any{}},
			"filesystems":    map[string]any{"type": "array", "maxItems": MaxFilesystems, "items": schemaRef("FilesystemStats"), "default": []any{}},
			"summary":        schemaRef("StorageSummary"),
			"updated_at":     nullableString(MaxTimestampLength, "Storage collection time in RFC3339"),
			"stale":          map[string]any{"type": "boolean"},
			"error":          nullableRef("ExtensionError"),
		},
	)
	systemIdentity := requiredObject(
		[]string{"distribution", "release_version", "pretty_name", "kernel_release", "architecture", "source"},
		map[string]any{
			"distribution":    nullableString(MaxSystemIdentityLength, "Host distribution"),
			"release_version": nullableString(MaxSystemIdentityLength, "Host release version"),
			"pretty_name":     nullableString(MaxSystemIdentityLength, "Host operating system display name"),
			"kernel_release":  nullableString(MaxSystemIdentityLength, "Host kernel release"),
			"architecture":    nullableString(MaxSystemIdentityLength, "Host architecture"),
			"source":          map[string]any{"type": "string", "enum": []string{"os-release", "dsm-version", "unknown", "unavailable"}},
		},
	)
	cpuUsage := requiredObject(
		[]string{"user_percent", "nice_percent", "system_percent", "idle_percent", "iowait_percent", "irq_percent", "softirq_percent", "steal_percent", "total_percent"},
		map[string]any{
			"user_percent": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100, "description": "Aggregate CPU user-time percentage"}, "nice_percent": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100, "description": "Aggregate CPU nice-time percentage"},
			"system_percent": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100, "description": "Aggregate CPU system-time percentage"}, "idle_percent": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100, "description": "Aggregate CPU idle-time percentage"},
			"iowait_percent": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100, "description": "Aggregate CPU I/O-wait percentage"}, "irq_percent": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100, "description": "Aggregate CPU IRQ percentage"},
			"softirq_percent": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100, "description": "Aggregate CPU soft-IRQ percentage"}, "steal_percent": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100, "description": "Aggregate CPU steal-time percentage"},
			"total_percent": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100, "description": "Aggregate non-idle CPU percentage"},
		},
	)
	cpuDetails := requiredObject(
		// instruction_sets is an additive optional field so older Device v2
		// clients remain valid while a server upgrade is rolling out.
		[]string{"architecture", "vendor", "family", "model_id", "model_name", "stepping", "virtualization", "l1d_cache", "l1i_cache", "l2_cache", "l3_cache", "logical_cpus", "sockets", "cores_per_socket", "threads_per_core", "max_mhz", "min_mhz", "current_mhz", "usage"},
		map[string]any{
			"architecture": nullableString(MaxCPUTextLength, "CPU architecture"), "vendor": nullableString(MaxCPUTextLength, "CPU vendor"),
			"family": nullableString(MaxCPUTextLength, "CPU family"), "model_id": nullableString(MaxCPUTextLength, "CPU model identifier"),
			"model_name": nullableString(MaxCPUModelLength, "CPU model name"), "stepping": nullableString(MaxCPUTextLength, "CPU stepping"),
			"virtualization": nullableString(MaxCPUTextLength, "CPU virtualization capability"), "l1d_cache": nullableString(MaxCPUTextLength, "L1 data cache"),
			"l1i_cache": nullableString(MaxCPUTextLength, "L1 instruction cache"), "l2_cache": nullableString(MaxCPUTextLength, "L2 cache"),
			"l3_cache":     nullableString(MaxCPUTextLength, "L3 cache"),
			"logical_cpus": nullableInteger(MaxCPUCount, "Logical CPU count"), "sockets": nullableInteger(MaxCPUCount, "CPU socket count"),
			"cores_per_socket": nullableInteger(MaxCPUCount, "CPU cores per socket"), "threads_per_core": nullableInteger(MaxCPUCount, "CPU threads per core"),
			"max_mhz":          map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": MaxCPUFrequencyMHz},
			"min_mhz":          map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": MaxCPUFrequencyMHz},
			"current_mhz":      map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": MaxCPUFrequencyMHz},
			"instruction_sets": nullableString(MaxCPUTextLength, "Bounded CPU instruction-set summary"),
			"usage":            nullableRef("CPUUsageStats"),
		},
	)
	memoryDetails := requiredObject(
		[]string{"total_bytes", "used_bytes", "available_bytes", "free_bytes", "buffers_bytes", "cached_bytes", "reclaimable_bytes", "active_bytes", "inactive_bytes", "dirty_bytes", "writeback_bytes", "slab_bytes", "swap_total_bytes", "swap_used_bytes", "swap_free_bytes", "swap_cached_bytes"},
		map[string]any{
			"total_bytes": nullableInteger(MaxSafeInteger, "Total host memory"), "used_bytes": nullableInteger(MaxSafeInteger, "Used host memory"),
			"available_bytes": nullableInteger(MaxSafeInteger, "Available host memory"), "free_bytes": nullableInteger(MaxSafeInteger, "Free host memory"),
			"buffers_bytes": nullableInteger(MaxSafeInteger, "Host buffer memory"), "cached_bytes": nullableInteger(MaxSafeInteger, "Host page cache memory"),
			"reclaimable_bytes": nullableInteger(MaxSafeInteger, "Reclaimable slab memory"), "active_bytes": nullableInteger(MaxSafeInteger, "Active memory"),
			"inactive_bytes": nullableInteger(MaxSafeInteger, "Inactive memory"), "dirty_bytes": nullableInteger(MaxSafeInteger, "Dirty memory"),
			"writeback_bytes": nullableInteger(MaxSafeInteger, "Writeback memory"), "slab_bytes": nullableInteger(MaxSafeInteger, "Slab memory"),
			"swap_total_bytes": nullableInteger(MaxSafeInteger, "Total swap"), "swap_used_bytes": nullableInteger(MaxSafeInteger, "Used swap"),
			"swap_free_bytes": nullableInteger(MaxSafeInteger, "Free swap"), "swap_cached_bytes": nullableInteger(MaxSafeInteger, "Swap cache"),
		},
	)
	clientBuild := requiredObject(
		[]string{"version", "revision", "build_time", "protocol"},
		map[string]any{
			"version":    map[string]any{"type": "string", "maxLength": MaxBuildVersionLength},
			"revision":   map[string]any{"type": "string", "maxLength": MaxBuildRevisionLength, "pattern": "^[0-9a-f]{40}$"},
			"build_time": nullableString(MaxTimestampLength, "Client build time in RFC3339"),
			"protocol":   map[string]any{"type": "string", "const": "device_v2"},
		},
	)
	serverBuild := requiredObject(
		[]string{"version", "revision", "build_time", "deployment"},
		map[string]any{
			"version":    map[string]any{"type": "string", "maxLength": MaxBuildVersionLength},
			"revision":   map[string]any{"type": "string", "maxLength": MaxBuildRevisionLength},
			"build_time": nullableString(MaxTimestampLength, "Server build time in RFC3339"),
			"deployment": map[string]any{"type": "string", "enum": []string{"production", "preview", "staging", "development", "unknown"}},
		},
	)
	hardware := requiredObject(
		[]string{"cpu_model", "cpu_temperature", "disk_temperature", "disk_smart_status", "disk_power_on_hours", "disk_written_bytes", "disk_read_bytes", "disk_device", "disk_smart_source", "updated_at", "stale", "error"},
		map[string]any{
			"cpu_model":           nullableString(MaxCPUModelLength, "Sanitized CPU model"),
			"cpu_details":         nullableRef("CPUDetails"),
			"memory_details":      nullableRef("MemoryDetails"),
			"cpu_temperature":     nullableRef("TemperatureReading"),
			"disk_temperature":    nullableRef("DiskTemperature"),
			"disk_smart_status":   map[string]any{"type": "string", "enum": []string{"passed", "failed", "unknown"}},
			"disk_power_on_hours": nullableInteger(MaxSafeInteger, "Disk power-on hours"),
			"disk_written_bytes":  nullableInteger(MaxSafeInteger, "Lifetime bytes written"),
			"disk_read_bytes":     nullableInteger(MaxSafeInteger, "Lifetime bytes read"),
			"disk_device":         nullableString(MaxDiskDeviceLength, "Sanitized device label"),
			"disk_smart_source":   nullableString(MaxDiskSmartSourceLength, "Fixed SMART collector source label"),
			"storage":             nullableRef("StorageStats"),
			"system_identity":     nullableRef("SystemIdentity"),
			"updated_at":          nullableString(MaxTimestampLength, "Client collection time in RFC3339"),
			"stale":               map[string]any{"type": "boolean", "description": "Recomputed by the Go server using a 900 second threshold"},
			"error":               nullableRef("ExtensionError"),
		},
	)
	hardware["example"] = map[string]any{
		"cpu_model": "Example CPU", "cpu_temperature": nil, "disk_temperature": nil,
		"disk_smart_status": "unknown", "disk_power_on_hours": nil, "disk_written_bytes": nil,
		"disk_read_bytes": nil, "disk_device": nil, "disk_smart_source": nil,
		"cpu_details": nil, "memory_details": nil, "storage": nil, "system_identity": nil,
		"updated_at": nil, "stale": true,
		"error": map[string]any{"code": "not_reported", "message": "Extension data was not reported", "source": "hardware", "retryable": false, "http_status": nil},
	}

	dockerContainer := requiredObject(
		[]string{"names", "image", "status", "ports"},
		map[string]any{
			"names":  map[string]any{"type": "string", "maxLength": MaxDockerNameLength},
			"image":  map[string]any{"type": "string", "maxLength": MaxDockerImageLength},
			"status": map[string]any{"type": "string", "maxLength": MaxDockerStatusLength},
			"ports":  map[string]any{"type": "string", "maxLength": MaxDockerPortsLength},
		},
	)
	dockerStats := requiredObject(
		[]string{"running", "total", "limit", "truncated", "containers", "updated_at", "stale", "error"},
		map[string]any{
			"running":   map[string]any{"type": "integer", "minimum": 0, "maximum": MaxDockerCount},
			"total":     map[string]any{"type": "integer", "minimum": 0, "maximum": MaxDockerCount},
			"limit":     map[string]any{"type": "integer", "minimum": 0, "maximum": MaxDockerContainers},
			"truncated": map[string]any{"type": "boolean"},
			"containers": map[string]any{
				"type": "array", "maxItems": MaxDockerContainers, "items": schemaRef("DockerContainerStats"), "default": []any{},
			},
			"updated_at": nullableString(MaxTimestampLength, "Client collection time in RFC3339"),
			"stale":      map[string]any{"type": "boolean", "description": "Recomputed by the Go server using a 120 second threshold"},
			"error":      nullableRef("ExtensionError"),
		},
	)
	dockerStats["example"] = map[string]any{
		"running": 1, "total": 1, "limit": 0, "truncated": false,
		"containers": []any{map[string]any{
			"names": "status-service", "image": "example/status-service:2.0",
			"status": "Up 2 hours", "ports": "-",
		}},
		"updated_at": "2026-07-13T12:00:00Z", "stale": false, "error": nil,
	}

	tokenUsage := requiredObject(
		[]string{"input_tokens", "output_tokens", "total_tokens", "estimated", "source", "window_start", "window_end"},
		map[string]any{
			"input_tokens":  nullableInteger(MaxSafeInteger, "Input tokens for the stated diagnostic window"),
			"output_tokens": nullableInteger(MaxSafeInteger, "Output tokens for the stated diagnostic window"),
			"total_tokens":  nullableInteger(MaxSafeInteger, "Input plus output tokens"),
			"estimated":     map[string]any{"type": "boolean"},
			"source":        map[string]any{"type": "string", "enum": []string{"hermes_api_payload", "local_session_state", "local_logs", "unavailable"}},
			"window_start":  nullableString(MaxTimestampLength, "Diagnostic window start in RFC3339"),
			"window_end":    nullableString(MaxTimestampLength, "Diagnostic window end in RFC3339"),
		},
	)
	configModel := requiredObject(
		[]string{"provider", "model", "base_url", "concurrency", "timeout_seconds"},
		map[string]any{
			"provider":        map[string]any{"type": "string", "maxLength": MaxProviderLength},
			"model":           map[string]any{"type": "string", "maxLength": MaxModelLength},
			"base_url":        map[string]any{"type": "string", "maxLength": MaxBaseURLLength, "description": "Sanitized URL without credentials, query, or fragment"},
			"concurrency":     nullableInteger(MaxHermesCounter, "Configured main-model concurrency"),
			"timeout_seconds": nullableDuration("Configured main-model timeout"),
		},
	)
	auxiliaryModel := requiredObject(
		[]string{"name", "provider", "model", "effective_provider", "effective_model", "source", "base_url_display", "timeout_seconds", "download_timeout_seconds", "max_concurrency", "language", "extra_body_configured", "credential_configured"},
		map[string]any{
			"name":                     map[string]any{"type": "string", "maxLength": MaxAuxiliaryNameLength},
			"provider":                 map[string]any{"type": "string", "maxLength": MaxProviderLength},
			"model":                    map[string]any{"type": "string", "maxLength": MaxModelLength},
			"effective_provider":       map[string]any{"type": "string", "maxLength": MaxProviderLength},
			"effective_model":          map[string]any{"type": "string", "maxLength": MaxModelLength},
			"source":                   map[string]any{"type": "string", "maxLength": MaxAuxiliaryNameLength, "enum": []string{"config", "main_model"}},
			"base_url_display":         map[string]any{"type": "string", "maxLength": MaxBaseURLLength},
			"timeout_seconds":          nullableDuration("Auxiliary model timeout"),
			"download_timeout_seconds": nullableDuration("Auxiliary download timeout"),
			"max_concurrency":          nullableInteger(MaxHermesCounter, "Auxiliary model concurrency"),
			"language":                 map[string]any{"type": "string", "maxLength": MaxAuxiliaryNameLength},
			"extra_body_configured":    map[string]any{"type": "boolean"},
			"credential_configured":    map[string]any{"type": "boolean", "description": "Boolean presence flag only; secret values are never returned"},
		},
	)
	delegation := requiredObject(
		[]string{"provider", "model", "base_url", "reasoning_effort", "max_concurrent_children", "max_spawn_depth", "child_timeout_seconds"},
		map[string]any{
			"provider":                map[string]any{"type": "string", "maxLength": MaxProviderLength},
			"model":                   map[string]any{"type": "string", "maxLength": MaxModelLength},
			"base_url":                map[string]any{"type": "string", "maxLength": MaxBaseURLLength},
			"reasoning_effort":        map[string]any{"type": "string", "maxLength": MaxReasoningEffortLength},
			"max_concurrent_children": nullableInteger(MaxHermesCounter, "Maximum concurrent delegated children"),
			"max_spawn_depth":         nullableInteger(MaxHermesCounter, "Maximum delegation depth"),
			"child_timeout_seconds":   nullableDuration("Delegated child timeout"),
		},
	)
	configSummary := requiredObject(
		[]string{"config_found", "main_model", "auxiliary_models", "delegation", "docker_volumes"},
		map[string]any{
			"config_found": map[string]any{"type": "boolean"},
			"main_model":   schemaRef("ConfigModelSummary"),
			"auxiliary_models": map[string]any{
				"type": "array", "maxItems": MaxAuxiliaryModels, "items": schemaRef("AuxiliaryModelSummary"), "default": []any{},
			},
			"delegation": schemaRef("DelegationSummary"),
			"docker_volumes": map[string]any{
				"type": "array", "maxItems": MaxDockerVolumes, "items": map[string]any{"type": "string", "maxLength": MaxDockerVolumeLength}, "default": []any{},
			},
		},
	)
	mixtureOfAgents := requiredObject(
		[]string{"source", "available", "name", "label", "description", "enabled", "configured", "tools", "error"},
		map[string]any{
			"source":      map[string]any{"type": "string", "maxLength": MaxErrorSourceLength},
			"available":   map[string]any{"type": "boolean"},
			"name":        map[string]any{"type": "string", "maxLength": MaxMOANameLength},
			"label":       map[string]any{"type": "string", "maxLength": MaxMOANameLength},
			"description": map[string]any{"type": "string", "maxLength": MaxMOADescriptionLength},
			"enabled":     map[string]any{"type": []string{"boolean", "null"}},
			"configured":  map[string]any{"type": []string{"boolean", "null"}},
			"tools":       map[string]any{"type": "array", "maxItems": MaxMOATools, "items": map[string]any{"type": "string", "maxLength": MaxMOANameLength}, "default": []any{}},
			"error":       nullableString(MaxErrorCodeLength, "Safe diagnostic code"),
		},
	)
	hermesProfile := requiredObject(
		[]string{"profile", "agent_version", "api_status", "service_status", "gateway_service", "manager_mode", "usage_mode", "provider", "model", "auth_refreshed_at", "scheduled_jobs_active", "scheduled_jobs_total", "sessions_active", "sessions_total", "sessions_has_more", "usage", "config_summary", "mixture_of_agents", "updated_at", "received_at", "stale", "error"},
		map[string]any{
			"profile":               map[string]any{"type": "string", "maxLength": MaxProfileNameLength, "pattern": "^[A-Za-z0-9_.-]+$"},
			"agent_version":         nullableString(MaxAgentVersionLength, "Hermes Agent version"),
			"api_status":            map[string]any{"type": "string", "enum": []string{"ok", "healthy", "unauthorized", "timeout", "unavailable", "error", "unknown"}},
			"service_status":        nullableString(MaxServiceStatusLength, "Service state"),
			"gateway_service":       nullableString(MaxGatewayServiceLength, "Gateway state"),
			"manager_mode":          nullableString(MaxManagerModeLength, "Gateway manager mode"),
			"usage_mode":            map[string]any{"type": []string{"string", "null"}, "enum": []any{"api", "auth_provider", "unknown", nil}},
			"provider":              nullableString(MaxProviderLength, "Sanitized provider display name"),
			"model":                 nullableString(MaxModelLength, "Sanitized model display name"),
			"auth_refreshed_at":     nullableString(MaxTimestampLength, "Provider refresh time in RFC3339"),
			"scheduled_jobs_active": nullableInteger(MaxHermesCounter, "Active scheduled jobs"),
			"scheduled_jobs_total":  nullableInteger(MaxHermesCounter, "Total scheduled jobs"),
			"sessions_active":       nullableInteger(MaxHermesCounter, "Active sessions"),
			"sessions_total":        nullableInteger(MaxHermesCounter, "Total sessions"),
			"sessions_has_more":     map[string]any{"type": "boolean", "description": "True when the configured pagination ceiling was reached"},
			"usage":                 schemaRef("TokenUsageStats"),
			"config_summary":        nullableRef("SanitizedConfigSummary"),
			"mixture_of_agents":     nullableRef("MixtureOfAgentsStats"),
			"updated_at":            nullableString(MaxTimestampLength, "Profile collection time in RFC3339"),
			"received_at":           nullableString(MaxTimestampLength, "Profile snapshot write time in RFC3339"),
			"stale":                 map[string]any{"type": "boolean", "description": "Recomputed by the Go server using a 900 second threshold"},
			"error":                 nullableRef("ExtensionError"),
		},
	)
	hermesStats := requiredObject(
		[]string{"profiles", "updated_at", "stale", "error"},
		map[string]any{
			"profiles":   map[string]any{"type": "array", "maxItems": MaxHermesProfiles, "items": schemaRef("HermesProfileStats"), "default": []any{}},
			"updated_at": nullableString(MaxTimestampLength, "Exporter collection time in RFC3339"),
			"stale":      map[string]any{"type": "boolean", "description": "Recomputed by the Go server using a 900 second threshold"},
			"error":      nullableRef("ExtensionError"),
		},
	)
	hermesStats["example"] = map[string]any{
		"profiles": []any{map[string]any{
			"profile": "profile-example", "agent_version": nil, "api_status": "unknown", "service_status": nil,
			"gateway_service": nil, "manager_mode": nil, "usage_mode": nil, "provider": nil, "model": nil,
			"auth_refreshed_at": nil, "scheduled_jobs_active": nil, "scheduled_jobs_total": nil,
			"sessions_active": nil, "sessions_total": nil, "sessions_has_more": false,
			"usage":          map[string]any{"input_tokens": nil, "output_tokens": nil, "total_tokens": nil, "estimated": true, "source": "unavailable", "window_start": nil, "window_end": nil},
			"config_summary": nil, "mixture_of_agents": nil, "updated_at": nil, "received_at": nil, "stale": true,
			"error": map[string]any{"code": "not_reported", "message": "Extension data was not reported", "source": "hermes", "retryable": false, "http_status": nil},
		}},
		"updated_at": nil, "stale": true,
		"error": map[string]any{"code": "not_reported", "message": "Extension data was not reported", "source": "hermes", "retryable": false, "http_status": nil},
	}

	luckyStatus := map[string]any{"type": "string", "enum": []string{"ok", "degraded", "error", "not_configured", "unavailable", "stale", "unknown"}}
	luckySource := map[string]any{"type": "string", "enum": []string{"api", "local_api", "config", "cli", "web_fallback", "unavailable"}}
	luckyModuleProperties := func(itemsName, itemSchema string) map[string]any {
		return map[string]any{
			"total":       map[string]any{"type": "integer", "minimum": 0, "maximum": MaxLuckyItems},
			"enabled":     map[string]any{"type": "integer", "minimum": 0, "maximum": MaxLuckyItems},
			"disabled":    map[string]any{"type": "integer", "minimum": 0, "maximum": MaxLuckyItems},
			"healthy":     map[string]any{"type": "integer", "minimum": 0, "maximum": MaxLuckyItems},
			"error_count": map[string]any{"type": "integer", "minimum": 0, "maximum": MaxLuckyItems},
			itemsName:     map[string]any{"type": "array", "maxItems": MaxLuckyItems, "items": schemaRef(itemSchema), "default": []any{}},
			"status":      luckyStatus, "updated_at": nullableString(MaxTimestampLength, "Module collection time in RFC3339"),
			"stale": map[string]any{"type": "boolean"}, "error": nullableRef("ExtensionError"),
		}
	}
	luckyDDNSRecord := requiredObject(
		[]string{"id", "display_name", "provider", "address_method", "local_record_change_status", "updated_records", "total_records", "enabled", "status", "record_type", "last_update_at", "next_sync_at", "last_success_at", "error"},
		map[string]any{
			"id": map[string]any{"type": "string", "maxLength": MaxLuckyNameLength}, "display_name": map[string]any{"type": "string", "maxLength": MaxLuckyNameLength},
			"provider": nullableString(MaxLuckyProviderLength, "Sanitized provider name"), "enabled": map[string]any{"type": "boolean"},
			"address_method": nullableString(MaxLuckyTextLength, "Sanitized address acquisition method"), "local_record_change_status": nullableString(MaxLuckyStatusLength, "Sanitized local record change state"),
			"updated_records": nullableInteger(MaxSafeInteger, "Updated domain record count"), "total_records": nullableInteger(MaxSafeInteger, "Total domain record count"),
			"status": map[string]any{"type": "string", "maxLength": MaxLuckyStatusLength}, "record_type": nullableString(MaxLuckyStatusLength, "Record type"),
			"last_update_at": nullableString(MaxTimestampLength, "Last synchronization time"), "next_sync_at": nullableString(MaxTimestampLength, "Next scheduled synchronization time"), "last_success_at": nullableString(MaxTimestampLength, "Last successful update time"), "error": nullableRef("ExtensionError"),
		},
	)
	luckyWebService := requiredObject(
		[]string{"id", "display_name", "enabled", "status", "protocol", "listen_port", "upstream_type", "tls_enabled", "certificate_ref", "connection_count", "enabled_subrules", "total_subrules", "error"},
		map[string]any{
			"id": map[string]any{"type": "string", "maxLength": MaxLuckyNameLength}, "display_name": map[string]any{"type": "string", "maxLength": MaxLuckyNameLength},
			"enabled": map[string]any{"type": "boolean"}, "status": map[string]any{"type": "string", "maxLength": MaxLuckyStatusLength},
			"protocol": map[string]any{"type": "string", "maxLength": MaxLuckyProtocolLength}, "listen_port": map[string]any{"type": []string{"integer", "null"}, "minimum": 1, "maximum": 65535},
			"upstream_type": nullableString(MaxLuckyStatusLength, "Sanitized upstream class"), "tls_enabled": map[string]any{"type": "boolean"},
			"certificate_ref": nullableString(MaxLuckyNameLength, "Sanitized certificate label"), "connection_count": nullableInteger(MaxSafeInteger, "Current connection count"),
			"enabled_subrules": nullableInteger(MaxSafeInteger, "Enabled Web subrule count"), "total_subrules": nullableInteger(MaxSafeInteger, "Total Web subrule count"), "error": nullableRef("ExtensionError"),
		},
	)
	luckyPortForward := requiredObject(
		[]string{"id", "display_name", "enabled", "status", "protocol", "listen_port", "target_type", "connection_count", "error"},
		map[string]any{
			"id": map[string]any{"type": "string", "maxLength": MaxLuckyNameLength}, "display_name": map[string]any{"type": "string", "maxLength": MaxLuckyNameLength},
			"enabled": map[string]any{"type": "boolean"}, "status": map[string]any{"type": "string", "maxLength": MaxLuckyStatusLength},
			"protocol": map[string]any{"type": "string", "maxLength": MaxLuckyProtocolLength}, "listen_port": map[string]any{"type": []string{"integer", "null"}, "minimum": 1, "maximum": 65535},
			"target_type": nullableString(MaxLuckyStatusLength, "Sanitized target class"), "connection_count": nullableInteger(MaxSafeInteger, "Current connection count"), "error": nullableRef("ExtensionError"),
		},
	)
	luckyCertificate := requiredObject(
		[]string{"id", "display_name", "san_count", "issuer", "source", "not_before", "not_after", "remaining_days", "status", "auto_renew", "last_renew_at", "next_renew_at", "error"},
		map[string]any{
			"id": map[string]any{"type": "string", "maxLength": MaxLuckyNameLength}, "display_name": map[string]any{"type": "string", "maxLength": MaxLuckyNameLength},
			"san_count": map[string]any{"type": "integer", "minimum": 0, "maximum": MaxDockerCount}, "issuer": nullableString(MaxLuckyNameLength, "Sanitized issuer"),
			"source": map[string]any{"type": "string", "maxLength": MaxLuckyStatusLength}, "not_before": nullableString(MaxTimestampLength, "Certificate activation time"),
			"not_after": nullableString(MaxTimestampLength, "Certificate expiration time"), "remaining_days": map[string]any{"type": []string{"integer", "null"}, "minimum": -MaxLuckyCertificateDays, "maximum": MaxLuckyCertificateDays},
			"status": map[string]any{"type": "string", "enum": []string{"valid", "expiring", "expired", "not_yet_valid", "invalid", "unknown"}}, "auto_renew": map[string]any{"type": []string{"boolean", "null"}},
			"last_renew_at": nullableString(MaxTimestampLength, "Last renewal time"), "next_renew_at": nullableString(MaxTimestampLength, "Next renewal time"), "error": nullableRef("ExtensionError"),
		},
	)
	luckyService := requiredObject([]string{"state", "process_running", "process_pid", "uptime_seconds", "api_reachable", "web_reachable", "error"}, map[string]any{
		"state": map[string]any{"type": "string", "maxLength": MaxLuckyStatusLength}, "process_running": map[string]any{"type": []string{"boolean", "null"}},
		"process_pid": nullableInteger(MaxSafeInteger, "Lucky process ID"), "uptime_seconds": nullableInteger(MaxSafeInteger, "Lucky process uptime"),
		"api_reachable": map[string]any{"type": "boolean"}, "web_reachable": map[string]any{"type": "boolean"}, "error": nullableRef("ExtensionError"),
	})
	luckyVersion := requiredObject([]string{"current", "latest", "update_available", "build_info", "checked_at", "stale", "error"}, map[string]any{
		"current": nullableString(MaxLuckyVersionLength, "Current Lucky version"), "latest": nullableString(MaxLuckyVersionLength, "Latest known Lucky version"),
		"update_available": map[string]any{"type": []string{"boolean", "null"}}, "build_info": nullableString(MaxLuckyBuildInfoLength, "Sanitized build information"),
		"checked_at": nullableString(MaxTimestampLength, "Latest-version check time"), "stale": map[string]any{"type": "boolean"}, "error": nullableRef("ExtensionError"),
	})
	luckyIPResolution := requiredObject([]string{"mode", "resolved_ip_count", "ipv4_count", "ipv6_count", "status", "updated_at", "stale", "error"}, map[string]any{
		"mode": nullableString(MaxLuckyTextLength, "Sanitized resolution mode"), "resolved_ip_count": map[string]any{"type": "integer", "minimum": 0, "maximum": MaxDockerCount},
		"ipv4_count": map[string]any{"type": "integer", "minimum": 0, "maximum": MaxDockerCount}, "ipv6_count": map[string]any{"type": "integer", "minimum": 0, "maximum": MaxDockerCount},
		"status": luckyStatus, "updated_at": nullableString(MaxTimestampLength, "Module collection time"), "stale": map[string]any{"type": "boolean"}, "error": nullableRef("ExtensionError"),
	})
	luckyCertificates := requiredObject([]string{"total", "valid", "expiring", "expired", "not_yet_valid", "invalid", "unknown", "items", "status", "updated_at", "stale", "error"}, map[string]any{
		"total": map[string]any{"type": "integer", "minimum": 0, "maximum": MaxLuckyItems}, "valid": map[string]any{"type": "integer", "minimum": 0, "maximum": MaxLuckyItems},
		"expiring": map[string]any{"type": "integer", "minimum": 0, "maximum": MaxLuckyItems}, "expired": map[string]any{"type": "integer", "minimum": 0, "maximum": MaxLuckyItems},
		"not_yet_valid": map[string]any{"type": "integer", "minimum": 0, "maximum": MaxLuckyItems}, "invalid": map[string]any{"type": "integer", "minimum": 0, "maximum": MaxLuckyItems},
		"unknown": map[string]any{"type": "integer", "minimum": 0, "maximum": MaxLuckyItems}, "items": map[string]any{"type": "array", "maxItems": MaxLuckyItems, "items": schemaRef("LuckyCertificate"), "default": []any{}},
		"status": luckyStatus, "updated_at": nullableString(MaxTimestampLength, "Module collection time"), "stale": map[string]any{"type": "boolean"}, "error": nullableRef("ExtensionError"),
	})
	luckyStats := requiredObject([]string{"status", "source", "service", "version", "ip_resolution", "dynamic_dns", "web_services", "port_forwards", "certificates", "updated_at", "stale", "error"}, map[string]any{
		"status": luckyStatus, "source": luckySource, "service": schemaRef("LuckyServiceStats"), "version": schemaRef("LuckyVersionStats"),
		"ip_resolution": schemaRef("LuckyIPResolutionStats"), "dynamic_dns": schemaRef("LuckyDynamicDNSStats"), "web_services": schemaRef("LuckyWebServicesStats"),
		"port_forwards": schemaRef("LuckyPortForwardsStats"), "certificates": schemaRef("LuckyCertificatesStats"),
		"updated_at": nullableString(MaxTimestampLength, "Client collection time in RFC3339"), "stale": map[string]any{"type": "boolean", "description": "Recomputed by the Go server using a 900 second threshold"}, "error": nullableRef("ExtensionError"),
	})
	easyTierStatus := map[string]any{"type": "string", "enum": []string{"healthy", "degraded", "unavailable", "stale", "not_configured", "unsupported_version", "invalid_data"}}
	easyTierCommand := requiredObject([]string{"status", "error"}, map[string]any{
		"status": easyTierStatus, "last_success_at": nullableString(MaxTimestampLength, "Last successful command collection time"), "collected_at": nullableString(MaxTimestampLength, "Command collection time"), "duration_ms": nullableInteger(30000, "Command duration in milliseconds"), "error": nullableRef("ExtensionError"),
	})
	easyTierNode := requiredObject([]string{"state", "instance_name", "network_name", "version", "peer_id"}, map[string]any{
		"state":                map[string]any{"type": "string", "maxLength": MaxEasyTierTextLength},
		"instance_name":        nullableString(MaxEasyTierTextLength, "Sanitized EasyTier instance name"),
		"network_name":         nullableString(MaxEasyTierTextLength, "Sanitized EasyTier network name"),
		"version":              nullableString(MaxEasyTierTextLength, "EasyTier version"),
		"peer_id":              nullableString(MaxEasyTierTextLength, "EasyTier peer identifier"),
		"overlay_ipv4":         nullableString(64, "Internal EasyTier overlay IPv4 only"),
		"proxy_cidrs":          map[string]any{"type": "array", "maxItems": 16, "items": map[string]any{"type": "string", "maxLength": 64}},
		"administrative_role":  map[string]any{"type": []string{"string", "null"}, "enum": []any{"site_router", "endpoint", "bootstrap_listener", "relay_capable", "observer", nil}},
		"schema_compatibility": map[string]any{"type": "string", "enum": []string{"supported", "unsupported", "unknown"}},
	})
	easyTierPeer := requiredObject([]string{"peer_id", "overlay_ipv4", "hostname", "version", "path_state", "transport", "address_family", "locally_initiated", "latency_ms", "loss_rate", "rx_bytes", "tx_bytes", "rx_packets", "tx_packets", "closed"}, map[string]any{
		"peer_id": nullableString(MaxEasyTierTextLength, "Peer identifier"), "overlay_ipv4": nullableString(64, "Internal overlay IPv4"), "hostname": nullableString(MaxEasyTierTextLength, "Sanitized peer hostname"), "version": nullableString(MaxEasyTierTextLength, "Peer version"), "path_state": map[string]any{"type": "string", "enum": []string{"direct", "relayed", "unknown"}}, "transport": map[string]any{"type": "string", "enum": []string{"udp", "tcp", "quic", "wg", "wss", "unknown"}}, "address_family": map[string]any{"type": "string", "enum": []string{"ipv4", "ipv6", "unknown"}}, "locally_initiated": map[string]any{"type": "boolean"}, "latency_ms": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 600000}, "loss_rate": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100}, "rx_bytes": integerOpenAPISchema(), "tx_bytes": integerOpenAPISchema(), "rx_packets": integerOpenAPISchema(), "tx_packets": integerOpenAPISchema(), "closed": map[string]any{"type": "boolean"},
	})
	easyTierRoute := requiredObject([]string{"peer_id", "overlay_ipv4", "hostname", "version", "next_hop_peer_id", "cost", "path_latency_ms", "proxy_cidrs", "path_state", "is_local"}, map[string]any{
		"peer_id": nullableString(MaxEasyTierTextLength, "Peer identifier"), "overlay_ipv4": nullableString(64, "Internal overlay IPv4"), "hostname": nullableString(MaxEasyTierTextLength, "Sanitized route hostname"), "version": nullableString(MaxEasyTierTextLength, "Route version"), "next_hop_peer_id": nullableString(MaxEasyTierTextLength, "Next hop peer identifier"), "cost": map[string]any{"type": []string{"integer", "null"}, "minimum": 0, "maximum": 1000000}, "path_latency_ms": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 600000}, "proxy_cidrs": map[string]any{"type": "array", "maxItems": 16, "items": map[string]any{"type": "string", "maxLength": 64}}, "path_state": map[string]any{"type": "string", "enum": []string{"direct", "relayed", "unknown"}}, "is_local": map[string]any{"type": "boolean"},
	})
	easyTierConnector := requiredObject([]string{"transport", "address_family", "port", "status"}, map[string]any{
		"transport": map[string]any{"type": "string", "enum": []string{"udp", "tcp", "quic", "wg", "wss", "unknown"}}, "address_family": map[string]any{"type": "string", "enum": []string{"ipv4", "ipv6", "unknown"}}, "port": map[string]any{"type": []string{"integer", "null"}, "minimum": 1, "maximum": 65535}, "status": map[string]any{"type": "string", "enum": []string{"connected", "connecting", "disconnected", "unknown"}},
	})
	easyTierStats := requiredObject([]string{"status", "source", "node", "peers", "routes", "connectors", "traffic", "command_status", "updated_at", "stale", "error"}, map[string]any{
		"status": easyTierStatus, "source": map[string]any{"type": "string", "enum": []string{"easytier_cli", "unavailable"}},
		"node":           schemaRef("EasyTierNodeStats"),
		"peers":          requiredObject([]string{"total", "direct", "relay", "unknown_path"}, map[string]any{"total": integerOpenAPISchema(), "direct": integerOpenAPISchema(), "relay": integerOpenAPISchema(), "unknown_path": integerOpenAPISchema(), "ipv6_udp_direct": map[string]any{"type": []string{"boolean", "null"}}, "items": map[string]any{"type": "array", "maxItems": MaxDockerCount, "items": easyTierPeer}}),
		"routes":         requiredObject([]string{"total"}, map[string]any{"total": integerOpenAPISchema(), "items": map[string]any{"type": "array", "maxItems": MaxDockerCount, "items": easyTierRoute}}),
		"connectors":     requiredObject([]string{"total", "tcp_configured", "tcp_active"}, map[string]any{"total": integerOpenAPISchema(), "tcp_configured": map[string]any{"type": "boolean"}, "tcp_active": map[string]any{"type": "boolean"}, "tcp_listener_available": map[string]any{"type": []string{"boolean", "null"}}, "items": map[string]any{"type": "array", "maxItems": MaxDockerCount, "items": easyTierConnector}}),
		"traffic":        requiredObject([]string{"bytes_rx", "bytes_tx", "bytes_forwarded"}, map[string]any{"bytes_rx": integerOpenAPISchema(), "bytes_tx": integerOpenAPISchema(), "bytes_forwarded": integerOpenAPISchema()}),
		"command_status": requiredObject([]string{"node_info", "peer_list", "route_list", "connector_list", "stats_show"}, map[string]any{"node_info": schemaRef("EasyTierCommandStatus"), "peer_list": schemaRef("EasyTierCommandStatus"), "route_list": schemaRef("EasyTierCommandStatus"), "connector_list": schemaRef("EasyTierCommandStatus"), "stats_show": schemaRef("EasyTierCommandStatus")}),
		"updated_at":     nullableString(MaxTimestampLength, "Client collection time in RFC3339"), "stale": map[string]any{"type": "boolean"}, "error": nullableRef("ExtensionError"),
	})
	easyTierExpectationValues := requiredObject([]string{"administrative_role", "network_name", "overlay_ipv4", "proxy_cidrs"}, map[string]any{
		"administrative_role": nullableString(MaxEasyTierTextLength, "Configured or observed EasyTier administrative role"),
		"network_name":        nullableString(MaxEasyTierTextLength, "Configured or observed EasyTier network name"),
		"overlay_ipv4":        nullableString(64, "Configured or observed internal EasyTier overlay IPv4"),
		"proxy_cidrs":         map[string]any{"type": "array", "maxItems": 16, "items": map[string]any{"type": "string", "maxLength": 64}},
	})
	easyTierExpectationProjection := requiredObject([]string{"configured", "result"}, map[string]any{
		"configured": map[string]any{"type": "boolean"},
		"result":     map[string]any{"type": "string", "enum": []string{"matched", "mismatch", "not_observable", "not_configured"}},
		"expected":   schemaRef("EasyTierExpectationValues"),
		"observed":   schemaRef("EasyTierExpectationValues"),
	})

	uniFiCapability := map[string]any{"type": "string", "enum": []string{"supported", "unknown", "unsupported"}}
	uniFiPresence := map[string]any{"type": "string", "enum": []string{"present", "not_present", "not_populated", "unknown"}}
	uniFiObservation := map[string]any{"type": "string", "enum": []string{"not_observed", "observed", "observed_zero_rpm", "unknown"}}
	uniFiFan := requiredObject([]string{"id", "supported", "present", "observed", "rpm", "state", "error"}, map[string]any{
		"id": map[string]any{"type": "string", "maxLength": MaxUniFiTextLength}, "supported": uniFiCapability, "present": uniFiPresence,
		"observed": map[string]any{"type": "boolean"}, "rpm": nullableInteger(100000, "Observed fan speed"), "state": uniFiObservation, "error": nullableRef("ExtensionError"),
	})
	uniFiPower := requiredObject([]string{"id", "supported", "present", "observed", "state", "error"}, map[string]any{
		"id": map[string]any{"type": "string", "maxLength": MaxUniFiTextLength}, "supported": uniFiCapability, "present": uniFiPresence,
		"observed": map[string]any{"type": "boolean"}, "state": uniFiObservation, "error": nullableRef("ExtensionError"),
	})
	uniFiMemory := requiredObject([]string{"total_bytes", "available_bytes", "free_bytes", "buffers_bytes", "cached_bytes", "swap_total_bytes", "swap_free_bytes", "used_bytes", "used_percent", "available_source"}, map[string]any{
		"total_bytes": nullableInteger(MaxSafeInteger, "Total memory bytes"), "available_bytes": nullableInteger(MaxSafeInteger, "Available memory bytes"), "free_bytes": nullableInteger(MaxSafeInteger, "Free memory bytes"),
		"buffers_bytes": nullableInteger(MaxSafeInteger, "Buffer bytes"), "cached_bytes": nullableInteger(MaxSafeInteger, "Cached bytes"), "swap_total_bytes": nullableInteger(MaxSafeInteger, "Swap total bytes"), "swap_free_bytes": nullableInteger(MaxSafeInteger, "Swap free bytes"),
		"used_bytes": nullableInteger(MaxSafeInteger, "Used memory bytes"), "used_percent": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100}, "available_source": map[string]any{"type": "string", "enum": []string{"mem_available", "fallback_memfree_buffers_cached"}},
	})
	uniFiLoad := requiredObject([]string{"one_minute", "five_minutes", "fifteen_minutes"}, map[string]any{
		"one_minute": map[string]any{"type": []string{"number", "null"}, "minimum": 0}, "five_minutes": map[string]any{"type": []string{"number", "null"}, "minimum": 0}, "fifteen_minutes": map[string]any{"type": []string{"number", "null"}, "minimum": 0},
	})
	uniFiSystem := requiredObject([]string{"cpu_usage_percent", "cpu_usage_reason", "cpu_temperature_c", "memory", "uptime_seconds", "load_average"}, map[string]any{
		"cpu_usage_percent": map[string]any{"type": []string{"number", "null"}, "minimum": 0, "maximum": 100}, "cpu_usage_reason": map[string]any{"type": []string{"string", "null"}, "enum": []any{"insufficient_delta", "counter_reset", "zero_delta", "invalid_sample", nil}},
		"cpu_temperature_c": map[string]any{"type": []string{"number", "null"}, "minimum": MinTemperatureCelsius, "maximum": MaxTemperatureCelsius}, "memory": nullableRef("UniFiMemoryStats"), "uptime_seconds": map[string]any{"type": []string{"number", "null"}, "minimum": 0}, "load_average": nullableRef("UniFiLoadAverage"),
	})
	uniFiStats := requiredObject([]string{"configured", "profile", "transport", "system", "fans", "power_supplies", "storage", "diagnostics", "updated_at", "stale", "error"}, map[string]any{
		"configured": map[string]any{"type": "boolean"}, "profile": map[string]any{"type": []string{"string", "null"}, "enum": []any{"udw", "ucg-max", "unknown", nil}},
		"transport": requiredObject([]string{"status", "last_attempt", "last_success"}, map[string]any{"status": map[string]any{"type": "string", "enum": []string{"disabled", "not_collected", "available", "unavailable"}}, "last_attempt": nullableString(MaxTimestampLength, "Latest collection attempt"), "last_success": nullableString(MaxTimestampLength, "Latest successful collection")}),
		"system":    nullableRef("UniFiSystemStats"), "fans": map[string]any{"type": "array", "maxItems": MaxUniFiFans, "items": schemaRef("UniFiFanStats"), "default": []any{}}, "power_supplies": map[string]any{"type": "array", "maxItems": MaxUniFiPowerSupplies, "items": schemaRef("UniFiPowerStats"), "default": []any{}},
		"storage": requiredObject([]string{"nvme"}, map[string]any{
			"nvme":     requiredObject([]string{"supported", "present", "observed"}, map[string]any{"supported": uniFiCapability, "present": uniFiPresence, "observed": map[string]any{"type": "boolean"}, "capacity_bytes": nullableInteger(MaxSafeInteger, "Storage capacity bytes")}),
			"sata_ssd": requiredObject([]string{"supported", "present", "observed"}, map[string]any{"supported": uniFiCapability, "present": uniFiPresence, "observed": map[string]any{"type": "boolean"}, "capacity_bytes": nullableInteger(MaxSafeInteger, "Storage capacity bytes")}),
			"tf":       requiredObject([]string{"supported", "present", "observed"}, map[string]any{"supported": uniFiCapability, "present": uniFiPresence, "observed": map[string]any{"type": "boolean"}, "capacity_bytes": nullableInteger(MaxSafeInteger, "Storage capacity bytes")}),
		}),
		"diagnostics": requiredObject([]string{"collection_status", "ignored_observations"}, map[string]any{
			"collection_status": map[string]any{"type": "string", "enum": []string{"not_collected", "available", "partial", "unavailable"}},
			"ignored_observations": map[string]any{
				"type": "array", "maxItems": MaxUniFiIgnoredObservations,
				"items": requiredObject([]string{"id", "reason"}, map[string]any{
					"id":     map[string]any{"type": "string", "maxLength": MaxUniFiTextLength},
					"reason": map[string]any{"type": "string", "enum": []string{"profile_not_populated", "optional_sensor_unavailable"}},
				}),
				"default": []any{},
			},
		}),
		"updated_at": nullableString(MaxTimestampLength, "Last successful UniFi collection"), "stale": map[string]any{"type": "boolean"}, "error": nullableRef("ExtensionError"),
	})

	statsServer := requiredObject(
		[]string{"name", "type", "host", "location", "online4", "online6", "extension_version", "received_at", "hardware", "docker", "hermes", "lucky", "easytier", "unifi"},
		map[string]any{
			"name": stringOpenAPISchema(), "type": stringOpenAPISchema(), "host": stringOpenAPISchema(), "location": stringOpenAPISchema(),
			"online4": map[string]any{"type": "boolean"}, "online6": map[string]any{"type": "boolean"},
			"enabled": map[string]any{"type": "boolean"}, "ingestion_mode": map[string]any{"type": "string", "enum": []string{"legacy", "device_v2", "cutover"}},
			"uptime": stringOpenAPISchema(), "load_1": numberOpenAPISchema(), "load_5": numberOpenAPISchema(), "load_15": numberOpenAPISchema(),
			"tcp_count": integerOpenAPISchema(), "udp_count": integerOpenAPISchema(), "process_count": integerOpenAPISchema(), "thread_count": integerOpenAPISchema(),
			"network_rx": integerOpenAPISchema(), "network_tx": integerOpenAPISchema(), "network_in": integerOpenAPISchema(), "network_out": integerOpenAPISchema(),
			"cpu": numberOpenAPISchema(), "cpu_cores": integerOpenAPISchema(), "cpu_model": stringOpenAPISchema(),
			"memory_total": integerOpenAPISchema(), "memory_used": integerOpenAPISchema(), "swap_total": integerOpenAPISchema(), "swap_used": integerOpenAPISchema(),
			"hdd_total": integerOpenAPISchema(), "hdd_used": integerOpenAPISchema(), "last_network_in": integerOpenAPISchema(), "last_network_out": integerOpenAPISchema(),
			"io_read": integerOpenAPISchema(), "io_write": integerOpenAPISchema(), "custom": stringOpenAPISchema(), "os": stringOpenAPISchema(),
			"extension_version":    map[string]any{"type": "string", "const": ExtensionSchemaVersion, "maxLength": MaxExtensionVersionLength},
			"received_at":          map[string]any{"type": "string", "format": "date-time", "maxLength": MaxTimestampLength},
			"hardware":             schemaRef("HardwareStats"),
			"docker":               schemaRef("DockerStats"),
			"hermes":               schemaRef("HermesStats"),
			"lucky":                schemaRef("LuckyStats"),
			"easytier":             schemaRef("EasyTierStats"),
			"unifi":                schemaRef("UniFiStats"),
			"client_build":         nullableRef("ClientBuildInfo"),
			"easytier_expectation": schemaRef("EasyTierExpectationProjection"),
		},
	)
	statsDocument := requiredObject(
		[]string{"servers", "sslcerts", "updated"},
		map[string]any{
			"servers":  map[string]any{"type": "array", "items": schemaRef("StatsServer")},
			"sslcerts": map[string]any{"type": "array", "items": map[string]any{"type": "object"}},
			"updated":  map[string]any{"type": "string"},
			"build":    schemaRef("ServerBuildInfo"),
			"reload":   map[string]any{"type": "boolean"},
		},
	)

	return map[string]any{
		"ExtensionError":                extensionError,
		"TemperatureReading":            temperature,
		"DiskTemperature":               diskTemperature,
		"PhysicalDiskStats":             physicalDisk,
		"FilesystemStats":               filesystem,
		"StorageSummary":                storageSummary,
		"StorageStats":                  storageStats,
		"SystemIdentity":                systemIdentity,
		"CPUUsageStats":                 cpuUsage,
		"CPUDetails":                    cpuDetails,
		"MemoryDetails":                 memoryDetails,
		"ClientBuildInfo":               clientBuild,
		"ServerBuildInfo":               serverBuild,
		"HardwareStats":                 hardware,
		"DockerContainerStats":          dockerContainer,
		"DockerStats":                   dockerStats,
		"TokenUsageStats":               tokenUsage,
		"ConfigModelSummary":            configModel,
		"AuxiliaryModelSummary":         auxiliaryModel,
		"DelegationSummary":             delegation,
		"SanitizedConfigSummary":        configSummary,
		"MixtureOfAgentsStats":          mixtureOfAgents,
		"HermesProfileStats":            hermesProfile,
		"HermesStats":                   hermesStats,
		"LuckyDDNSRecord":               luckyDDNSRecord,
		"LuckyWebService":               luckyWebService,
		"LuckyPortForward":              luckyPortForward,
		"LuckyCertificate":              luckyCertificate,
		"LuckyServiceStats":             luckyService,
		"LuckyVersionStats":             luckyVersion,
		"LuckyIPResolutionStats":        luckyIPResolution,
		"LuckyDynamicDNSStats":          requiredObject([]string{"total", "enabled", "disabled", "healthy", "error_count", "records", "status", "updated_at", "stale", "error"}, luckyModuleProperties("records", "LuckyDDNSRecord")),
		"LuckyWebServicesStats":         requiredObject([]string{"total", "enabled", "disabled", "healthy", "error_count", "services", "status", "updated_at", "stale", "error"}, luckyModuleProperties("services", "LuckyWebService")),
		"LuckyPortForwardsStats":        requiredObject([]string{"total", "enabled", "disabled", "healthy", "error_count", "rules", "status", "updated_at", "stale", "error"}, luckyModuleProperties("rules", "LuckyPortForward")),
		"LuckyCertificatesStats":        luckyCertificates,
		"LuckyStats":                    luckyStats,
		"EasyTierCommandStatus":         easyTierCommand,
		"EasyTierNodeStats":             easyTierNode,
		"EasyTierStats":                 easyTierStats,
		"EasyTierExpectationValues":     easyTierExpectationValues,
		"EasyTierExpectationProjection": easyTierExpectationProjection,
		"UniFiFanStats":                 uniFiFan,
		"UniFiPowerStats":               uniFiPower,
		"UniFiMemoryStats":              uniFiMemory,
		"UniFiLoadAverage":              uniFiLoad,
		"UniFiSystemStats":              uniFiSystem,
		"UniFiStats":                    uniFiStats,
		"StatsServer":                   statsServer,
		"StatsDocument":                 statsDocument,
	}
}

func stringOpenAPISchema() map[string]any {
	return map[string]any{"type": "string"}
}

func integerOpenAPISchema() map[string]any {
	return map[string]any{"type": "integer"}
}

func numberOpenAPISchema() map[string]any {
	return map[string]any{"type": "number"}
}
