package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"net"
	"net/netip"
	"os"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/cppla/serverstatus/server/contracts"
)

type Options struct {
	ConfigPath              string
	StatsPath               string
	PersistencePath         string
	RegistryPath            string
	LegacyMappingPath       string
	DeviceCredentialsDir    string
	DeviceEndpointEnabled   bool
	TrustedProxyMode        bool
	TrustedProxyCIDRs       string
	AllowLoopbackDeviceHTTP bool
	PreAuthRateLimit        int
	DeviceRateLimit         int
	WebDir                  string
	HTTPAddr                string
	AgentAddr               string
	AdminToken              string
	CORSOrigin              string
	Verbose                 bool
}

type NodeState struct {
	DeviceID       string
	LegacyUsername string
	DisplayName    string
	ExpectedFQDN   *string
	Enabled        bool
	Order          int
	Ownership      contracts.IngestionOwnership

	Config         ServerConfig
	Connected      bool
	Connection     net.Conn
	ConnectionID   uint64
	Family         int
	Online4        bool
	Online6        bool
	Stats          AgentStats
	Extension      ExtensionSnapshot
	HasUpdate      bool
	LastNetworkIn  int64
	LastNetworkOut int64
	LastUpdate     time.Time
	Pong           bool

	IdentityStatus         string
	ProtocolMode           string
	ReportedName           *string
	ReportedFQDN           *string
	ReportedHostname       *string
	LastSeen               time.Time
	CollectedAt            time.Time
	LastAcceptedGeneration uint64
	LastRequestDigest      [sha256.Size]byte
	HasLastRequestDigest   bool
	Restored               bool
	IdentityError          bool
	Degraded               bool
}

type App struct {
	opts      Options
	startedAt time.Time
	ctx       context.Context
	cancel    context.CancelFunc

	mutationMu sync.Mutex
	configMu   sync.RWMutex
	document   ConfigDocument
	runtime    RuntimeConfig

	nodeMu                sync.RWMutex
	deviceIngestLocks     sync.Map
	nodes                 map[string]*NodeState
	registry              *contracts.DeviceRegistry
	legacyMap             map[string]string
	deviceUsers           map[string]string
	orphans               []contracts.OrphanedDevice
	ownershipFailClosed   bool
	deviceEndpointEnabled bool
	deviceCredentials     map[string]deviceCredentialSet
	trustedProxyPrefixes  []netip.Prefix
	preAuthLimiter        *boundedRateLimiter
	deviceLimiter         *boundedRateLimiter
	connectionID          atomic.Uint64
	updateID              atomic.Uint64
	generation            atomic.Uint64
	agentRunning          atomic.Bool
	reloadWrites          atomic.Int32

	certMu sync.RWMutex
	certs  map[string]*CertState

	statsWake chan struct{}
	persistMu sync.Mutex
	logger    *log.Logger
}

func NewApp(opts Options) (*App, error) {
	var err error
	opts, err = resolveOptionsPaths(opts)
	if err != nil {
		return nil, err
	}
	doc, runtime, err := readConfig(opts.ConfigPath)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithCancel(context.Background())
	app := &App{
		opts:      opts,
		startedAt: time.Now(),
		ctx:       ctx,
		cancel:    cancel,
		nodes:     make(map[string]*NodeState),
		certs:     make(map[string]*CertState),
		statsWake: make(chan struct{}, 1),
		logger:    log.New(os.Stdout, "serverstatus ", log.LstdFlags|log.Lmicroseconds),
	}
	if err := app.loadMultiDeviceRuntime(runtime); err != nil {
		cancel()
		return nil, err
	}
	if app.registry != nil {
		paths, pathErr := openPersistencePaths(
			app.opts.PersistencePath,
			app.opts.PersistencePath+"~",
			true,
		)
		if pathErr != nil {
			cancel()
			return nil, errors.New("multi-device persistence path is unavailable")
		}
		paths.close()
	}
	if err := app.configureDeviceEndpoint(); err != nil {
		cancel()
		return nil, err
	}
	app.applyValidatedConfig(doc, runtime, false)
	if err := app.restorePersistentState(); err != nil {
		cancel()
		return nil, err
	}
	return app, nil
}

