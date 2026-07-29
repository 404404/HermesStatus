package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

func TestDeviceEndpointDefaultsDisabledAndMethodIsFixed(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	app := newStageCApp(t, registry, []contracts.CredentialRecord{
		activeTestCredentialRecord("device-alpha"),
	}, func(opts *Options) {
		opts.DeviceEndpointEnabled = false
	})
	response := performDeviceUpdateRequest(
		app, http.MethodPost, validDeviceEnvelope(t, "device-alpha", nil, 12),
		testCurrentToken, "device-alpha", true,
	)
	if response.Code != http.StatusNotFound ||
		response.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("disabled endpoint was exposed: %d %#v", response.Code, response.Header())
	}
	commandRequest := httptest.NewRequest(
		http.MethodPost,
		"https://example.invalid"+deviceUpdatePath+"/command",
		nil,
	)
	commandResponse := httptest.NewRecorder()
	app.router().ServeHTTP(commandResponse, commandRequest)
	if commandResponse.Code != http.StatusNotFound {
		t.Fatalf("unexpected command/control route exists: %d", commandResponse.Code)
	}

	enabled := newStageCApp(t, registry, []contracts.CredentialRecord{
		activeTestCredentialRecord("device-alpha"),
	}, nil)
	response = performDeviceUpdateRequest(
		enabled, http.MethodGet, nil, testCurrentToken, "device-alpha", true,
	)
	if response.Code != http.StatusMethodNotAllowed ||
		response.Header().Get("Allow") != http.MethodPost {
		t.Fatalf("non-POST method was not rejected with Allow: POST: %d %#v",
			response.Code, response.Header())
	}
}

func TestDeviceEndpointAcceptsDirectTLSAndSanitizesSuccess(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	app := newStageCApp(t, registry, []contracts.CredentialRecord{
		activeTestCredentialRecord("device-alpha"),
	}, nil)
	server := httptest.NewTLSServer(app.router())
	defer server.Close()
	request, err := http.NewRequest(
		http.MethodPost,
		server.URL+deviceUpdatePath,
		bytes.NewReader(validDeviceEnvelope(t, "device-alpha", nil, 42)),
	)
	if err != nil {
		t.Fatal(err)
	}
	setDeviceHeaders(request, testCurrentToken, "device-alpha")
	response, err := server.Client().Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusAccepted ||
		response.Header.Get("Cache-Control") != "no-store" ||
		!strings.HasPrefix(response.Header.Get("Content-Type"), "application/json") {
		t.Fatalf("direct TLS update failed: status=%d headers=%#v",
			response.StatusCode, response.Header)
	}
	var success contracts.SuccessResponse
	if err := json.NewDecoder(response.Body).Decode(&success); err != nil {
		t.Fatal(err)
	}
	if err := contracts.ValidateSuccessResponse(success); err != nil ||
		!success.Accepted || len(success.Monitors) != 1 ||
		success.Monitors[0].Name != "example" ||
		!strings.HasPrefix(success.ConfigGeneration, "g-") {
		t.Fatalf("success response is not sanitized/valid: %#v err=%v", success, err)
	}
	node := app.nodes["device-alpha"]
	if node.Stats.CPU != 42 || node.ProtocolMode != "device_v2" ||
		node.LastAcceptedGeneration == 0 {
		t.Fatalf("TLS adapter did not call unified ingestion: %#v", node)
	}
}

