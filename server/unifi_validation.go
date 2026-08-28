package main

import (
	"encoding/json"
	"math"
	"sort"
	"strconv"
)

func DecodeUniFiStatsJSON(data []byte) (*UniFiStats, error) {
	if len(data) > MaxUniFiPayloadBytes {
		return nil, validationError(validationCodePayloadTooLarge, "unifi", "object exceeds the allowed size")
	}
	if err := validateRequiredUniFi(data); err != nil {
		return nil, err
	}
	var stats UniFiStats
	if err := decodeStrictJSON(data, &stats); err != nil {
		return nil, err
	}
	stats = SanitizeUniFiStats(stats)
	if err := ValidateUniFiStats(&stats); err != nil {
		return nil, err
	}
	return &stats, nil
}

func ValidateUniFiStats(stats *UniFiStats) error {
	if stats == nil || !validUniFiTransportStatus(stats.Transport.Status) {
		return validationError(validationCodeInvalidValue, "unifi", "contains an unsupported transport status")
	}
	if err := validateDateTime("unifi.transport.last_attempt", stats.Transport.LastAttempt, true); err != nil {
		return err
	}
	if err := validateDateTime("unifi.transport.last_success", stats.Transport.LastSuccess, true); err != nil {
		return err
	}
	if err := validateDateTime("unifi.updated_at", stats.UpdatedAt, true); err != nil {
		return err
	}
	if err := ValidateExtensionError("unifi.error", stats.Error); err != nil {
		return err
	}
	if stats.API != nil {
		if err := validateUniFiAPI(stats.API); err != nil {
			return err
		}
	}
	if !stats.Configured {
		if stats.Profile != nil || stats.System != nil || stats.Stale || stats.Error != nil || stats.Transport.Status != UniFiTransportDisabled || (stats.API != nil && (stats.API.Enabled || stats.API.Status != "disabled")) {
			return validationError(validationCodeInvalidValue, "unifi", "disabled telemetry must not claim a collection result")
		}
	} else {
		if stats.Profile == nil || (*stats.Profile != "udw" && *stats.Profile != "ucg-max" && *stats.Profile != "unknown") {
			return validationError(validationCodeInvalidValue, "unifi.profile", "must be an explicitly supported profile or a decode-safe unknown marker")
		}
		if *stats.Profile == "unknown" && (!stats.Stale || stats.Error == nil) {
			return validationError(validationCodeInvalidValue, "unifi.profile", "unknown profile is only valid for a degraded decode-safe observation")
		}
		if stats.Transport.Status == UniFiTransportDisabled {
			return validationError(validationCodeInvalidValue, "unifi.transport.status", "configured telemetry cannot be disabled")
		}
		if stats.Stale && stats.Error == nil {
			return validationError(validationCodeInvalidValue, "unifi.error", "stale telemetry requires an error")
		}
		if !stats.Stale && stats.Error != nil {
			return validationError(validationCodeInvalidValue, "unifi.error", "fresh telemetry cannot carry an error")
		}
		if stats.System != nil {
			if err := validateUniFiSystem(stats.System); err != nil {
				return err
			}
		}
		if !stats.Stale && stats.System == nil {
			return validationError(validationCodeInvalidValue, "unifi.system", "fresh telemetry requires a system observation")
		}
	}
	if stats.Fans == nil || stats.PowerSupplies == nil || stats.Diagnostics.Ignored == nil {
		return validationError(validationCodeInvalidValue, "unifi", "arrays must not be null")
	}
	if len(stats.Fans) > MaxUniFiFans || len(stats.PowerSupplies) > MaxUniFiPowerSupplies || len(stats.Diagnostics.Ignored) > MaxUniFiIgnoredObservations {
		return validationError(validationCodeInvalidValue, "unifi", "collection exceeds the allowed size")
	}
	if err := validateUniFiFans(stats.Fans); err != nil {
		return err
	}
	if err := validateUniFiPower(stats.PowerSupplies); err != nil {
		return err
	}
	if err := validateUniFiStorage(stats.Storage); err != nil {
		return err
	}
	if stats.Diagnostics.CollectionStatus != "not_collected" && stats.Diagnostics.CollectionStatus != "available" && stats.Diagnostics.CollectionStatus != "partial" && stats.Diagnostics.CollectionStatus != "unavailable" {
		return validationError(validationCodeInvalidValue, "unifi.diagnostics.collection_status", "is invalid")
	}
	for _, item := range stats.Diagnostics.Ignored {
		if err := validateRequiredString("unifi.diagnostics.ignored_observations.id", item.ID, MaxUniFiTextLength); err != nil {
			return err
		}
		if item.Reason != "profile_not_populated" && item.Reason != "optional_sensor_unavailable" {
			return validationError(validationCodeInvalidValue, "unifi.diagnostics.ignored_observations.reason", "is invalid")
		}
	}
	return validatePayloadSize("unifi", stats, MaxUniFiPayloadBytes)
}