func (a *App) StartBackground() {
	go a.statsLoop()
	go a.sslLoop()
	a.wakeStatsWriter()
}

func (a *App) Close() {
	a.cancel()
	a.disconnectAll("Server shutting down...")
	_ = a.PersistStats()
}

func (a *App) ConfigSnapshot() ConfigDocument {
	a.configMu.RLock()
	defer a.configMu.RUnlock()
	clone, err := cloneDocument(a.document)
	if err != nil {
		panic(err)
	}
	return clone
}

func (a *App) RuntimeSnapshot() RuntimeConfig {
	a.configMu.RLock()
	defer a.configMu.RUnlock()
	result := a.runtime
	result.Servers = append([]ServerConfig(nil), a.runtime.Servers...)
	result.Monitors = append([]MonitorConfig(nil), a.runtime.Monitors...)
	result.SSLCerts = append([]SSLCertConfig(nil), a.runtime.SSLCerts...)
	return result
}

func (a *App) ReplaceConfig(input ConfigDocument) (ConfigDocument, *APIError) {
	a.mutationMu.Lock()
	defer a.mutationMu.Unlock()
	normalized, runtime, apiErr := normalizeConfig(input)
	if apiErr != nil {
		return nil, apiErr
	}
	if err := writeConfig(a.opts.ConfigPath, normalized); err != nil {
		return nil, &APIError{Status: 500, Message: "config could not be written", Details: map[string]any{"error": err.Error()}}
	}
	a.applyValidatedConfig(normalized, runtime, true)
	return a.ConfigSnapshot(), nil
}

func (a *App) MutateConfig(mutate func(ConfigDocument) *APIError) (ConfigDocument, *APIError) {
	a.mutationMu.Lock()
	defer a.mutationMu.Unlock()
	doc := a.ConfigSnapshot()
	if apiErr := mutate(doc); apiErr != nil {
		return nil, apiErr
	}
	normalized, runtime, apiErr := normalizeConfig(doc)
	if apiErr != nil {
		return nil, apiErr
	}
	if err := writeConfig(a.opts.ConfigPath, normalized); err != nil {
		return nil, &APIError{Status: 500, Message: "config could not be written", Details: map[string]any{"error": err.Error()}}
	}
	a.applyValidatedConfig(normalized, runtime, true)
	return a.ConfigSnapshot(), nil
}

func (a *App) ReloadConfig() *APIError {
	a.mutationMu.Lock()
	defer a.mutationMu.Unlock()
	doc, runtime, err := readConfig(a.opts.ConfigPath)
	if err != nil {
		if apiErr, ok := err.(*APIError); ok {
			return apiErr
		}
		return &APIError{Status: 500, Message: "config could not be reloaded", Details: map[string]any{"error": err.Error()}}
	}
	a.applyValidatedConfig(doc, runtime, true)
	return nil
}

func (a *App) applyValidatedConfig(doc ConfigDocument, runtime RuntimeConfig, disconnect bool) {
	a.configMu.Lock()
	a.nodeMu.Lock()
	oldNodes := a.nodes
	connections := make([]net.Conn, 0)
	now := time.Now()
	newNodes := a.rebuildNodesLocked(runtime, oldNodes, disconnect, now)
	if disconnect {
		for _, node := range oldNodes {
			if node.Connection != nil {
				connections = append(connections, node.Connection)
			}
		}
	}
	a.document = doc
	a.runtime = runtime
	a.nodes = newNodes
	a.generation.Add(1)
	a.nodeMu.Unlock()
	a.configMu.Unlock()

	a.reconcileCerts(runtime.SSLCerts)
	if disconnect {
		for _, conn := range connections {
			_, _ = conn.Write([]byte("Server reloading...\n"))
			_ = conn.Close()
		}
	}
	a.reloadWrites.Store(2)
	a.wakeStatsWriter()
}

