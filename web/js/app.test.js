#!/usr/bin/env node

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const app = require('./app.js');
const ROOT = path.resolve(__dirname, '../..');
const indexMarkup = fs.readFileSync(path.join(ROOT, 'web/index.html'), 'utf8');
const appSource = fs.readFileSync(path.join(ROOT, 'web/js/app.js'), 'utf8');

function fixture(name){
  return JSON.parse(fs.readFileSync(path.join(ROOT, `testdata/migration/stats-${name}.json`), 'utf8'));
}

function multiDeviceFixture(name){
  return JSON.parse(fs.readFileSync(
    path.join(ROOT, `testdata/multi_device/valid/${name}.json`),
    'utf8'
  ));
}

function statsDocument(name, overrides = {}){
  const extension = fixture(name);
  return {
    schema_version: 2,
    default_device_id: 'device-alpha',
    updated: Math.floor(new Date(extension.received_at).getTime() / 1000),
    servers: [{
      device_id: 'device-alpha', display_name: 'Fixture Host',
      status: 'online', identity_status: 'matched', protocol_mode: 'device_v2',
      name: 'fixture-host', disabled: false, online4: true, online6: false,
      cpu: 10, memory_used: 7 * 1024 * 1024, memory_total: 10 * 1024 * 1024,
      hdd_used: 90 * 1024, hdd_total: 100 * 1024, uptime: '12 天 3 小时',
      os: 'Example Linux 2.0', hardware: extension.hardware, docker: extension.docker,
      hermes: extension.hermes, lucky: extension.lucky, ...overrides
    }]
  };
}

