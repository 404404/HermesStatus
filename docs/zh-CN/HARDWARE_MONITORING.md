# 硬件监控设计（2.3 Preview）

[English](../design/HARDWARE_MONITORING.md) · [文档目录](README.md)

## 范围

硬件监控是已配置 Client 的只读当前状态观测能力。在不改变单一
`/json/stats.json` 请求路径的前提下，它在主页和 Docker 之间增加 Hardware 页面。页面包含：

1. CPU 详情：架构、步进、插槽/核心/线程汇总、当前及最低/最高频率和虚拟化等受限信息；并列的 CPU 时间占比同样为六行：总量、用户态、内核态、I/O 等待、IRQ 和 SoftIRQ。不渲染厂商、系列/型号、拓扑、缓存、空闲、Nice 或 Steal。
2. 内存详情：先展示物理内存和 Swap 的已用/可用/总量及已用百分比，再展示空闲内存、Buffers、缓存、可回收 Slab、活动/非活动、Dirty/Writeback、Slab 和 Swap Cache。
3. 系统信息：发行版/版本、内核和架构。
4. 物理磁盘：型号、容量、温度、SMART 结果、通电时间和累计计数器；每个关联分区或逻辑卷独占一行，展示分区/格式、已用/总容量和使用率条。

它不控制磁盘、不改变挂载、不运行修复命令、不读取目录内容、不暴露原始 SMART 属性、不上报序列号/WWN/UUID，也不会用磁盘数据创建设备身份。

## 存储模型

`hardware.storage` 域含有独立且有数量限制的 `physical_disks`、`filesystems` 数组，以及摘要、更新时间、陈旧标志和已脱敏错误。二者刻意不做一对一对应。

```text
文件系统 / 逻辑卷
  → 分区、LVM、MD RAID、device mapper 或 Btrfs 层
  → 零个或多个物理磁盘
```

Client 基于只读系统元数据构建有上限、可防循环的 block-device graph 来推导关系，不会根据 `dm-0`、`md2` 或厂商特定挂载点名称猜测。它支持普通分区和通用 LVM、MD RAID、device-mapper 存储栈。多设备 Btrfs 仅由一个 source 无法证明全部成员，因此后端关系会保留未知而不是不完整的单盘关系。一个文件系统行绝不会被填入臆造的单盘温度或 SMART 结果。

Server 会在投影和持久化之前校验数量、字符串长度、计数器、状态、路径和采集状态。浏览器会转义所有磁盘、型号、挂载点、文件系统、操作系统和溯源字符串。

CPU 详情只解析固定的 `lscpu --json` allowlist；若其中缺少当前 MHz，则从有限行数的 `/proc/cpuinfo` `cpu MHz` 数值计算平均值。不会转发原始命令或 proc 文件输出。CPU 使用率由两次聚合 `/proc/stat` 采样计算，`iowait` 与 idle 独立展示。内存只解析固定的 `/proc/meminfo` allowlist。这些值仅是观测，不得作为设备身份；可选源不可用时不伪造数值。

## 物理 SMART 采集

`SMART_DEVICE` 继续兼容单盘安装。Device v2 推荐在 `client-v2.json` 中使用显式 allowlist：

```json
"hardware": {
  "smart_devices": [
    {"path": "/dev/sda", "type": null, "label": "data-disk-a"},
    {"path": "/dev/sdb", "type": "sat", "label": "data-disk-b"}
  ],
  "primary_smart_device": "/dev/sda"
}
```

`path` 必须是已映射到 Client 容器中且经过校验的 `/dev/*` 路径。`type` 是可选且有长度限制的 smartctl 设备类型，不是命令参数片段。`label` 是采集器配置元数据，不承诺作为持久化或 UI 字段。环境变量 `HERMESSTATUS_SMART_DEVICES` / `SMART_DEVICES` 和 `HERMESSTATUS_PRIMARY_SMART_DEVICE` / `PRIMARY_SMART_DEVICE` 可作为 JSON 覆盖。优先级为 CLI、环境变量、JSON 文件、默认值；Legacy `SMART_DEVICE` 是最低优先级的单项形式。

每块已配置磁盘独立采集。一块盘失败、不支持或权限不足会使硬件观测降级，但不会丢弃其他盘。`auto` 作为兼容模式保留，只能发现容器内已经可见和已授权的设备；不会改变 cgroup、扫描不可访问的宿主机设备或扩大 `/dev` 权限。

兼容的单盘 SMART 字段遵循：

- 恰好一块有效物理盘时由它提供；
- 多盘且显式配置 `primary_smart_device` 时由指定盘提供；
- 其他情况绝不任意选第一块盘。详细 storage 为权威数据，单盘 SMART 结果仅在可行时提供聚合状态。

## 最小权限