func sameServerIdentity(left, right ServerConfig) bool {
	return left.Username == right.Username && left.Name == right.Name && left.Type == right.Type && left.Host == right.Host && left.Location == right.Location
}

func (a *App) disconnectAll(reason string) {
	a.nodeMu.Lock()
	connections := make([]net.Conn, 0)
	for _, node := range a.nodes {
		if node.Connection != nil {
			connections = append(connections, node.Connection)
			node.Connection = nil
			node.Connected = false
			node.Online4 = false
			node.Online6 = false
		}
	}
	a.nodeMu.Unlock()
	for _, conn := range connections {
		if reason != "" {
			_, _ = conn.Write([]byte(reason + "\n"))
		}
		_ = conn.Close()
	}
}

func (a *App) statsLoop() {
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-a.ctx.Done():
			return
		case <-ticker.C:
		case <-a.statsWake:
		}
		if err := a.PersistStats(); err != nil {
			a.logger.Printf("write stats: %v", err)
		}
	}
}

func (a *App) wakeStatsWriter() {
	select {
	case a.statsWake <- struct{}{}:
	default:
	}
}

func (a *App) SnapshotStats() map[string]any {
	return a.snapshotStats(false)
}

func (a *App) snapshotStats(consumeReload bool) map[string]any {
	runtime := a.RuntimeSnapshot()
	now := time.Now()
	serverKeys := make([]string, 0, len(runtime.Servers))
	if a.registry != nil {
		for _, device := range sortedRegistryDevices(a.registry) {
			serverKeys = append(serverKeys, device.ID)
		}
	} else {
		for _, server := range runtime.Servers {
			if !server.Disabled {
				serverKeys = append(serverKeys, server.Username)
			}
		}
	}
	servers := make([]any, 0, len(serverKeys))
	a.nodeMu.Lock()
	for _, deviceID := range serverKeys {
		node := a.nodes[deviceID]
		if node == nil {
			continue
		}
		server := node.Config
		base := map[string]any{
			"name": server.Name, "type": server.Type, "host": server.Host, "location": server.Location,
			"online4": false, "online6": false,
		}
		extension := snapshotExtension(node.Extension, now)
		if node.Restored {
			forceExtensionStale(&extension)
		}
		base["extension_version"] = extension.ExtensionVersion
		base["received_at"] = extension.ReceivedAt
		base["hardware"] = extension.Hardware
		base["docker"] = extension.Docker
		base["hermes"] = extension.Hermes
		base["lucky"] = extension.Lucky
		if a.registry != nil {
			status := a.deviceStatusAt(node, now)
			identityStatus := node.IdentityStatus
			protocolMode := node.ProtocolMode
			if !node.Enabled {
				identityStatus = "disabled"
				protocolMode = "none"
			}
			base["device_id"] = node.DeviceID
			base["display_name"] = node.DisplayName
			base["status"] = status
			base["identity_status"] = identityStatus
			base["protocol_mode"] = protocolMode
			base["last_seen"] = nullableTime(node.LastSeen)
			base["collected_at"] = nullableTime(node.CollectedAt)
			base["stale"] = a.deviceIsStaleAt(node, now)
			base["expected_fqdn"] = nil
			base["reported_fqdn"] = nil
		}
		if node.HasUpdate && (a.registry != nil || node.Connected) {
			s := node.Stats
			updateTrafficBaselines(node, s.NetworkIn, s.NetworkOut, monthResetWindow(now, server.MonthStart))
			base["online4"] = node.Online4
			base["online6"] = node.Online6
			base["uptime"] = formatUptime(s.Uptime)
			base["load_1"], base["load_5"], base["load_15"] = round2(s.Load1), round2(s.Load5), round2(s.Load15)
			base["ping_10010"], base["ping_189"], base["ping_10086"] = round2(s.Ping10010), round2(s.Ping189), round2(s.Ping10086)
			base["time_10010"], base["time_189"], base["time_10086"] = s.Time10010, s.Time189, s.Time10086
			base["tcp_count"], base["udp_count"] = s.TCPCount, s.UDPCount
			base["process_count"], base["thread_count"] = s.ProcessCount, s.ThreadCount
			base["network_rx"], base["network_tx"] = s.NetworkRX, s.NetworkTX
			base["network_in"], base["network_out"] = s.NetworkIn, s.NetworkOut
			base["cpu"], base["cpu_cores"], base["cpu_model"] = int(s.CPU), s.CPUCores, s.CPUModel
			base["memory_total"], base["memory_used"] = s.MemoryTotal, s.MemoryUsed
			base["swap_total"], base["swap_used"] = s.SwapTotal, s.SwapUsed
			base["hdd_total"], base["hdd_used"] = s.HDDTotal, s.HDDUsed
			base["last_network_in"] = trafficBaseline(s.NetworkIn, node.LastNetworkIn)
			base["last_network_out"] = trafficBaseline(s.NetworkOut, node.LastNetworkOut)
			base["io_read"], base["io_write"] = s.IORead, s.IOWrite
			base["custom"], base["os"] = s.Custom, s.OS
		} else {
			base["last_network_in"] = node.LastNetworkIn
			base["last_network_out"] = node.LastNetworkOut
			base["os"] = node.Stats.OS
			base["cpu_model"] = node.Stats.CPUModel
		}
		servers = append(servers, base)
	}
	a.nodeMu.Unlock()

	result := map[string]any{
		"servers":  servers,
		"sslcerts": a.sslSnapshot(runtime.SSLCerts, now),
		"updated":  strconv.FormatInt(now.Unix(), 10),
	}
	if a.registry != nil {
		result["schema_version"] = 2
		result["generated_at"] = now.UTC().Format(time.RFC3339)
		result["default_device_id"] = a.registry.Defaults.DefaultDeviceID
	}
	if a.reloadWrites.Load() > 0 {
		result["reload"] = true
		if consumeReload {
			a.reloadWrites.Add(-1)
		}
	}
	return result
}