func validateUniFiAPI(value *UniFiAPIStats) error {
	if value == nil {
		return nil
	}
	if value.Status != "disabled" && value.Status != "available" && value.Status != "partial" && value.Status != "unavailable" {
		return validationError(validationCodeInvalidValue, "unifi.api.status", "is invalid")
	}
	if err := validateDateTime("unifi.api.last_attempt", value.LastAttempt, true); err != nil {
		return err
	}
	if err := validateDateTime("unifi.api.last_success", value.LastSuccess, true); err != nil {
		return err
	}
	if !value.Enabled {
		if value.Status != "disabled" || len(value.Endpoints) != 0 || value.Summary != nil || value.Telemetry != nil || value.Error != nil {
			return validationError(validationCodeInvalidValue, "unifi.api", "disabled API must not claim an observation")
		}
		return nil
	}
	if value.Status == "disabled" || len(value.Endpoints) > MaxUniFiAPIEndpoints {
		return validationError(validationCodeInvalidValue, "unifi.api", "enabled API state is invalid")
	}
	allowed := map[string]bool{"info": true, "sites": true, "devices": true, "clients": true, "networks": true, "legacy_stat_device": true, "lags": true, "topology": true, "port_anomalies": true}
	seen := map[string]bool{}
	okCount, failedCount := 0, 0
	for _, endpoint := range value.Endpoints {
		if !allowed[endpoint.Name] || seen[endpoint.Name] || (endpoint.Status != "ok" && endpoint.Status != "error" && endpoint.Status != "unsupported") {
			return validationError(validationCodeInvalidValue, "unifi.api.endpoints", "contains an invalid endpoint")
		}
		seen[endpoint.Name] = true
		if endpoint.HTTPStatus != nil && (*endpoint.HTTPStatus < 100 || *endpoint.HTTPStatus > 599) {
			return validationError(validationCodeInvalidValue, "unifi.api.endpoints.http_status", "is invalid")
		}
		if endpoint.Status == "ok" {
			okCount++
			if endpoint.Error != nil {
				return validationError(validationCodeInvalidValue, "unifi.api.endpoints.error", "successful endpoint must not contain an error")
			}
		} else {
			failedCount++
			if endpoint.Error == nil {
				return validationError(validationCodeInvalidValue, "unifi.api.endpoints.error", "failed endpoint requires an error")
			}
			if err := ValidateExtensionError("unifi.api.endpoints.error", endpoint.Error); err != nil {
				return err
			}
		}
	}
	if value.Status == "available" && failedCount != 0 {
		return validationError(validationCodeInvalidValue, "unifi.api.status", "available API cannot contain failed endpoints")
	}
	if value.Status == "partial" && (okCount == 0 || failedCount == 0) {
		return validationError(validationCodeInvalidValue, "unifi.api.status", "partial API requires successful and failed endpoints")
	}
	if value.Status == "unavailable" && okCount != 0 {
		return validationError(validationCodeInvalidValue, "unifi.api.status", "unavailable API cannot contain successful endpoints")
	}
	if value.Status == "partial" && (value.Error == nil || value.Error.Code != "api_partial_failure") {
		return validationError(validationCodeInvalidValue, "unifi.api.error", "partial API requires api_partial_failure")
	}
	if value.Status == "available" && value.Error != nil {
		return validationError(validationCodeInvalidValue, "unifi.api.error", "available API must not contain an error")
	}
	if value.Status == "unavailable" && value.Error == nil {
		return validationError(validationCodeInvalidValue, "unifi.api.error", "unavailable API requires an error")
	}
	if err := ValidateExtensionError("unifi.api.error", value.Error); err != nil {
		return err
	}
	if value.Summary != nil {
		for field, item := range map[string]*string{"model": value.Summary.Model, "firmware": value.Summary.Firmware, "application_version": value.Summary.ApplicationVersion} {
			if err := validateOptionalString("unifi.api.summary."+field, item, MaxCPUModelLength); err != nil {
				return err
			}
		}
	}
	if err := validateUniFiAPITelemetry(value.Telemetry); err != nil {
		return err
	}
	return nil
}

