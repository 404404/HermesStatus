package main

import (
	"encoding/json"
	"net/netip"
	"net/url"
	"sort"
	"strings"
)

var internalEasyTierCIDRPrefixes = []netip.Prefix{
	netip.MustParsePrefix("10.0.0.0/8"),
	netip.MustParsePrefix("172.16.0.0/12"),
	netip.MustParsePrefix("192.168.0.0/16"),
	netip.MustParsePrefix("fc00::/7"),
}

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
		"easytier.node.hostname":      stats.Node.Hostname,
		"easytier.node.inst_id":       stats.Node.InstanceID,
	} {
		if err := validateOptionalString(field, value, MaxEasyTierTextLength); err != nil {
			return err
		}
	}
	if err := validateOptionalInternalIPv4("easytier.node.overlay_ipv4", stats.Node.OverlayIPv4); err != nil {
		return err
	}
	if err := validateInternalCIDRs("easytier.node.proxy_cidrs", stats.Node.ProxyCIDRs); err != nil {
		return err
	}
	if err := validateEasyTierNodeDetails(&stats.Node); err != nil {
		return err
	}
	if stats.Node.AdministrativeRole != nil && !validEasyTierAdministrativeRole(*stats.Node.AdministrativeRole) {
		return validationError(validationCodeInvalidValue, "easytier.node.administrative_role", "is invalid")
	}
	if stats.Node.SchemaCompatibility != "" && stats.Node.SchemaCompatibility != "supported" && stats.Node.SchemaCompatibility != "unsupported" && stats.Node.SchemaCompatibility != "unknown" {
		return validationError(validationCodeInvalidValue, "easytier.node.schema_compatibility", "is invalid")
	}
	if stats.Peers.Total < 0 || stats.Peers.Total > MaxDockerCount || stats.Peers.Direct < 0 || stats.Peers.Relay < 0 || stats.Peers.UnknownPath < 0 || stats.Peers.Direct+stats.Peers.Relay+stats.Peers.UnknownPath != stats.Peers.Total {
		return validationError(validationCodeInvalidValue, "easytier.peers", "counts are invalid")
	}
	if stats.Routes.Total < 0 || stats.Routes.Total > MaxDockerCount || stats.Connectors.Total < 0 || stats.Connectors.Total > MaxDockerCount {
		return validationError(validationCodeInvalidValue, "easytier", "counts are invalid")
	}
	if stats.Peers.Items != nil && (len(stats.Peers.Items) != stats.Peers.Total || len(stats.Peers.Items) > MaxDockerCount) {
		return validationError(validationCodeInvalidValue, "easytier.peers.items", "does not match the bounded total")
	}
	for index := range stats.Peers.Items {
		if err := validateEasyTierPeer(&stats.Peers.Items[index]); err != nil {
			return err
		}
	}
	if stats.Routes.Items != nil && (len(stats.Routes.Items) != stats.Routes.Total || len(stats.Routes.Items) > MaxDockerCount) {
		return validationError(validationCodeInvalidValue, "easytier.routes.items", "does not match the bounded total")
	}
	for index := range stats.Routes.Items {
		if err := validateEasyTierRoute(&stats.Routes.Items[index]); err != nil {
			return err
		}
	}
	if stats.Connectors.Items != nil && (len(stats.Connectors.Items) != stats.Connectors.Total || len(stats.Connectors.Items) > MaxDockerCount) {
		return validationError(validationCodeInvalidValue, "easytier.connectors.items", "does not match the bounded total")
	}
	for index := range stats.Connectors.Items {
		if err := validateEasyTierConnector(&stats.Connectors.Items[index]); err != nil {
			return err
		}
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
	for field, value := range map[string]int64{
		"easytier.traffic.packets_rx": stats.Traffic.PacketsRX,
		"easytier.traffic.packets_tx": stats.Traffic.PacketsTX,
	} {
		if value < 0 || value > MaxSafeInteger {
			return validationError(validationCodeInvalidValue, field, "counter is invalid")
		}
	}
	if err := validateOptionalBoundedFloat("easytier.traffic.rx_bps", stats.Traffic.RXBPS, float64(MaxSafeInteger)); err != nil {
		return err
	}
	if err := validateOptionalBoundedFloat("easytier.traffic.tx_bps", stats.Traffic.TXBPS, float64(MaxSafeInteger)); err != nil {
		return err
	}
	if len(stats.Traffic.ByInstance) > 16 || len(stats.Traffic.Samples) > 64 {
		return validationError(validationCodeInvalidValue, "easytier.traffic", "contains too many bounded detail items")
	}
	for index := range stats.Traffic.ByInstance {
		if err := validateEasyTierInstanceTraffic(&stats.Traffic.ByInstance[index]); err != nil {
			return err
		}
	}
	if err := validateEasyTierMetricSamples(stats.Traffic.Samples); err != nil {
		return err
	}
	for _, command := range []EasyTierCommandStatus{stats.CommandStatus.NodeInfo, stats.CommandStatus.PeerList, stats.CommandStatus.RouteList, stats.CommandStatus.ConnectorList, stats.CommandStatus.StatsShow} {
		if !validEasyTierStatus(command.Status) {
			return validationError(validationCodeInvalidValue, "easytier.command_status", "contains an unsupported status")
		}
		if err := ValidateExtensionError("easytier.command_status.error", command.Error); err != nil {
			return err
		}
		if err := validateDateTime("easytier.command_status.last_success_at", command.LastSuccessAt, true); err != nil {
			return err
		}
		if err := validateDateTime("easytier.command_status.collected_at", command.CollectedAt, true); err != nil {
			return err
		}
		if command.DurationMS != nil && (*command.DurationMS < 0 || *command.DurationMS > 30000) {
			return validationError(validationCodeInvalidValue, "easytier.command_status.duration_ms", "is invalid")
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

func validateEasyTierNodeDetails(node *EasyTierNodeStats) error {
	if len(node.Listeners) > 16 || len(node.STUNInfo.PublicIPs) > 16 {
		return validationError(validationCodeInvalidValue, "easytier.node", "contains too many detail values")
	}
	for _, listener := range node.Listeners {
		if err := validateEasyTierListener("easytier.node.listeners", listener); err != nil {
			return err
		}
	}
	for _, address := range node.STUNInfo.PublicIPs {
		if _, err := netip.ParseAddr(address); err != nil {
			return validationError(validationCodeInvalidValue, "easytier.node.stun_info.public_ips", "contains an invalid address")
		}
	}
	for field, value := range map[string]*string{
		"easytier.node.stun_info.udp_nat_type":     node.STUNInfo.UDPNATType,
		"easytier.node.stun_info.tcp_nat_type":     node.STUNInfo.TCPNATType,
		"easytier.node.stun_info.last_update_time": node.STUNInfo.LastUpdateTime,
	} {
		if err := validateOptionalString(field, value, MaxEasyTierTextLength); err != nil {
			return err
		}
	}
	return nil
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

func validEasyTierAdministrativeRole(value string) bool {
	return value == "site_router" || value == "endpoint" || value == "bootstrap_listener" || value == "relay_capable" || value == "observer"
}

func validateEasyTierPeer(peer *EasyTierPeer) error {
	if peer == nil || !validEasyTierPathState(peer.PathState) || !validEasyTierTransport(peer.Transport) || !validEasyTierAddressFamily(peer.AddressFamily) {
		return validationError(validationCodeInvalidValue, "easytier.peers.items", "contains an invalid enum")
	}
	for field, value := range map[string]*string{"peer_id": peer.PeerID, "hostname": peer.Hostname, "version": peer.Version, "cost": peer.Cost, "nat_type": peer.NATType, "rx_display": peer.RXDisplay, "tx_display": peer.TXDisplay} {
		if err := validateOptionalString("easytier.peers.items."+field, value, MaxEasyTierTextLength); err != nil {
			return err
		}
	}
	if err := validateOptionalInternalIPv4("easytier.peers.items.overlay_ipv4", peer.OverlayIPv4); err != nil {
		return err
	}
	if err := validateOptionalBoundedFloat("easytier.peers.items.latency_ms", peer.LatencyMS, 600000); err != nil {
		return err
	}
	if err := validateOptionalBoundedFloat("easytier.peers.items.loss_rate", peer.LossRate, 100); err != nil {
		return err
	}
	for field, value := range map[string]int64{"rx_bytes": peer.RXBytes, "tx_bytes": peer.TXBytes, "rx_packets": peer.RXPackets, "tx_packets": peer.TXPackets} {
		if value < 0 || value > MaxSafeInteger {
			return validationError(validationCodeInvalidValue, "easytier.peers.items."+field, "is invalid")
		}
	}
	if len(peer.EstablishedTunnels) > 8 {
		return validationError(validationCodeInvalidValue, "easytier.peers.items.established_tunnels", "is too large")
	}
	for _, tunnel := range peer.EstablishedTunnels {
		if len(tunnel) == 0 || len(tunnel) > 16 || !isEasyTierIdentifier(tunnel) {
			return validationError(validationCodeInvalidValue, "easytier.peers.items.established_tunnels", "contains an invalid tunnel")
		}
	}
	return nil
}

func validateEasyTierRoute(route *EasyTierRoute) error {
	if route == nil || !validEasyTierPathState(route.PathState) {
		return validationError(validationCodeInvalidValue, "easytier.routes.items", "contains an invalid path state")
	}
	for field, value := range map[string]*string{"peer_id": route.PeerID, "hostname": route.Hostname, "version": route.Version, "next_hop_peer_id": route.NextHopPeerID} {
		if err := validateOptionalString("easytier.routes.items."+field, value, MaxEasyTierTextLength); err != nil {
			return err
		}
	}
	if err := validateOptionalInternalIPv4("easytier.routes.items.overlay_ipv4", route.OverlayIPv4); err != nil {
		return err
	}
	if route.Cost != nil && (*route.Cost < 0 || *route.Cost > 1000000) {
		return validationError(validationCodeInvalidValue, "easytier.routes.items.cost", "is invalid")
	}
	if err := validateOptionalBoundedFloat("easytier.routes.items.path_latency_ms", route.PathLatencyMS, 600000); err != nil {
		return err
	}
	return validateInternalCIDRs("easytier.routes.items.proxy_cidrs", route.ProxyCIDRs)
}

func validateEasyTierConnector(connector *EasyTierConnector) error {
	if connector == nil || !validEasyTierTransport(connector.Transport) || !validEasyTierAddressFamily(connector.AddressFamily) || !validEasyTierConnectorStatus(connector.Status) {
		return validationError(validationCodeInvalidValue, "easytier.connectors.items", "contains an invalid enum")
	}
	if connector.Port != nil && (*connector.Port < 1 || *connector.Port > 65535) {
		return validationError(validationCodeInvalidValue, "easytier.connectors.items.port", "is invalid")
	}
	if connector.RawStatus != nil && (*connector.RawStatus < 0 || *connector.RawStatus > 2147483647) {
		return validationError(validationCodeInvalidValue, "easytier.connectors.items.raw_status", "is invalid")
	}
	if connector.URL != nil {
		if err := validateEasyTierListener("easytier.connectors.items.url", *connector.URL); err != nil {
			return err
		}
	}
	if err := validateOptionalString("easytier.connectors.items.endpoint", connector.Endpoint, MaxEasyTierTextLength); err != nil {
		return err
	}
	return nil
}

func validateEasyTierListener(field, value string) error {
	parsed, err := url.Parse(value)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || parsed.Path != "" || !validEasyTierTransport(parsed.Scheme) || parsed.Port() == "" {
		return validationError(validationCodeInvalidValue, field, "contains an invalid listener")
	}
	return validateRequiredString(field, value, MaxEasyTierTextLength)
}

func validateEasyTierInstanceTraffic(item *EasyTierInstanceTraffic) error {
	if item == nil {
		return validationError(validationCodeInvalidValue, "easytier.traffic.by_instance", "contains a nil item")
	}
	for field, value := range map[string]*string{
		"network_name": item.NetworkName, "from_instance_id": item.FromInstanceID, "to_instance_id": item.ToInstanceID,
	} {
		if err := validateOptionalString("easytier.traffic.by_instance."+field, value, MaxEasyTierTextLength); err != nil {
			return err
		}
	}
	for field, value := range map[string]*int64{"bytes_rx": item.BytesRX, "bytes_tx": item.BytesTX, "packets_rx": item.PacketsRX, "packets_tx": item.PacketsTX} {
		if value != nil && (*value < 0 || *value > MaxSafeInteger) {
			return validationError(validationCodeInvalidValue, "easytier.traffic.by_instance."+field, "is invalid")
		}
	}
	return nil
}

func validateEasyTierMetricSamples(samples []EasyTierMetricSample) error {
	identities := map[string]bool{}
	for _, sample := range samples {
		if sample.Value < 0 || sample.Value > MaxSafeInteger || len(sample.Labels) > 8 || !isEasyTierIdentifier(sample.Name) {
			return validationError(validationCodeInvalidValue, "easytier.traffic.samples", "contains an invalid metric")
		}
		labels := make([]string, 0, len(sample.Labels))
		for key, value := range sample.Labels {
			if !isEasyTierIdentifier(key) || validateRequiredString("easytier.traffic.samples.labels", value, MaxEasyTierTextLength) != nil {
				return validationError(validationCodeInvalidValue, "easytier.traffic.samples.labels", "contains an invalid label")
			}
			labels = append(labels, key+"="+value)
		}
		sort.Strings(labels)
		identity := sample.Name + "\x00" + strings.Join(labels, "\x00")
		if identities[identity] {
			return validationError(validationCodeInvalidValue, "easytier.traffic.samples", "contains duplicate name and labels")
		}
		identities[identity] = true
	}
	return nil
}

func isEasyTierIdentifier(value string) bool {
	if len(value) == 0 || len(value) > 64 {
		return false
	}
	for _, character := range value {
		if !(character >= 'a' && character <= 'z' || character >= '0' && character <= '9' || character == '_') {
			return false
		}
	}
	return true
}

func validateOptionalInternalIPv4(field string, value *string) error {
	if value == nil {
		return nil
	}
	address, err := netip.ParseAddr(*value)
	if err != nil || !address.Is4() || !address.IsPrivate() {
		return validationError(validationCodeInvalidValue, field, "must be an internal IPv4 address")
	}
	return nil
}

func validateOptionalBoundedFloat(field string, value *float64, maximum float64) error {
	if value == nil {
		return nil
	}
	if *value < 0 || *value > maximum {
		return validationError(validationCodeInvalidValue, field, "is invalid")
	}
	return nil
}

func validateInternalCIDRs(field string, values []string) error {
	if len(values) > 16 {
		return validationError(validationCodeInvalidValue, field, "is too large")
	}
	for _, cidr := range values {
		prefix, err := netip.ParsePrefix(cidr)
		if err != nil || !isInternalEasyTierCIDR(prefix) {
			return validationError(validationCodeInvalidValue, field, "must be an internal CIDR")
		}
	}
	return nil
}

func isInternalEasyTierCIDR(prefix netip.Prefix) bool {
	prefix = prefix.Masked()
	for _, allowed := range internalEasyTierCIDRPrefixes {
		if prefix.Addr().BitLen() == allowed.Addr().BitLen() && allowed.Bits() <= prefix.Bits() && allowed.Contains(prefix.Addr()) {
			return true
		}
	}
	return false
}

func canonicalEasyTierCIDR(value string) string {
	prefix, err := netip.ParsePrefix(value)
	if err != nil {
		return SanitizeText(value)
	}
	return prefix.Masked().String()
}

func validEasyTierPathState(value string) bool {
	return value == "direct" || value == "relayed" || value == "unknown"
}
func validEasyTierTransport(value string) bool {
	return value == "udp" || value == "tcp" || value == "quic" || value == "wg" || value == "wss" || value == "unknown"
}
func validEasyTierAddressFamily(value string) bool {
	return value == "ipv4" || value == "ipv6" || value == "unknown"
}
func validEasyTierConnectorStatus(value string) bool {
	return value == "connected" || value == "connecting" || value == "disconnected" || value == "unknown"
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
	result.Node.OverlayIPv4 = sanitizeStringPointer(result.Node.OverlayIPv4)
	result.Node.Hostname = sanitizeStringPointer(result.Node.Hostname)
	result.Node.InstanceID = sanitizeStringPointer(result.Node.InstanceID)
	result.Node.STUNInfo.UDPNATType = sanitizeStringPointer(result.Node.STUNInfo.UDPNATType)
	result.Node.STUNInfo.TCPNATType = sanitizeStringPointer(result.Node.STUNInfo.TCPNATType)
	result.Node.STUNInfo.LastUpdateTime = sanitizeStringPointer(result.Node.STUNInfo.LastUpdateTime)
	for index := range result.Node.Listeners {
		result.Node.Listeners[index] = SanitizeText(result.Node.Listeners[index])
	}
	for index := range result.Node.STUNInfo.PublicIPs {
		result.Node.STUNInfo.PublicIPs[index] = SanitizeText(result.Node.STUNInfo.PublicIPs[index])
	}
	for index := range result.Node.ProxyCIDRs {
		result.Node.ProxyCIDRs[index] = canonicalEasyTierCIDR(result.Node.ProxyCIDRs[index])
	}
	result.UpdatedAt = sanitizeStringPointer(result.UpdatedAt)
	result.Error = sanitizeExtensionError(result.Error)
	commands := []*EasyTierCommandStatus{&result.CommandStatus.NodeInfo, &result.CommandStatus.PeerList, &result.CommandStatus.RouteList, &result.CommandStatus.ConnectorList, &result.CommandStatus.StatsShow}
	for _, command := range commands {
		command.LastSuccessAt = sanitizeStringPointer(command.LastSuccessAt)
		command.CollectedAt = sanitizeStringPointer(command.CollectedAt)
		command.Error = sanitizeExtensionError(command.Error)
	}
	for index := range result.Peers.Items {
		peer := &result.Peers.Items[index]
		peer.PeerID = sanitizeStringPointer(peer.PeerID)
		peer.OverlayIPv4 = sanitizeStringPointer(peer.OverlayIPv4)
		peer.Hostname = sanitizeStringPointer(peer.Hostname)
		peer.Version = sanitizeStringPointer(peer.Version)
		peer.Cost = sanitizeStringPointer(peer.Cost)
		peer.NATType = sanitizeStringPointer(peer.NATType)
		peer.RXDisplay = sanitizeStringPointer(peer.RXDisplay)
		peer.TXDisplay = sanitizeStringPointer(peer.TXDisplay)
		for tunnelIndex := range peer.EstablishedTunnels {
			peer.EstablishedTunnels[tunnelIndex] = SanitizeText(peer.EstablishedTunnels[tunnelIndex])
		}
	}
	for index := range result.Routes.Items {
		route := &result.Routes.Items[index]
		route.PeerID = sanitizeStringPointer(route.PeerID)
		route.OverlayIPv4 = sanitizeStringPointer(route.OverlayIPv4)
		route.Hostname = sanitizeStringPointer(route.Hostname)
		route.Version = sanitizeStringPointer(route.Version)
		route.NextHopPeerID = sanitizeStringPointer(route.NextHopPeerID)
		cleanCIDRs := make([]string, 0, len(route.ProxyCIDRs))
		for _, cidr := range route.ProxyCIDRs {
			cleanCIDRs = append(cleanCIDRs, canonicalEasyTierCIDR(cidr))
		}
		route.ProxyCIDRs = cleanCIDRs
	}
	for index := range result.Connectors.Items {
		connector := &result.Connectors.Items[index]
		connector.URL = sanitizeStringPointer(connector.URL)
		connector.Endpoint = sanitizeStringPointer(connector.Endpoint)
	}
	for index := range result.Traffic.ByInstance {
		item := &result.Traffic.ByInstance[index]
		item.NetworkName = sanitizeStringPointer(item.NetworkName)
		item.FromInstanceID = sanitizeStringPointer(item.FromInstanceID)
		item.ToInstanceID = sanitizeStringPointer(item.ToInstanceID)
	}
	for index := range result.Traffic.Samples {
		sample := &result.Traffic.Samples[index]
		sample.Name = SanitizeText(sample.Name)
		cleanLabels := make(map[string]string, len(sample.Labels))
		for key, value := range sample.Labels {
			cleanLabels[SanitizeText(key)] = SanitizeText(value)
		}
		sample.Labels = cleanLabels
	}
	return result
}
