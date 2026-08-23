package main

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"github.com/cppla/serverstatus/server/contracts"
)

func validEasyTierFixture() EasyTierStats {
	stats := newEmptyEasyTierStats(EasyTierHealthy, EasyTierSourceCLI, nil)
	updatedAt := "2026-08-10T12:00:00Z"
	instanceName := "fixture-node"
	stats.Node.State = "running"
	stats.Node.InstanceName = &instanceName
	stats.UpdatedAt = &updatedAt
	stats.Peers = EasyTierPeerStats{Total: 2, Direct: 1, Relay: 1}
	stats.Routes.Total = 1
	stats.Traffic = EasyTierTrafficStats{BytesRX: 10, BytesTX: 20, BytesForwarded: 5}
	return stats
}

func TestEasyTierStrictValidationAndSanitization(t *testing.T) {
	stats := validEasyTierFixture()
	raw, err := json.Marshal(stats)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := DecodeEasyTierStatsJSON(raw)
	if err != nil {
		t.Fatal(err)
	}
	if decoded.Peers.Direct != 1 || decoded.Traffic.BytesTX != 20 {
		t.Fatalf("projection was lost: %#v", decoded)
	}

	var object map[string]any
	if err := json.Unmarshal(raw, &object); err != nil {
		t.Fatal(err)
	}
	object["rpc_portal"] = "127.0.0.1:15888"
	raw, _ = json.Marshal(object)
	_, err = DecodeEasyTierStatsJSON(raw)
	assertValidationError(t, err, validationCodeUnknownField)
	if strings.Contains(err.Error(), "rpc_portal") {
		t.Fatalf("forbidden field leaked: %v", err)
	}

	stats = validEasyTierFixture()
	secret := "token=must-not-appear"
	stats.Node.InstanceName = &secret
	raw, _ = json.Marshal(stats)
	decoded, err = DecodeEasyTierStatsJSON(raw)
	if err != nil {
		t.Fatal(err)
	}
	if *decoded.Node.InstanceName != RedactedValue {
		t.Fatalf("secret-like value was not redacted: %q", *decoded.Node.InstanceName)
	}
}

func TestEasyTierDomainIsOptionalForBackwardCompatibility(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-normal.json")
	if stats.EasyTier != nil {
		t.Fatal("legacy fixture unexpectedly has EasyTier")
	}
	if err := ValidateExtensionStats(stats); err != nil {
		t.Fatal(err)
	}

	payload := structuredUpdatePayload(t, "update-normal.json", nil)
	_, extension, issues, err := decodeAgentUpdate(payload)
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 0 || extension.EasyTier == nil || extension.EasyTier.Status != EasyTierNotConfigured {
		t.Fatalf("missing EasyTier must be safe not_configured: issues=%#v stats=%#v", issues, extension.EasyTier)
	}
}

func TestEasyTierDetailedProjectionRejectsPublicAndInvalidValues(t *testing.T) {
	stats := validEasyTierFixture()
	peerID, overlay, hostname := "54321", "10.250.250.2", "<script>alert(1)</script>"
	latency, loss := 12.5, 0.1
	stats.Peers = EasyTierPeerStats{Total: 1, Direct: 1, Items: []EasyTierPeer{{PeerID: &peerID, OverlayIPv4: &overlay, Hostname: &hostname, PathState: "direct", Transport: "udp", AddressFamily: "ipv6", LatencyMS: &latency, LossRate: &loss}}}
	stats.Routes = EasyTierRouteStats{Total: 1, Items: []EasyTierRoute{{PeerID: &peerID, OverlayIPv4: &overlay, ProxyCIDRs: []string{"192.168.88.0/24"}, PathState: "direct"}}}
	stats.Connectors = EasyTierConnectorStats{Total: 1, Items: []EasyTierConnector{{Transport: "tcp", AddressFamily: "ipv6", Status: "connected"}}}
	if err := ValidateEasyTierStats(&stats); err != nil {
		t.Fatalf("valid detailed projection rejected: %v", err)
	}
	public := "8.8.8.8"
	stats.Peers.Items[0].OverlayIPv4 = &public
	if err := ValidateEasyTierStats(&stats); err == nil {
		t.Fatal("public peer overlay was accepted")
	}
}

