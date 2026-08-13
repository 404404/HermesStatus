package main

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func hardwareText(value string) *string     { return &value }
func hardwareCounter(value int64) *int64    { return &value }
func hardwareNumber(value float64) *float64 { return &value }
func hardwareCount(value int) *int          { return &value }

func validCPUDetailsFixture() CPUDetails {
	return CPUDetails{
		Architecture: hardwareText("x86_64"), Vendor: hardwareText("GenuineIntel"),
		Family: hardwareText("6"), ModelID: hardwareText("151"), ModelName: hardwareText("Example CPU"),
		Stepping: hardwareText("2"), Virtualization: hardwareText("VT-x"),
		L1DCache: hardwareText("128 KiB"), L1ICache: hardwareText("128 KiB"),
		L2Cache: hardwareText("1 MiB"), L3Cache: hardwareText("4 MiB"),
		LogicalCPUs: hardwareCount(4), Sockets: hardwareCount(1), CoresPerSocket: hardwareCount(2), ThreadsPerCore: hardwareCount(2),
		MaxMHz: hardwareNumber(3400), MinMHz: hardwareNumber(800), CurrentMHz: hardwareNumber(2100),
		Usage: &CPUUsageStats{
			UserPercent: hardwareNumber(10), NicePercent: hardwareNumber(0), SystemPercent: hardwareNumber(5),
			IdlePercent: hardwareNumber(80), IOWaitPercent: hardwareNumber(2), IRQPercent: hardwareNumber(0),
			SoftIRQPercent: hardwareNumber(1), StealPercent: hardwareNumber(2), TotalPercent: hardwareNumber(20),
		},
	}
}

func validMemoryDetailsFixture() MemoryDetails {
	total, used, available := int64(16000), int64(6000), int64(10000)
	swapTotal, swapUsed, swapFree := int64(4000), int64(1000), int64(3000)
	return MemoryDetails{
		TotalBytes: &total, UsedBytes: &used, AvailableBytes: &available,
		FreeBytes: hardwareCounter(5000), BuffersBytes: hardwareCounter(1000), CachedBytes: hardwareCounter(3000), ReclaimableBytes: hardwareCounter(500),
		ActiveBytes: hardwareCounter(4000), InactiveBytes: hardwareCounter(6000), DirtyBytes: hardwareCounter(10), WritebackBytes: hardwareCounter(1), SlabBytes: hardwareCounter(700),
		SwapTotalBytes: &swapTotal, SwapUsedBytes: &swapUsed, SwapFreeBytes: &swapFree, SwapCachedBytes: hardwareCounter(0),
	}
}

func validStorageFixture() StorageStats {
	updatedAt := "2026-07-28T12:00:00Z"
	capacity := int64(8001563222016)
	powerOn := int64(12345)
	written := int64(3200000000000)
	read := int64(1900000000000)
	temperature := 41.0
	total := int64(100000000000)
	used := int64(25000000000)
	available := int64(75000000000)
	usage := 25.0
	return StorageStats{
		PhysicalDisks: []PhysicalDiskStats{{
			ID: "sda", Device: "/dev/sda", Model: hardwareText("Example Disk"),
			CapacityBytes: &capacity, TemperatureC: &temperature, SMARTStatus: DiskSMARTPassed,
			PowerOnHours: &powerOn, WrittenBytes: &written, ReadBytes: &read,
			SMARTSource: hardwareText("smartctl-json"), CollectionStatus: "healthy",
		}},
		Filesystems: []FilesystemStats{{
			Source: hardwareText("/dev/mapper/vg-root"), Mountpoint: "/", FSType: hardwareText("ext4"),
			TotalBytes: &total, UsedBytes: &used, AvailableBytes: &available, UsagePercent: &usage,
			BackingDiskIDs: []string{"sda"}, StackType: "lvm", CollectionStatus: "healthy",
		}},
		Summary: StorageSummary{
			PhysicalDiskCount: 1, SMARTPassed: 1, TemperatureMinC: &temperature,
			TemperatureMaxC: &temperature, FilesystemCount: 1,
		},
		UpdatedAt: &updatedAt,
	}
}

