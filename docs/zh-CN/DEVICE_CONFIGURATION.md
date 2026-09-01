# 设备配置

本文描述 Device v2 配置边界。示例只使用文档地址和占位 secret 路径。

## 路径与挂载

典型宿主机路径均应 root-owned：

| 宿主机路径 | 容器路径 | 用途 |
| --- | --- | --- |
| `/etc/hermesstatus/client-v2.json` | 同路径 | Client 配置 |
| `/etc/hermesstatus/credentials.d/<device>.token` | `/run/secrets/hermesstatus-device-token` | Device v2 token |
| `/etc/hermesstatus/ca.crt` | `/run/secrets/hermesstatus-ca.crt` | Server CA |
| 固定 SMART 设备 | 相同设备节点 | 指定 SMART 观测 |
| 固定空文件系统探针目录 | 固定 `/host-storage/...` 路径 | 指定文件系统观测 |

所有 secret 与 probe 挂载都是只读。不要为观测而挂载整个 `/dev`、主机根目录、Docker socket 或软件包树。

## Device v2 文件

```json
{
  "device": {
    "id": "example-device",
    "server": {
      "url": "https://status.example.invalid:443",
      "ca_file": "/run/secrets/hermesstatus-ca.crt",
      "token_file": "/run/secrets/hermesstatus-device-token"
    }
  },
  "hardware": {
    "smart_devices": ["/dev/sda"],
    "filesystem_probes": [
      {"mountpoint": "/data", "probe_path": "/host-storage/data"}
    ]
  }
}
```

Registry 是展示名称的权威来源。`device.id` 是稳定身份，不能用展示名称、地址、hostname 或 EasyTier peer ID 替代。

## 可选集成

Lucky 接受显式的 loopback base URL、TLS 策略与可选 token-file 模式。配置 token 时只将该文件挂到固定 secret 路径；空 token 文件不能代替 `auth_mode: none`。

EasyTier 需要显式启用、固定只读 CLI 路径和 loopback RPC 端点。可选 administrative role 可以省略；空值与省略具有相同默认语义。已知非空 role 会被严格校验。

## Synology/DSM 说明

DSM 存储是分层的。为目标数据卷配置窄范围只读 probe，并将其显示为文件系统，而不是把 RAID `/dev/md*` 卷绑定到单块成员盘。需要 DSM 身份时，只挂载相应版本文件的小范围只读来源，不要挂载宽泛系统目录。

## 检查表

1. 创建 Registry 设备与仅保存 digest 的 Server 凭据。
2. 写入 `client-v2.json` 与 root-owned token/CA 文件。
3. 校验 Server 和 Client 配置。
4. 执行非修改 preflight，再部署不可变镜像。
5. 在 UI 确认身份、HTTPS ingestion、fresh 状态与展示名称。

## UniFi target（可选）

仅在需要已验证 target 时，才将 `unifi` 对象加入同一个 Device v2 文件。profile 只选择有界采集 source，不能建立 controller 硬件 identity 或静态能力；静态能力只在 runtime identity 通过冻结 Catalog 的 verified alias 后投影。未知 profile 必须 fail-closed。配置中不存在 command、path、token、SSH-key 或 shell 字段：

```json
"unifi": {
  "enabled": true,
  "profile": "ucg-max",
  "host": "console.example.invalid",
  "port": 22,
  "username": "root",
  "credential_file": "/run/secrets/unifi-password",
  "known_hosts_file": "/run/secrets/unifi-known-hosts",
  "connect_timeout_seconds": 10,
  "interval_seconds": 60
}
```

禁用时严格使用 `"unifi": {"enabled": false}`，或移除可选对象。credential 与 known-host 文件须分别以 root-owned 只读方式挂载。profile 不能证明硬件物理存在：UCG Max 的 `fan1=0` 是观测值，不是风扇健康失败；未知 runtime model 保留观测但不投影静态能力，未知 NVMe capability/presence 必须继续保持 unknown。
