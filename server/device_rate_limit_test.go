package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

func TestBoundedRateLimiterCapacityCleanupAndRetry(t *testing.T) {
	now := time.Date(2026, 7, 29, 12, 0, 0, 0, time.UTC)
	limiter := newBoundedRateLimiter(2, 2, time.Minute, 2*time.Minute)
	if allowed, _ := limiter.Allow("a", now); !allowed {
		t.Fatal("first request was blocked")
	}
	if allowed, _ := limiter.Allow("a", now.Add(time.Second)); !allowed {
		t.Fatal("second request was blocked")
	}
	if allowed, retry := limiter.Allow("a", now.Add(2*time.Second)); allowed ||
		retry < time.Second || retry > time.Minute {
		t.Fatalf("limit/retry boundary failed: allowed=%t retry=%s", allowed, retry)
	}
	if allowed, _ := limiter.Allow("b", now); !allowed {
		t.Fatal("second key was blocked before capacity")
	}
	if allowed, retry := limiter.Allow("c", now); allowed || retry != time.Second {
		t.Fatalf("bounded capacity was exceeded: allowed=%t retry=%s", allowed, retry)
	}
	if limiter.Len() != 2 {
		t.Fatalf("limiter map exceeded capacity: %d", limiter.Len())
	}
	if allowed, _ := limiter.Allow("c", now.Add(3*time.Minute)); !allowed {
		t.Fatal("expired entries were not cleaned")
	}
	if limiter.Len() != 1 {
		t.Fatalf("cleanup did not remove expired entries: %d", limiter.Len())
	}
}

func TestDeviceEndpointPreAuthRateLimitDoesNotModifyState(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	app := newStageCApp(t, registry, []contracts.CredentialRecord{
		activeTestCredentialRecord("device-alpha"),
	}, func(opts *Options) {
		opts.PreAuthRateLimit = 1
		opts.DeviceRateLimit = 100
	})
	body := validDeviceEnvelope(t, "device-alpha", nil, 12)
	first := performDeviceUpdateRequest(
		app, "POST", body, testWrongToken, "device-alpha", true,
	)
	second := performDeviceUpdateRequest(
		app, "POST", body, testWrongToken, "device-alpha", true,
	)
	if first.Code != 401 || second.Code != 429 ||
		second.Header().Get("Retry-After") == "" {
		t.Fatalf("pre-auth limit failed: first=%d second=%d headers=%#v",
			first.Code, second.Code, second.Header())
	}
	node := app.nodes["device-alpha"]
	if node.HasUpdate || node.LastAcceptedGeneration != 0 || !node.LastSeen.IsZero() {
		t.Fatalf("pre-auth limiter modified device state: %#v", node)
	}
}

func TestDeviceEndpointPerDeviceRateLimitIsIsolatedAndNotPersisted(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
		testRegistryDevice("device-beta", "Beta", 20, true, "device_v2", nil),
	)
	now := time.Now()
	app := newStageCApp(t, registry, []contracts.CredentialRecord{
		activeTestCredentialRecord("device-alpha"),
		testCredentialRecord("device-beta", testCredentialSlot(
			"current", testNextToken, now.Add(-time.Hour), now.Add(time.Hour),
		)),
	}, func(opts *Options) {
		opts.PreAuthRateLimit = 100
		opts.DeviceRateLimit = 1
	})
	first := performDeviceUpdateRequest(
		app, "POST", validDeviceEnvelope(t, "device-alpha", nil, 21),
		testCurrentToken, "device-alpha", true,
	)
	acceptedGeneration := app.nodes["device-alpha"].LastAcceptedGeneration
	second := performDeviceUpdateRequest(
		app, "POST", validDeviceEnvelope(t, "device-alpha", nil, 22),
		testCurrentToken, "device-alpha", true,
	)
	beta := performDeviceUpdateRequest(
		app, "POST", validDeviceEnvelope(t, "device-beta", nil, 31),
		testNextToken, "device-beta", true,
	)
	if first.Code != 202 || second.Code != 429 || beta.Code != 202 {
		t.Fatalf("per-device limiter isolation failed: alpha1=%d alpha2=%d beta=%d",
			first.Code, second.Code, beta.Code)
	}
	if app.nodes["device-alpha"].Stats.CPU != 21 ||
		app.nodes["device-alpha"].LastAcceptedGeneration != acceptedGeneration ||
		app.nodes["device-beta"].Stats.CPU != 31 {
		t.Fatal("rate-limited request modified state or crossed devices")
	}
	if err := app.PersistStats(); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(app.opts.PersistencePath)
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"rate_limited", "src-", "Retry-After"} {
		if strings.Contains(string(data), forbidden) {
			t.Fatalf("limiter state leaked into persistence: %q", forbidden)
		}
	}
}

