package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"strings"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

type AgentServer struct {
	app *App
}

func NewAgentServer(app *App) *AgentServer {
	return &AgentServer{app: app}
}

func (s *AgentServer) ListenAndServe() error {
	listener, err := net.Listen("tcp", s.app.opts.AgentAddr)
	if err != nil {
		return err
	}
	s.app.logger.Printf("agent TCP listening on %s", listener.Addr())
	return s.Serve(listener)
}

func (s *AgentServer) Serve(listener net.Listener) error {
	defer listener.Close()
	s.app.agentRunning.Store(true)
	defer s.app.agentRunning.Store(false)
	go func() {
		<-s.app.ctx.Done()
		_ = listener.Close()
	}()
	for {
		conn, err := listener.Accept()
		if err != nil {
			if s.app.ctx.Err() != nil || errors.Is(err, net.ErrClosed) {
				return nil
			}
			return err
		}
		go s.handleConnection(conn)
	}
}

func (s *AgentServer) handleConnection(conn net.Conn) {
	defer conn.Close()
	if tcpConn, ok := conn.(*net.TCPConn); ok {
		_ = tcpConn.SetNoDelay(true)
		_ = tcpConn.SetKeepAlive(true)
		_ = tcpConn.SetKeepAlivePeriod(10 * time.Second)
	}
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	if _, err := io.WriteString(conn, "Authentication required:\n"); err != nil {
		return
	}

	reader := bufio.NewReaderSize(conn, 64*1024)
	credentials, err := reader.ReadString('\n')
	if err != nil {
		return
	}
	credentials = strings.TrimSpace(credentials)
	parts := strings.SplitN(credentials, ":", 2)
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		_, _ = io.WriteString(conn, "Wrong username and/or password.\n")
		return
	}
	family := remoteFamily(conn.RemoteAddr())
	deviceID, connectionID, monitors, apiErr := s.app.connectAgent(parts[0], parts[1], conn, family)
	if apiErr != nil {
		_, _ = io.WriteString(conn, apiErr.Message+"\n")
		return
	}
	defer s.app.disconnectAgent(deviceID, conn, connectionID)

	if _, err := io.WriteString(conn, "Authentication successful. Access granted.\n"); err != nil {
		return
	}
	// Existing Python agents use recv() instead of a line reader during the
	// handshake. Keep the auth and metadata packets separate for compatibility.
	time.Sleep(20 * time.Millisecond)
	var metadata strings.Builder
	fmt.Fprintf(&metadata, "You are connecting via: IPv%d\n", family)
	for index, monitor := range monitors {
		payload := map[string]any{"name": monitor.Name, "host": monitor.Host, "interval": monitor.Interval, "type": monitor.Type, "monitor": index}
		data, _ := json.Marshal(payload)
		metadata.Write(data)
		metadata.WriteByte('\n')
	}
	if _, err := io.WriteString(conn, metadata.String()); err != nil {
		return
	}

	_ = conn.SetDeadline(time.Now().Add(20 * time.Second))
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 4096), maxRequestBody)
	for scanner.Scan() {
		_ = conn.SetDeadline(time.Now().Add(20 * time.Second))
		line := strings.TrimSpace(scanner.Text())
		switch {
		case strings.HasPrefix(line, "update"):
			body := strings.TrimSpace(strings.TrimPrefix(line, "update"))
			generation := s.app.updateID.Add(1)
			issues, err := s.app.ingestDeviceUpdateAt(deviceIngestRequest{
				DeviceID:     deviceID,
				ProtocolMode: "legacy_single_device",
				CollectedAt:  time.Now(),
				FlatStats:    []byte(body),
				Generation:   generation,
				ConnectionID: connectionID,
			}, time.Now())
			if err != nil {
				if s.app.agentPong(deviceID, connectionID) {
					_, _ = io.WriteString(conn, "1\n")
				}
				continue
			}
			for _, issue := range issues {
				s.app.logger.Printf(
					"extension update username=%q domain=%s code=%s field=%s reason=%q payload_length=%d device_id=%q",
					parts[0], issue.Domain, issue.Code, issue.Field, issue.Reason, issue.PayloadLength, deviceID,
				)
			}
			if s.app.agentPong(deviceID, connectionID) {
				_, _ = io.WriteString(conn, "0\n")
			}
		case strings.HasPrefix(line, "pong"):
			value := strings.TrimSpace(strings.TrimPrefix(line, "pong"))
			s.app.setAgentPong(deviceID, connectionID, value == "1" || strings.EqualFold(value, "on"))
		default:
			if s.app.agentPong(deviceID, connectionID) {
				_, _ = io.WriteString(conn, "1\n")
			}
		}
	}
}

