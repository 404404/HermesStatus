package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"strings"
	"testing"
	"time"
)

func TestTCPStructuredUpdateAndDomainFailureIsolation(t *testing.T) {
	app := newTestApp(t, minimalTestConfig())
	var logs bytes.Buffer
	app.logger = log.New(&logs, "serverstatus ", 0)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	serveDone := make(chan error, 1)
	go func() { serveDone <- NewAgentServer(app).Serve(listener) }()

	connection, err := net.DialTimeout("tcp", listener.Addr().String(), time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	reader := bufio.NewReader(connection)
	readContains(t, reader, "Authentication required")
	_, _ = fmt.Fprintln(connection, "s01:secret")
	readContains(t, reader, "Authentication successful")
	readContains(t, reader, "You are connecting via: IPv4")
	readContains(t, reader, `"monitor":0`)
	_, _ = fmt.Fprintln(connection, "pong on")

	payload := structuredUpdatePayload(t, "update-normal.json", map[string]any{
		"cpu": 42, "memory_total": 8192, "memory_used": 2048, "hdd_total": 120000, "hdd_used": 30000,
	})
	before := time.Now().UTC()
	if _, err := fmt.Fprintf(connection, "update %s\n", payload); err != nil {
		t.Fatal(err)
	}
	readContains(t, reader, "0")
	eventually(t, time.Second, func() bool {
		server := app.SnapshotStats()["servers"].([]any)[0].(map[string]any)
		hardware, ok := server["hardware"].(*HardwareStats)
		return server["cpu"] == 42 && ok && hardware.CPUModel != nil && *hardware.CPUModel == "Example CPU 4-Core"
	})
	server := app.SnapshotStats()["servers"].([]any)[0].(map[string]any)
	receivedAt, err := time.Parse(time.RFC3339, server["received_at"].(string))
	if err != nil || receivedAt.Before(before) || receivedAt.After(time.Now().UTC()) {
		t.Fatalf("TCP update did not set received_at: %v %v", receivedAt, err)
	}

	var fields map[string]json.RawMessage
	if err := json.Unmarshal(payload, &fields); err != nil {
		t.Fatal(err)
	}
	var hardware map[string]any
	if err := json.Unmarshal(fields["hardware"], &hardware); err != nil {
		t.Fatal(err)
	}
	hardware["unexpected_extension_field"] = "password=private-log-value"
	fields["hardware"] = mustRawJSON(t, hardware)
	fields["cpu"] = mustRawJSON(t, 73)
	invalidPayload, _ := json.Marshal(fields)
	if _, err := fmt.Fprintf(connection, "update %s\n", invalidPayload); err != nil {
		t.Fatal(err)
	}
	readContains(t, reader, "0")
	eventually(t, time.Second, func() bool {
		server := app.SnapshotStats()["servers"].([]any)[0].(map[string]any)
		hardware := server["hardware"].(*HardwareStats)
		return server["cpu"] == 73 && hardware.Error != nil && hardware.Error.Code == validationCodeUnknownField && server["docker"].(*DockerStats).Total == 3
	})

	logText := logs.String()
	if !strings.Contains(logText, `username="s01" domain=hardware code=unknown_field field=extension reason="payload contains an unknown field" payload_length=`) {
		t.Fatalf("safe domain failure was not logged: %s", logText)
	}
	for _, forbidden := range []string{"private-log-value", "unexpected_extension_field", "password="} {
		if strings.Contains(logText, forbidden) {
			t.Fatalf("TCP log leaked %q: %s", forbidden, logText)
		}
	}

	app.cancel()
	_ = listener.Close()
	select {
	case err := <-serveDone:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("agent server did not stop")
	}
}