func TestEasyTierZeroPeerKeepsIPv6UDPDirectNotObservable(t *testing.T) {
	stats := validEasyTierFixture()
	stats.Peers = EasyTierPeerStats{}
	raw, err := json.Marshal(stats)
	if err != nil {
		t.Fatal(err)
	}
	var projection map[string]any
	if err := json.Unmarshal(raw, &projection); err != nil {
		t.Fatal(err)
	}
	peers := projection["peers"].(map[string]any)
	if value, exists := peers["ipv6_udp_direct"]; !exists || value != nil {
		t.Fatalf("zero-peer IPv6 UDP Direct must remain explicit null, got %#v", peers)
	}
}

func TestRestoredEasyTierProjectionIsExplicitlyStale(t *testing.T) {
	stats := validEasyTierFixture()
	stats.Stale = false
	extension := ExtensionSnapshot{EasyTier: &stats}
	forceExtensionStale(&extension)
	if !extension.EasyTier.Stale || extension.EasyTier.Status != EasyTierStale {
		t.Fatalf("restored EasyTier state became fresh: %#v", extension.EasyTier)
	}
}

func TestEasyTierExpectationIsDiagnosticOnlyAndRequiresObservedRole(t *testing.T) {
	expectation := &contracts.EasyTierExpectation{AdministrativeRole: "site_router", NetworkName: "home-404", OverlayIPv4: "10.250.250.1", ProxyCIDRs: []string{"192.168.68.0/24"}}
	overlay, network, role := "10.250.250.1", "home-404", "site_router"
	stats := validEasyTierFixture()
	stats.Stale = false
	stats.Node.OverlayIPv4, stats.Node.NetworkName, stats.Node.AdministrativeRole = &overlay, &network, &role
	stats.Node.ProxyCIDRs = []string{"192.168.68.0/24"}
	projection := projectEasyTierExpectation(expectation, &stats).(map[string]any)
	if projection["result"] != "matched" {
		t.Fatalf("expected match, got %#v", projection)
	}
	stats.Node.AdministrativeRole = nil
	projection = projectEasyTierExpectation(expectation, &stats).(map[string]any)
	if projection["result"] != "not_observable" {
		t.Fatalf("missing observed role must not become a match: %#v", projection)
	}
}

func TestEasyTierExpectationUsesNodeProxyCIDRsWithoutPeriodicRoutes(t *testing.T) {
	expectation := &contracts.EasyTierExpectation{AdministrativeRole: "site_router", NetworkName: "home-404", OverlayIPv4: "10.250.250.1", ProxyCIDRs: []string{"192.168.68.0/24"}}
	overlay, network, role := "10.250.250.1", "home-404", "site_router"
	stats := validEasyTierFixture()
	stats.Stale = false
	stats.Node.OverlayIPv4, stats.Node.NetworkName, stats.Node.AdministrativeRole = &overlay, &network, &role
	stats.Node.ProxyCIDRs = []string{"192.168.68.0/24"}
	projection := projectEasyTierExpectation(expectation, &stats).(map[string]any)
	if projection["result"] != "matched" {
		t.Fatalf("node proxy CIDRs did not produce the expected comparison: %#v", projection)
	}
	stats.CommandStatus.RouteList.Status = EasyTierUnavailable
	projection = projectEasyTierExpectation(expectation, &stats).(map[string]any)
	if projection["result"] != "matched" {
		t.Fatalf("non-periodic route status affected node observation: %#v", projection)
	}
	stats.CommandStatus.RouteList.Status = EasyTierHealthy
	stats.CommandStatus.NodeInfo.Status = EasyTierUnavailable
	projection = projectEasyTierExpectation(expectation, &stats).(map[string]any)
	if projection["result"] != "not_observable" {
		t.Fatalf("failed node source became a comparison result: %#v", projection)
	}
	stats.CommandStatus.NodeInfo.Status = EasyTierHealthy
	stats.Stale = true
	projection = projectEasyTierExpectation(expectation, &stats).(map[string]any)
	if projection["result"] != "not_observable" {
		t.Fatalf("stale EasyTier state became a comparison result: %#v", projection)
	}
}