func remoteFamily(address net.Addr) int {
	host, _, err := net.SplitHostPort(address.String())
	if err == nil {
		if ip := net.ParseIP(host); ip != nil && ip.To4() == nil {
			return 6
		}
	}
	return 4
}

func (a *App) connectAgent(username, password string, conn net.Conn, family int) (string, uint64, []MonitorConfig, *APIError) {
	a.configMu.RLock()
	defer a.configMu.RUnlock()
	var config *ServerConfig
	for index := range a.runtime.Servers {
		if a.runtime.Servers[index].Username == username {
			server := a.runtime.Servers[index]
			config = &server
			break
		}
	}
	if config == nil || config.Password != password {
		return "", 0, nil, &APIError{Status: 401, Message: "Wrong username and/or password."}
	}
	if config.Disabled {
		return "", 0, nil, &APIError{Status: 403, Message: "Server is disabled."}
	}
	if a.ownershipFailClosed {
		return "", 0, nil, &APIError{Status: 409, Message: "Server protocol is inactive."}
	}
	a.nodeMu.Lock()
	defer a.nodeMu.Unlock()
	deviceID, mapped := a.deviceIDForUsername(username)
	if !mapped {
		return "", 0, nil, &APIError{Status: 403, Message: "Server is not configured."}
	}
	node := a.nodes[deviceID]
	if node == nil {
		return "", 0, nil, &APIError{Status: 404, Message: "Server is not configured."}
	}
	if !node.Enabled {
		return "", 0, nil, &APIError{Status: 403, Message: "Server is disabled."}
	}
	if a.registry != nil && !contracts.OwnershipAllows(node.Ownership, "legacy_single_device", time.Now()) {
		return "", 0, nil, &APIError{Status: 409, Message: "Server protocol is inactive."}
	}
	if node.Connected {
		return "", 0, nil, &APIError{Status: 409, Message: "Only one connection per user allowed."}
	}
	id := a.connectionID.Add(1)
	node.Connected = true
	node.Connection = conn
	node.ConnectionID = id
	node.Family = family
	if a.registry == nil {
		node.HasUpdate = false
	}
	node.Pong = false
	node.Online4 = family == 4
	node.Online6 = family == 6
	a.wakeStatsWriter()
	return deviceID, id, append([]MonitorConfig(nil), a.runtime.Monitors...), nil
}

func (a *App) disconnectAgent(identity string, conn net.Conn, connectionID uint64) {
	a.nodeMu.Lock()
	deviceID := a.resolveNodeKey(identity)
	node := a.nodes[deviceID]
	if node == nil || node.ConnectionID != connectionID || node.Connection != conn {
		a.nodeMu.Unlock()
		return
	}
	node.Connected = false
	node.Connection = nil
	node.Online4 = false
	node.Online6 = false
	if a.registry == nil {
		node.HasUpdate = false
	}
	node.Pong = false
	a.nodeMu.Unlock()
	a.wakeStatsWriter()
}

func (a *App) setAgentPong(identity string, connectionID uint64, enabled bool) {
	a.nodeMu.Lock()
	defer a.nodeMu.Unlock()
	deviceID := a.resolveNodeKey(identity)
	if node := a.nodes[deviceID]; node != nil && node.ConnectionID == connectionID {
		node.Pong = enabled
	}
}

func (a *App) agentPong(identity string, connectionID uint64) bool {
	a.nodeMu.RLock()
	defer a.nodeMu.RUnlock()
	deviceID := a.resolveNodeKey(identity)
	node := a.nodes[deviceID]
	return node != nil && node.ConnectionID == connectionID && node.Pong
}
