package main

import (
	"encoding/json"
	"fmt"
	"math"
	"strings"
	"testing"
)

func TestMigrationUpdateFixturesDecode(t *testing.T) {
	for _, name := range []string{"update-normal.json", "update-empty.json", "update-degraded.json", "update-long-values.json"} {
		t.Run(name, func(t *testing.T) {
			mustDecodeUpdate(t, name)
		})
	}
}

func TestMigrationStatsFixturesDecode(t *testing.T) {
	for _, name := range []string{"stats-normal.json", "stats-empty.json", "stats-degraded.json", "stats-long-values.json"} {
		t.Run(name, func(t *testing.T) {
			snapshot, err := DecodeExtensionSnapshotJSON(readFixture(t, name))
			if err != nil {
				t.Fatal(err)
			}
			if snapshot.ReceivedAt == "" {
				t.Fatal("received_at was empty")
			}
		})
	}
}

func TestDecodeRejectsMissingRequiredField(t *testing.T) {
	data := readFixture(t, "update-empty.json")
	var object map[string]any
	if err := json.Unmarshal(data, &object); err != nil {
		t.Fatal(err)
	}
	delete(object["hardware"].(map[string]any), "stale")
	data, _ = json.Marshal(object)
	_, err := DecodeExtensionStatsJSON(data)
	assertValidationError(t, err, validationCodeMissingField)
}

func TestDecodeRejectsUnknownField(t *testing.T) {
	data := readFixture(t, "update-empty.json")
	var object map[string]any
	if err := json.Unmarshal(data, &object); err != nil {
		t.Fatal(err)
	}
	object["secret_extension"] = "not allowed"
	data, _ = json.Marshal(object)
	_, err := DecodeExtensionStatsJSON(data)
	assertValidationError(t, err, validationCodeUnknownField)
	if strings.Contains(err.Error(), "secret_extension") {
		t.Fatalf("unknown field name leaked: %v", err)
	}
}

func TestDecodeRejectsTrailingJSON(t *testing.T) {
	data := append(readFixture(t, "update-empty.json"), []byte(` {}`)...)
	_, err := DecodeExtensionStatsJSON(data)
	assertValidationError(t, err, validationCodeInvalidJSON)
}

func TestValidationRejectsUnsupportedEnums(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*ExtensionStats)
	}{
		{"smart", func(stats *ExtensionStats) { stats.Hardware.DiskSMARTStatus = "maybe" }},
		{"api", func(stats *ExtensionStats) { stats.Hermes.Profiles[0].APIStatus = "ready" }},
		{"usage-mode", func(stats *ExtensionStats) {
			value := HermesUsageMode("oauth")
			stats.Hermes.Profiles[0].UsageMode = &value
		}},
		{"token-source", func(stats *ExtensionStats) { stats.Hermes.Profiles[0].Usage.Source = "monthly" }},
		{"lucky-status", func(stats *ExtensionStats) { stats.Lucky.Status = "ready" }},
		{"lucky-source", func(stats *ExtensionStats) { stats.Lucky.Source = "raw" }},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			stats := mustDecodeUpdate(t, "update-normal.json")
			test.mutate(stats)
			if err := ValidateExtensionStats(stats); err == nil {
				t.Fatal("expected validation error")
			}
		})
	}
}

func TestLuckyRejectsUnknownAndSecretFields(t *testing.T) {
	data := readFixture(t, "update-normal.json")
	var object map[string]any
	if err := json.Unmarshal(data, &object); err != nil {
		t.Fatal(err)
	}
	lucky := object["lucky"].(map[string]any)
	lucky["raw_response"] = map[string]any{"value": "not allowed"}
	raw, _ := json.Marshal(lucky)
	_, err := DecodeLuckyStatsJSON(raw)
	assertValidationError(t, err, validationCodeUnknownField)

	delete(lucky, "raw_response")
	lucky["dynamic_dns"].(map[string]any)["records"].([]any)[0].(map[string]any)["display_name"] = "pass" + "word=not-allowed"
	raw, _ = json.Marshal(lucky)
	decoded, err := DecodeLuckyStatsJSON(raw)
	if err != nil {
		t.Fatal(err)
	}
	if decoded.DynamicDNS.Records[0].DisplayName != RedactedValue {
		t.Fatalf("secret-like Lucky value was not redacted: %q", decoded.DynamicDNS.Records[0].DisplayName)
	}
}