func (a *App) PersistStats() error {
	a.persistMu.Lock()
	defer a.persistMu.Unlock()
	if err := writeStatsFile(a.opts.StatsPath, a.snapshotStats(true)); err != nil {
		return err
	}
	if a.registry == nil {
		return nil
	}
	snapshot, err := a.snapshotPersistenceV2(time.Now())
	if err != nil {
		return err
	}
	return writePersistenceV2(a.opts.PersistencePath, snapshot)
}

func monthResetWindow(now time.Time, monthStart int) bool {
	return now.Day() == clamp(monthStart, 1, 28) && now.Hour() == 0 && now.Minute() < 5
}

func trafficBaseline(current, baseline int64) int64 {
	if current == 0 || baseline == 0 {
		return current
	}
	return baseline
}

func updateTrafficBaselines(node *NodeState, currentIn, currentOut int64, reset bool) {
	if reset {
		node.LastNetworkIn = currentIn
		node.LastNetworkOut = currentOut
		return
	}
	if node.LastNetworkIn == 0 || (currentIn != 0 && node.LastNetworkIn > currentIn) {
		node.LastNetworkIn = currentIn
	}
	if node.LastNetworkOut == 0 || (currentOut != 0 && node.LastNetworkOut > currentOut) {
		node.LastNetworkOut = currentOut
	}
}

func round2(value float64) float64 {
	return math.Round(value*100) / 100
}

