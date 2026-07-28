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

	statsServer := requiredObject(
		[]string{"name", "type", "host", "location", "online4", "online6", "extension_version", "received_at", "hardware", "docker", "hermes", "lucky"},
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
			"lucky":             schemaRef("LuckyStats"),
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
		"LuckyDDNSRecord":        luckyDDNSRecord,
		"LuckyWebService":        luckyWebService,
		"LuckyPortForward":       luckyPortForward,
		"LuckyCertificate":       luckyCertificate,
		"LuckyServiceStats":      luckyService,
		"LuckyVersionStats":      luckyVersion,
		"LuckyIPResolutionStats": luckyIPResolution,
		"LuckyDynamicDNSStats":   requiredObject([]string{"total", "enabled", "disabled", "healthy", "error_count", "records", "status", "updated_at", "stale", "error"}, luckyModuleProperties("records", "LuckyDDNSRecord")),
		"LuckyWebServicesStats":  requiredObject([]string{"total", "enabled", "disabled", "healthy", "error_count", "services", "status", "updated_at", "stale", "error"}, luckyModuleProperties("services", "LuckyWebService")),
		"LuckyPortForwardsStats": requiredObject([]string{"total", "enabled", "disabled", "healthy", "error_count", "rules", "status", "updated_at", "stale", "error"}, luckyModuleProperties("rules", "LuckyPortForward")),
		"LuckyCertificatesStats": luckyCertificates,
		"LuckyStats":             luckyStats,
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
