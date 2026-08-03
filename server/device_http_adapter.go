package main

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"math"
	"mime"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/cppla/serverstatus/server/contracts"
	"github.com/gin-gonic/gin"
)

const (
	deviceUpdatePath  = "/api/v2/device-updates"
	maxDeviceMonitors = 256
)

type deviceRequestAudit struct {
	RequestID   string
	Status      int
	Outcome     string
	DeviceRef   string
	SlotID      string
	BodySize    int
	StartedAt   time.Time
	RateLimited bool
}

func (a *App) deviceUpdateHandler(c *gin.Context) {
	audit := deviceRequestAudit{
		RequestID: newDeviceRequestID(),
		StartedAt: time.Now(),
	}
	defer func() {
		a.logDeviceRequest(audit)
	}()

	if !a.deviceEndpointEnabled {
		a.writeDeviceError(c, &audit, http.StatusNotFound, "not_found", 0)
		return
	}
	if c.Request.Method != http.MethodPost {
		c.Header("Allow", http.MethodPost)
		a.writeDeviceError(c, &audit, http.StatusMethodNotAllowed, "method_not_allowed", 0)
		return
	}
	if !a.deviceRequestIsSecure(c.Request) {
		a.writeDeviceError(c, &audit, http.StatusForbidden, "insecure_transport", 0)
		return
	}
	now := time.Now()
	if allowed, retry := a.preAuthLimiter.Allow(a.preAuthRequestKey(c.Request), now); !allowed {
		audit.RateLimited = true
		a.writeDeviceError(c, &audit, http.StatusTooManyRequests, "rate_limited", retry)
		return
	}
	if !validDeviceContentType(c.GetHeader("Content-Type")) {
		a.writeDeviceError(c, &audit, http.StatusUnsupportedMediaType, "unsupported_content_type", 0)
		return
	}
	body, bodyErr := readDeviceBody(c)
	audit.BodySize = len(body)
	if bodyErr != nil {
		status := http.StatusBadRequest
		code := "invalid_envelope"
		if errors.Is(bodyErr, errDeviceBodyTooLarge) {
			status = http.StatusRequestEntityTooLarge
			code = "body_too_large"
		}
		a.writeDeviceError(c, &audit, status, code, 0)
		return
	}

	headerValues := exactHeaderValues(c.Request.Header, "X-HermesStatus-Device-ID")
	if len(headerValues) != 1 || !validDeviceHeaderID(headerValues[0]) {
		a.writeDeviceError(c, &audit, http.StatusBadRequest, "invalid_device_header", 0)
		return
	}
	headerDeviceID := headerValues[0]
	audit.DeviceRef = deviceAuditRef(headerDeviceID)
	registryDevice, registered := a.registryDevice(headerDeviceID)
	credentialSet, credentialExists := a.deviceCredentials[headerDeviceID]
	authenticated, ok := authenticateDeviceBearer(
		exactHeaderValues(c.Request.Header, "Authorization"), credentialSet, now,
	)
	if !registered || !credentialExists || !ok {
		a.writeDeviceError(c, &audit, http.StatusUnauthorized, "unauthorized", 0)
		return
	}
	audit.SlotID = authenticated.SlotID
	if registryDevice.Enabled == nil || !*registryDevice.Enabled {
		a.writeDeviceError(c, &audit, http.StatusForbidden, "forbidden", 0)
		return
	}
	if !contracts.OwnershipAllows(registryDevice.Ingestion, "device_v2", now) {
		a.writeDeviceError(c, &audit, http.StatusForbidden, "inactive_protocol", 0)
		return
	}
	if allowed, retry := a.deviceLimiter.Allow(authenticated.DeviceID, now); !allowed {
		audit.RateLimited = true
		a.writeDeviceError(c, &audit, http.StatusTooManyRequests, "rate_limited", retry)
		return
	}

	envelope, err := contracts.DecodeDeviceUpdateEnvelope(body)
	if err != nil {
		a.writeDeviceError(c, &audit, http.StatusBadRequest, "invalid_envelope", 0)
		return
	}
	if envelope.Device.ID != authenticated.DeviceID {
		a.writeDeviceError(c, &audit, http.StatusForbidden, "identity_mismatch", 0)
		return
	}
	collectedAt, err := time.Parse(time.RFC3339, envelope.CollectedAt)
	if err != nil || validateDeviceCollectedAt(collectedAt, now) != nil {
		a.writeDeviceError(c, &audit, http.StatusBadRequest, "invalid_envelope", 0)
		return
	}
	flatStats, err := json.Marshal(envelope.Stats)
	if err != nil {
		a.writeDeviceError(c, &audit, http.StatusBadRequest, "invalid_envelope", 0)
		return
	}
	canonicalEnvelope, err := canonicalDeviceEnvelope(envelope)
	if err != nil {
		a.writeDeviceError(c, &audit, http.StatusBadRequest, "invalid_envelope", 0)
		return
	}
	requestDigest := sha256.Sum256(canonicalEnvelope)
	identityClass, identityErr := evaluateIdentity(
		registryDevice.ExpectedFQDN,
		envelope.Device.ReportedFQDN,
		"device_v2",
	)
	monitors, configGeneration, err := a.deviceMonitorSnapshot()
	if err != nil {
		a.writeDeviceError(c, &audit, http.StatusInternalServerError, "internal_error", 0)
		return
	}
	response := contracts.SuccessResponse{
		Accepted:         true,
		ServerTime:       now.UTC().Format(time.RFC3339),
		ConfigGeneration: "g-" + strconv.FormatUint(configGeneration, 10),
		Monitors:         monitors,
	}
	if err := contracts.ValidateSuccessResponse(response); err != nil {
		a.writeDeviceError(c, &audit, http.StatusInternalServerError, "internal_error", 0)
		return
	}
	_, err = a.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID:           authenticated.DeviceID,
		ProtocolMode:       "device_v2",
		CollectedAt:        collectedAt,
		FlatStats:          flatStats,
		ReportedName:       envelope.Device.ReportedName,
		ReportedFQDN:       envelope.Device.ReportedFQDN,
		ReportedHostname:   envelope.Device.Hostname,
		RequestDigest:      requestDigest,
		HasRequestDigest:   true,
		IdentityClass:      identityClass,
		IdentityRejected:   identityErr != nil,
		IdentityClassified: true,
		AssignGeneration:   true,
		PersistBeforeAck:   true,
	}, now)
	if err != nil && !errors.Is(err, errIdempotentReplay) {
		status, code := deviceIngestHTTPError(err)
		a.writeDeviceError(c, &audit, status, code, 0)
		return
	}
	audit.Status = http.StatusAccepted
	audit.Outcome = "accepted"
	if errors.Is(err, errIdempotentReplay) {
		audit.Outcome = "idempotent"
	}
	c.Header("Cache-Control", "no-store")
	c.JSON(http.StatusAccepted, response)
}