func TestValidationRejectsTemperatureRange(t *testing.T) {
	for _, value := range []float64{MinTemperatureCelsius - 1, MaxTemperatureCelsius + 1, math.NaN(), math.Inf(1)} {
		stats := mustDecodeUpdate(t, "update-normal.json")
		stats.Hardware.CPUTemperature.Value = value
		if err := ValidateExtensionStats(stats); err == nil {
			t.Fatalf("temperature %f accepted", value)
		}
	}
}

func TestValidationRejectsOverlongStrings(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-normal.json")
	value := strings.Repeat("x", MaxModelLength+1)
	stats.Hermes.Profiles[0].Model = &value
	err := ValidateExtensionStats(stats)
	assertValidationError(t, err, validationCodeInvalidValue)
	if strings.Contains(err.Error(), value) {
		t.Fatal("overlong value leaked in validation error")
	}
}

func TestValidationRejectsOversizedCollections(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-empty.json")
	stats.Docker.Containers = make([]DockerContainerStats, MaxDockerContainers+1)
	stats.Docker.Total = len(stats.Docker.Containers)
	if err := ValidateExtensionStats(stats); err == nil {
		t.Fatal("oversized container array accepted")
	}
	stats = mustDecodeUpdate(t, "update-empty.json")
	stats.Hermes.Profiles = make([]HermesProfileStats, MaxHermesProfiles+1)
	if err := ValidateExtensionStats(stats); err == nil {
		t.Fatal("oversized profile array accepted")
	}
}

func TestReleaseBHermesProfileFieldsValidate(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-normal.json")
	profile := &stats.Hermes.Profiles[0]
	receivedAt := "2026-07-15T00:00:01Z"
	concurrency := int64(4)
	timeout := 120.0
	configured := true
	profile.ReceivedAt = &receivedAt
	profile.SessionsHasMore = true
	profile.ConfigSummary = &SanitizedConfigSummary{
		ConfigFound: true,
		MainModel: ConfigModelSummary{
			Provider: "Example Provider", Model: "example-model", BaseURL: "provider default",
			Concurrency: &concurrency, TimeoutSeconds: &timeout,
		},
		AuxiliaryModels: []AuxiliaryModelSummary{{
			Name: "vision", Provider: "auto", EffectiveProvider: "Example Provider",
			EffectiveModel: "example-model", Source: "main_model", BaseURLDisplay: "provider default",
		}},
		Delegation:    DelegationSummary{Provider: "Example Provider", Model: "delegate-model", BaseURL: "provider default"},
		DockerVolumes: []string{"/srv/example/workspace:/workspace"},
	}
	profile.MixtureOfAgents = &MixtureOfAgentsStats{
		Source: "GET /v1/toolsets", Available: true, Name: "moa", Label: "Mixture of Agents",
		Configured: &configured, Tools: []string{"mixture_of_agents"},
	}
	if err := ValidateExtensionStats(stats); err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(SanitizeExtensionStats(*stats))
	if err != nil {
		t.Fatal(err)
	}
	for _, expected := range []string{"auxiliary_models", "mixture_of_agents", "received_at", "docker_volumes"} {
		if !strings.Contains(string(data), expected) {
			t.Fatalf("Release B field %q is missing: %s", expected, data)
		}
	}
}

func TestHermesProfileNamesMustBeUnique(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-normal.json")
	stats.Hermes.Profiles = append(stats.Hermes.Profiles, stats.Hermes.Profiles[0])
	if err := ValidateHermesStats(stats.Hermes); err == nil {
		t.Fatal("duplicate profile name was accepted")
	}
}

func TestSecretVolumePathIsRejectedOrRedacted(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-normal.json")
	stats.Hermes.Profiles[0].ConfigSummary.DockerVolumes = []string{"/srv/example/.env:/workspace/.env:ro"}
	if err := ValidateExtensionStats(stats); err == nil {
		t.Fatal("secret file mount was accepted")
	}
	sanitized := SanitizeExtensionStats(*stats)
	if sanitized.Hermes.Profiles[0].ConfigSummary.DockerVolumes[0] != RedactedValue {
		t.Fatal("secret file mount was not redacted")
	}
}