func formatUptime(seconds int64) string {
	days := seconds / 86400
	if days > 0 {
		return fmt.Sprintf("%d 天", days)
	}
	return fmt.Sprintf("%02d:%02d:%02d", seconds/3600, (seconds/60)%60, seconds%60)
}

func (a *App) restorePersistentState() error {
	if a.registry != nil {
		return a.restorePersistenceV2()
	}
	data, err := os.ReadFile(a.opts.StatsPath)
	if err != nil {
		primaryErr := err
		data, err = os.ReadFile(a.opts.StatsPath + "~")
		if err != nil {
			if code := statsReadErrorCode(primaryErr, err); code != "" {
				a.logger.Printf("read previous stats: %s", code)
			}
			return nil
		}
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var previous struct {
		Servers []map[string]any `json:"servers"`
	}
	if err := decoder.Decode(&previous); err != nil {
		a.logger.Printf("read previous stats: invalid_json")
		return nil
	}
	a.nodeMu.Lock()
	defer a.nodeMu.Unlock()
	for _, node := range a.nodes {
		for _, saved := range previous.Servers {
			if fmt.Sprint(saved["name"]) != node.Config.Name || fmt.Sprint(saved["type"]) != node.Config.Type || fmt.Sprint(saved["host"]) != node.Config.Host || fmt.Sprint(saved["location"]) != node.Config.Location {
				continue
			}
			node.LastNetworkIn = anyInt64(saved["last_network_in"])
			node.LastNetworkOut = anyInt64(saved["last_network_out"])
			node.Stats.OS = anyString(saved["os"])
			node.Stats.CPUModel = anyString(saved["cpu_model"])
			break
		}
	}
	return nil
}

func statsReadErrorCode(primaryErr, backupErr error) string {
	if errors.Is(primaryErr, os.ErrPermission) || errors.Is(backupErr, os.ErrPermission) {
		return "permission_denied"
	}
	if errors.Is(primaryErr, os.ErrNotExist) && errors.Is(backupErr, os.ErrNotExist) {
		return ""
	}
	return "unavailable"
}

func anyString(value any) string {
	if value == nil {
		return ""
	}
	return fmt.Sprint(value)
}

func anyInt64(value any) int64 {
	switch number := value.(type) {
	case json.Number:
		parsed, _ := number.Int64()
		return parsed
	case float64:
		return int64(number)
	case int64:
		return number
	case int:
		return int64(number)
	case string:
		parsed, _ := strconv.ParseInt(number, 10, 64)
		return parsed
	default:
		return 0
	}
}

func (a *App) ResetTraffic(username string) (map[string]any, *APIError) {
	a.nodeMu.Lock()
	deviceID := a.resolveNodeKey(username)
	node := a.nodes[deviceID]
	if node == nil {
		a.nodeMu.Unlock()
		return nil, &APIError{Status: 404, Message: "server was not found", Details: map[string]any{"username": username}}
	}
	if !node.Connected || !node.HasUpdate {
		a.nodeMu.Unlock()
		return nil, &APIError{Status: 409, Message: "server has no current traffic counters; it may be offline", Details: map[string]any{"username": username}}
	}
	previousIn, previousOut := node.LastNetworkIn, node.LastNetworkOut
	networkIn, networkOut := node.Stats.NetworkIn, node.Stats.NetworkOut
	node.LastNetworkIn, node.LastNetworkOut = networkIn, networkOut
	server := node.Config
	a.nodeMu.Unlock()
	a.wakeStatsWriter()
	return map[string]any{
		"server": server,
		"stats": map[string]any{
			"network_in": networkIn, "network_out": networkOut,
			"previous_last_network_in": previousIn, "previous_last_network_out": previousOut,
			"last_network_in": networkIn, "last_network_out": networkOut,
			"month_in_before": max64(0, networkIn-previousIn), "month_out_before": max64(0, networkOut-previousOut),
		},
	}, nil
}

func max64(left, right int64) int64 {
	if left > right {
		return left
	}
	return right
}