func canonicalDeviceEnvelope(envelope *contracts.DeviceUpdateEnvelope) ([]byte, error) {
	canonicalStats := make(map[string]json.RawMessage, len(envelope.Stats))
	for name, raw := range envelope.Stats {
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.UseNumber()
		var value any
		if err := decoder.Decode(&value); err != nil {
			return nil, err
		}
		var trailing any
		if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
			return nil, errors.New("nested stats contains multiple JSON values")
		}
		canonical, err := json.Marshal(value)
		if err != nil {
			return nil, err
		}
		canonicalStats[name] = canonical
	}
	copy := *envelope
	copy.Stats = canonicalStats
	return json.Marshal(copy)
}

func exactHeaderValues(header http.Header, name string) []string {
	var values []string
	for key, keyValues := range header {
		if strings.EqualFold(key, name) {
			values = append(values, keyValues...)
		}
	}
	return values
}

func (a *App) registryDevice(deviceID string) (contracts.RegistryDevice, bool) {
	if a.registry == nil {
		return contracts.RegistryDevice{}, false
	}
	for _, device := range a.registry.Devices {
		if device.ID == deviceID {
			return device, true
		}
	}
	return contracts.RegistryDevice{}, false
}

func validDeviceContentType(value string) bool {
	mediaType, parameters, err := mime.ParseMediaType(value)
	if err != nil || !strings.EqualFold(mediaType, "application/json") {
		return false
	}
	for key, parameter := range parameters {
		if !strings.EqualFold(key, "charset") || !strings.EqualFold(parameter, "utf-8") {
			return false
		}
	}
	return true
}

var errDeviceBodyTooLarge = errors.New("device update body is too large")

