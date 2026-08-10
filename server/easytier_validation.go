package main

import "encoding/json"

func DecodeEasyTierStatsJSON(data []byte) (*EasyTierStats, error) {
	if len(data) > MaxEasyTierPayloadBytes {
		return nil, validationError(validationCodePayloadTooLarge, "easytier", "object exceeds the allowed size")
	}
	if err := validateRequiredEasyTier(data); err != nil {
		return nil, err
	}
	var stats EasyTierStats
	if err := decodeStrictJSON(data, &stats); err != nil {
		return nil, err
	}
	stats = SanitizeEasyTierStats(stats)
	if err := ValidateEasyTierStats(&stats); err != nil {
		return nil, err
	}
	return &stats, nil
}

func ValidateEasyTierStats(stats *EasyTierStats) error {
	if stats == nil || !validEasyTierStatus(stats.Status) || !validEasyTierSource(stats.Source) {
		return validationError(validationCodeInvalidValue, "easytier", "contains an unsupported status or source")
	}
	if err := validateRequiredString("easytier.node.state", stats.Node.State, MaxEasyTierTextLength); err != nil {
		return err
	}
	for field, value := range map[string]*string{
		"easytier.node.instance_name": stats.Node.InstanceName,
		"easytier.node.network_name":  stats.Node.NetworkName,
		"easytier.node.version":       stats.Node.Version,
		"easytier.node.peer_id":       stats.Node.PeerID,
	} {
		if err := validateOptionalString(field, value, MaxEasyTierTextLength); err != nil {
			return err
		}
	}
	if stats.Peers.Total < 0 || stats.Peers.Total > MaxDockerCount || stats.Peers.Direct < 0 || stats.Peers.Relay < 0 || stats.Peers.UnknownPath < 0 || stats.Peers.Direct+stats.Peers.Relay+stats.Peers.UnknownPath != stats.Peers.Total {
		return validationError(validationCodeInvalidValue, "easytier.peers", "counts are invalid")
	}
	if stats.Routes.Total < 0 || stats.Routes.Total > MaxDockerCount || stats.Connectors.Total < 0 || stats.Connectors.Total > MaxDockerCount {
		return validationError(validationCodeInvalidValue, "easytier", "counts are invalid")
	}
	for field, value := range map[string]int64{
		"easytier.traffic.bytes_rx":        stats.Traffic.BytesRX,
		"easytier.traffic.bytes_tx":        stats.Traffic.BytesTX,
		"easytier.traffic.bytes_forwarded": stats.Traffic.BytesForwarded,
	} {
		if value < 0 || value > MaxSafeInteger {
			return validationError(validationCodeInvalidValue, field, "counter is invalid")
		}
	}
	for _, command := range []EasyTierCommandStatus{stats.CommandStatus.NodeInfo, stats.CommandStatus.PeerList, stats.CommandStatus.RouteList, stats.CommandStatus.ConnectorList, stats.CommandStatus.StatsShow} {
		if !validEasyTierStatus(command.Status) {
			return validationError(validationCodeInvalidValue, "easytier.command_status", "contains an unsupported status")
		}
		if err := ValidateExtensionError("easytier.command_status.error", command.Error); err != nil {
			return err
		}
	}
	if err := validateDateTime("easytier.updated_at", stats.UpdatedAt, true); err != nil {
		return err
	}
	if err := ValidateExtensionError("easytier.error", stats.Error); err != nil {
		return err
	}
	return validatePayloadSize("easytier", stats, MaxEasyTierPayloadBytes)
}

func validEasyTierStatus(value EasyTierStatus) bool {
	switch value {
	case EasyTierHealthy, EasyTierDegraded, EasyTierUnavailable, EasyTierStale, EasyTierNotConfigured, EasyTierUnsupportedVersion, EasyTierInvalidData:
		return true
	default:
		return false
	}
}

func validEasyTierSource(value EasyTierSource) bool {
	return value == EasyTierSourceCLI || value == EasyTierSourceUnavailable
}

func validateRequiredEasyTier(raw json.RawMessage) error {
	object, err := requiredObject(raw, "easytier")
	if err != nil {
		return err
	}
	if err := requireFields(object, "easytier", "status", "source", "node", "peers", "routes", "connectors", "traffic", "command_status", "updated_at", "stale", "error"); err != nil {
		return err
	}
	for _, requirement := range []struct {
		key   string
		field string
		keys  []string
	}{
		{"node", "easytier.node", []string{"state", "instance_name", "network_name", "version", "peer_id"}},
		{"peers", "easytier.peers", []string{"total", "direct", "relay", "unknown_path"}},
		{"routes", "easytier.routes", []string{"total"}},
		{"connectors", "easytier.connectors", []string{"total", "tcp_configured", "tcp_active"}},
		{"traffic", "easytier.traffic", []string{"bytes_rx", "bytes_tx", "bytes_forwarded"}},
		{"command_status", "easytier.command_status", []string{"node_info", "peer_list", "route_list", "connector_list", "stats_show"}},
	} {
		child, childErr := requiredObject(object[requirement.key], requirement.field)
		if childErr != nil {
			return childErr
		}
		if childErr = requireFields(child, requirement.field, requirement.keys...); childErr != nil {
			return childErr
		}
	}
	commands, _ := requiredObject(object["command_status"], "easytier.command_status")
	for _, name := range []string{"node_info", "peer_list", "route_list", "connector_list", "stats_show"} {
		child, childErr := requiredObject(commands[name], "easytier.command_status."+name)
		if childErr != nil {
			return childErr
		}
		if childErr = requireFields(child, "easytier.command_status."+name, "status", "error"); childErr != nil {
			return childErr
		}
	}
	return nil
}

func SanitizeEasyTierStats(input EasyTierStats) EasyTierStats {
	result := input
	result.Node.State = SanitizeText(result.Node.State)
	result.Node.InstanceName = sanitizeStringPointer(result.Node.InstanceName)
	result.Node.NetworkName = sanitizeStringPointer(result.Node.NetworkName)
	result.Node.Version = sanitizeStringPointer(result.Node.Version)
	result.Node.PeerID = sanitizeStringPointer(result.Node.PeerID)
	result.UpdatedAt = sanitizeStringPointer(result.UpdatedAt)
	result.Error = sanitizeExtensionError(result.Error)
	commands := []*EasyTierCommandStatus{&result.CommandStatus.NodeInfo, &result.CommandStatus.PeerList, &result.CommandStatus.RouteList, &result.CommandStatus.ConnectorList, &result.CommandStatus.StatsShow}
	for _, command := range commands {
		command.Error = sanitizeExtensionError(command.Error)
	}
	return result
}
