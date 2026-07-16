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
	hardware := requiredObject(
		[]string{"cpu_model", "cpu_temperature", "disk_temperature", "disk_smart_status", "disk_power_on_hours", "disk_written_bytes", "disk_read_bytes", "disk_device", "disk_smart_source", "updated_at", "stale", "error"},
		map[string]any{
			"cpu_model":           nullableString(MaxCPUModelLength, "Sanitized CPU model"),
			"cpu_temperature":     nullableRef("TemperatureReading"),
			"disk_temperature":    nullableRef("DiskTemperature"),
			"disk_smart_status":   map[string]any{"type": "string", "enum": []string{"passed", "failed", "unknown"}},
			"disk_power_on_hours": nullableInteger(MaxSafeInteger, "Disk power-on hours"),
			"disk_written_bytes":  nullableInteger(MaxSafeInteger, "Lifetime bytes written"),
			"disk_read_bytes":     nullableInteger(MaxSafeInteger, "Lifetime bytes read"),
			"disk_device":         nullableString(MaxDiskDeviceLength, "Sanitized device label"),
			"disk_smart_source":   nullableString(MaxDiskSmartSourceLength, "Fixed SMART collector source label"),
			"updated_at":          nullableString(MaxTimestampLength, "Client collection time in RFC3339"),
			"stale":               map[string]any{"type": "boolean", "description": "Recomputed by the Go server using a 900 second threshold"},
			"error":               nullableRef("ExtensionError"),
		},
	)
	hardware["example"] = map[string]any{
		"cpu_model": "Example CPU", "cpu_temperature": nil, "disk_temperature": nil,
		"disk_smart_status": "unknown", "disk_power_on_hours": nil, "disk_written_bytes": nil,
		"disk_read_bytes": nil, "disk_device": nil, "disk_smart_source": nil,
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

	statsServer := requiredObject(
		[]string{"name", "type", "host", "location", "online4", "online6", "extension_version", "received_at", "hardware", "docker", "hermes"},
		map[string]any{
			"name": stringOpenAPISchema(), "type": stringOpenAPISchema(), "host": stringOpenAPISchema(), "location": stringOpenAPISchema(),
			"online4": map[string]any{"type": "boolean"}, "online6": map[string]any{"type": "boolean"},
			"uptime": stringOpenAPISchema(), "load_1": numberOpenAPISchema(), "load_5": numberOpenAPISchema(), "load_15": numberOpenAPISchema(),
			"ping_10010": numberOpenAPISchema(), "ping_189": numberOpenAPISchema(), "ping_10086": numberOpenAPISchema(),
			"time_10010": integerOpenAPISchema(), "time_189": integerOpenAPISchema(), "time_10086": integerOpenAPISchema(),
			"tcp_count": integerOpenAPISchema(), "udp_count": integerOpenAPISchema(), "process_count": integerOpenAPISchema(), "thread_count": integerOpenAPISchema(),
			"network_rx": integerOpenAPISchema(), "network_tx": integerOpenAPISchema(), "network_in": integerOpenAPISchema(), "network_out": integerOpenAPISchema(),
			"cpu": numberOpenAPISchema(), "cpu_cores": integerOpenAPISchema(), "cpu_model": stringOpenAPISchema(),
			"memory_total": integerOpenAPISchema(), "memory_used": integerOpenAPISchema(), "swap_total": integerOpenAPISchema(), "swap_used": integerOpenAPISchema(),
			"hdd_total": integerOpenAPISchema(), "hdd_used": integerOpenAPISchema(), "last_network_in": integerOpenAPISchema(), "last_network_out": integerOpenAPISchema(),
			"io_read": integerOpenAPISchema(), "io_write": integerOpenAPISchema(), "custom": stringOpenAPISchema(), "os": stringOpenAPISchema(),
			"extension_version": map[string]any{"type": "string", "const": ExtensionSchemaVersion, "maxLength": MaxExtensionVersionLength},
			"received_at":       map[string]any{"type": "string", "format": "date-time", "maxLength": MaxTimestampLength},
			"hardware":          schemaRef("HardwareStats"),
			"docker":            schemaRef("DockerStats"),
			"hermes":            schemaRef("HermesStats"),
		},
	)
	statsDocument := requiredObject(
		[]string{"servers", "sslcerts", "updated"},
		map[string]any{
			"servers":  map[string]any{"type": "array", "items": schemaRef("StatsServer")},
			"sslcerts": map[string]any{"type": "array", "items": map[string]any{"type": "object"}},
			"updated":  map[string]any{"type": "string"},
			"reload":   map[string]any{"type": "boolean"},
		},
	)

	return map[string]any{
		"ExtensionError":         extensionError,
		"TemperatureReading":     temperature,
		"DiskTemperature":        diskTemperature,
		"HardwareStats":          hardware,
		"DockerContainerStats":   dockerContainer,
		"DockerStats":            dockerStats,
		"TokenUsageStats":        tokenUsage,
		"ConfigModelSummary":     configModel,
		"AuxiliaryModelSummary":  auxiliaryModel,
		"DelegationSummary":      delegation,
		"SanitizedConfigSummary": configSummary,
		"MixtureOfAgentsStats":   mixtureOfAgents,
		"HermesProfileStats":     hermesProfile,
		"HermesStats":            hermesStats,
		"StatsServer":            statsServer,
		"StatsDocument":          statsDocument,
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