func readDeviceBody(c *gin.Context) ([]byte, error) {
	if c.Request.ContentLength > contracts.MaxEnvelopeBytes {
		return nil, errDeviceBodyTooLarge
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, contracts.MaxEnvelopeBytes)
	data, err := io.ReadAll(c.Request.Body)
	if err != nil {
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			return nil, errDeviceBodyTooLarge
		}
		return nil, errors.New("device update body is invalid")
	}
	if len(data) == 0 {
		return nil, errors.New("device update body is empty")
	}
	return data, nil
}

func (a *App) deviceRequestIsSecure(request *http.Request) bool {
	if request.TLS != nil {
		return true
	}
	remoteAddress, ok := remoteIP(request.RemoteAddr)
	if !ok {
		return false
	}
	if a.opts.AllowLoopbackDeviceHTTP && remoteAddress.IsLoopback() {
		return true
	}
	if !a.opts.TrustedProxyMode || !prefixContains(a.trustedProxyPrefixes, remoteAddress) {
		return false
	}
	values := exactHeaderValues(request.Header, "X-Forwarded-Proto")
	return len(values) == 1 && values[0] == "https"
}

func (a *App) preAuthRequestKey(request *http.Request) string {
	remoteAddress, ok := remoteIP(request.RemoteAddr)
	if !ok {
		return globalUnauthenticatedSourceKey
	}
	if a.opts.TrustedProxyMode && prefixContains(a.trustedProxyPrefixes, remoteAddress) {
		values := exactHeaderValues(request.Header, "X-Forwarded-For")
		if len(values) != 1 {
			return globalUnauthenticatedSourceKey
		}
		forwardedAddress, err := netip.ParseAddr(values[0])
		if err != nil || forwardedAddress.Zone() != "" {
			return globalUnauthenticatedSourceKey
		}
		return preAuthSourceKey(forwardedAddress.Unmap().String())
	}
	return preAuthSourceKey(remoteAddress.String())
}

func remoteIP(remoteAddress string) (netip.Addr, bool) {
	host, _, err := net.SplitHostPort(remoteAddress)
	if err != nil {
		host = remoteAddress
	}
	address, err := netip.ParseAddr(host)
	if err != nil || address.Zone() != "" {
		return netip.Addr{}, false
	}
	return address.Unmap(), true
}

func prefixContains(prefixes []netip.Prefix, address netip.Addr) bool {
	for _, prefix := range prefixes {
		if prefix.Contains(address) {
			return true
		}
	}
	return false
}

func (a *App) sanitizedDeviceMonitors() ([]contracts.SanitizedMonitor, error) {
	monitors, _, err := a.deviceMonitorSnapshot()
	return monitors, err
}

func (a *App) deviceMonitorSnapshot() (
	[]contracts.SanitizedMonitor,
	uint64,
	error,
) {
	a.configMu.RLock()
	configured := append([]MonitorConfig(nil), a.runtime.Monitors...)
	configGeneration := a.generation.Load()
	a.configMu.RUnlock()
	monitors, err := sanitizedMonitorSnapshot(configured)
	return monitors, configGeneration, err
}

func sanitizedMonitorSnapshot(
	configured []MonitorConfig,
) ([]contracts.SanitizedMonitor, error) {
	if len(configured) > maxDeviceMonitors {
		return nil, errors.New("monitor response exceeds limit")
	}
	monitors := make([]contracts.SanitizedMonitor, 0, len(configured))
	for _, monitor := range configured {
		if !safeMonitorField(monitor.Name, 128) ||
			!safeMonitorHost(monitor.Host, monitor.Type) ||
			monitor.Interval < 1 || monitor.Interval > 86400 {
			return nil, errors.New("monitor response is invalid")
		}
		monitors = append(monitors, contracts.SanitizedMonitor{
			Name: monitor.Name, Host: monitor.Host,
			Interval: monitor.Interval, Type: monitor.Type,
		})
	}
	return monitors, nil
}

func safeMonitorField(value string, maxRunes int) bool {
	if value == "" || !utf8.ValidString(value) || utf8.RuneCountInString(value) > maxRunes {
		return false
	}
	for _, character := range value {
		if character < 0x20 || character == 0x7f {
			return false
		}
	}
	return true
}