func validClientBuildFixture() *ClientBuildInfo {
	buildTime := "2026-07-28T12:00:00Z"
	return &ClientBuildInfo{
		Version: "2.3-preview", Revision: strings.Repeat("a", 40), BuildTime: &buildTime, Protocol: "device_v2",
	}
}

func TestHardwareObservabilityOptionalFieldsDecodeAndValidate(t *testing.T) {
	var payload map[string]any
	if err := json.Unmarshal(readFixture(t, "update-normal.json"), &payload); err != nil {
		t.Fatal(err)
	}
	payload["hardware"].(map[string]any)["storage"] = validStorageFixture()
	payload["hardware"].(map[string]any)["system_identity"] = SystemIdentity{
		Distribution: hardwareText("Ubuntu"), ReleaseVersion: hardwareText("24.04"),
		PrettyName: hardwareText("Ubuntu 24.04 LTS"), KernelRelease: hardwareText("6.8.0-test"),
		Architecture: hardwareText("x86_64"), Source: "os-release",
	}
	payload["hardware"].(map[string]any)["cpu_details"] = validCPUDetailsFixture()
	payload["hardware"].(map[string]any)["memory_details"] = validMemoryDetailsFixture()
	payload["client_build"] = validClientBuildFixture()
	encoded, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	stats, err := DecodeExtensionStatsJSON(encoded)
	if err != nil {
		t.Fatal(err)
	}
	if stats.Hardware.Storage == nil || len(stats.Hardware.Storage.PhysicalDisks) != 1 ||
		stats.Hardware.SystemIdentity == nil || stats.Hardware.CPUDetails == nil || stats.Hardware.MemoryDetails == nil || stats.ClientBuild == nil {
		t.Fatalf("new optional fields were not retained: %#v", stats)
	}
}

func TestHardwareDetailsRejectInconsistentCPUAndMemory(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-normal.json")
	cpu := validCPUDetailsFixture()
	stats.Hardware.CPUDetails = &cpu
	memory := validMemoryDetailsFixture()
	stats.Hardware.MemoryDetails = &memory
	if err := ValidateExtensionStats(stats); err != nil {
		t.Fatalf("valid CPU and memory details rejected: %v", err)
	}
	cpu.Usage.TotalPercent = hardwareNumber(99)
	if err := ValidateExtensionStats(stats); err == nil {
		t.Fatal("inconsistent CPU total percent was accepted")
	}
	cpu = validCPUDetailsFixture()
	stats.Hardware.CPUDetails = &cpu
	memory = validMemoryDetailsFixture()
	memory.UsedBytes = hardwareCounter(7000)
	stats.Hardware.MemoryDetails = &memory
	if err := ValidateExtensionStats(stats); err == nil {
		t.Fatal("inconsistent memory partition was accepted")
	}
}