func TestDeviceEndpointTransportAndTrustedProxyBoundaries(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	credentials := []contracts.CredentialRecord{activeTestCredentialRecord("device-alpha")}
	plain := newStageCApp(t, registry, credentials, func(opts *Options) {
		opts.AllowLoopbackDeviceHTTP = false
	})
	for name, mutate := range map[string]func(*http.Request){
		"plain-http": func(*http.Request) {},
		"forged-forwarded-proto": func(request *http.Request) {
			request.Header.Set("X-Forwarded-Proto", "https")
		},
	} {
		t.Run(name, func(t *testing.T) {
			request := newDeviceRequest(
				http.MethodPost, validDeviceEnvelope(t, "device-alpha", nil, 12),
				testCurrentToken, "device-alpha", false,
			)
			mutate(request)
			request.RemoteAddr = "127.0.0.1:40000"
			response := httptest.NewRecorder()
			plain.router().ServeHTTP(response, request)
			if response.Code != http.StatusForbidden {
				t.Fatalf("insecure request was accepted: %d", response.Code)
			}
		})
	}

	loopbackTest := newStageCApp(t, registry, credentials, func(opts *Options) {
		opts.AllowLoopbackDeviceHTTP = true
	})
	response := performDeviceUpdateRequest(
		loopbackTest, http.MethodPost,
		validDeviceEnvelope(t, "device-alpha", nil, 13),
		testCurrentToken, "device-alpha", false,
	)
	if response.Code != http.StatusAccepted {
		t.Fatalf("explicit loopback test mode was rejected: %d %s", response.Code, response.Body.String())
	}
	nonLoopback := newDeviceRequest(
		http.MethodPost, validDeviceEnvelope(t, "device-alpha", nil, 14),
		testCurrentToken, "device-alpha", false,
	)
	nonLoopback.RemoteAddr = "192.0.2.10:40000"
	recorder := httptest.NewRecorder()
	loopbackTest.router().ServeHTTP(recorder, nonLoopback)
	if recorder.Code != http.StatusForbidden {
		t.Fatalf("non-loopback HTTP entered test mode: %d", recorder.Code)
	}

	trusted := newStageCApp(t, registry, credentials, func(opts *Options) {
		opts.AllowLoopbackDeviceHTTP = false
		opts.TrustedProxyMode = true
		opts.TrustedProxyCIDRs = "192.0.2.10/32"
	})
	for _, testCase := range []struct {
		name       string
		remoteAddr string
		proto      []string
		want       int
	}{
		{"trusted", "192.0.2.10:443", []string{"https"}, http.StatusAccepted},
		{"untrusted", "192.0.2.11:443", []string{"https"}, http.StatusForbidden},
		{"invalid-proto", "192.0.2.10:443", []string{"http"}, http.StatusForbidden},
		{"multiple-proto", "192.0.2.10:443", []string{"https", "https"}, http.StatusForbidden},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			request := newDeviceRequest(
				http.MethodPost, validDeviceEnvelope(t, "device-alpha", nil, 15),
				testCurrentToken, "device-alpha", false,
			)
			request.RemoteAddr = testCase.remoteAddr
			request.Header["X-Forwarded-Proto"] = testCase.proto
			response := httptest.NewRecorder()
			trusted.router().ServeHTTP(response, request)
			if response.Code != testCase.want {
				t.Fatalf("proxy boundary status=%d want=%d body=%s",
					response.Code, testCase.want, response.Body.String())
			}
		})
	}
}