func safeMonitorHost(value, monitorType string) bool {
	if !safeMonitorField(value, 253) || strings.ContainsAny(value, `\`+" \t\r\n") {
		return false
	}
	if monitorType == "tcp" {
		host, portText, err := net.SplitHostPort(value)
		if err != nil || !safeMonitorNetworkHost(host) {
			return false
		}
		port, err := strconv.Atoi(portText)
		return err == nil && port >= 1 && port <= 65535
	}
	if monitorType != "http" && monitorType != "https" {
		return false
	}
	parsed, err := url.Parse(value)
	if err != nil || parsed.User != nil ||
		parsed.Scheme != monitorType ||
		parsed.Hostname() == "" || !parsed.IsAbs() {
		return false
	}
	if !safeMonitorNetworkHost(parsed.Hostname()) {
		return false
	}
	if portText := parsed.Port(); portText != "" {
		port, err := strconv.Atoi(portText)
		if err != nil || port < 1 || port > 65535 {
			return false
		}
	}
	if parsed.Fragment != "" || strings.Contains(parsed.EscapedPath(), "..") {
		return false
	}
	// Monitor definitions are copied into both the Management API config and
	// device responses. Queries are forbidden outright so authorization
	// material cannot cross either boundary under an unexpected parameter
	// name or encoding.
	if parsed.ForceQuery || parsed.RawQuery != "" {
		return false
	}
	decodedPath, err := url.PathUnescape(parsed.EscapedPath())
	if err != nil {
		return false
	}
	for _, segment := range strings.Split(decodedPath, "/") {
		if segment == ".." {
			return false
		}
	}
	return true
}

func safeMonitorNetworkHost(value string) bool {
	if value == "" || len(value) > 253 || strings.Contains(value, "%") {
		return false
	}
	if net.ParseIP(value) != nil {
		return true
	}
	for _, label := range strings.Split(value, ".") {
		if label == "" || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return false
		}
		for _, character := range label {
			if !(character >= 'a' && character <= 'z') &&
				!(character >= 'A' && character <= 'Z') &&
				!(character >= '0' && character <= '9') &&
				character != '-' {
				return false
			}
		}
	}
	return true
}

func deviceIngestHTTPError(err error) (int, string) {
	switch {
	case errors.Is(err, errDeviceClockSkew):
		return http.StatusBadRequest, "invalid_envelope"
	case errors.Is(err, errStaleReport):
		return http.StatusConflict, "stale_report"
	case errors.Is(err, errReportConflict),
		errors.Is(err, errStaleGeneration):
		return http.StatusConflict, "report_conflict"
	case errors.Is(err, errDeviceDisabled),
		errors.Is(err, errInactiveOwner),
		errors.Is(err, errDeviceIdentity):
		return http.StatusForbidden, "forbidden"
	default:
		return http.StatusInternalServerError, "internal_error"
	}
}

func (a *App) writeDeviceError(
	c *gin.Context,
	audit *deviceRequestAudit,
	status int,
	outcome string,
	retry time.Duration,
) {
	audit.Status = status
	audit.Outcome = outcome
	c.Header("Cache-Control", "no-store")
	if status == http.StatusTooManyRequests {
		seconds := int(math.Ceil(retry.Seconds()))
		if seconds < 1 {
			seconds = 1
		}
		if seconds > 300 {
			seconds = 300
		}
		c.Header("Retry-After", strconv.Itoa(seconds))
	}
	publicCode := outcome
	if status == http.StatusUnauthorized {
		publicCode = "unauthorized"
	}
	if status == http.StatusForbidden {
		publicCode = "forbidden"
	}
	response := contracts.ErrorResponse{Error: contracts.PublicError{
		Code: publicCode, RequestID: audit.RequestID,
	}}
	c.JSON(status, response)
}

func newDeviceRequestID() string {
	var value [12]byte
	if _, err := rand.Read(value[:]); err != nil {
		return "request-unavailable"
	}
	return "req-" + hex.EncodeToString(value[:])
}

func deviceAuditRef(deviceID string) string {
	digest := sha256.Sum256([]byte(deviceID))
	return "device-" + hex.EncodeToString(digest[:6])
}

func (a *App) logDeviceRequest(audit deviceRequestAudit) {
	latency := time.Since(audit.StartedAt)
	if audit.Outcome == "" {
		audit.Outcome = "internal_error"
	}
	a.logger.Printf(
		"device update request_id=%s status=%d outcome=%s protocol=device_v2 device_ref=%q credential_slot=%q latency_ms=%d body_size=%d rate_limited=%t",
		audit.RequestID,
		audit.Status,
		audit.Outcome,
		audit.DeviceRef,
		audit.SlotID,
		latency.Milliseconds(),
		audit.BodySize,
		audit.RateLimited,
	)
}