func TestDockerCountInvariants(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*DockerStats)
	}{
		{"running-over-total", func(stats *DockerStats) { stats.Running = stats.Total + 1 }},
		{"complete-size-mismatch", func(stats *DockerStats) { stats.Total++ }},
		{"truncated-size-mismatch", func(stats *DockerStats) { stats.Truncated = true; stats.Total = len(stats.Containers) }},
		{"negative-limit", func(stats *DockerStats) { stats.Limit = -1 }},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			stats := mustDecodeUpdate(t, "update-normal.json")
			test.mutate(stats.Docker)
			if err := ValidateDockerStats(stats.Docker); err == nil {
				t.Fatal("expected validation error")
			}
		})
	}
}

func TestTokenUsageRules(t *testing.T) {
	one, two, three := int64(1), int64(2), int64(3)
	start, end := "2026-07-13T00:00:00Z", "2026-07-13T01:00:00Z"
	tests := []struct {
		name  string
		usage TokenUsageStats
	}{
		{"partial-counters", TokenUsageStats{InputTokens: &one, Estimated: true, Source: TokenSourceLocalLogs}},
		{"bad-total", TokenUsageStats{InputTokens: &one, OutputTokens: &two, TotalTokens: &two, Source: TokenSourceHermesAPI}},
		{"partial-window", TokenUsageStats{InputTokens: &one, OutputTokens: &two, TotalTokens: &three, Source: TokenSourceHermesAPI, WindowStart: &start}},
		{"unavailable-values", TokenUsageStats{InputTokens: &one, OutputTokens: &two, TotalTokens: &three, Estimated: true, Source: TokenSourceUnavailable}},
		{"unavailable-not-estimated", TokenUsageStats{Source: TokenSourceUnavailable}},
		{"local-not-estimated", TokenUsageStats{InputTokens: &one, OutputTokens: &two, TotalTokens: &three, Source: TokenSourceLocalSessionState, WindowStart: &start, WindowEnd: &end}},
		{"reversed-window", TokenUsageStats{InputTokens: &one, OutputTokens: &two, TotalTokens: &three, Source: TokenSourceHermesAPI, WindowStart: &end, WindowEnd: &start}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if err := ValidateTokenUsageStats("usage", &test.usage); err == nil {
				t.Fatal("expected validation error")
			}
		})
	}
}

func TestTimestampRules(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-normal.json")
	bad := "not-a-date"
	stats.Hardware.UpdatedAt = &bad
	if err := ValidateHardwareStats(stats.Hardware); err == nil {
		t.Fatal("invalid timestamp accepted")
	}
	stats = mustDecodeUpdate(t, "update-empty.json")
	stats.Hardware.Stale = false
	if err := ValidateHardwareStats(stats.Hardware); err == nil {
		t.Fatal("fresh object without updated_at accepted")
	}
}

func TestExtensionErrorRules(t *testing.T) {
	tests := []ExtensionError{
		{Code: "Bad-Code", Message: "safe", Source: "collector"},
		{Code: "failed", Message: "safe", Source: "bad source"},
		{Code: "failed", Message: "safe", Source: "collector", HTTPStatus: intPointer(99)},
		{Code: "failed", Message: strings.Repeat("x", MaxErrorMessageLength+1), Source: "collector"},
	}
	for index := range tests {
		if err := ValidateExtensionError("error", &tests[index]); err == nil {
			t.Fatalf("invalid error %d accepted", index)
		}
	}
}

func TestSecretDetectionPatterns(t *testing.T) {
	values := []string{
		"Authorization: Bearer example",
		"Bearer example-value",
		"api_key=example",
		"api-key: example",
		"apikey=example",
		"token=example",
		"access_token=example",
		"refresh_token=example",
		"password=example",
		"passwd=example",
		"secret=example",
		"credential=example",
		"worker --token=example",
		"worker --password example",
		"https://example.invalid/?key=example",
	}
	for _, value := range values {
		if !ContainsSecretLikeText(value) {
			t.Fatalf("secret-like value not detected: %s", value)
		}
		if SanitizeText(value) != RedactedValue {
			t.Fatalf("secret-like value not redacted")
		}
	}
	if ContainsSecretLikeText("example-model-token-counter") {
		t.Fatal("benign token word was rejected")
	}
}