func validateUniFiAPITelemetry(value *UniFiAPITelemetry) error {
	if value == nil {
		return nil
	}
	if value.Identity != nil {
		for field, item := range map[string]*string{"model": value.Identity.Model, "display_name": value.Identity.DisplayName, "firmware": value.Identity.Firmware, "status": value.Identity.Status} {
			if err := validateOptionalString("unifi.api.telemetry.identity."+field, item, MaxUniFiTextLength); err != nil {
				return err
			}
		}
		if err := validateOptionalFloat("unifi.api.telemetry.identity.uptime_seconds", value.Identity.UptimeSeconds, float64(MaxSafeInteger)); err != nil {
			return err
		}
	}
	if value.Controller != nil {
		for field, item := range map[string]*string{"application_version": value.Controller.ApplicationVersion, "build": value.Controller.Build, "state": value.Controller.State} {
			if err := validateOptionalString("unifi.api.telemetry.controller."+field, item, MaxUniFiTextLength); err != nil {
				return err
			}
		}
	}
	if len(value.WANs) > MaxUniFiAPIWans || len(value.Uplinks) > MaxUniFiAPIUplinks || len(value.Temperatures) > MaxUniFiAPITemperatures {
		return validationError(validationCodeInvalidValue, "unifi.api.telemetry", "array exceeds the allowed size")
	}
	for index, item := range value.WANs {
		prefix := "unifi.api.telemetry.wans[" + strconv.Itoa(index) + "]"
		for field, text := range map[string]*string{"id": item.ID, "name": item.Name, "interface": item.Interface, "isp": item.ISP, "link_state": item.LinkState, "failover_state": item.FailoverState, "load_balancing_state": item.LoadBalancingState} {
			if err := validateOptionalString(prefix+"."+field, text, MaxUniFiTextLength); err != nil {
				return err
			}
		}
		for field, number := range map[string]*float64{"uptime_seconds": item.UptimeSeconds, "downtime_seconds": item.DowntimeSeconds, "latency_ms": item.LatencyMs, "packet_loss_percent": item.PacketLossPercent} {
			if err := validateOptionalFloat(prefix+"."+field, number, float64(MaxSafeInteger)); err != nil {
				return err
			}
		}
		for field, number := range map[string]*int64{"rx_bps": item.RxBPS, "tx_bps": item.TxBPS, "rx_bytes": item.RxBytes, "tx_bytes": item.TxBytes, "configured_upstream_bps": item.ConfiguredUpstreamBPS, "configured_downstream_bps": item.ConfiguredDownstreamBPS} {
			if err := validateCounter(prefix+"."+field, number, MaxSafeInteger); err != nil {
				return err
			}
		}
	}
	for index, item := range value.Uplinks {
		prefix := "unifi.api.telemetry.uplinks[" + strconv.Itoa(index) + "]"
		for field, text := range map[string]*string{"name": item.Name, "link_state": item.LinkState, "duplex": item.Duplex, "wan_id": item.WANID} {
			if err := validateOptionalString(prefix+"."+field, text, MaxUniFiTextLength); err != nil {
				return err
			}
		}
		if err := validateOptionalFloat(prefix+".speed_mbps", item.SpeedMbps, float64(MaxSafeInteger)); err != nil {
			return err
		}
	}
	for index, item := range value.Temperatures {
		prefix := "unifi.api.telemetry.temperatures[" + strconv.Itoa(index) + "]"
		if err := validateRequiredString(prefix+".id", item.ID, MaxUniFiTextLength); err != nil {
			return err
		}
		if err := validateRequiredString(prefix+".label", item.Label, MaxUniFiTextLength); err != nil {
			return err
		}
		if err := validateRequiredString(prefix+".source", item.Source, MaxUniFiTextLength); err != nil {
			return err
		}
		if err := validateTemperature(prefix+".celsius", item.Celsius); err != nil {
			return err
		}
	}
	if value.Clients != nil {
		if value.Clients.Total < 0 {
			return validationError(validationCodeInvalidValue, "unifi.api.telemetry.clients.total", "is invalid")
		}
		for field, item := range map[string]*int{"wired": value.Clients.Wired, "wireless": value.Clients.Wireless} {
			if item != nil && (*item < 0 || *item > value.Clients.Total) {
				return validationError(validationCodeInvalidValue, "unifi.api.telemetry.clients."+field, "is invalid")
			}
		}
	}
	if value.Devices != nil {
		if value.Devices.Total < 0 || value.Devices.Online < 0 || value.Devices.Offline < 0 || value.Devices.Online+value.Devices.Offline > value.Devices.Total {
			return validationError(validationCodeInvalidValue, "unifi.api.telemetry.devices", "counts are invalid")
		}
		if len(value.Devices.ByType) > 4 {
			return validationError(validationCodeInvalidValue, "unifi.api.telemetry.devices.by_type", "is too large")
		}
		for key, count := range value.Devices.ByType {
			if key != "gateway" && key != "ap" && key != "switch" && key != "other" || count < 0 || count > value.Devices.Total {
				return validationError(validationCodeInvalidValue, "unifi.api.telemetry.devices.by_type", "contains an invalid count")
			}
		}
	}
	if value.Networks != nil && (value.Networks.Total < 0 || value.Networks.VLAN < 0 || value.Networks.VLAN > value.Networks.Total) {
		return validationError(validationCodeInvalidValue, "unifi.api.telemetry.networks", "counts are invalid")
	}
	if len(value.Ports) > MaxUniFiAPIPorts || len(value.LAGs) > MaxUniFiAPILags {
		return validationError(validationCodeInvalidValue, "unifi.api.telemetry.ports", "array exceeds the allowed size")
	}
	for index, item := range value.Ports {
		prefix := "unifi.api.telemetry.ports[" + strconv.Itoa(index) + "]"
		if err := validateRequiredString(prefix+".device_id", item.DeviceID, MaxUniFiTextLength); err != nil {
			return err
		}
		if item.PortIndex < 1 || item.PortIndex > 65535 {
			return validationError(validationCodeInvalidValue, prefix+".port_idx", "is invalid")
		}
		for field, text := range map[string]*string{"name": item.Name, "media": item.Media} {
			if err := validateOptionalString(prefix+"."+field, text, MaxUniFiTextLength); err != nil {
				return err
			}
		}
		if err := validateOptionalFloat(prefix+".speed_mbps", item.SpeedMbps, float64(MaxSafeInteger)); err != nil {
			return err
		}
		if err := validateOptionalFloat(prefix+".max_speed_mbps", item.MaxSpeedMbps, float64(MaxSafeInteger)); err != nil {
			return err
		}
		for field, number := range map[string]*int64{"rx_bytes": item.RxBytes, "tx_bytes": item.TxBytes, "rx_packets": item.RxPackets, "tx_packets": item.TxPackets, "rx_errors": item.RxErrors, "tx_errors": item.TxErrors, "rx_dropped": item.RxDropped, "tx_dropped": item.TxDropped, "rx_multicast": item.RxMulticast, "tx_multicast": item.TxMulticast, "rx_broadcast": item.RxBroadcast, "tx_broadcast": item.TxBroadcast, "rx_bps": item.RxBPS, "tx_bps": item.TxBPS} {
			if err := validateCounter(prefix+"."+field, number, MaxSafeInteger); err != nil {
				return err
			}
		}
		for field, number := range map[string]*float64{"rx_utilization_pct": item.RxUtilizationPct, "tx_utilization_pct": item.TxUtilizationPct} {
			if err := validateOptionalFloat(prefix+"."+field, number, 100); err != nil {
				return err
			}
		}
		if item.PeerCount != nil && (*item.PeerCount < 0 || int64(*item.PeerCount) > MaxSafeInteger) {
			return validationError(validationCodeInvalidValue, prefix+".peer_count", "is invalid")
		}
		if item.PoE != nil {
			poe := item.PoE
			for field, text := range map[string]*string{"state": poe.State, "mode": poe.Mode, "class": poe.Class} {
				if err := validateOptionalString(prefix+".poe."+field, text, MaxUniFiTextLength); err != nil {
					return err
				}
			}
			for field, number := range map[string]*float64{"power_w": poe.PowerW, "max_power_w": poe.MaxPowerW, "voltage_v": poe.VoltageV, "current_ma": poe.CurrentMA} {
				if err := validateOptionalFloat(prefix+".poe."+field, number, float64(MaxSafeInteger)); err != nil {
					return err
				}
			}
		}
	}
	if value.PortSummary != nil {
		if value.PortSummary.Total < 0 || value.PortSummary.Up < 0 || value.PortSummary.Down < 0 || value.PortSummary.Up+value.PortSummary.Down > value.PortSummary.Total || value.PortSummary.PoEActive < 0 || value.PortSummary.PoEActive > value.PortSummary.Total {
			return validationError(validationCodeInvalidValue, "unifi.api.telemetry.port_summary", "counts are invalid")
		}
		if err := validateOptionalFloat("unifi.api.telemetry.port_summary.poe_total_power_w", value.PortSummary.PoETotalPowerW, float64(MaxSafeInteger)); err != nil {
			return err
		}
	}
	for index, item := range value.LAGs {
		prefix := "unifi.api.telemetry.lags[" + strconv.Itoa(index) + "]"
		if err := validateRequiredString(prefix+".lag_id", item.LAGID, MaxUniFiTextLength); err != nil {
			return err
		}
		if err := validateRequiredString(prefix+".lag_member", item.Member, MaxUniFiTextLength); err != nil {
			return err
		}
	}
	if value.Topology != nil {
		if len(value.Topology.Links) > MaxUniFiAPITopologyLinks || value.Topology.LinkCount < 0 || value.Topology.LinkCount != len(value.Topology.Links) {
			return validationError(validationCodeInvalidValue, "unifi.api.telemetry.topology", "is invalid")
		}
		for index, item := range value.Topology.Links {
			prefix := "unifi.api.telemetry.topology.links[" + strconv.Itoa(index) + "]"
			for field, text := range map[string]*string{"source_device_id": item.SourceDeviceID, "target_device_id": item.TargetDeviceID, "state": item.State} {
				if err := validateOptionalString(prefix+"."+field, text, MaxUniFiTextLength); err != nil {
					return err
				}
			}
		}
	}
	if value.Anomalies != nil {
		if value.Anomalies.AnomalyCount < 0 || value.Anomalies.AffectedPortCount < 0 || value.Anomalies.AffectedPortCount > value.Anomalies.AnomalyCount || len(value.Anomalies.RecentTypes) > MaxUniFiAPIAnomalyTypes {
			return validationError(validationCodeInvalidValue, "unifi.api.telemetry.anomalies", "is invalid")
		}
		for _, text := range value.Anomalies.RecentTypes {
			if err := validateRequiredString("unifi.api.telemetry.anomalies.recent_types", text, MaxUniFiTextLength); err != nil {
				return err
			}
		}
	}
	return nil
}