func TestEasyTierCIDRsRejectPrefixesThatEscapePrivateRanges(t *testing.T) {
	stats := validEasyTierFixture()
	stats.Node.ProxyCIDRs = []string{"10.0.0.1/0"}
	if err := ValidateEasyTierStats(&stats); err == nil {
		t.Fatal("CIDR spanning public address space was accepted")
	}
	stats = validEasyTierFixture()
	stats.Node.ProxyCIDRs = []string{"192.168.68.1/24"}
	raw, err := json.Marshal(stats)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := DecodeEasyTierStatsJSON(raw)
	if err != nil {
		t.Fatal(err)
	}
	if got := decoded.Node.ProxyCIDRs[0]; got != "192.168.68.0/24" {
		t.Fatalf("CIDR was not canonicalized: %q", got)
	}
}

func TestEasyTierExpectationBoundsObservedCIDRProjection(t *testing.T) {
	expectation := &contracts.EasyTierExpectation{AdministrativeRole: "site_router", NetworkName: "home-404", OverlayIPv4: "10.250.250.1"}
	overlay, network, role := "10.250.250.1", "home-404", "site_router"
	stats := validEasyTierFixture()
	stats.Stale = false
	stats.Node.OverlayIPv4, stats.Node.NetworkName, stats.Node.AdministrativeRole = &overlay, &network, &role
	for index := 0; index < 16; index++ {
		stats.Node.ProxyCIDRs = append(stats.Node.ProxyCIDRs, fmt.Sprintf("192.168.%d.0/24", index))
	}
	projection := projectEasyTierExpectation(expectation, &stats).(map[string]any)
	observed := projection["observed"].(map[string]any)["proxy_cidrs"].([]string)
	if len(observed) != 16 {
		t.Fatalf("observed CIDR projection exceeds its contract bound: %#v", observed)
	}
}

func TestEasyTierMetricSamplesPreserveLabelIdentityAndRejectSecrets(t *testing.T) {
	stats := validEasyTierFixture()
	stats.Traffic.Samples = []EasyTierMetricSample{
		{Name: "peer_rpc_client_rx", Value: 1, Labels: map[string]string{"method_name": "first"}},
		{Name: "peer_rpc_client_rx", Value: 2, Labels: map[string]string{"method_name": "second"}},
	}
	if err := ValidateEasyTierStats(&stats); err != nil {
		t.Fatalf("same metric name with distinct labels was rejected: %v", err)
	}
	stats.Traffic.Samples = append(stats.Traffic.Samples, EasyTierMetricSample{Name: "peer_rpc_client_rx", Value: 3, Labels: map[string]string{"method_name": "first"}})
	if err := ValidateEasyTierStats(&stats); err == nil {
		t.Fatal("duplicate name and labels was accepted")
	}
	stats = validEasyTierFixture()
	secret := "token=must-not-appear"
	stats.Node.Hostname = &secret
	raw, err := json.Marshal(stats)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := DecodeEasyTierStatsJSON(raw)
	if err != nil {
		t.Fatal(err)
	}
	if decoded.Node.Hostname == nil || *decoded.Node.Hostname != RedactedValue {
		t.Fatalf("secret-like node value was not redacted: %#v", decoded.Node.Hostname)
	}
}
