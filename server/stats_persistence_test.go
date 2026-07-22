package main

import (
	"bytes"
	"encoding/json"
	"log"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestStatsStartupDegradesSafelyAndRewritesInvalidFiles(t *testing.T) {
	cases := []struct {
		name string
		data []byte
	}{
		{name: "missing", data: nil},
		{name: "empty", data: []byte{}},
		{name: "invalid", data: []byte("{invalid")},
		{name: "wrong-root", data: []byte("[]")},
		{name: "truncated", data: []byte(`{"servers":[`)},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			app := newTestAppWithStats(t, testCase.data)
			server := app.SnapshotStats()["servers"].([]any)[0].(map[string]any)
			if server["hardware"].(*HardwareStats).Error.Code != "not_reported" {
				t.Fatalf("invalid persistence was treated as current state: %#v", server)
			}
			if err := app.PersistStats(); err != nil {
				t.Fatal(err)
			}
			data, err := os.ReadFile(app.opts.StatsPath)
			if err != nil {
				t.Fatal(err)
			}
			var document map[string]any
			if err := json.Unmarshal(data, &document); err != nil {
				t.Fatalf("stats file was not replaced with valid JSON: %v", err)
			}
			if _, ok := document["servers"].([]any); !ok {
				t.Fatalf("rewritten stats has no servers array: %#v", document)
			}
			matches, err := filepath.Glob(filepath.Join(filepath.Dir(app.opts.StatsPath), ".serverstatus-*.tmp"))
			if err != nil || len(matches) != 0 {
				t.Fatalf("atomic-write temporary files remain: %v, %v", matches, err)
			}
		})
	}
}

func TestStatsWriteReportsUnwritableDataPath(t *testing.T) {
	directory := t.TempDir()
	blockingFile := filepath.Join(directory, "not-a-directory")
	if err := os.WriteFile(blockingFile, []byte("block"), 0o600); err != nil {
		t.Fatal(err)
	}
	err := writeStatsFile(filepath.Join(blockingFile, "stats.json"), map[string]any{"servers": []any{}})
	if err == nil {
		t.Fatal("write unexpectedly succeeded through a non-directory path")
	}
	if strings.Contains(err.Error(), "block") {
		t.Fatalf("error leaked file contents: %v", err)
	}
}

func TestStatsRestoreLogDoesNotExposeDamagedContent(t *testing.T) {
	app := newTestAppWithStats(t, nil)
	damaged := "credential-fragment that must not be logged"
	if err := os.MkdirAll(filepath.Dir(app.opts.StatsPath), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(app.opts.StatsPath, []byte(damaged), 0o600); err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	app.logger = log.New(&output, "", 0)
	app.restorePersistentState()
	if !strings.Contains(output.String(), "invalid_json") {
		t.Fatalf("sanitized error code was not logged: %q", output.String())
	}
	if strings.Contains(output.String(), "credential") || strings.Contains(output.String(), "invalid character") {
		t.Fatalf("damaged stats content leaked into logs: %q", output.String())
	}
}

func TestStatsReadErrorsUseSafeDiagnosticCodes(t *testing.T) {
	if code := statsReadErrorCode(os.ErrNotExist, os.ErrNotExist); code != "" {
		t.Fatalf("missing first-start files should be quiet, got %q", code)
	}
	if code := statsReadErrorCode(os.ErrPermission, os.ErrNotExist); code != "permission_denied" {
		t.Fatalf("permission error was not classified safely: %q", code)
	}
	if code := statsReadErrorCode(os.ErrInvalid, os.ErrNotExist); code != "unavailable" {
		t.Fatalf("read error was not classified safely: %q", code)
	}
}

func TestStatsRestoreMatchesStableIdentityAcrossMultipleNodes(t *testing.T) {
	doc := minimalTestConfig()
	doc["servers"] = append(doc["servers"].([]any), map[string]any{
		"username": "s02", "name": "node2", "type": "physical", "host": "host2",
		"location": "SG", "password": "secret", "monthstart": 1,
	})
	app := newTestApp(t, doc)
	persisted := map[string]any{
		"servers": []any{
			map[string]any{
				"name": "node2", "type": "physical", "host": "host2", "location": "SG",
				"last_network_in": 220, "last_network_out": 221, "os": "second-os", "cpu_model": "second-cpu",
				"docker": map[string]any{"running": 5, "total": 8},
			},
			map[string]any{
				"name": "node1", "type": "kvm", "host": "host1", "location": "CN",
				"last_network_in": 110, "last_network_out": 111, "os": "first-os", "cpu_model": "first-cpu",
				"docker": map[string]any{"running": 2, "total": 3},
			},
		},
	}
	data, err := json.Marshal(persisted)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(app.opts.StatsPath), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(app.opts.StatsPath, data, 0o600); err != nil {
		t.Fatal(err)
	}
	app.restorePersistentState()
	if app.nodes["s01"].LastNetworkIn != 110 || app.nodes["s01"].Stats.OS != "first-os" {
		t.Fatalf("first node was restored from the wrong array entry: %#v", app.nodes["s01"])
	}
	if app.nodes["s02"].LastNetworkIn != 220 || app.nodes["s02"].Stats.OS != "second-os" {
		t.Fatalf("second node was not restored by stable identity: %#v", app.nodes["s02"])
	}
	for _, username := range []string{"s01", "s02"} {
		if app.nodes[username].Extension.Docker.Total != 0 {
			t.Fatalf("persisted Docker count was restored as fresh for %s", username)
		}
	}
}

func newTestAppWithStats(t *testing.T, stats []byte) *App {
	t.Helper()
	directory := t.TempDir()
	configPath := filepath.Join(directory, "config.json")
	statsPath := filepath.Join(directory, "data", "stats.json")
	webDir := filepath.Join(directory, "web")
	if err := os.MkdirAll(webDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(webDir, "index.html"), []byte("test"), 0o644); err != nil {
		t.Fatal(err)
	}
	config, err := json.Marshal(minimalTestConfig())
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(configPath, config, 0o600); err != nil {
		t.Fatal(err)
	}
	if stats != nil {
		if err := os.MkdirAll(filepath.Dir(statsPath), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(statsPath, stats, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	app, err := NewApp(Options{
		ConfigPath: configPath,
		StatsPath:  statsPath,
		WebDir:     webDir,
		HTTPAddr:   "127.0.0.1:0",
		AgentAddr:  "127.0.0.1:0",
		AdminToken: "test-token",
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Close)
	return app
}