func TestDeviceEndpointHTTPValidationMatrix(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	app := newStageCApp(t, registry, []contracts.CredentialRecord{
		activeTestCredentialRecord("device-alpha"),
	}, nil)
	validBody := validDeviceEnvelope(t, "device-alpha", nil, 12)
	invalidCollectedAt := replaceEnvelopeField(
		t, validBody, "collected_at", "not-a-timestamp",
	)
	futureCollectedAt := replaceEnvelopeField(
		t, validBody, "collected_at",
		time.Now().UTC().Add(MaxDeviceClockSkew+time.Minute).Format(time.RFC3339),
	)
	unknownDeviceField := addDeviceEnvelopeField(
		t, validBody, "unexpected", "raw-secret-marker",
	)
	missingRequiredStats := removeStatsEnvelopeField(t, validBody, "hardware")
	tests := []struct {
		name   string
		body   []byte
		token  string
		device string
		mutate func(*http.Request)
		want   int
	}{
		{"unsupported-content-type", validBody, testCurrentToken, "device-alpha", func(request *http.Request) {
			request.Header.Set("Content-Type", "text/plain")
		}, http.StatusUnsupportedMediaType},
		{"valid-charset", validBody, testCurrentToken, "device-alpha", func(request *http.Request) {
			request.Header.Set("Content-Type", "application/json; charset=UTF-8")
		}, http.StatusAccepted},
		{"invalid-charset", validBody, testCurrentToken, "device-alpha", func(request *http.Request) {
			request.Header.Set("Content-Type", "application/json; charset=latin1")
		}, http.StatusUnsupportedMediaType},
		{"empty-body", nil, testCurrentToken, "device-alpha", nil, http.StatusBadRequest},
		{"trailing-json", append(append([]byte(nil), validBody...), []byte(` {}`)...), testCurrentToken, "device-alpha", nil, http.StatusBadRequest},
		{"unknown-field", addEnvelopeField(t, validBody, "raw-secret-marker", true), testCurrentToken, "device-alpha", nil, http.StatusBadRequest},
		{"unknown-device-field", unknownDeviceField, testCurrentToken, "device-alpha", nil, http.StatusBadRequest},
		{"missing-required-stats", missingRequiredStats, testCurrentToken, "device-alpha", nil, http.StatusBadRequest},
		{"invalid-collected-at", invalidCollectedAt, testCurrentToken, "device-alpha", nil, http.StatusBadRequest},
		{"future-collected-at", futureCollectedAt, testCurrentToken, "device-alpha", nil, http.StatusBadRequest},
		{"invalid-device-header", validBody, testCurrentToken, "INVALID ID", nil, http.StatusBadRequest},
		{"ip-device-header", validBody, testCurrentToken, "192.0.2.10", nil, http.StatusBadRequest},
		{"missing-device-header", validBody, testCurrentToken, "", nil, http.StatusBadRequest},
		{"duplicate-device-header", validBody, testCurrentToken, "device-alpha", func(request *http.Request) {
			request.Header["X-HermesStatus-Device-ID"] = []string{"device-alpha", "device-alpha"}
		}, http.StatusBadRequest},
		{"next-token", validBody, testNextToken, "device-alpha", nil, http.StatusAccepted},
		{"missing-token", validBody, "", "device-alpha", nil, http.StatusUnauthorized},
		{"wrong-token", validBody, testWrongToken, "device-alpha", nil, http.StatusUnauthorized},
		{"wrong-scheme", validBody, testCurrentToken, "device-alpha", func(request *http.Request) {
			request.Header.Set("Authorization", "Basic "+testCurrentToken)
		}, http.StatusUnauthorized},
		{"duplicate-authorization", validBody, testCurrentToken, "device-alpha", func(request *http.Request) {
			request.Header["Authorization"] = []string{"Bearer " + testCurrentToken, "Bearer " + testCurrentToken}
		}, http.StatusUnauthorized},
		{"unknown-device", validBody, testCurrentToken, "unknown-device", nil, http.StatusUnauthorized},
	}
	for _, testCase := range tests {
		t.Run(testCase.name, func(t *testing.T) {
			request := newDeviceRequest(
				http.MethodPost, testCase.body,
				testCase.token, testCase.device, true,
			)
			if testCase.mutate != nil {
				testCase.mutate(request)
			}
			response := httptest.NewRecorder()
			app.router().ServeHTTP(response, request)
			if response.Code != testCase.want {
				t.Fatalf("status=%d want=%d body=%s",
					response.Code, testCase.want, response.Body.String())
			}
			if response.Header().Get("Cache-Control") != "no-store" {
				t.Fatal("response omitted Cache-Control: no-store")
			}
			if testCase.want != http.StatusAccepted {
				assertBoundedDeviceError(t, response)
			}
		})
	}

	oversized := bytes.Repeat([]byte("x"), contracts.MaxEnvelopeBytes+1)
	response := performDeviceUpdateRequest(
		app, http.MethodPost, oversized, testCurrentToken, "device-alpha", true,
	)
	if response.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("oversized body status=%d body=%s", response.Code, response.Body.String())
	}
}