func validateOptionalFloat(field string, value *float64, max float64) error {
	if value == nil {
		return nil
	}
	if math.IsNaN(*value) || math.IsInf(*value, 0) || *value < 0 || *value > max {
		return validationError(validationCodeInvalidValue, field, "is invalid")
	}
	return nil
}

func validateUniFiSystem(value *UniFiSystemStats) error {
	if value == nil || value.Memory == nil || value.LoadAverage == nil {
		return validationError(validationCodeInvalidValue, "unifi.system", "is incomplete")
	}
	if err := validateOptionalString("unifi.system.cpu_model", value.CPUModel, MaxCPUModelLength); err != nil {
		return err
	}
	if err := validateOptionalBoundedFloat("unifi.system.cpu_usage_percent", value.CPUUsagePercent, 100); err != nil {
		return err
	}
	if err := validateOptionalEnum("unifi.system.cpu_usage_reason", value.CPUUsageReason, "insufficient_delta", "counter_reset", "zero_delta", "invalid_sample"); err != nil {
		return err
	}
	if value.CPUUsagePercent == nil && value.CPUUsageReason == nil {
		return validationError(validationCodeInvalidValue, "unifi.system.cpu_usage", "unavailable CPU usage requires a reason")
	}
	if value.CPUUsagePercent != nil && value.CPUUsageReason != nil {
		return validationError(validationCodeInvalidValue, "unifi.system.cpu_usage", "numeric CPU usage cannot include a reason")
	}
	if value.CPUTemperatureC == nil {
		return validationError(validationCodeInvalidValue, "unifi.system.cpu_temperature_c", "is required")
	}
	if err := validateTemperature("unifi.system.cpu_temperature_c", *value.CPUTemperatureC); err != nil {
		return err
	}
	if value.UptimeSeconds == nil || math.IsNaN(*value.UptimeSeconds) || math.IsInf(*value.UptimeSeconds, 0) || *value.UptimeSeconds < 0 || *value.UptimeSeconds > float64(MaxSafeInteger) {
		return validationError(validationCodeInvalidValue, "unifi.system.uptime_seconds", "is invalid")
	}
	for field, value := range map[string]*float64{"one_minute": value.LoadAverage.OneMinute, "five_minutes": value.LoadAverage.FiveMinutes, "fifteen_minutes": value.LoadAverage.FifteenMinutes} {
		if value == nil || math.IsNaN(*value) || math.IsInf(*value, 0) || *value < 0 || *value > float64(MaxSafeInteger) {
			return validationError(validationCodeInvalidValue, "unifi.system.load_average."+field, "is invalid")
		}
	}
	return validateUniFiMemory(value.Memory)
}

