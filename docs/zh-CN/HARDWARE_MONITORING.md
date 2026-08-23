# 硬件监控设计

硬件域是一个有边界、可故障隔离的观测管道。SMART 命令失败不能让 CPU、内存、文件系统、Docker 或其他硬件观测消失。

## 来源与归一化

Client 通过固定解析器采集 CPU、内存、系统身份、文件系统、物理磁盘和 SMART。硬件展示将物理盘属性（型号、容量、温度、SMART、通电时间）与卷/文件系统（挂载点、来源、格式、使用量、采集状态）区分开。这能支持 DSM RAID、mdraid、LVM 和 device-mapper，而不虚构磁盘从属关系。

概览采用最大的健康已配置文件系统。对 DSM，数据卷会自然被选中，无需硬编码卷名称。

## SMART 语义

SMART 设备必须来自明确 allowlist。native return-status 优先；若 native 状态不可用，但 attributes/thresholds 提供可信回退，磁盘可显示 `passed` 与 `partial` 质量、`health_source: attribute_check` 及诊断 warning。该可用 partial 状态本身不会使整个存储或设备 degraded；真实 health failed 必须保持为失败。

## 最小权限

使用明确设备映射，并在需要时使用 `SYS_RAWIO`。不要使用 privileged、`SYS_ADMIN`、宽泛 `/dev`、`/dev/sg*`、主机根目录或任意路径。文件系统观测依赖配置的窄范围只读 probe；DSM 版本数据同样只能是窄范围只读输入。