async function run(){
  const normal = app.buildViewModel(statsDocument('normal'));
  assert.equal(normal.host.name, 'fixture-host');
  assert.equal(normal.profiles.length, 2);
  assert.equal(normal.containers.length, 3);
  assert.equal(normal.lucky.status, 'ok');
  assert.equal(normal.lucky.certificates.expiring, 1);
  assert.equal(app.luckyIsConfigured(normal.lucky), true);
  assert.equal(app.usageBand(normal.resources.cpuPercent), 'low');
  assert.equal(app.usageBand(normal.resources.memoryPercent), 'medium');
  assert.equal(app.usageBand(normal.resources.diskPercent), 'high');
  assert.equal(app.normalizePageName('home'), 'home');
  assert.equal(app.normalizePageName('hardware'), 'hardware');
  assert.equal(app.normalizePageName('docker'), 'docker');
  assert.equal(app.normalizePageName('lucky'), 'lucky');
  assert.equal(app.normalizePageName('unifi'), 'unifi');
  assert.equal(app.normalizePageName('unexpected'), 'home');
  assert.equal(app.pageFromHash(''), 'home');
  assert.equal(app.pageFromHash('#home'), 'home');
  assert.equal(app.pageFromHash('#hardware'), 'hardware');
  assert.equal(app.pageFromHash('#docker'), 'docker');
  assert.equal(app.pageFromHash('#lucky'), 'lucky');
  assert.equal(app.pageFromHash('#unifi'), 'unifi');
  assert.equal(app.pageFromHash('#invalid'), 'home');
  assert.deepEqual(app.parseDashboardHash('#docker?device=device-alpha'), {
    page: 'docker', deviceId: 'device-alpha', needsRewrite: false
  });
  assert.equal(app.parseDashboardHash('#lucky?device=device%2Dbeta').deviceId, 'device-beta');
  assert.equal(app.parseDashboardHash('#home?device=device-a&device=device-b').deviceId, null);
  assert.equal(app.parseDashboardHash('#home?device=device-a&unexpected=1').needsRewrite, true);
  assert.equal(app.parseDashboardHash('#home?device=%3Cscript%3E').deviceId, null);
  assert.equal(app.canonicalDashboardHash('docker', 'device-alpha'), '#docker?device=device-alpha');
  assert.equal(app.canonicalDashboardHash('unexpected', null), '#home');
  assert.equal(app.validDeviceId('device-alpha'), true);
  assert.equal(app.validDeviceId('DEVICE-ALPHA'), false);
  assert.equal(app.validDeviceId('<script>'), false);
  assert.doesNotMatch(indexMarkup, /Lucky Monitoring|luckyHomeSummary|luckyHomeMeta/);
  assert.match(appSource, /<h2>EasyTier运行状态\/版本<\/h2>/);
  assert.match(appSource, /<h2>系统已运行时间<\/h2>/);
  assert.match(appSource, /<dt>指令集<\/dt>/);
  assert.match(appSource, /<h2>运行中\/容器总数<\/h2>/);
  assert.match(appSource, /<h2>Lucky运行状态\/版本<\/h2>/);
  assert.match(appSource, /采集状态/);
  assert.match(appSource, /EasyTier远端节点数/);
  assert.match(appSource, /EasyTier流量统计/);
  assert.match(indexMarkup, /id="unifiPorts"/);
  assert.match(indexMarkup, /id="unifiEmptyState"/);
  assert.match(appSource, /已配置 UniFi 目标，但访问失败，请检查 SSH 密码和 API Key/);
  assert.match(appSource, /未配置 UniFi 目标/);

	assert.doesNotMatch(appSource, /easytierCommandsBody/);
  assert.match(appSource, /easytierPeersBody/);
  assert.match(appSource, /easytierExpectationBody/);
  assert.match(appSource, /function expectationBadge\(value\)/);
  assert.match(appSource, /expectationBadge\(expectation\.result/);
  assert.match(appSource, /const peerSummary = !commandAvailable\('peer_list'\)/);
	assert.match(appSource, /const tcpConnectorText = commandAvailable\('connector_list'\)/);
	assert.match(appSource, /const trafficText = commandAvailable\('stats_show'\)/);
	assert.match(appSource, /peer\.established_tunnels/);
  assert.doesNotMatch(appSource, /CPU温度\/硬盘温度/);
  assert.doesNotMatch(appSource, /已运行时间\/操作系统/);
	assert.doesNotMatch(indexMarkup, /easytierCommandsTitle/);
	assert.match(indexMarkup, /<th>已建立隧道<\/th>/);
	assert.ok(
		indexMarkup.indexOf('easytierSummaryTitle') < indexMarkup.indexOf('easytierPeersTitle')
		&& indexMarkup.indexOf('easytierPeersTitle') < indexMarkup.indexOf('easytierRoutesTitle')
		&& indexMarkup.indexOf('easytierRoutesTitle') < indexMarkup.indexOf('easytierConnectorsTitle')
		&& indexMarkup.indexOf('easytierConnectorsTitle') < indexMarkup.indexOf('easytierExpectationTitle')
	);
  assert.doesNotMatch(indexMarkup, /<th>说明<\/th>/);
  assert.equal(app.formatUptimeHours(90061), '25 h (约1.04天)');
  assert.equal(app.formatCelsius(47), '47℃');
  assert.equal(app.formatCelsius(47.25), '47.3℃');
  assert.equal(
    app.cpuLogicalProcessorText({logical_cpus: 16, sockets: 2, cores_per_socket: 4, threads_per_core: 2}),
    '16（2 插槽 / 8 核心 / 16 线程）'
  );
  assert.equal(app.formatTrafficBytes(0), '0.0B');
  assert.equal(app.formatTrafficBytes(1000000), '1.0MB');
	assert.deepEqual(app.easytierOverviewText({
		command_status: {peer_list: {status: 'healthy'}, stats_show: {status: 'healthy'}},
		peers: {total: 0, direct: 0, relay: 0, unknown_path: 0},
		traffic: {bytes_rx: 0, bytes_tx: 0, bytes_forwarded: 0}
	}), {peers: '0（— / — / —）', traffic: '0.0B / 0.0B / 0.0B'});
	assert.deepEqual(app.easytierOverviewText({
		command_status: {peer_list: {status: 'unavailable'}, stats_show: {status: 'invalid_data'}},
		peers: {direct: 0, relay: 0, unknown_path: 0},
		traffic: {bytes_rx: 0, bytes_tx: 0, bytes_forwarded: 0}
	}), {peers: '数据不可用', traffic: '数据不可用'});
	assert.deepEqual(app.easytierOverviewText({}), {peers: '数据不可用', traffic: '数据不可用'});
	assert.equal(app.ipv6UdpDirectText({ipv6_udp_direct: null}, true), '未观察到');
	assert.equal(app.ipv6UdpDirectText({ipv6_udp_direct: true}, true), '是');
	assert.equal(app.ipv6UdpDirectText({ipv6_udp_direct: null}, false), '数据不可用');
  assert.equal(app.profileSummary([{agent_version: '0.19.0'}, {agent_version: '0.19.0'}, {agent_version: '0.19.0'}]), 'Agent版本: 0.19.0，3个配置');
  assert.equal(
    app.modelBreakdown({model: 'example-model', usage_mode: 'api', provider: 'OpenCode Go'}),
    'example-model / api / OpenCode Go'
  );

  const udwUniFi = {
    configured: true, profile: 'udw', stale: false, updated_at: '2026-08-27T01:02:03Z', error: null,
    transport: {status: 'available', last_attempt: '2026-08-27T01:02:03Z', last_success: '2026-08-27T01:02:03Z'},
    system: {
      cpu_model: 'Annapurna AL324',
      cpu_usage_percent: 12.5, cpu_usage_reason: null, cpu_temperature_c: 64.2, uptime_seconds: 123456,
      memory: {used_bytes: 2_000_000_000, total_bytes: 4_000_000_000, used_percent: 50, available_source: 'mem_available'},
      load_average: {one_minute: 1.16, five_minutes: 1.29, fifteen_minutes: 1.17}
    },
    fans: [
      {id: 'fan1', supported: 'supported', present: 'present', observed: true, rpm: 1698, state: 'observed', error: null},
      {id: 'fan2', supported: 'supported', present: 'present', observed: true, rpm: 2752, state: 'observed', error: null}
    ],
    power_supplies: [{id: 'psu1', supported: 'supported', present: 'unknown', observed: false, state: 'not_observed', error: null}],
    storage: {
      nvme: {supported: 'unsupported', present: 'not_present', observed: false, capacity_bytes: null},
      sata_ssd: {supported: 'supported', present: 'present', observed: false, capacity_bytes: 128000000000},
      tf: {supported: 'supported', present: 'not_present', observed: false, capacity_bytes: null}
    },
    diagnostics: {collection_status: 'available', ignored_observations: [{id: 'fan3', reason: 'profile_not_populated'}]}
  };
  const ucgMaxUniFi = {
    ...udwUniFi, profile: 'ucg-max',
    system: {...udwUniFi.system, cpu_usage_percent: null, cpu_usage_reason: 'insufficient_delta', cpu_temperature_c: null,
      memory: {...udwUniFi.system.memory, available_source: 'fallback_memfree_buffers_cached'}},
    fans: [{id: 'fan1', supported: 'supported', present: 'unknown', observed: true, rpm: 0, state: 'observed_zero_rpm', error: null}],
    power_supplies: [], storage: {
      nvme: {supported: 'unknown', present: 'unknown', observed: false, capacity_bytes: null},
      sata_ssd: {supported: 'unknown', present: 'unknown', observed: false, capacity_bytes: null},
      tf: {supported: 'unknown', present: 'unknown', observed: false, capacity_bytes: null}
    }
  };
  const unifiView = app.buildViewModel(statsDocument('normal', {unifi: udwUniFi}));
  assert.equal(unifiView.unifi.profile, 'udw');
  assert.equal(app.unifiIsConfigured(udwUniFi), true);
  assert.equal(app.unifiIsConfigured({configured: false, transport: {status: 'disabled'}}), false);
  assert.deepEqual(app.unifiTransportSummary({configured: false, transport: {status: 'disabled'}}), {status: 'disabled', text: '未配置'});
  assert.deepEqual(app.unifiTransportSummary({...udwUniFi, stale: true}), {status: 'stale', text: '数据陈旧'});
  assert.deepEqual(app.unifiTransportSummary({...udwUniFi, transport: {status: 'unavailable'}}), {status: 'unavailable', text: '不可用'});
  assert.equal(app.unifiApiStatusText(udwUniFi), '可用（SSH）');
  assert.deepEqual(app.unifiCollectionStatus({...udwUniFi, api: {status: 'available'}}), {ssh: '成功', api: '成功'});
  assert.deepEqual(app.unifiCollectionStatus({...udwUniFi, stale: true, api: {status: 'partial'}}), {ssh: '失败', api: '部分成功'});
  assert.equal(app.unifiApiStatusText({...udwUniFi, api_reachable: false}), '不可用');
  assert.equal(app.unifiApiStatusText({...udwUniFi, api: {status: 'available'}}), '可用');
  assert.equal(app.unifiApiStatusText({...udwUniFi, api: {status: 'unavailable', error: {code: 'api_auth_failure'}}}), '认证失败');
  assert.match(app.unifiSystemRows(udwUniFi).map(row => row.join(' ')).join(' '), /64\.2℃/);
  assert.match(app.unifiSystemRows(udwUniFi).map(row => row.join(' ')).join(' '), /2\.00 GB \/ 4\.00 GB/);
  assert.match(app.unifiSystemRows(ucgMaxUniFi).map(row => row.join(' ')).join(' '), /CPU 使用率[\s\S]*usage-bar[\s\S]*-/);
  assert.match(app.unifiSystemRows(ucgMaxUniFi).map(row => row.join(' ')).join(' '), /可用内存回退估算/);
  assert.match(app.unifiFanRows(udwUniFi), /1,698 RPM/);
  assert.match(app.unifiFanRows(ucgMaxUniFi), /已观察到 0 RPM/);
  assert.doesNotMatch(app.unifiFanRows(ucgMaxUniFi), /失败/);
  assert.match(app.unifiFanRows({...ucgMaxUniFi, fans: [{id: 'fan1', supported: 'supported', present: 'unknown', observed: false, rpm: null, state: 'not_observed'}]}), /未观察到/);
  assert.match(app.unifiPowerRows(udwUniFi), /未知/);
  const udwStorageRows = app.unifiStorageRows(udwUniFi).map(row => row.join(' ')).join(' ');
  assert.match(udwStorageRows, /SATA SSD/);
  assert.match(udwStorageRows, /128 GB/);
  assert.match(udwStorageRows, /TF/);
  assert.match(udwStorageRows, /未安装/);
  assert.match(udwStorageRows, /NVMe/);
  const storageWithUsage = {...udwUniFi, storage: {
    ...udwUniFi.storage,
    sata_ssd: {...udwUniFi.storage.sata_ssd, total_bytes: 128000000000, used_bytes: 64000000000, usage_percent: 50}
  }};
  const storageMarkup = app.unifiStorageMarkup(storageWithUsage);
  assert.match(storageMarkup, /unifi-storage-table/);
  assert.match(storageMarkup, /64\.0 GB \/ 128 GB/);
  assert.match(storageMarkup, /50%/);
  const notInstalledStorage = app.unifiStorageMarkup(udwUniFi);
  const tfRow = notInstalledStorage.match(/<tr>[^]*?<\/tr>/g).find(row => row.includes('>TF<'));
  assert.match(tfRow, /未安装/);
  assert.equal((tfRow.match(/(?:<td>-<\/td>|<td class=\"table-usage\">-<\/td>)/g) || []).length, 4);
  const unsupportedStorageMarkup = app.unifiStorageMarkup({...udwUniFi, storage: {
    nvme: {supported: 'unsupported', present: 'not_present', observed: false, capacity_bytes: 1000000000, used_bytes: 100},
  }});
  assert.match(unsupportedStorageMarkup, /NVMe/);
  assert.match(unsupportedStorageMarkup, /不支持/);
  assert.match(unsupportedStorageMarkup, /<td>-<\/td>/g);
  assert.match(app.unifiPowerRows({...udwUniFi, power_supplies: [{id: 'psu1', supported: 'unsupported', present: 'not_present', observed: false, state: 'not_observed'}]}), /不支持[\s\S]*未安装/);
  assert.match(app.unifiPowerRows(udwUniFi), /未提供/);
  const apiFixture = {enabled: true, status: 'available', telemetry: {
    identity: {model: 'UniFi Dream Wall', display_name: 'UDW', firmware: '5.1.31', status: 'ONLINE'},
    controller: {application_version: '10.5.67', state: 'ONLINE'},
    uplinks: [{name: 'UniFi Dream Wall', link_state: 'ONLINE', speed_mbps: 2500}, {name: 'USW Flex Mini', link_state: 'ONLINE', speed_mbps: 1000}],
    clients: {total: 19, wired: 14, wireless: 5, observed: true},
    networks: {total: 3, vlan: 3},
    ports: [
      {device_id: 'udw-1', port_idx: 10, name: 'Port 10', media: 'GE', up: false, enabled: true, uplink: false, speed_mbps: 0, max_speed_mbps: 1000, rx_bytes: 0, tx_bytes: 0, poe: {supported: false}},
      {device_id: 'udw-1', port_idx: 2, name: 'Port 2', media: 'GE', up: true, enabled: true, uplink: false, speed_mbps: 1000, max_speed_mbps: 2500, rx_bytes: 1000, tx_bytes: 2000, tx_errors: 2, tx_dropped: 3, rx_errors: 0, rx_dropped: 1, poe: {supported: true, active: true, power_w: 3.32, max_power_w: 30}, peer_count: 1},
      {device_id: 'udw-1', port_idx: 7, name: 'Port 7', media: '2.5GE', up: true, enabled: true, uplink: true, speed_mbps: 2500, max_speed_mbps: 2500, rx_bytes: 1000, tx_bytes: 2000, rx_bps: 1000000, tx_bps: 2000000, poe: {supported: true, active: true, power_w: 3.32, max_power_w: 30}, peer_count: 1},
      {device_id: 'switch-1', port_idx: 1, name: 'Port 1', media: 'GE', up: true, enabled: true, uplink: false, speed_mbps: 1000, max_speed_mbps: 1000, rx_bytes: 0, tx_bytes: 0, poe: {supported: false}}
    ],
    port_summary: {total: 1, up: 1, down: 0, poe_active: 1, poe_total_power_w: 3.32},
    lags: [], topology: null, anomalies: null
  }};
  const systemCards = app.unifiSystemCards({...udwUniFi, api: apiFixture});
  const apiTelemetryMarkup = app.unifiApiTelemetryMarkup({...udwUniFi, api: apiFixture});
  const portTelemetryMarkup = app.unifiPortTelemetryMarkup({...udwUniFi, api: apiFixture});
  const wanMarkup = app.unifiWanMarkup({...udwUniFi, api: {...apiFixture, telemetry: {...apiFixture.telemetry, wans: [{id: 'wan1', name: 'WAN', online: true, active: true, isp: 'Example ISP', link_speed_mbps: 2500, latency_ms: 0, packet_loss_percent: 0, jitter_ms: 0, sla_status: 'healthy'}]}}});
  assert.match(portTelemetryMarkup, /unifi-ports-table/);
  assert.match(portTelemetryMarkup, /Port 7/);
  assert.match(portTelemetryMarkup, /2\.5 GbE/);
  assert.match(portTelemetryMarkup, />7<\/td>/);
  assert.match(portTelemetryMarkup, /端口编号/);
  assert.match(portTelemetryMarkup, />上行</);
  assert.match(portTelemetryMarkup, /2\.5 GbE \/ 2\.5 GbE/);
  assert.match(portTelemetryMarkup, /2\.00 KB/);
  assert.match(portTelemetryMarkup, /1\.00 KB/);
  assert.match(portTelemetryMarkup, /3\.32 W/);
  assert.match(portTelemetryMarkup, /发送 \/ 接收 \(错误\/丢弃\)/);
  assert.match(portTelemetryMarkup, /2 \/ 3 \/ 0 \/ 1/);
  assert.match(portTelemetryMarkup, /PoE 总功率：6\.64 W \/ 60 W/);
  assert.match(portTelemetryMarkup, /未连接 \/ 1 GbE/);
  assert.match(portTelemetryMarkup, /发送 \/ 接收 \(错误\/丢弃\)/);
  assert.match(wanMarkup, /Example ISP/);
  assert.match(wanMarkup, /0\.0 ms \/ 0\.00% \/ 0\.0 ms/);
  assert.doesNotMatch(portTelemetryMarkup, /<th>RX<\/th>|<th>TX<\/th>|<th>连接<\/th>/);
  assert.equal(app.unifiPortLinkText({up: false, speed_mbps: 1000, max_speed_mbps: 10000}), '未连接 / 10 GbE');
  assert.equal(app.unifiPortPoeText({poe: {supported: false, power_w: 0}}), '-');
  assert.doesNotMatch(portTelemetryMarkup, /mac_table|mac_address|192\\.168/);
  assert.match(apiTelemetryMarkup, /UniFi 设备型号/);
  assert.match(apiTelemetryMarkup, /UniFi Dream Wall/);
  assert.match(apiTelemetryMarkup, /在线/);
  assert.match(apiTelemetryMarkup, /2\.5 GbE/);
  assert.equal(app.unifiLinkBandwidth(100), 'FE');
  assert.equal(app.unifiLinkBandwidth(1000), '1 GbE');
  assert.equal(app.unifiLinkBandwidth(10000), '10 GbE');
  assert.doesNotMatch(apiTelemetryMarkup, /WAN|双工|速率|设备身份|连接客户端/);
  assert.match(apiTelemetryMarkup, /unifi-api-table/);
  assert.match(systemCards, /<h2>设备名称\/型号<\/h2>/);
  assert.match(systemCards, /UDW/);
  assert.match(systemCards, /UniFi Dream Wall/);
  assert.match(systemCards, /<h2>CPU<\/h2>/);
  assert.match(systemCards, /<h2>内存<\/h2>/);
  assert.doesNotMatch(systemCards, /<h2>CPU 使用率<\/h2>/);
  assert.doesNotMatch(systemCards, /<h2>内存使用率<\/h2>/);
  assert.match(systemCards, /CPU 温度/);
  assert.match(systemCards, /负载/);
  assert.match(systemCards, /19 \(14 \/ 5\)/);
  assert.match(systemCards, /总数 \(有线 \/ 无线\)/);
  assert.match(systemCards, /运行时间/);
  assert.match(systemCards, /控制器状态 \(版本\)/);
  assert.match(systemCards, /在线.*5\.1\.31/);
  assert.match(systemCards, /网络应用状态 \(版本\)/);
  assert.match(systemCards, /10\.5\.67/);
  assert.match(systemCards, /网络摘要/);
  assert.match(systemCards, /3 \/ 3 <span class="card-mini-meta">\(网络 \/ VLAN\)<\/span>/);
  assert.match(systemCards, /3 \/ 3/);
  assert.match(systemCards, /power-on-days/);
  assert.match(systemCards, /data-fit-single-line="unifi-primary-value"/);
  assert.match(systemCards, /Annapurna AL324/);
  const unavailableCards = app.unifiSystemCards({...ucgMaxUniFi, api: {...apiFixture, telemetry: {...apiFixture.telemetry, identity: {model: 'UDW', display_name: 'UDW', status: 'ONLINE'}}}});
  assert.match(unavailableCards, /<div class="usage-bar"[\s\S]*<span>-<\/span>/);
  assert.match(systemCards, /2\.00 GB \/ 4\.00 GB/);
  assert.match(systemCards, /<h2>CPU<\/h2>[\s\S]*Annapurna AL324/);
  assert.match(portTelemetryMarkup, /UniFi Dream Wall/);
  assert.match(portTelemetryMarkup, /USW Flex Mini/);
  assert.ok(portTelemetryMarkup.indexOf('>2</td>') < portTelemetryMarkup.indexOf('>7</td>'));
  assert.ok(portTelemetryMarkup.indexOf('>7</td>') < portTelemetryMarkup.indexOf('>10</td>'));
  assert.doesNotMatch(portTelemetryMarkup, /已连接 · 上联/);
  assert.doesNotMatch(systemCards, /card-mini-meta"[^>]*>\(网络 \/ VLAN\)<\/div>/);
  const cardLabels = ['设备名称/型号', 'CPU', '内存', '负载', '连接客户端', 'CPU 温度', '运行时间', '控制器状态 (版本)', '网络应用状态 (版本)', '网络摘要'];
  let previous = -1;
  for(const label of cardLabels){
    const position = systemCards.indexOf(`<h2>${label}</h2>`);
    assert.ok(position > previous, `${label} card order`);
    previous = position;
  }
  assert.doesNotMatch(app.unifiFanRows(udwUniFi), /fan3|fan4/);
  const unavailableUniFi = {...ucgMaxUniFi, stale: true, system: null, fans: [], power_supplies: [], updated_at: null,
    transport: {status: 'unavailable', last_attempt: '2026-08-27T01:02:04Z', last_success: '2026-08-27T01:02:03Z'},
    error: {code: 'ssh_timeout'}};
  assert.deepEqual(app.unifiTransportSummary(unavailableUniFi), {status: 'unavailable', text: '不可用'});
  assert.match(app.unifiFanRows(unavailableUniFi), /暂无可显示的风扇观测/);
  assert.match(app.unifiSystemRows(ucgMaxUniFi).map(row => row.join(' ')).join(' '), /CPU 温度 -/);
  assert.doesNotMatch(app.unifiSystemRows(ucgMaxUniFi).map(row => row.join(' ')).join(' '), /CPU 温度 0℃/);

  const multiDiskHardware = {
    cpu_temperatures: [
      {label: 'CPU Package', value: 44}, {label: 'CPU0', value: 47}
    ],
    storage: {
      physical_disks: [
        {id: 'sda', device: '/dev/sda', model: 'Disk A', temperature_c: 42, smart_status: 'passed', power_on_hours: 12000, written_bytes: 2_000_000_000_000, read_bytes: 1_000_000_000_000},
        {id: 'sdb', device: '/dev/sdb', model: 'Disk B', temperature_c: 50, smart_status: 'failed', power_on_hours: 22344, written_bytes: 4_730_000_000_000, read_bytes: 2_500_000_000_000},
        {id: 'sdc', device: '/dev/sdc', model: 'Disk C', temperature_c: 39, smart_status: 'passed', power_on_hours: 3000, written_bytes: null, read_bytes: null}
      ],
      filesystems: [{
        source: '/dev/mapper/vg-root', mountpoint: '/', fs_type: 'ext4',
        used_bytes: 32_500_000_000, total_bytes: 110_000_000_000,
        usage_percent: 29.5, backing_disk_ids: ['sda', 'sdb']
      }]
    }
  };
  assert.deepEqual(
    app.physicalDisksForView(multiDiskHardware).map(disk => disk.id),
    ['sda', 'sdb', 'sdc']
  );
  assert.equal(app.filesystemItemsForView(multiDiskHardware).length, 1);
  assert.deepEqual(app.dataFilesystemItemsForView(multiDiskHardware).map(item => item.mountpoint), ['/']);
  assert.equal(app.diskPowerOnText({power_on_hours: 1970}), '1,970 h (约82.08天)');
  assert.deepEqual(
    app.maximumTemperature(app.temperatureSensorEntries(multiDiskHardware)),
    {label: 'CPU0', value: 47}
  );
  assert.deepEqual(app.filesystemBackingDisks(multiDiskHardware.storage.filesystems[0]), {
    text: '2 块磁盘', title: 'sda / sdb'
  });
  const linkedFilesystemMarkup = app.renderFilesystemDetails(multiDiskHardware);
  assert.match(linkedFilesystemMarkup, /2 块磁盘/);
  assert.match(linkedFilesystemMarkup, /title="sda \/ sdb"/);
  assert.match(app.smartHomeMarkup(multiDiskHardware.storage.physical_disks, multiDiskHardware), /2 \/ 3 通过/);
  assert.match(app.smartHomeMarkup(multiDiskHardware.storage.physical_disks, multiDiskHardware), /sdb故障/);
  const legacyDisk = app.physicalDisksForView({
    disk_device: '/dev/sda', disk_smart_status: 'passed', disk_power_on_hours: 12000,
    disk_written_bytes: 2_000_000_000_000, disk_read_bytes: 1_000_000_000_000,
    disk_temperature: {current: 42}
  });
  assert.equal(legacyDisk.length, 1);
  assert.equal(legacyDisk[0].id, 'sda');
  assert.equal(app.smartHomeMarkup(legacyDisk, {}), '通过');
  const attributeFallbackDisk = [{
    id: 'sdu', smart_status: 'passed', completeness: 'partial', health_source: 'attribute_check'
  }];
  assert.equal(app.smartHomeMarkup(attributeFallbackDisk, {}), '通过（属性检查）');
  const diagnosticMarkup = app.deviceDiagnosticsMarkup({
    host: {
      device_id: 'device-alpha', display_name: '<script>display</script>', status: 'online',
      identity_status: 'matched', protocol_mode: 'device_v2', disabled: false,
      ingestion_mode: 'device_v2', last_seen_at: '2026-08-01T00:00:00Z',
      last_accepted_at: '2026-08-01T00:00:01Z', source_ip: '192.0.2.1', fqdn: 'hidden.example'
    },
    hardware: {},
    easytierExpectation: {
      configured: true,
      expected: {network_name: '<img src=x>', overlay_ipv4: '10.250.250.1', proxy_cidrs: ['192.168.68.0/24']}
    }
  });
  assert.match(diagnosticMarkup, /&lt;script&gt;display/);
  assert.doesNotMatch(diagnosticMarkup, /<script>|<img src=x>|source_ip|192\.0\.2\.1|hidden\.example/);
	const unconfiguredDiagnostics = app.deviceDiagnosticsMarkup({
		host: {}, hardware: {},
		easytierExpectation: {configured: false, expected: {network_name: 'must-not-render', proxy_cidrs: ['192.168.68.0/24']}}
	});
	assert.match(unconfiguredDiagnostics, /EasyTier 预期已配置[\s\S]*否/);
	assert.doesNotMatch(unconfiguredDiagnostics, /must-not-render/);
	assert.doesNotMatch(unconfiguredDiagnostics, /192\.168\.68\.0\/24/);
  const provenanceMarkup = app.buildProvenanceMarkup({
    document: {schema_version: 2, build: {environment: 'staging', version: '2.3', revision: '0123456789abcdef', token: 'must-not-render'}},
    host: {protocol_mode: 'device_v2'},
    hardware: {client_build: {version: '2.3', revision: 'fedcba9876543210', protocol: 'device_v2'}}
  });
  assert.match(provenanceMarkup, /0123456789ab/);
  assert.match(provenanceMarkup, /fedcba987654/);
  assert.doesNotMatch(provenanceMarkup, /must-not-render/);
  assert.doesNotMatch(provenanceMarkup, /preview/i);

  const empty = app.buildViewModel(statsDocument('empty'));
  assert.equal(empty.profiles.length, 0);
  assert.equal(empty.containers.length, 0);
  assert.equal(empty.hardware.cpu_temperature, null);
  assert.equal(app.luckyIsConfigured(empty.lucky), false);
  assert.deepEqual(app.luckyServiceSummaryItems({status: 'not_configured'}), [
    ['进程状态', '未配置'], ['API 可用性', '未配置'], ['API 错误', '-']
  ]);
  assert.deepEqual(app.luckyServiceSummaryItems({
    status: 'unavailable', service: {process_running: false, api_reachable: false, error: {code: 'connection_refused'}}
  }), [['进程状态', '未运行'], ['API 可用性', '不可用'], ['API 错误', 'connection_refused']]);

  const dsmHardware = {
    system_identity: {distribution: 'Synology DSM', source: 'dsm-version', version: '7.2.1-69057 Update 1'},
    storage: {
      physical_disks: [
        {id: 'sda', device: '/dev/sda', model: 'DSM Disk A', capacity_bytes: 8_000_000_000_000, temperature_c: 37, smart_status: 'passed', power_on_hours: 1970},
        {id: 'sdb', device: '/dev/sdb', model: 'DSM Disk B', capacity_bytes: 8_000_000_000_000, temperature_c: 38, smart_status: 'passed', power_on_hours: 1971},
        {id: 'sdc', device: '/dev/sdc', model: 'DSM Disk C', capacity_bytes: 8_000_000_000_000, temperature_c: 39, smart_status: 'passed', power_on_hours: 1972},
        {id: 'sdd', device: '/dev/sdd', model: 'DSM Disk D', capacity_bytes: 8_000_000_000_000, temperature_c: 40, smart_status: 'passed', power_on_hours: 1973}
      ],
      filesystems: [
        {mountpoint: '/volume1', source: '/dev/md2', fs_type: 'btrfs', total_bytes: 911000000000, used_bytes: 101000000000, usage_percent: 11.1, collection_status: 'healthy', backing_disk_ids: []},
        {mountpoint: '/volume2', source: '/dev/md3', fs_type: 'ext4', total_bytes: 7930000000000, used_bytes: 4039000000000, usage_percent: 50.9, collection_status: 'healthy', backing_disk_ids: []},
        {mountpoint: '/var/packages/example', source: 'tmpfs', fs_type: 'tmpfs', total_bytes: 990000000000, collection_status: 'healthy'},
        {mountpoint: '/dev/shm', source: 'tmpfs', fs_type: 'tmpfs', total_bytes: 1000000000000, collection_status: 'healthy'}
      ]
    }
  };
  const dsmHost = {hdd_used: 4039000, hdd_total: 7930000, os: 'Synology DSM 7.2.1-69057 Update 1'};
  const dsmDiskUsage = app.homeDiskUsage(dsmHost, dsmHardware);
  assert.equal(dsmDiskUsage.text, '4.04 TB / 7.93 TB (vol2)');
  assert.equal(dsmDiskUsage.valueText, '4.04 TB / 7.93 TB');
  assert.equal(dsmDiskUsage.label, 'vol2');
  assert.equal(app.conciseOsVersion(dsmHost, dsmHardware), 'DSM 7.2.1');
  assert.deepEqual(app.dataFilesystemItemsForView(dsmHardware).map(item => item.mountpoint), ['/volume1', '/volume2']);
  const dsmFilesystemMarkup = app.renderFilesystemDetails(dsmHardware);
  assert.match(dsmFilesystemMarkup, /\/volume1/);
  assert.match(dsmFilesystemMarkup, /\/dev\/md2/);
  assert.match(dsmFilesystemMarkup, /btrfs/);
  assert.match(dsmFilesystemMarkup, /\/volume2/);
  assert.match(dsmFilesystemMarkup, /\/dev\/md3/);
  assert.match(dsmFilesystemMarkup, /ext4/);
  assert.match(dsmFilesystemMarkup, /4\.04 TB/);
  assert.match(dsmFilesystemMarkup, /7\.93 TB/);
  assert.match(dsmFilesystemMarkup, /50\.9%/);
	assert.match(dsmFilesystemMarkup, /<td title="-">-<\/td>/);
  assert.doesNotMatch(dsmFilesystemMarkup, /\/dev\/shm|\/var\/packages/);
  const dsmPhysicalDiskMarkup = app.renderPhysicalDiskRows(dsmHardware);
  for(const device of ['sda', 'sdb', 'sdc', 'sdd']) {
    assert.equal((dsmPhysicalDiskMarkup.match(new RegExp(`/dev/${device}`, 'g')) || []).length, 1);
  }
  assert.match(dsmPhysicalDiskMarkup, /1,970 h \(约82\.08天\)/);
  assert.doesNotMatch(dsmPhysicalDiskMarkup, /\/dev\/md2|分区 \/ 格式|已用 \/ 总容量|使用率/);
  const incompleteFilesystemMarkup = app.renderFilesystemDetails({storage: {filesystems: [{
    mountpoint: '/', source: '/dev/mapper/linux-root', fs_type: 'ext4',
    used_bytes: 1_000_000_000, total_bytes: 10_000_000_000,
    usage_percent: 10, collection_status: 'partial'
  }, {
    mountpoint: '/data', source: '/dev/mapper/linux-data', fs_type: 'xfs',
    used_bytes: 2_000_000_000, total_bytes: 10_000_000_000, usage_percent: 20
  }]}});
  assert.match(incompleteFilesystemMarkup, /部分采集/);
  assert.match(incompleteFilesystemMarkup, /<td>-<\/td>/);
  assert.match(appSource, /parenthesizedMeta\(resources\.diskLabel\)/);
  assert.equal(app.homeDiskUsage({hdd_used: 1, hdd_total: 2}, dsmHardware).label, null);
  assert.match(appSource, /view\.hermes\?\.error\?\.code === 'not_installed'/);

  const noHermesAgent = statsDocument('normal');
  noHermesAgent.servers[0].hermes = {
    profiles: [], updated_at: '2026-08-20T00:00:00Z', stale: false,
    error: {code: 'not_installed'}
  };
  const noHermesAgentView = app.buildViewModel(noHermesAgent);
  assert.equal(app.collectWarnings(noHermesAgentView).length, 0);
  assert.equal(app.dashboardCondition(noHermesAgentView).kind, 'ready');

  const degraded = app.buildViewModel(statsDocument('degraded'));
  assert.equal(app.collectWarnings(degraded).length, 5);
  assert.equal(degraded.hardware.disk_smart_status, 'unknown');
  assert.deepEqual(degraded.profiles.map(profile => profile.api_status), ['unauthorized', 'timeout']);

  const longValues = app.buildViewModel(statsDocument('long-values'));
  assert.ok(longValues.profiles[0].model.length > 180);
  assert.ok(longValues.containers[0].status.length > 100);
  assert.ok(longValues.containers[0].image.length > 160);
  assert.doesNotMatch(indexMarkup, /<th>命令<\/th>/);
  assert.doesNotMatch(appSource, /container\.command/);
  assert.deepEqual(Object.keys(longValues.containers[0]).sort(), ['image', 'names', 'ports', 'status']);

  const modalMarkup = app.profileModalMarkup({
    profile: 'profile-a',
    agent_version: '0.3.0',
    api_status: 'ok',
    service_status: 'healthy',
    gateway_service: 'running',
    manager_mode: 'docker (foreground)',
    usage_mode: 'auth_provider',
    provider: 'Example Provider',
    model: 'example-model',
    auth_refreshed_at: '2026-07-15T00:00:00Z',
    scheduled_jobs_active: 2,
    scheduled_jobs_total: 3,
    sessions_active: 4,
    sessions_total: 5,
    sessions_has_more: true,
    usage: {input_tokens: 100, output_tokens: 20, total_tokens: 120, estimated: true, source: 'local_logs', window_start: '2026-07-14T00:00:00Z', window_end: '2026-07-15T00:00:00Z'},
    config_summary: {
      config_found: true,
      main_model: {provider: 'Example Provider', model: 'example-model', base_url: 'provider default', concurrency: 4, timeout_seconds: 120},
      auxiliary_models: [{name: 'vision', provider: 'auto', model: '', effective_provider: 'Example Provider', effective_model: 'example-model', source: 'main_model', base_url_display: 'provider default', timeout_seconds: 120, max_concurrency: null}],
      delegation: {provider: 'Example Provider', model: 'delegate-model', reasoning_effort: 'medium', max_concurrent_children: 2, max_spawn_depth: 1, child_timeout_seconds: 300},
      docker_volumes: ['/srv/example/workspace:/workspace']
    },
    mixture_of_agents: {available: true, label: 'Mixture of Agents', configured: true, enabled: true, tools: ['mixture_of_agents'], error: null},
    updated_at: '2026-07-15T00:00:00Z',
    received_at: '2026-07-15T00:00:01Z',
    stale: false,
    error: null
  });
  for(const label of [
    '服务状态', '网关状态', 'API 状态', '运行模式', 'Agent 版本',
    '主模型', '模型提供商', '使用模式', 'Provider/模型配置刷新时间', '定时任务 活动/总数',
    '会话 活动/总数', '输入/输出/总 Token', 'Token 来源',
    '配置摘要', '辅助模型', '容器挂载点', 'Mixture of Agents',
    '数据更新时间', '采集错误'
  ]){
    assert.match(modalMarkup, new RegExp(label));
  }
  assert.match(modalMarkup, /本地运行快照/);
  assert.match(modalMarkup, /继承主模型/);
  assert.match(modalMarkup, /\/srv\/example\/workspace:\/workspace/);
  const escapedMarkup = app.profileModalMarkup({profile: '<script>throw 1</script>', usage: {}, config_summary: {}, mixture_of_agents: {}, error: {message: '<img src=x>'}});
  assert.doesNotMatch(escapedMarkup, /<script>|<img src=x>/);
  assert.match(escapedMarkup, /&lt;script&gt;/);

  assert.equal(app.buildViewModel({ servers: [] }).host, null);
  const firstDisabled = { name: 'disabled', disabled: true };
  const firstEnabled = { name: 'enabled', disabled: false };
  assert.equal(app.selectSingleHost([firstDisabled, firstEnabled]).name, 'enabled');
  assert.equal(app.selectSingleHost([firstDisabled]).name, 'disabled');

  const missingExtensions = app.buildViewModel({
    servers: [{ name: 'native-only', cpu: 0, memory_used: 0, memory_total: 0, hdd_used: 0, hdd_total: 0 }]
  });
  assert.equal(missingExtensions.host.name, 'native-only');
  assert.equal(missingExtensions.resources.cpuPercent, 0);
  assert.equal(missingExtensions.resources.memoryPercent, null);
  assert.deepEqual(missingExtensions.profiles, []);
  assert.deepEqual(missingExtensions.containers, []);

  const alpha = statsDocument('normal').servers[0];
  const beta = {
    ...alpha,
    device_id: 'device-beta',
    display_name: 'Beta',
    name: 'beta-host',
    status: 'offline',
    cpu: 77,
    docker: {...alpha.docker, running: 1, total: 2},
    lucky: {...alpha.lucky, status: 'not_configured'}
  };
  const neverSeen = {
    ...alpha,
    device_id: 'device-gamma',
    display_name: 'Gamma',
    name: 'gamma-host',
    status: 'never_seen',
    hardware: {},
    docker: {},
    hermes: {},
    lucky: {}
  };
  const disabled = {
    ...alpha,
    device_id: 'device-disabled',
    display_name: 'Disabled',
    status: 'disabled'
  };
  const multi = {
    schema_version: 2,
    default_device_id: 'device-beta',
    servers: [alpha, beta, neverSeen, disabled]
  };
  const frozenFour = multiDeviceFixture('stats-v2-four');
  assert.equal(
    app.resolveDeviceSelection(frozenFour, null, null).selectedDeviceId,
    'device-beta'
  );
  assert.deepEqual(
    app.selectableDevices(frozenFour).map(device => device.device_id),
    ['device-beta', 'device-gamma', 'device-alpha']
  );
  assert.equal(
    app.dashboardCondition(app.buildViewModel(frozenFour, 'device-beta')).kind,
    'never-seen'
  );
  assert.deepEqual(
    app.selectableDevices(multi).map(device => device.device_id),
    ['device-alpha', 'device-beta', 'device-gamma']
  );
  assert.equal(app.resolveDeviceSelection(multi, 'device-alpha', 'device-gamma').selectedDeviceId, 'device-alpha');
  assert.equal(app.resolveDeviceSelection(multi, null, 'device-gamma').selectedDeviceId, 'device-gamma');
  assert.equal(app.resolveDeviceSelection(multi, null, null).selectedDeviceId, 'device-beta');
  const recovered = app.resolveDeviceSelection(multi, null, 'removed-device');
  assert.equal(recovered.selectedDeviceId, 'device-beta');
  assert.equal(recovered.recovered, true);
  const betaView = app.buildViewModel(multi, 'device-beta');
  assert.equal(betaView.host.name, 'beta-host');
  assert.equal(betaView.resources.cpuPercent, 77);
  assert.equal(betaView.docker.running, 1);
  assert.equal(betaView.lucky.status, 'not_configured');
  assert.equal(app.dashboardCondition(betaView).kind, 'offline');
  assert.equal(app.dashboardCondition(app.buildViewModel(multi, 'device-gamma')).kind, 'never-seen');
  assert.equal(app.buildViewModel(multi, 'device-disabled').host, null);

  const stored = new Map();
  const storage = {
    getItem: key => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, value),
    removeItem: key => stored.delete(key)
  };
  app.writeStoredDeviceId(storage, 'device-beta');
  assert.equal(app.readStoredDeviceId(storage), 'device-beta');
  app.writeStoredDeviceId(storage, '<script>');
  assert.equal(app.readStoredDeviceId(storage), null);
  assert.equal(stored.has(app.DEVICE_STORAGE_KEY), false);
  const hostile = {
    servers: [{
      ...alpha,
      device_id: '<img-src=x>',
      display_name: '<script>throw 1</script>'
    }]
  };
  assert.deepEqual(app.selectableDevices(hostile), []);
  assert.equal(app.deviceDisplayName({display_name: '界'.repeat(200)}).length, 128);
  assert.deepEqual(app.selectableDevices({
    servers: [alpha, {...alpha}]
  }), []);
  assert.deepEqual(app.normalizeStatsPayload({
    servers: Array.from({length: app.MAX_UI_DEVICES + 1}, (_, index) => ({
      ...alpha,
      device_id: `device-${index}`
    }))
  }).servers, []);
  assert.equal(
    app.deviceDisplayName({
      device_id: 'device-alpha',
      display_name: 'Registry Name',
      name: 'Reported Name',
      reported_name: 'Untrusted Name',
      hostname: 'untrusted-host',
      reported_fqdn: 'untrusted.example.invalid'
    }),
    'Registry Name'
  );
  const sixteen = multiDeviceFixture('stats-v2-sixteen');
  assert.equal(app.selectableDevices(sixteen).length, app.MAX_UI_DEVICES);
  assert.equal(
    app.selectableDevices(sixteen).map(app.deviceDisplayName).join('|'),
    sixteen.servers.map(server => server.display_name).join('|')
  );
  const hostileError = '<img src=x onerror=throw(1)>';
  assert.equal(
    app.dashboardCondition(normal, new Error(hostileError)).message,
    hostileError
  );

  assert.equal(app.usageBand(0), 'low');
  assert.equal(app.usageBand(60), 'low');
  assert.equal(app.usageBand(60.01), 'medium');
  assert.equal(app.usageBand(80), 'medium');
  assert.equal(app.usageBand(80.01), 'high');
  assert.equal(app.usageBand(null), 'unknown');
  assert.equal(
    app.cleanCpuModel('Intel(R) Pentium(R) Silver N5030 CPU @ 1.10GHz'),
    'Intel Pentium Silver N5030'
  );
  assert.equal(
    app.cleanCpuModel('Intel(R) Atom(TM) CPU C3538 @ 2.10GHz'),
    'Intel Atom CPU C3538'
  );
  assert.equal(app.cleanCpuModel('Intel Celeron J4125'), 'Intel Celeron J4125');
  assert.equal(app.cleanCpuModel('Example(TM) Processor'), 'Example Processor');

  assert.equal(app.dashboardCondition(normal).kind, 'ready');
  assert.equal(app.dashboardCondition(app.buildViewModel({servers: []})).kind, 'empty');
  assert.equal(app.dashboardCondition(app.buildViewModel(statsDocument('normal', {online4: false, online6: false}))).kind, 'ready');
  assert.equal(app.dashboardCondition(app.buildViewModel({servers: [{name: 'legacy-offline', online4: false, online6: false}]})).kind, 'offline');
  assert.equal(app.dashboardCondition(degraded).kind, 'error');
  assert.equal(app.dashboardCondition(empty).kind, 'stale');
  const staleDocument = statsDocument('normal');
  staleDocument.servers[0].hardware.stale = true;
  assert.equal(app.dashboardCondition(app.buildViewModel(staleDocument)).kind, 'stale');
  assert.equal(app.dashboardCondition(app.buildViewModel({servers: [{name: 'native-only', online4: true, online6: false}]})).kind, 'unknown');
  assert.equal(app.dashboardCondition(normal, new Error('offline')).kind, 'error');

  let visibleDocument = { marker: 'old' };
  let errorCount = 0;
  let busyTransitions = [];
  const failedController = app.createRefreshController({
    fetchStats: async () => { throw new Error('offline'); },
    onSuccess: documentValue => { visibleDocument = documentValue; },
    onError: () => { errorCount += 1; },
    onBusy: busy => { busyTransitions.push(busy); }
  });
  assert.equal(await failedController.refresh('manual'), false);
  assert.deepEqual(visibleDocument, { marker: 'old' });
  assert.equal(errorCount, 1);
  assert.deepEqual(busyTransitions, [true, false]);

  const scheduled = [];
  const cleared = [];
  const reasons = [];
  let timerId = 0;
  const controller = app.createRefreshController({
    fetchStats: async reason => { reasons.push(reason); return { ok: true }; },
    setIntervalFn: (callback, delay) => {
      const id = ++timerId;
      scheduled.push({ id, callback, delay });
      return id;
    },
    clearIntervalFn: id => cleared.push(id)
  });
  controller.start();
  controller.start();
  assert.equal(scheduled[0].delay, 600000);
  assert.equal(scheduled[1].delay, app.REFRESH_INTERVAL_MS);
  assert.deepEqual(cleared, [1]);
  assert.equal(await controller.refresh('manual'), true);
  await scheduled[1].callback();
  assert.deepEqual(reasons, ['manual', 'auto']);
  controller.stop();
  assert.deepEqual(cleared, [1, 2]);

  let releaseFetch;
  const pendingController = app.createRefreshController({
    fetchStats: () => new Promise(resolve => { releaseFetch = resolve; })
  });
  const firstRefresh = pendingController.refresh('manual');
  assert.equal(await pendingController.refresh('manual'), false);
  releaseFetch({ ok: true });
  assert.equal(await firstRefresh, true);

  assert.match(app.statsUrl(), /^\/json\/stats\.json\?_=/);
  assert.equal(app.fittedFontSize(23, 11, 240, 200), 23);
  assert.equal(app.fittedFontSize(23, 11, 240, 480), 11.5);
  assert.equal(app.fittedFontSize(23, 11, 240, 2400), 11);
  assert.equal(app.approximateDays(12000), 500);
  assert.equal(app.approximateDays(null), null);

  const frontendSource = [
    fs.readFileSync(path.join(ROOT, 'web/index.html'), 'utf8'),
    fs.readFileSync(path.join(ROOT, 'web/js/app.js'), 'utf8')
  ].join('\n');
  assert.doesNotMatch(frontendSource, /Bearer|ADMIN_TOKEN|Authorization\s*[:=]|api[_ -]?key\s*[:=]/i);

  const css = fs.readFileSync(path.join(ROOT, 'web/css/app.css'), 'utf8');
  assert.match(css, /overflow-x:hidden/);
  assert.match(css, /overflow-x:auto/);
  assert.match(css, /max-height:calc\(100dvh - 2rem\)/);
  assert.match(css, /\.resource-value\{[^}]*height:27px;min-height:27px/);
  assert.match(css, /@media \(max-width:1180px\)/);
  assert.match(css, /@media \(max-width:720px\)/);
  assert.match(css, /\.detail-list\.unifi-summary\{grid-template-columns:repeat\(3,minmax\(0,1fr\)\)\}/);
  assert.match(css, /\.unifi-system-cards\{grid-template-columns:repeat\(5,minmax\(0,1fr\)\)/);
  assert.match(css, /\.unifi-storage-table\{min-width:940px!important;table-layout:auto\}/);
  assert.match(css, /@media \(max-width:720px\)[\s\S]*\.unifi-system-cards\{grid-template-columns:1fr\}/);
  assert.match(css, /@media \(max-width:720px\)[\s\S]*\.detail-list\.unifi-summary\{grid-template-columns:1fr\}/);
  assert.match(css, /\.device-buttons\{[^}]*overflow-x:auto/);
  assert.match(css, /\.nav\{[^}]*overflow-x:auto/);
  assert.match(css, /@media \(max-width:720px\)\{[\s\S]*\.device-buttons\{display:none\}/);
  assert.match(css, /@media \(max-width:720px\)\{[\s\S]*\.device-select-label\{display:block\}/);

  assert.match(indexMarkup, /id="refreshButton"/);
  assert.match(indexMarkup, /id="deviceSelector"/);
  assert.match(indexMarkup, /id="deviceButtons"/);
  assert.match(indexMarkup, /id="deviceSelect"/);
  assert.match(indexMarkup, /id="deviceSelectionNotice"[^>]*aria-live="polite"/);
  assert.match(indexMarkup, /id="deviceDiagnosticsButton"[^>]*aria-haspopup="dialog"/);
  assert.match(indexMarkup, /id="deviceDiagnosticsModal"[^>]*hidden/);
  assert.match(indexMarkup, /id="aboutButton"[^>]*aria-haspopup="dialog"/);
  assert.match(indexMarkup, /id="aboutModal"[^>]*hidden/);
  assert.match(indexMarkup, /id="homeTab"[^>]*>主页<\/button>/);
  assert.match(indexMarkup, /id="hardwareTab"[^>]*>硬件信息<\/button>/);
  assert.match(indexMarkup, /id="dockerTab"[^>]*>Docker<\/button>/);
  assert.match(indexMarkup, /id="luckyTab"[^>]*>Lucky<\/button>/);
  assert.match(indexMarkup, /id="unifiTab"[^>]*>UniFi<\/button>/);
  assert.ok(
    indexMarkup.indexOf('id="hardwareTab"') < indexMarkup.indexOf('id="unifiTab"')
      && indexMarkup.indexOf('id="unifiTab"') < indexMarkup.indexOf('id="dockerTab"'),
    'UniFi tab must remain between hardware and Docker'
  );
  assert.match(indexMarkup, /id="unifiPage"[^>]*data-page="unifi"[^>]*hidden/);
  assert.match(indexMarkup, /id="luckyServiceSummary"/);
  assert.match(appSource, /\['API 可用性', service\.api_reachable/);
  assert.doesNotMatch(indexMarkup, /data-page-target="[^"]+"[^>]*>主机<\/button>/);
  assert.match(indexMarkup, /id="unifiSummary"/);
  assert.match(indexMarkup, /id="unifiSystem"/);
  assert.match(indexMarkup, /id="unifiFansBody"/);
  assert.match(indexMarkup, /id="unifiPowerBody"/);
  assert.match(indexMarkup, /id="unifiStorage"/);
  assert.ok(
    indexMarkup.indexOf('id="unifiSystem"') < indexMarkup.indexOf('unifiSummaryTitle')
      && indexMarkup.indexOf('unifiSummaryTitle') < indexMarkup.indexOf('unifiStorageTitle')
      && indexMarkup.indexOf('unifiStorageTitle') < indexMarkup.indexOf('unifiFansTitle')
      && indexMarkup.indexOf('unifiFansTitle') < indexMarkup.indexOf('unifiPowerTitle')
  );
  assert.doesNotMatch(indexMarkup, /<h2[^>]*>通用遥测<\/h2>/);
  assert.match(indexMarkup, /<th>转速<\/th>/);
  assert.match(indexMarkup, /<th>功率<\/th>/);
  assert.match(indexMarkup, /<th>风扇转速<\/th>/);
  assert.match(indexMarkup, /未安装时容量与使用情况显示为 -/);
  assert.match(indexMarkup, /观测=本轮是否取得转速读数/);
  assert.doesNotMatch(indexMarkup, /raw thermal|PWM|cpuload|remote command/i);
  assert.match(appSource, /function renderUniFi\(view\)/);
  assert.match(appSource, /function unifiTransportSummary\(unifi\)/);
  assert.match(appSource, /observed_zero_rpm/);
  assert.match(indexMarkup, /id="homePage"[^>]*data-page="home"/);
  assert.match(indexMarkup, /id="hardwarePage"[^>]*data-page="hardware"[^>]*hidden/);
  assert.match(indexMarkup, /id="dockerPage"[^>]*data-page="docker"[^>]*hidden/);
  assert.match(indexMarkup, /id="luckyPage"[^>]*data-page="lucky"[^>]*hidden/);
  assert.doesNotMatch(indexMarkup, /id="dockerSummary"/);
  const homeMarkup = indexMarkup.slice(indexMarkup.indexOf('id="homePage"'), indexMarkup.indexOf('id="hardwarePage"'));
  const hardwareMarkup = indexMarkup.slice(indexMarkup.indexOf('id="hardwarePage"'), indexMarkup.indexOf('id="dockerPage"'));
  const dockerMarkup = indexMarkup.slice(indexMarkup.indexOf('id="dockerPage"'), indexMarkup.indexOf('id="luckyPage"'));
  const luckyMarkup = indexMarkup.slice(indexMarkup.indexOf('id="luckyPage"'), indexMarkup.indexOf('id="profileModal"'));
  assert.match(homeMarkup, /id="overviewCards"/);
  assert.match(homeMarkup, /id="profilesBody"/);
  assert.doesNotMatch(homeMarkup, /id="containersBody"/);
  assert.match(hardwareMarkup, /id="hardwareSystemInfo"/);
  assert.match(hardwareMarkup, /id="hardwareCpuInfo"/);
  assert.doesNotMatch(hardwareMarkup, /hardwareCpuInstructionSets/);
  assert.match(hardwareMarkup, /id="hardwareCpuUsage"/);
  assert.match(hardwareMarkup, /class="hardware-cpu-columns"/);
  assert.match(hardwareMarkup, /class="hardware-cpu-column"/);
  assert.match(hardwareMarkup, /id="hardwareMemoryInfo"/);
  assert.doesNotMatch(hardwareMarkup, /hardwareMemoryPrimary|hardwareMemorySecondary|hardwareMemoryTertiary/);
  assert.match(hardwareMarkup, /id="hardwareFilesystemsBody"/);
  assert.match(hardwareMarkup, /卷 \/ 文件系统/);
  assert.match(indexMarkup, /css\/app\.css\?v=20260828-1/);
  assert.match(indexMarkup, /js\/app\.js\?v=20260828-1/);
  assert.match(hardwareMarkup, /id="hardwareDisksBody"/);
  assert.deepEqual(
    [...hardwareMarkup.matchAll(/<th>([^<]+)<\/th>/g)].map(match => match[1]),
    ['设备', '型号', '容量', '温度', 'SMART', '通电时间', '挂载点', '来源', '格式', '关联物理磁盘', '已用 / 总容量', '使用率', '采集状态']
  );
  assert.match(dockerMarkup, /id="containersBody"/);
  assert.deepEqual(
    [...dockerMarkup.matchAll(/<th>([^<]+)<\/th>/g)]
      .map(match => match[1])
      .slice(-4),
    ['容器名称', '镜像', '状态', '端口']
  );
  assert.doesNotMatch(luckyMarkup, /id="luckyOverview"/);
  assert.match(luckyMarkup, /id="luckyConfigBody"/);
  assert.doesNotMatch(luckyMarkup, /id="luckyDDNSBody"/);
  assert.doesNotMatch(luckyMarkup, /id="luckyNetworkBody"/);
  assert.doesNotMatch(luckyMarkup, /id="luckyWebBody"/);
  assert.doesNotMatch(luckyMarkup, /id="luckyForwardBody"/);
  assert.match(luckyMarkup, /id="luckyCertificateBody"/);
  assert.deepEqual(
    [...luckyMarkup.matchAll(/<th(?: [^>]*)?>([^<]+)<\/th>/g)].map(match => match[1]).slice(0, 10),
    ['DDNS服务商', '地址获取方式', '本地记录状态', '最近同步时间/下次同步时间', '已更新/总域名记录', 'Web服务', '已启用/端口转发总和', '监听端口', '连接数', '已启用/规则总和']
  );
  assert.doesNotMatch(luckyMarkup, /id="luckyConfigMeta"/);
  assert.doesNotMatch(appSource, /接口 \/ Web/);
  assert.match(appSource, /refresh\('initial'\)/);
  assert.match(appSource, /setActivePage\(tab\.dataset\.pageTarget\)/);
  assert.match(appSource, /parseDashboardHash\(window\.location\.hash\)/);
  assert.match(appSource, /\['home', 'hardware', 'unifi', 'docker', 'lucky', 'easytier'\]/);
  const homeHardwareSource = appSource.slice(appSource.indexOf('function renderHardware'), appSource.indexOf('function filesystemBackingDisks'));
  assert.deepEqual(
    [...homeHardwareSource.matchAll(/<h2>([^<]+)<\/h2>/g)].map(match => match[1]),
    ['硬盘 SMART 状态', '硬盘写入/读取量', '硬盘通电时间', 'CPU温度', '硬盘温度', '运行中/容器总数', 'Lucky运行状态/版本', 'EasyTier运行状态/版本', '系统已运行时间', '操作系统版本']
  );
  assert.match(homeHardwareSource, /smartHomeMarkup\(physicalDisks, hardware\)/);
  assert.match(homeHardwareSource, /maxDiskBy\(physicalDisks, diskTemperatureC\)/);
  assert.match(homeHardwareSource, /maximumTemperature\(temperatureSensorEntries\(hardware\)\)/);
  assert.match(appSource, /function deviceDiagnosticsMarkup\(view\)/);
  assert.match(appSource, /function buildProvenanceMarkup\(view\)/);
  assert.match(appSource, /function cpuDetailsForView\(hardware\)/);
  assert.match(appSource, /function cpuLogicalProcessorText\(cpu\)/);
  assert.match(css, /\.hardware-cpu-columns\{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(css, /\.hardware-cpu-info\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)\}/);
  assert.match(css, /\.hardware-cpu-info \.hardware-cpu-instruction-row\{grid-column:1\/-1\}/);
  assert.match(css, /#hardwareCpuUsage\.hardware-cpu-usage-grid\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)\}/);
  assert.match(css, /\.hardware-usage-item\{display:grid;grid-template-columns:minmax\(0,auto\) minmax\(96px,1fr\)/);
  assert.match(css, /\.hardware-memory-grid\{display:grid;grid-template-columns:minmax\(460px,1\.6fr\) minmax\(260px,1fr\) minmax\(220px,\.9fr\)/);
  assert.match(css, /\.hardware-memory-grid \.detail-row dt,\.hardware-memory-grid \.detail-row dd\{white-space:nowrap\}/);
  assert.match(css, /\.detail-list\.hardware-three-column-info\{grid-template-columns:repeat\(3,minmax\(0,1fr\)\)\}/);
  assert.match(css, /@media \(max-width:720px\)\{[\s\S]*\.detail-list\.hardware-three-column-info\{grid-template-columns:1fr\}/);
  assert.match(appSource, /\['物理内存已用 \/ 可用 \/ 总量'/);
  assert.match(appSource, /\['Swap 内存已用 \/ 可用 \/ 总量'/);
  const memorySource = appSource.slice(appSource.indexOf('const memoryRows'), appSource.indexOf('const memoryPlaceholders'));
  assert.deepEqual(
    [...memorySource.matchAll(/\['([^']+)'/g)].map(match => match[1]),
    ['物理内存已用 / 可用 / 总量', '活动 / 非活动', '可回收 Slab', 'Swap 内存已用 / 可用 / 总量', 'Buffers', 'Slab', '空闲内存', '页面缓存', 'Swap Cache', 'Dirty / Writeback']
  );
  assert.match(appSource, /const memoryPlaceholders = Array\.from\(\{length: Math\.max\(0, 12 - memoryRows\.length\)/);
  assert.match(appSource, /\['频率（最低 \/ 最高）'/);
  assert.match(appSource, /\['当前频率', formatMHz\(cpu\.current_mhz\)\]/);
  assert.match(appSource, /function cpuInstructionDetailRow\(value\)/);
  assert.match(appSource, /hardware-cpu-instruction-row/);
  assert.doesNotMatch(appSource, /\['步进', textOrDash\(cpu\.stepping\)\]/);
  assert.doesNotMatch(appSource, /\['虚拟化', textOrDash\(cpu\.virtualization\)\]/);
  assert.doesNotMatch(appSource, /\['空闲', cpuUsage\.idle_percent\]/);
  assert.doesNotMatch(appSource, /\['Nice', cpuUsage\.nice_percent\]/);
  assert.doesNotMatch(appSource, /\['Steal', cpuUsage\.steal_percent\]/);
  assert.doesNotMatch(appSource, /\['中断 IRQ', cpuUsage\.irq_percent\]/);
  assert.doesNotMatch(appSource, /\['软中断 SoftIRQ', cpuUsage\.softirq_percent\]/);
  assert.doesNotMatch(appSource, /发行版.*distribution|发行版本.*release/);
  assert.match(appSource, /I\/O 等待/);
  assert.match(appSource, /function renderPhysicalDiskRows\(hardware\)/);
  assert.match(appSource, /function renderFilesystemDetails\(hardware\)/);
  assert.doesNotMatch(appSource, /function partitionRowsForDisk\(disk, filesystems\)|function filesystemBelongsToDisk\(filesystem, disk\)/);
  assert.match(appSource, /function diskSmartMarkup\(disk\)/);
  assert.match(appSource, /属性检查/);
  assert.doesNotMatch(
    appSource.slice(appSource.indexOf('function deviceDiagnosticsMarkup'), appSource.indexOf('function buildProvenanceMarkup')),
    /source_ip|fqdn|token|digest|credential|Authorization/i
  );
  assert.match(appSource, /if\(!byId\('deviceDiagnosticsModal'\)\.hidden\) closeDeviceDiagnostics\(\)/);
  assert.match(appSource, /else if\(!byId\('aboutModal'\)\.hidden\) closeAbout\(\)/);
  assert.doesNotMatch(appSource, /renderDockerSummary|renderLuckyOverview/);
  const pageSwitchSource = appSource.slice(appSource.indexOf('function setActivePage'), appSource.indexOf('function detailRow'));
  assert.doesNotMatch(pageSwitchSource, /fetchStats|controller\.refresh|setInterval/);
  assert.doesNotMatch(appSource, /WebSocket|EventSource|\/api\/|\/testdata\//);
  assert.equal((appSource.match(/\/json\/stats\.json/g) || []).length, 1);
  assert.equal((appSource.match(/setIntervalImplementation\(/g) || []).length, 1);
  assert.equal((appSource.match(/fetchStats\(\)/g) || []).length, 1);
  assert.equal((appSource.match(/currentStats:/g) || []).length, 1);
  assert.doesNotMatch(appSource, /lastDocument/);
  const selectorSource = appSource.slice(
    appSource.indexOf('function renderDeviceSelector'),
    appSource.indexOf('function renderDashboard')
  );
  assert.match(selectorSource, /\.textContent = label/);
  assert.match(selectorSource, /option\.textContent/);
  assert.doesNotMatch(selectorSource, /\.innerHTML/);
  const pageStateSource = appSource.slice(
    appSource.indexOf('function setPageState'),
    appSource.indexOf('function resourceBar')
  );
  assert.match(pageStateSource, /pageStateMessage'\)\.textContent = state\.message/);
  assert.doesNotMatch(pageStateSource, /\.innerHTML/);
  const deviceSwitchSource = appSource.slice(
    appSource.indexOf('function selectDevice'),
    appSource.indexOf('function applyPageVisibility')
  );
  assert.doesNotMatch(deviceSwitchSource, /fetchStats|controller\.refresh|setInterval/);
  assert.match(appSource, /event\.key === 'Escape'/);
  assert.match(appSource, /event\.target === byId\('profileModal'\)/);

  console.log('HermesStatus dashboard tests passed');
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