func validateUniFiMemory(value *UniFiMemoryStats) error {
	if value == nil || value.TotalBytes == nil || value.AvailableBytes == nil || value.UsedBytes == nil || value.UsedPercent == nil {
		return validationError(validationCodeInvalidValue, "unifi.system.memory", "is incomplete")
	}
	for field, item := range map[string]*int64{"total_bytes": value.TotalBytes, "available_bytes": value.AvailableBytes, "free_bytes": value.FreeBytes, "buffers_bytes": value.BuffersBytes, "cached_bytes": value.CachedBytes, "swap_total_bytes": value.SwapTotalBytes, "swap_free_bytes": value.SwapFreeBytes, "used_bytes": value.UsedBytes} {
		if err := validateCounter("unifi.system.memory."+field, item, MaxSafeInteger); err != nil {
			return err
		}
	}
	if *value.TotalBytes <= 0 || *value.AvailableBytes > *value.TotalBytes || *value.UsedBytes < 0 || *value.UsedBytes+*value.AvailableBytes != *value.TotalBytes {
		return validationError(validationCodeInvalidValue, "unifi.system.memory", "total, available, and used values are inconsistent")
	}
	if math.IsNaN(*value.UsedPercent) || math.IsInf(*value.UsedPercent, 0) || *value.UsedPercent < 0 || *value.UsedPercent > 100 {
		return validationError(validationCodeInvalidValue, "unifi.system.memory.used_percent", "is invalid")
	}
	if value.AvailableSource != "mem_available" && value.AvailableSource != "fallback_memfree_buffers_cached" {
		return validationError(validationCodeInvalidValue, "unifi.system.memory.available_source", "is invalid")
	}
	return nil
}