func TestHardwareObservabilityRejectsUnsafeOrInconsistentStorage(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-normal.json")
	storage := validStorageFixture()
	stats.Hardware.Storage = &storage
	storage.PhysicalDisks[0].Model = hardwareText("unsafe\nmodel")
	if err := ValidateExtensionStats(stats); err == nil {
		t.Fatal("control character in physical disk model was accepted")
	}

	storage = validStorageFixture()
	stats.Hardware.Storage = &storage
	storage.PhysicalDisks[0].CollectionStatus = "healthy"
	storage.Summary.SMARTPassed = 0
	if err := ValidateExtensionStats(stats); err == nil {
		t.Fatal("inconsistent storage summary was accepted")
	}

	storage = validStorageFixture()
	stats.Hardware.Storage = &storage
	storage.Filesystems[0].BackingDiskIDs = []string{"unreported"}
	if err := ValidateExtensionStats(stats); err == nil {
		t.Fatal("filesystem reference to an unreported physical disk was accepted")
	}

	storage = validStorageFixture()
	stats.Hardware.Storage = &storage
	storage.Filesystems[0].Source = nil
	if err := ValidateExtensionStats(stats); err != nil {
		t.Fatalf("healthy filesystem without a forwardable source was rejected: %v", err)
	}

	storage = validStorageFixture()
	stats.Hardware.Storage = &storage
	storage.Filesystems[0].Mountpoint = "/mnt/My Drive/数据"
	if err := ValidateExtensionStats(stats); err != nil {
		t.Fatalf("valid non-ASCII filesystem mountpoint was rejected: %v", err)
	}

	storage = validStorageFixture()
	stats.Hardware.Storage = &storage
	storage.PhysicalDisks[0].ID = "disk+1"
	storage.PhysicalDisks[0].Device = "/dev/disk+1"
	storage.Filesystems[0].BackingDiskIDs = []string{"disk+1"}
	if err := ValidateExtensionStats(stats); err != nil {
		t.Fatalf("client-accepted plus-sign device path was rejected: %v", err)
	}

	storage = validStorageFixture()
	stats.Hardware.Storage = &storage
	storage.Filesystems[0].Mountpoint = "/mnt/../invalid"
	if err := ValidateExtensionStats(stats); err == nil {
		t.Fatal("filesystem mountpoint with parent traversal was accepted")
	}

	storage = validStorageFixture()
	stats.Hardware.Storage = &storage
	for len(storage.PhysicalDisks) <= MaxPhysicalDisks {
		disk := storage.PhysicalDisks[0]
		disk.ID = "sda" + strings.Repeat("x", len(storage.PhysicalDisks))
		storage.PhysicalDisks = append(storage.PhysicalDisks, disk)
	}
	if err := ValidateExtensionStats(stats); err == nil {
		t.Fatal("too many physical disks were accepted")
	}
}

func TestTopologyOnlyDiskDoesNotDegradeAnOtherwiseHealthyDevice(t *testing.T) {
	storage := validStorageFixture()
	storage.PhysicalDisks = append(storage.PhysicalDisks, PhysicalDiskStats{
		ID: "sdb", Device: "/dev/sdb", SMARTStatus: DiskSMARTUnknown,
		CollectionStatus: "unsupported",
	})
	if extensionHasBusinessError(ExtensionStats{
		Hardware: &HardwareStats{Storage: &storage},
	}) {
		t.Fatal("topology-only unsupported disk degraded an otherwise healthy device")
	}
	storage.PhysicalDisks[1].CollectionStatus = "unavailable"
	if !extensionHasBusinessError(ExtensionStats{
		Hardware: &HardwareStats{Storage: &storage},
	}) {
		t.Fatal("attempted unavailable SMART disk did not degrade the device")
	}
}

func TestPartialSMARTAttributeFallbackIsStrictAndPreservesHealth(t *testing.T) {
	stats := mustDecodeUpdate(t, "update-normal.json")
	storage := validStorageFixture()
	disk := &storage.PhysicalDisks[0]
	disk.CollectionStatus = "partial"
	disk.Completeness = hardwareText("partial")
	disk.HealthSource = hardwareText("attribute_check")
	disk.NativeStatus = hardwareText("unavailable")
	disk.Error = &ExtensionError{
		Code: "smart_return_status_unavailable", Source: "smartctl",
		Message: "safe", Retryable: false,
	}
	stats.Hardware.Storage = &storage
	if err := ValidateExtensionStats(stats); err != nil {
		t.Fatalf("valid partial SMART attribute fallback rejected: %v", err)
	}
	if storage.PhysicalDisks[0].SMARTStatus != DiskSMARTPassed {
		t.Fatalf("partial fallback health was altered: %#v", storage.PhysicalDisks[0])
	}

	disk.NativeStatus = hardwareText("available")
	if err := ValidateExtensionStats(stats); err == nil {
		t.Fatal("partial SMART fallback with native status was accepted")
	}
}