func TestSanitizerRemovesSecretsAndRawErrors(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-normal.json")
	secret := "password=do-not-leak"
	stats.Hardware.CPUModel = &secret
	stats.Docker.Containers[0].Image = "image?token=do-not-leak"
	stats.Hermes.Profiles[0].Provider = &secret
	stats.Hermes.Profiles[0].Error = &ExtensionError{Code: "api_timeout", Message: "raw response password=do-not-leak", Source: "hermes-api", Retryable: true}
	sanitized := SanitizeExtensionStats(*stats)
	data, err := json.Marshal(sanitized)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "do-not-leak") || strings.Contains(string(data), "raw response") {
		t.Fatalf("sanitized output leaked source text: %s", data)
	}
	if *sanitized.Hardware.CPUModel != RedactedValue || sanitized.Docker.Containers[0].Image != RedactedValue || *sanitized.Hermes.Profiles[0].Provider != RedactedValue {
		t.Fatal("secret-like fields were not redacted")
	}
	if sanitized.Hermes.Profiles[0].Error.Message != "Hermes API request timed out" {
		t.Fatalf("raw error was not normalized: %#v", sanitized.Hermes.Profiles[0].Error)
	}
}

func TestDecodeErrorDoesNotLeakInput(t *testing.T) {
	secret := "password=extremely-sensitive-value"
	_, err := DecodeExtensionStatsJSON([]byte(fmt.Sprintf(`{"%s"`, secret)))
	if err == nil {
		t.Fatal("malformed JSON accepted")
	}
	if strings.Contains(err.Error(), secret) || strings.Contains(err.Error(), "extremely-sensitive-value") {
		t.Fatalf("decode error leaked input: %v", err)
	}
}

func TestCollectorErrorMessagesAreSafeAndStable(t *testing.T) {
	tests := map[string]string{
		"smartctl_unavailable":      "SMART data is unavailable",
		"sector_size_unknown":       "Logical sector size is unavailable",
		"smart_value_invalid":       "One or more SMART values are invalid",
		"hwmon_unavailable":         "CPU temperature is unavailable",
		"host_os_unavailable":       "Host operating system data is unavailable",
		"cpu_model_unavailable":     "Host CPU model is unavailable",
		"docker_unavailable":        "Docker data is unavailable",
		"docker_response_too_large": "Docker data exceeds the allowed size",
	}
	for code, expected := range tests {
		t.Run(code, func(t *testing.T) {
			if actual := safeErrorMessage(code); actual != expected {
				t.Fatalf("safeErrorMessage(%q) = %q, want %q", code, actual, expected)
			}
			if ContainsSecretLikeText(expected) {
				t.Fatalf("safe message for %q contains secret-like text", code)
			}
		})
	}
}

func TestValidationDoesNotPanicOnZeroValues(t *testing.T) {
	tests := []func() error{
		func() error { return ValidateExtensionStats(nil) },
		func() error { return ValidateExtensionSnapshot(nil) },
		func() error { return ValidateHardwareStats(&HardwareStats{}) },
		func() error { return ValidateDockerStats(&DockerStats{}) },
		func() error { return ValidateHermesStats(&HermesStats{}) },
		func() error { return ValidateHermesProfileStats(0, nil) },
		func() error { return ValidateTokenUsageStats("usage", nil) },
	}
	for index, test := range tests {
		func() {
			defer func() {
				if recovered := recover(); recovered != nil {
					t.Fatalf("validator %d panicked: %v", index, recovered)
				}
			}()
			_ = test()
		}()
	}
}

func TestNullCollectionsAreRejected(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-empty.json")
	stats.Docker.Containers = nil
	if err := ValidateDockerStats(stats.Docker); err == nil {
		t.Fatal("null containers accepted")
	}
	stats = mustDecodeUpdate(t, "update-empty.json")
	stats.Hermes.Profiles = nil
	if err := ValidateHermesStats(stats.Hermes); err == nil {
		t.Fatal("null profiles accepted")
	}
}

func assertValidationError(t *testing.T, err error, code string) {
	t.Helper()
	if err == nil {
		t.Fatal("expected validation error")
	}
	validationErr, ok := err.(*ExtensionValidationError)
	if !ok {
		t.Fatalf("unexpected error type %T: %v", err, err)
	}
	if validationErr.Code != code {
		t.Fatalf("error code=%q, want %q", validationErr.Code, code)
	}
}

func intPointer(value int) *int { return &value }