func validateUniFiFans(items []UniFiFanStats) error {
	ids := map[string]struct{}{}
	for _, item := range items {
		if err := validateRequiredString("unifi.fans.id", item.ID, MaxUniFiTextLength); err != nil {
			return err
		}
		if _, exists := ids[item.ID]; exists {
			return validationError(validationCodeInvalidValue, "unifi.fans", "IDs must be unique")
		}
		ids[item.ID] = struct{}{}
		if !validUniFiCapability(item.Supported) || !validUniFiPresence(item.Present) || !validUniFiObservation(item.State) {
			return validationError(validationCodeInvalidValue, "unifi.fans", "contains an invalid capability state")
		}
		if item.RPM != nil && (*item.RPM < 0 || *item.RPM > 100000) {
			return validationError(validationCodeInvalidValue, "unifi.fans.rpm", "is invalid")
		}
		if item.Observed != (item.State == UniFiObservationObserved || item.State == UniFiObservationObservedZeroRPM) {
			return validationError(validationCodeInvalidValue, "unifi.fans.observed", "does not match state")
		}
		if !item.Observed && item.RPM != nil {
			return validationError(validationCodeInvalidValue, "unifi.fans.rpm", "requires an observed fan")
		}
		if item.State == UniFiObservationObservedZeroRPM && (item.RPM == nil || *item.RPM != 0) {
			return validationError(validationCodeInvalidValue, "unifi.fans.state", "requires zero RPM")
		}
		if err := ValidateExtensionError("unifi.fans.error", item.Error); err != nil {
			return err
		}
	}
	return nil
}

func validateUniFiPower(items []UniFiPowerStats) error {
	ids := map[string]struct{}{}
	for _, item := range items {
		if err := validateRequiredString("unifi.power_supplies.id", item.ID, MaxUniFiTextLength); err != nil {
			return err
		}
		if _, exists := ids[item.ID]; exists {
			return validationError(validationCodeInvalidValue, "unifi.power_supplies", "IDs must be unique")
		}
		ids[item.ID] = struct{}{}
		if !validUniFiCapability(item.Supported) || !validUniFiPresence(item.Present) || !validUniFiObservation(item.State) {
			return validationError(validationCodeInvalidValue, "unifi.power_supplies", "contains an invalid capability state")
		}
		if item.Observed != (item.State == UniFiObservationObserved || item.State == UniFiObservationObservedZeroRPM) {
			return validationError(validationCodeInvalidValue, "unifi.power_supplies.observed", "does not match state")
		}
		if err := ValidateExtensionError("unifi.power_supplies.error", item.Error); err != nil {
			return err
		}
	}
	return nil
}

func validateUniFiStorage(value UniFiStorageStats) error {
	if err := validateUniFiStorageCapability("unifi.storage.nvme", value.NVMe); err != nil {
		return err
	}
	for name, capability := range map[string]*UniFiStorageCapability{
		"sata_ssd": value.SATA,
		"tf":       value.TF,
	} {
		if capability != nil {
			if err := validateUniFiStorageCapability("unifi.storage."+name, *capability); err != nil {
				return err
			}
		}
	}
	return nil
}

func validateUniFiStorageCapability(field string, value UniFiStorageCapability) error {
	if !validUniFiCapability(value.Supported) || !validUniFiPresence(value.Present) {
		return validationError(validationCodeInvalidValue, field, "contains an invalid capability state")
	}
	if value.CapacityBytes != nil && (*value.CapacityBytes < 0 || *value.CapacityBytes > MaxSafeInteger) {
		return validationError(validationCodeInvalidValue, field+".capacity_bytes", "is invalid")
	}
	return nil
}

func validUniFiTransportStatus(value UniFiTransportStatus) bool {
	return value == UniFiTransportDisabled || value == UniFiTransportNotCollected || value == UniFiTransportAvailable || value == UniFiTransportUnavailable
}
func validUniFiCapability(value UniFiCapabilityState) bool {
	return value == UniFiCapabilitySupported || value == UniFiCapabilityUnknown || value == UniFiCapabilityUnsupported
}
func validUniFiPresence(value UniFiPresenceState) bool {
	return value == UniFiPresencePresent || value == UniFiPresenceNotPresent || value == UniFiPresenceNotPopulated || value == UniFiPresenceUnknown
}
func validUniFiObservation(value UniFiObservationState) bool {
	return value == UniFiObservationNotObserved || value == UniFiObservationObserved || value == UniFiObservationObservedZeroRPM || value == UniFiObservationUnknown
}