func TestDeviceEndpointIdentityOwnershipAndStateIsolation(t *testing.T) {
	expected := "alpha.example.invalid"
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", &expected),
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
		testRegistryDevice("device-disabled", "Disabled", 30, false, "device_v2", nil),
		testRegistryDevice("device-legacy", "Legacy", 40, true, "legacy", nil),
	)
	registry.Defaults.DefaultDeviceID = "device-alpha"
	records := []contracts.CredentialRecord{
		activeTestCredentialRecord("device-alpha"),
		testCredentialRecord("device-beta", testCredentialSlot(
			"current", testNextToken, time.Now().Add(-time.Hour), time.Now().Add(time.Hour),
		)),
		testCredentialRecord("device-disabled", testCredentialSlot(
			"current", testWrongToken, time.Now().Add(-time.Hour), time.Now().Add(time.Hour),
		)),
		testCredentialRecord("device-legacy", testCredentialSlot(
			"current", "synthetic-legacy-token-000000000004", time.Now().Add(-time.Hour), time.Now().Add(time.Hour),
		)),
	}
	app := newStageCApp(t, registry, records, nil)

	for _, testCase := range []struct {
		name     string
		headerID string
		bodyID   string
		token    string
		fqdn     *string
		want     int
	}{
		{"fqdn-match", "device-alpha", "device-alpha", testCurrentToken, &expected, http.StatusAccepted},
		{"header-body-mismatch", "device-alpha", "device-beta", testCurrentToken, nil, http.StatusForbidden},
		{"fqdn-missing", "device-alpha", "device-alpha", testCurrentToken, nil, http.StatusForbidden},
		{"fqdn-mismatch", "device-alpha", "device-alpha", testCurrentToken, stringPointer("other.example.invalid"), http.StatusForbidden},
		{"disabled", "device-disabled", "device-disabled", testWrongToken, nil, http.StatusForbidden},
		{"legacy-owner", "device-legacy", "device-legacy", "synthetic-legacy-token-000000000004", nil, http.StatusForbidden},
		{"no-fqdn-expectation", "device-beta", "device-beta", testNextToken, nil, http.StatusAccepted},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			beforeAlpha := app.nodes["device-alpha"].LastAcceptedGeneration
			beforeBeta := app.nodes["device-beta"].LastAcceptedGeneration
			response := performDeviceUpdateRequest(
				app, http.MethodPost,
				validDeviceEnvelope(t, testCase.bodyID, testCase.fqdn, 27),
				testCase.token, testCase.headerID, true,
			)
			if response.Code != testCase.want {
				t.Fatalf("status=%d want=%d body=%s",
					response.Code, testCase.want, response.Body.String())
			}
			if testCase.want != http.StatusAccepted {
				if testCase.name == "fqdn-missing" || testCase.name == "fqdn-mismatch" {
					if app.nodes["device-alpha"].Stats.CPU != 27 ||
						app.nodes["device-alpha"].LastAcceptedGeneration != beforeAlpha {
						t.Fatal("FQDN failure replaced business data or generation")
					}
				} else if app.nodes["device-alpha"].LastAcceptedGeneration != beforeAlpha ||
					app.nodes["device-beta"].LastAcceptedGeneration != beforeBeta {
					t.Fatal("rejected identity/ownership request changed another device")
				}
			}
		})
	}

	invalidFQDN := stringPointer("192.0.2.10")
	response := performDeviceUpdateRequest(
		app, http.MethodPost,
		validDeviceEnvelope(t, "device-alpha", invalidFQDN, 99),
		testCurrentToken, "device-alpha", true,
	)
	if response.Code != http.StatusBadRequest ||
		app.nodes["device-alpha"].Stats.CPU == 99 {
		t.Fatalf("invalid FQDN was not rejected safely: %d", response.Code)
	}
}

func TestDeviceEndpointMalformedDomainDegradesOnlyAfterValidAuthentication(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	app := newStageCApp(t, registry, []contracts.CredentialRecord{
		activeTestCredentialRecord("device-alpha"),
	}, nil)
	body := validDeviceEnvelope(t, "device-alpha", nil, 61)
	var envelope map[string]any
	_ = json.Unmarshal(body, &envelope)
	stats := envelope["stats"].(map[string]any)
	hardware := stats["hardware"].(map[string]any)
	hardware["unexpected_domain_field"] = "raw-secret-marker"
	body, _ = json.Marshal(envelope)

	response := performDeviceUpdateRequest(
		app, http.MethodPost, body, testWrongToken, "device-alpha", true,
	)
	if response.Code != http.StatusUnauthorized || app.nodes["device-alpha"].HasUpdate {
		t.Fatal("malformed domain reached state before authentication")
	}
	response = performDeviceUpdateRequest(
		app, http.MethodPost, body, testCurrentToken, "device-alpha", true,
	)
	if response.Code != http.StatusAccepted ||
		app.nodes["device-alpha"].Stats.CPU != 61 ||
		app.deviceStatusAt(app.nodes["device-alpha"], time.Now()) != "degraded" {
		t.Fatalf("authenticated partial domain was not isolated: %d %#v",
			response.Code, app.nodes["device-alpha"])
	}
}

