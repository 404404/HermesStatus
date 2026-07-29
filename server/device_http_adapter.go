package main

import (
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

	if c.Request.Method != http.MethodPost {
		c.Header("Allow", http.MethodPost)
		a.writeDeviceError(c, &audit, http.StatusMethodNotAllowed, "method_not_allowed", 0)
		return
	}
	if !a.deviceEndpointEnabled {
		a.writeDeviceError(c, &audit, http.StatusNotFound, "not_found", 0)
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
	if registryDevice.Enabled == nil || !*registryDevice.Enabled {
		a.writeDeviceError(c, &audit, http.StatusForbidden, "forbidden", 0)
		return
	}
	if !contracts.OwnershipAllows(registryDevice.Ingestion, "device_v2", now) {
		a.writeDeviceError(c, &audit, http.StatusForbidden, "inactive_protocol", 0)
		return
	}
	identityStatus, identityErr := evaluateIdentity(
		registryDevice.ExpectedFQDN,
		envelope.Device.ReportedFQDN,
		"device_v2",
	)
	if identityErr != nil {
		a.markDeviceHTTPIdentityError(authenticated.DeviceID, identityStatus)
		a.writeDeviceError(c, &audit, http.StatusForbidden, "identity_mismatch", 0)
		return
	}
	collectedAt, err := time.Parse(time.RFC3339, envelope.CollectedAt)
	if err != nil || collectedAt.Sub(now) > MaxDeviceClockSkew {
		a.writeDeviceError(c, &audit, http.StatusBadRequest, "invalid_envelope", 0)
		return
	}
	flatStats, err := json.Marshal(envelope.Stats)
	if err != nil {
		a.writeDeviceError(c, &audit, http.StatusBadRequest, "invalid_envelope", 0)
		return
	}
	generation := a.updateID.Add(1)
	_, err = a.ingestDeviceUpdateAt(deviceIngestRequest{
		DeviceID:         authenticated.DeviceID,
		ProtocolMode:     "device_v2",
		CollectedAt:      collectedAt,
		FlatStats:        flatStats,
		Generation:       generation,
		ReportedName:     envelope.Device.ReportedName,
		ReportedFQDN:     envelope.Device.ReportedFQDN,
		ReportedHostname: envelope.Device.Hostname,
	}, now)
	if err != nil {
		status, code := deviceIngestHTTPError(err)
		a.writeDeviceError(c, &audit, status, code, 0)
		return
	}
	monitors, err := a.sanitizedDeviceMonitors()
	if err != nil {
		a.writeDeviceError(c, &audit, http.StatusInternalServerError, "internal_error", 0)
		return
	}

	response := contracts.SuccessResponse{
		Accepted:         true,
		ServerTime:       now.UTC().Format(time.RFC3339),
		ConfigGeneration: "g-" + strconv.FormatUint(a.generation.Load(), 10),
		Monitors:         monitors,
	}
	if err := contracts.ValidateSuccessResponse(response); err != nil {
		a.writeDeviceError(c, &audit, http.StatusInternalServerError, "internal_error", 0)
		return
	}
	audit.Status = http.StatusAccepted
	audit.Outcome = "accepted"
	c.Header("Cache-Control", "no-store")
	c.JSON(http.StatusAccepted, response)
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

func (a *App) markDeviceHTTPIdentityError(deviceID, identityStatus string) {
	a.nodeMu.Lock()
	defer a.nodeMu.Unlock()
	node := a.nodes[deviceID]
	if node == nil || !node.Enabled {
		return
	}
	node.IdentityStatus = identityStatus
	node.IdentityError = true
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
	runtime := a.RuntimeSnapshot()
	if len(runtime.Monitors) > maxDeviceMonitors {
		return nil, errors.New("monitor response exceeds limit")
	}
	monitors := make([]contracts.SanitizedMonitor, 0, len(runtime.Monitors))
	for _, monitor := range runtime.Monitors {
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
	lower := strings.ToLower(value)
	for _, forbidden := range []string{"token=", "password=", "secret=", "api_key=", "apikey="} {
		if strings.Contains(lower, forbidden) {
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
	case errors.Is(err, errDeviceDisabled),
		errors.Is(err, errInactiveOwner),
		errors.Is(err, errDeviceIdentity):
		return http.StatusForbidden, "forbidden"
	case errors.Is(err, errStaleGeneration):
		return http.StatusConflict, "forbidden"
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