func validateRequiredUniFi(raw json.RawMessage) error {
	object, err := requiredObject(raw, "unifi")
	if err != nil {
		return err
	}
	if err := requireFields(object, "unifi", "configured", "profile", "transport", "system", "fans", "power_supplies", "storage", "diagnostics", "updated_at", "stale", "error"); err != nil {
		return err
	}
	for _, spec := range []struct {
		key, field string
		required   []string
	}{
		{"transport", "unifi.transport", []string{"status", "last_attempt", "last_success"}},
		{"storage", "unifi.storage", []string{"nvme"}},
		{"diagnostics", "unifi.diagnostics", []string{"collection_status", "ignored_observations"}},
	} {
		child, childErr := requiredObject(object[spec.key], spec.field)
		if childErr != nil {
			return childErr
		}
		if childErr = requireFields(child, spec.field, spec.required...); childErr != nil {
			return childErr
		}
	}
	if object["system"] != nil && string(object["system"]) != "null" {
		child, childErr := requiredObject(object["system"], "unifi.system")
		if childErr != nil {
			return childErr
		}
		if childErr = requireFields(child, "unifi.system", "cpu_usage_percent", "cpu_usage_reason", "cpu_temperature_c", "memory", "uptime_seconds", "load_average"); childErr != nil {
			return childErr
		}
	}
	return nil
}

func sanitizeUniFiAPITelemetry(input *UniFiAPITelemetry) *UniFiAPITelemetry {
	if input == nil {
		return nil
	}
	result := *input
	if input.Identity != nil {
		identity := *input.Identity
		identity.Model = sanitizeStringPointer(identity.Model)
		identity.DisplayName = sanitizeStringPointer(identity.DisplayName)
		identity.Firmware = sanitizeStringPointer(identity.Firmware)
		identity.Status = sanitizeStringPointer(identity.Status)
		result.Identity = &identity
	}
	if input.Controller != nil {
		controller := *input.Controller
		controller.ApplicationVersion = sanitizeStringPointer(controller.ApplicationVersion)
		controller.Build = sanitizeStringPointer(controller.Build)
		controller.State = sanitizeStringPointer(controller.State)
		result.Controller = &controller
	}
	result.WANs = append([]UniFiAPIWAN(nil), input.WANs...)
	if input.WANs != nil && result.WANs == nil {
		result.WANs = make([]UniFiAPIWAN, 0)
	}
	for index := range result.WANs {
		item := &result.WANs[index]
		item.ID = sanitizeStringPointer(item.ID)
		item.Name = sanitizeStringPointer(item.Name)
		item.Interface = sanitizeStringPointer(item.Interface)
		item.ISP = sanitizeStringPointer(item.ISP)
		item.LinkState = sanitizeStringPointer(item.LinkState)
		item.FailoverState = sanitizeStringPointer(item.FailoverState)
		item.LoadBalancingState = sanitizeStringPointer(item.LoadBalancingState)
	}
	result.Uplinks = append([]UniFiAPIUplink(nil), input.Uplinks...)
	if input.Uplinks != nil && result.Uplinks == nil {
		result.Uplinks = make([]UniFiAPIUplink, 0)
	}
	for index := range result.Uplinks {
		item := &result.Uplinks[index]
		item.Name = sanitizeStringPointer(item.Name)
		item.LinkState = sanitizeStringPointer(item.LinkState)
		item.Duplex = sanitizeStringPointer(item.Duplex)
		item.WANID = sanitizeStringPointer(item.WANID)
	}
	result.Ports = append([]UniFiAPIPort(nil), input.Ports...)
	if input.Ports != nil && result.Ports == nil {
		result.Ports = make([]UniFiAPIPort, 0)
	}
	for index := range result.Ports {
		item := &result.Ports[index]
		item.DeviceID = SanitizeText(item.DeviceID)
		item.Name = sanitizeStringPointer(item.Name)
		item.Media = sanitizeStringPointer(item.Media)
		if item.PoE != nil {
			poe := *item.PoE
			poe.State = sanitizeStringPointer(poe.State)
			poe.Mode = sanitizeStringPointer(poe.Mode)
			poe.Class = sanitizeStringPointer(poe.Class)
			item.PoE = &poe
		}
	}
	result.LAGs = append([]UniFiAPILAG(nil), input.LAGs...)
	if input.LAGs != nil && result.LAGs == nil {
		result.LAGs = make([]UniFiAPILAG, 0)
	}
	for index := range result.LAGs {
		result.LAGs[index].LAGID = SanitizeText(result.LAGs[index].LAGID)
		result.LAGs[index].Member = SanitizeText(result.LAGs[index].Member)
	}
	if input.Topology != nil {
		topology := *input.Topology
		topology.Links = append([]UniFiAPITopologyLink(nil), input.Topology.Links...)
		if topology.Links == nil {
			topology.Links = make([]UniFiAPITopologyLink, 0)
		}
		for index := range topology.Links {
			topology.Links[index].SourceDeviceID = sanitizeStringPointer(topology.Links[index].SourceDeviceID)
			topology.Links[index].TargetDeviceID = sanitizeStringPointer(topology.Links[index].TargetDeviceID)
			topology.Links[index].State = sanitizeStringPointer(topology.Links[index].State)
		}
		result.Topology = &topology
	}
	if input.Anomalies != nil {
		anomalies := *input.Anomalies
		anomalies.RecentTypes = append([]string(nil), input.Anomalies.RecentTypes...)
		for index := range anomalies.RecentTypes {
			anomalies.RecentTypes[index] = SanitizeText(anomalies.RecentTypes[index])
		}
		result.Anomalies = &anomalies
	}
	result.Temperatures = append([]UniFiAPITemperature(nil), input.Temperatures...)
	if input.Temperatures != nil && result.Temperatures == nil {
		result.Temperatures = make([]UniFiAPITemperature, 0)
	}
	for index := range result.Temperatures {
		result.Temperatures[index].ID = SanitizeText(result.Temperatures[index].ID)
		result.Temperatures[index].Label = SanitizeText(result.Temperatures[index].Label)
		result.Temperatures[index].Source = SanitizeText(result.Temperatures[index].Source)
	}
	if input.Clients != nil {
		clients := *input.Clients
		result.Clients = &clients
	}
	if input.Devices != nil {
		devices := *input.Devices
		devices.ByType = make(map[string]int, len(input.Devices.ByType))
		for key, count := range input.Devices.ByType {
			devices.ByType[SanitizeText(key)] = count
		}
		result.Devices = &devices
	}
	if input.Networks != nil {
		networks := *input.Networks
		result.Networks = &networks
	}
	return &result
}