func TestDeviceEndpointConcurrentDevicesRemainIsolated(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	)
	app := newStageCApp(t, registry, []contracts.CredentialRecord{
		activeTestCredentialRecord("device-alpha"),
		testCredentialRecord("device-beta", testCredentialSlot(
			"current", testNextToken, time.Now().Add(-time.Hour), time.Now().Add(time.Hour),
		)),
	}, nil)
	type update struct {
		device string
		token  string
		body   []byte
	}
	updates := []update{
		{
			device: "device-alpha", token: testCurrentToken,
			body: validDeviceEnvelope(t, "device-alpha", nil, 31),
		},
		{
			device: "device-beta", token: testNextToken,
			body: validDeviceEnvelope(t, "device-beta", nil, 47),
		},
	}
	start := make(chan struct{})
	results := make(chan int, len(updates))
	var wait sync.WaitGroup
	for _, item := range updates {
		item := item
		wait.Add(1)
		go func() {
			defer wait.Done()
			<-start
			response := performDeviceUpdateRequest(
				app, http.MethodPost, item.body,
				item.token, item.device, true,
			)
			results <- response.Code
		}()
	}
	close(start)
	wait.Wait()
	close(results)
	for status := range results {
		if status != http.StatusAccepted {
			t.Fatalf("concurrent device update failed: %d", status)
		}
	}
	if app.nodes["device-alpha"].Stats.CPU != 31 ||
		app.nodes["device-beta"].Stats.CPU != 47 {
		t.Fatalf("concurrent updates crossed device state: alpha=%v beta=%v",
			app.nodes["device-alpha"].Stats.CPU, app.nodes["device-beta"].Stats.CPU)
	}
}

func TestDeviceEndpointErrorsAndLogsNeverExposeSecrets(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", stringPointer("alpha.example.invalid")),
	)
	app := newStageCApp(t, registry, []contracts.CredentialRecord{
		activeTestCredentialRecord("device-alpha"),
	}, nil)
	var logs bytes.Buffer
	app.logger = log.New(&logs, "", 0)
	body := addEnvelopeField(
		t, validDeviceEnvelope(t, "device-alpha", nil, 12),
		"raw-secret-marker", "body-secret-marker",
	)
	snapshotTime := time.Unix(1_800_000_000, 0).UTC()
	beforeSnapshot, err := app.snapshotPersistenceV2(snapshotTime)
	if err != nil {
		t.Fatal(err)
	}
	beforePersistence, _ := json.Marshal(beforeSnapshot)
	wrongDigest := sha256.Sum256([]byte("synthetic-secret-token-000000000099"))
	response := performDeviceUpdateRequest(
		app, http.MethodPost, body,
		"synthetic-secret-token-000000000099", "device-alpha", true,
	)
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("wrong credential status=%d", response.Code)
	}
	afterSnapshot, err := app.snapshotPersistenceV2(snapshotTime)
	if err != nil {
		t.Fatal(err)
	}
	afterPersistence, _ := json.Marshal(afterSnapshot)
	if !bytes.Equal(beforePersistence, afterPersistence) {
		t.Fatal("failed authentication changed persistence state")
	}
	statsJSON, _ := json.Marshal(app.SnapshotStats())
	combined := logs.String() + response.Body.String() + string(statsJSON)
	for _, forbidden := range []string{
		"synthetic-secret-token", "body-secret-marker", "raw-secret-marker",
		"alpha.example.invalid", "Authorization", "sha256",
		hex.EncodeToString(wrongDigest[:]), filepath.Dir(app.opts.DeviceCredentialsDir),
	} {
		if forbidden != "" && strings.Contains(combined, forbidden) {
			t.Fatalf("secret-bearing value %q leaked: %s", forbidden, combined)
		}
	}
	if strings.Contains(response.Body.String(), "current") ||
		strings.Contains(response.Body.String(), "next") {
		t.Fatalf("credential slot leaked in public error: %s", response.Body.String())
	}
}