基础 Client Compose 为非 privileged，且不映射宿主机块设备。对一块或多块已确认磁盘，使用受审计的覆盖文件添加 `SYS_RAWIO`、替换 `devices:` 并逐盘映射：

```yaml
cap_add:
  - SYS_RAWIO
devices: !override
  - /dev/sda:/dev/sda:r
  - /dev/sdb:/dev/sdb:r
environment: !override
  HERMESSTATUS_CONFIG_FILE: /etc/hermesstatus/client-v2.json
  SMART_DEVICE: ""
```

对应 JSON allowlist 只能包含这些路径。不得使用 `privileged`、挂载完整 `/dev`、增加 `SYS_ADMIN`、调用 shell，也不能只因拓扑引用某控制器就授予它访问权。如果某平台 SMART 必须要更多访问权限，应记录限制并停止，不能默认扩大信任边界。

当某个**已显式配置**的文件系统 probe 位于已知 LVM 或 device-mapper 逻辑卷上时，可在已授权物理盘之外，只读映射这一个逻辑卷（例如
`/dev/mapper/vgdata-root:/dev/mapper/vgdata-root:r`）。这只允许安全地从逻辑卷经分区解析到物理盘；不授权整个 `/dev/mapper` 目录、device-mapper control 节点或任何其他块设备。没有任何已配置 probe 使用该逻辑卷时，应省略此映射。

## 文件系统 probe

容器文件系统容量不能自动等同于宿主机文件系统容量。Client 只采集显式配置且以只读方式挂载的 probe：

```json
"filesystem_probes": [
  {"mountpoint": "/data", "probe_path": "/host-storage/data"}
]
```

```yaml
volumes:
  - /srv/example-data:/host-storage/data:ro
```

展示挂载点（最多 512 个字符）与容器 probe 路径必须是绝对路径、长度受限且不含父级遍历。展示挂载点会原样保留，包括合法的重复空白。采集器只使用 `findmnt` 和 `statvfs` 获取元数据和容量。bind mount source 如 `/dev/sda1[/data]` 会归一化为 `/dev/sda1`；非设备 source 不会上报，以免泄露远端端点。它不会递归读取目录。伪文件系统、无效元数据和不可访问 probe 都是不可用数据，不能显示为零使用量，也不能因此挂载宿主机根目录、进入 mount namespace、使用 `nsenter` 或增加 `CAP_SYS_ADMIN`。

`available_bytes` 使用 `statvfs.f_bavail`（普通写入者可用空间），而 `used_bytes` 使用 `f_blocks - f_bfree`，因此保留块不会被错误显示为可用。物理磁盘表会为每个已安全解析出的文件系统行重复该磁盘；没有关联卷的磁盘只显示一行“不可用”分区信息，绝不编造分区数据。

## 主页与 Hardware 语义

主页的温度、SMART、累计 I/O 和通电时间卡片仅使用物理磁盘记录。多盘时选取的最大值或聚合状态会标明设备，不代表文件系统的逻辑 I/O；单盘继续使用紧凑的单盘展示。Hardware 页面提供完整的安全库存，小屏幕使用可横向滚动的表格。

系统身份来自安全的宿主机元数据，如已挂载的 `os-release` 和 `uname`；DSM 版本来源为可选且只解析 allowlist 的文本源。DSM 来源不可用时回退到通用操作系统身份，绝不执行或 source 配置文件。

## 诊断与溯源

Hardware 页面和只读设备诊断可显示已脱敏的设备身份/状态、协议、采集时间、系统身份、逐项采集状态和 EasyTier expectation 配置状态。绝不显示 token、token digest、credential 或 Registry 路径、源地址证据、私有 CA、认证头、原始 SMART 输出或原始宿主机配置。

构建溯源在镜像构建时注入。Server 构建信息和选中 Client 的可选构建信息包含有边界的版本、完整 Git revision、可选构建时间/协议。生产镜像不得在运行时调用 Git。候选资格验证要求完整 revision 与相应的 `org.opencontainers.image.revision` label 一致。

部署环境是 allowlist 的运维设置，例如 `HERMESSTATUS_DEPLOYMENT_ENV=preview`，绝不能由端口推断。当前独立的 2.3 Preview staging 使用宿主机 21443，同时与 2.2 容器、配置、状态、镜像、网络和重启生命周期隔离。

## 资格验证状态

真实资格验证覆盖已可用的 GK50 硬件采集及其单盘兼容路径。无秘密 synthetic fixture 覆盖通用 LVM、MD RAID、device mapper、Btrfs/EXT4、多盘 SMART 部分失败、恶意字符串、文件系统 probe 失败和溯源校验。

Synology DSM 布局已经准备并仅完成 synthetic 合同资格验证。真实 DSM 设备名、存储布局、版本解析、容量、SMART 和内存观测仍需在真实 Synology 主机安装后以只读方式验证。Synthetic 示例绝不代表真实设备或双站点已验证。