func TestPreAuthSourceKeyTrustBoundary(t *testing.T) {
	registry := testRegistry(
		testRegistryDevice("device-alpha", "Alpha", 10, true, "device_v2", nil),
	)
	app := newStageCApp(t, registry, []contracts.CredentialRecord{
		activeTestCredentialRecord("device-alpha"),
	}, func(opts *Options) {
		opts.TrustedProxyMode = true
		opts.TrustedProxyCIDRs = "192.0.2.10/32"
	})

	trusted := httptest.NewRequest(
		http.MethodPost, "http://backend.invalid"+deviceUpdatePath, nil,
	)
	trusted.RemoteAddr = "192.0.2.10:443"
	trusted.Header.Set("X-Forwarded-For", "203.0.113.7")
	if got, want := app.preAuthRequestKey(trusted), preAuthSourceKey("203.0.113.7"); got != want {
		t.Fatalf("trusted proxy source key=%q want=%q", got, want)
	}

	forged := httptest.NewRequest(
		http.MethodPost, "https://backend.invalid"+deviceUpdatePath, nil,
	)
	forged.RemoteAddr = "198.51.100.8:443"
	forged.Header.Set("X-Forwarded-For", "203.0.113.7")
	if got, want := app.preAuthRequestKey(forged), preAuthSourceKey("198.51.100.8"); got != want {
		t.Fatalf("untrusted XFF changed limiter key: got=%q want=%q", got, want)
	}

	malformed := httptest.NewRequest(
		http.MethodPost, "http://backend.invalid"+deviceUpdatePath, nil,
	)
	malformed.RemoteAddr = "not-an-address"
	malformed.Header.Set("X-Forwarded-For", "203.0.113.7")
	if got := app.preAuthRequestKey(malformed); got != globalUnauthenticatedSourceKey {
		t.Fatalf("unreliable source did not use bounded global limiter: %q", got)
	}
}

func TestPerDeviceLimiterIsBoundedToRegisteredDevices(t *testing.T) {
	devices := make([]contracts.RegistryDevice, 0, contracts.MaxRegisteredDevices)
	credentials := make([]contracts.CredentialRecord, 0, contracts.MaxRegisteredDevices)
	for index := 0; index < contracts.MaxRegisteredDevices; index++ {
		deviceID := fmt.Sprintf("device-%02d", index)
		devices = append(devices, testRegistryDevice(
			deviceID, deviceID, index, true, "device_v2", nil,
		))
		credentials = append(credentials, activeTestCredentialRecord(deviceID))
	}
	app := newStageCApp(t, testRegistry(devices...), credentials, func(opts *Options) {
		opts.PreAuthRateLimit = 100
		opts.DeviceRateLimit = 100
	})
	for index := 0; index < contracts.MaxRegisteredDevices; index++ {
		deviceID := fmt.Sprintf("device-%02d", index)
		response := performDeviceUpdateRequest(
			app, http.MethodPost, validDeviceEnvelope(t, deviceID, nil, float64(index)),
			testCurrentToken, deviceID, true,
		)
		if response.Code != http.StatusAccepted {
			t.Fatalf("registered device %s was rate limited: %d %s",
				deviceID, response.Code, response.Body.String())
		}
	}
	if got := app.deviceLimiter.Len(); got != contracts.MaxRegisteredDevices {
		t.Fatalf("per-device limiter state=%d want=%d",
			got, contracts.MaxRegisteredDevices)
	}
	unknown := performDeviceUpdateRequest(
		app, http.MethodPost, validDeviceEnvelope(t, "device-00", nil, 99),
		testCurrentToken, "device-17", true,
	)
	if unknown.Code != http.StatusUnauthorized ||
		app.deviceLimiter.Len() != contracts.MaxRegisteredDevices {
		t.Fatalf("unregistered device created limiter state: status=%d entries=%d",
			unknown.Code, app.deviceLimiter.Len())
	}
}