func TestDeviceEndpointReturns500ForUnsafeMonitorAfterValidIngestion(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	doc := minimalTestConfig()
	doc["monitors"] = []any{map[string]any{
		"name": "unsafe", "host": "https://example.invalid/?token=raw-secret-marker",
		"interval": 60, "type": "https",
	}}
	app := newStageCAppWithConfig(t, doc, registry, []contracts.CredentialRecord{
		activeTestCredentialRecord("device-alpha"),
	}, nil)
	response := performDeviceUpdateRequest(
		app, http.MethodPost, validDeviceEnvelope(t, "device-alpha", nil, 77),
		testCurrentToken, "device-alpha", true,
	)
	if response.Code != http.StatusInternalServerError ||
		!app.nodes["device-alpha"].HasUpdate ||
		app.nodes["device-alpha"].Stats.CPU != 77 ||
		strings.Contains(response.Body.String(), "raw-secret-marker") {
		t.Fatalf("unsafe monitor boundary failed: %d %s", response.Code, response.Body.String())
	}
}

func TestSanitizedMonitorTargetsRejectExecutableOrPathInjection(t *testing.T) {
	for _, monitor := range []struct {
		host string
		kind string
	}{
		{"http://example.invalid/health", "http"},
		{"https://192.0.2.10:8443/status", "https"},
		{"example.invalid:443", "tcp"},
		{"[2001:db8::1]:443", "tcp"},
	} {
		if !safeMonitorHost(monitor.host, monitor.kind) {
			t.Fatalf("safe monitor was rejected: %#v", monitor)
		}
	}
	for _, monitor := range []struct {
		host string
		kind string
	}{
		{"../../etc/passwd", "https"},
		{"file:///etc/passwd", "https"},
		{"https://user:password@example.invalid", "https"},
		{"https://example.invalid/#fragment", "https"},
		{"https://example.invalid/?token=secret", "https"},
		{"https://example.invalid/../admin", "https"},
		{"example.invalid:443", "command"},
		{"https://example.invalid", "tcp"},
	} {
		if safeMonitorHost(monitor.host, monitor.kind) {
			t.Fatalf("unsafe monitor was accepted: %#v", monitor)
		}
	}
}

func newStageCApp(
	t *testing.T,
	registry contracts.DeviceRegistry,
	credentials []contracts.CredentialRecord,
	mutateOptions func(*Options),
) *App {
	t.Helper()
	return newStageCAppWithConfig(t, minimalTestConfig(), registry, credentials, mutateOptions)
}

func newStageCAppWithConfig(
	t *testing.T,
	doc ConfigDocument,
	registry contracts.DeviceRegistry,
	credentials []contracts.CredentialRecord,
	mutateOptions func(*Options),
) *App {
	t.Helper()
	directory := t.TempDir()
	configPath := filepath.Join(directory, "config.json")
	statsPath := filepath.Join(directory, "stats.json")
	persistencePath := filepath.Join(directory, "state-v2.json")
	registryPath := filepath.Join(directory, "registry.json")
	mappingPath := filepath.Join(directory, "legacy-mapping.json")
	credentialDirectory := filepath.Join(directory, "credentials")
	if err := os.Mkdir(credentialDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	writeJSONTestFile(t, configPath, doc)
	writeJSONTestFile(t, registryPath, registry)
	writeJSONTestFile(t, mappingPath, contracts.LegacyMappingDocument{Version: 1})
	for _, record := range credentials {
		writeJSONTestFile(t, filepath.Join(credentialDirectory, record.DeviceID+".json"), record)
	}
	opts := Options{
		ConfigPath: configPath, StatsPath: statsPath,
		PersistencePath: persistencePath, RegistryPath: registryPath,
		LegacyMappingPath: mappingPath, DeviceCredentialsDir: credentialDirectory,
		DeviceEndpointEnabled: true, WebDir: directory,
		HTTPAddr: "127.0.0.1:0", AgentAddr: "127.0.0.1:0",
		AdminToken: "test-admin-token",
	}
	if mutateOptions != nil {
		mutateOptions(&opts)
	}
	app, err := NewApp(opts)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Close)
	return app
}