func SanitizeUniFiStats(input UniFiStats) UniFiStats {
	result := input
	if input.System != nil {
		system := *input.System
		system.CPUModel = sanitizeStringPointer(system.CPUModel)
		result.System = &system
	}
	result.Profile = sanitizeStringPointer(result.Profile)
	result.Transport.LastAttempt = sanitizeStringPointer(result.Transport.LastAttempt)
	result.Transport.LastSuccess = sanitizeStringPointer(result.Transport.LastSuccess)
	if input.API != nil {
		api := *input.API
		api.LastAttempt = sanitizeStringPointer(api.LastAttempt)
		api.LastSuccess = sanitizeStringPointer(api.LastSuccess)
		api.Error = sanitizeExtensionError(api.Error)
		api.Endpoints = append([]UniFiAPIEndpoint(nil), input.API.Endpoints...)
		if input.API.Endpoints != nil && api.Endpoints == nil {
			api.Endpoints = make([]UniFiAPIEndpoint, 0)
		}
		for index := range api.Endpoints {
			api.Endpoints[index].Error = sanitizeExtensionError(api.Endpoints[index].Error)
		}
		api.Telemetry = sanitizeUniFiAPITelemetry(input.API.Telemetry)
		if api.Summary != nil {
			summary := *api.Summary
			summary.Model = sanitizeStringPointer(summary.Model)
			summary.Firmware = sanitizeStringPointer(summary.Firmware)
			summary.ApplicationVersion = sanitizeStringPointer(summary.ApplicationVersion)
			api.Summary = &summary
		}
		result.API = &api
	}
	result.UpdatedAt = sanitizeStringPointer(result.UpdatedAt)
	result.Error = sanitizeExtensionError(result.Error)
	result.Fans = append([]UniFiFanStats(nil), input.Fans...)
	result.PowerSupplies = append([]UniFiPowerStats(nil), input.PowerSupplies...)
	result.Diagnostics.Ignored = append([]UniFiIgnoredObservation(nil), input.Diagnostics.Ignored...)
	if input.Fans != nil && result.Fans == nil {
		result.Fans = make([]UniFiFanStats, 0)
	}
	if input.PowerSupplies != nil && result.PowerSupplies == nil {
		result.PowerSupplies = make([]UniFiPowerStats, 0)
	}
	if input.Diagnostics.Ignored != nil && result.Diagnostics.Ignored == nil {
		result.Diagnostics.Ignored = make([]UniFiIgnoredObservation, 0)
	}
	for index := range result.Fans {
		result.Fans[index].ID = SanitizeText(result.Fans[index].ID)
		result.Fans[index].Error = sanitizeExtensionError(result.Fans[index].Error)
	}
	for index := range result.PowerSupplies {
		result.PowerSupplies[index].ID = SanitizeText(result.PowerSupplies[index].ID)
		result.PowerSupplies[index].Error = sanitizeExtensionError(result.PowerSupplies[index].Error)
	}
	for index := range result.Diagnostics.Ignored {
		result.Diagnostics.Ignored[index].ID = SanitizeText(result.Diagnostics.Ignored[index].ID)
		result.Diagnostics.Ignored[index].Reason = SanitizeText(result.Diagnostics.Ignored[index].Reason)
	}
	sort.SliceStable(result.Fans, func(i, j int) bool { return result.Fans[i].ID < result.Fans[j].ID })
	sort.SliceStable(result.PowerSupplies, func(i, j int) bool { return result.PowerSupplies[i].ID < result.PowerSupplies[j].ID })
	sort.SliceStable(result.Diagnostics.Ignored, func(i, j int) bool { return result.Diagnostics.Ignored[i].ID < result.Diagnostics.Ignored[j].ID })
	return result
}
