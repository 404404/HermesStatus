package main

import (
	"encoding/json"
	"strings"
	"testing"
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