func activeTestCredentialRecord(deviceID string) contracts.CredentialRecord {
	now := time.Now()
	return testCredentialRecord(
		deviceID,
		testCredentialSlot("current", testCurrentToken, now.Add(-time.Hour), now.Add(time.Hour)),
		testCredentialSlot("next", testNextToken, now.Add(-time.Minute), now.Add(2*time.Hour)),
	)
}

func validDeviceEnvelope(
	t *testing.T,
	deviceID string,
	reportedFQDN *string,
	cpu float64,
) []byte {
	t.Helper()
	var stats map[string]any
	if err := json.Unmarshal(readFixture(t, "update-normal.json"), &stats); err != nil {
		t.Fatal(err)
	}
	stats["cpu"] = cpu
	device := map[string]any{"id": deviceID}
	if reportedFQDN != nil {
		device["reported_fqdn"] = *reportedFQDN
	}
	envelope := map[string]any{
		"schema_version": 2,
		"device":         device,
		"collected_at":   time.Now().UTC().Format(time.RFC3339),
		"stats":          stats,
	}
	data, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func addEnvelopeField(t *testing.T, body []byte, key string, value any) []byte {
	t.Helper()
	var envelope map[string]any
	if err := json.Unmarshal(body, &envelope); err != nil {
		t.Fatal(err)
	}
	envelope[key] = value
	data, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func replaceEnvelopeField(t *testing.T, body []byte, key string, value any) []byte {
	return addEnvelopeField(t, body, key, value)
}

func addDeviceEnvelopeField(t *testing.T, body []byte, key string, value any) []byte {
	t.Helper()
	var envelope map[string]any
	if err := json.Unmarshal(body, &envelope); err != nil {
		t.Fatal(err)
	}
	envelope["device"].(map[string]any)[key] = value
	data, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func removeStatsEnvelopeField(t *testing.T, body []byte, key string) []byte {
	t.Helper()
	var envelope map[string]any
	if err := json.Unmarshal(body, &envelope); err != nil {
		t.Fatal(err)
	}
	delete(envelope["stats"].(map[string]any), key)
	data, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func performDeviceUpdateRequest(
	app *App,
	method string,
	body []byte,
	token string,
	deviceID string,
	secure bool,
) *httptest.ResponseRecorder {
	request := newDeviceRequest(method, body, token, deviceID, secure)
	response := httptest.NewRecorder()
	app.router().ServeHTTP(response, request)
	return response
}

func newDeviceRequest(
	method string,
	body []byte,
	token string,
	deviceID string,
	secure bool,
) *http.Request {
	scheme := "http"
	if secure {
		scheme = "https"
	}
	request := httptest.NewRequest(
		method, scheme+"://example.invalid"+deviceUpdatePath, bytes.NewReader(body),
	)
	request.RemoteAddr = "127.0.0.1:40000"
	setDeviceHeaders(request, token, deviceID)
	return request
}

func setDeviceHeaders(request *http.Request, token string, deviceID string) {
	request.Header.Set("Content-Type", "application/json")
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	if deviceID != "" {
		request.Header.Set("X-HermesStatus-Device-ID", deviceID)
	}
}

func assertBoundedDeviceError(t *testing.T, response *httptest.ResponseRecorder) {
	t.Helper()
	if !strings.HasPrefix(response.Header().Get("Content-Type"), "application/json") {
		t.Fatalf("error response is not JSON: %#v", response.Header())
	}
	var public contracts.ErrorResponse
	if err := json.Unmarshal(response.Body.Bytes(), &public); err != nil {
		t.Fatal(err)
	}
	if err := contracts.ValidateErrorResponse(public); err != nil {
		t.Fatalf("error response is invalid: %#v err=%v", public, err)
	}
	if response.Body.Len() > 512 {
		t.Fatalf("error response is unbounded: %d", response.Body.Len())
	}
}

func stringPointer(value string) *string {
	return &value
}