func TestHardwareObservabilityRejectsSerialAndInvalidClientBuild(t *testing.T) {
	var payload map[string]any
	if err := json.Unmarshal(readFixture(t, "update-normal.json"), &payload); err != nil {
		t.Fatal(err)
	}
	storage := validStorageFixture()
	physicalDisk, err := json.Marshal(storage.PhysicalDisks[0])
	if err != nil {
		t.Fatal(err)
	}
	var disk map[string]any
	if err := json.Unmarshal(physicalDisk, &disk); err != nil {
		t.Fatal(err)
	}
	disk["serial"] = "never-accepted"
	payload["hardware"].(map[string]any)["storage"] = map[string]any{
		"physical_disks": []any{disk}, "filesystems": storage.Filesystems, "summary": storage.Summary,
		"updated_at": storage.UpdatedAt, "stale": false, "error": nil,
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := DecodeExtensionStatsJSON(encoded); err == nil {
		t.Fatal("raw serial field was accepted")
	}

	stats := mustDecodeUpdate(t, "update-normal.json")
	stats.ClientBuild = validClientBuildFixture()
	stats.ClientBuild.Revision = "not-a-full-sha"
	if err := ValidateExtensionStats(stats); err == nil {
		t.Fatal("invalid client revision was accepted")
	}
}

func TestHardwareObservabilityPersistenceRestoresClientBuild(t *testing.T) {
	now := time.Date(2026, 7, 28, 12, 0, 0, 0, time.UTC)
	hardware := NewNotReportedHardwareStats()
	hardware.Storage = ptrStorage(validStorageFixture())
	build := validClientBuildFixture()
	node := &NodeState{
		DeviceID: "device-alpha", ProtocolMode: "device_v2", HasUpdate: true,
		Extension: extensionSnapshotAt(ExtensionStats{
			ExtensionVersion: ExtensionSchemaVersion, Hardware: &hardware,
			Docker: ptrDocker(NewNotReportedDockerStats()), Hermes: ptrHermes(NewNotReportedHermesStats()),
			ClientBuild: build,
		}, now),
	}
	persisted, err := persistedDeviceFromNode(&App{}, node, now)
	if err != nil {
		t.Fatal(err)
	}
	if _, exists := persisted.Domains["client_build"]; !exists {
		t.Fatalf("client build was not persisted: %#v", persisted.Domains)
	}
	restored := &NodeState{Extension: newNotReportedExtensionSnapshot(now)}
	if err := restorePersistedDeviceFields(restored, persisted); err != nil {
		t.Fatal(err)
	}
	if restored.Extension.ClientBuild == nil || restored.Extension.ClientBuild.Revision != build.Revision ||
		restored.Extension.Hardware.Storage == nil {
		t.Fatalf("hardware observability state was not restored: %#v", restored.Extension)
	}
}

func TestServerBuildInfoIsSafeAndStatsProjected(t *testing.T) {
	previousVersion, previousCommit, previousBuildTime := version, commit, buildTime
	t.Setenv("HERMESSTATUS_DEPLOYMENT_ENV", "preview")
	defer func() { version, commit, buildTime = previousVersion, previousCommit, previousBuildTime }()
	version, commit, buildTime = "2.3-preview", strings.Repeat("b", 40), "2026-07-28T12:00:00Z"
	build := serverBuildInfo()
	if build.Version != "2.3-preview" || build.Revision != strings.Repeat("b", 40) || build.BuildTime == nil || build.Deployment != "preview" {
		t.Fatalf("server build projection is invalid: %#v", build)
	}
	stats := newTestApp(t, minimalTestConfig()).SnapshotStats()
	if _, ok := stats["build"].(ServerBuildInfo); !ok {
		t.Fatalf("stats omitted server build metadata: %#v", stats)
	}
}

func ptrStorage(value StorageStats) *StorageStats { return &value }
