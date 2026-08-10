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
  assert.equal(app.normalizePageName('docker'), 'docker');
  assert.equal(app.normalizePageName('lucky'), 'lucky');
  assert.equal(app.normalizePageName('unexpected'), 'home');
  assert.equal(app.pageFromHash(''), 'home');
  assert.equal(app.pageFromHash('#home'), 'home');
  assert.equal(app.pageFromHash('#docker'), 'docker');
  assert.equal(app.pageFromHash('#lucky'), 'lucky');
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
  assert.match(appSource, /<h2>运行中\/容器总数<\/h2>/);
  assert.match(appSource, /<h2>Lucky运行状态\/版本<\/h2>/);
  assert.match(appSource, /EasyTier远端节点数/);
  assert.match(appSource, /EasyTier接收\/发送\/转发流量/);
  assert.doesNotMatch(appSource, /CPU温度\/硬盘温度/);
  assert.doesNotMatch(appSource, /已运行时间\/操作系统/);
  assert.match(indexMarkup, /<h2 id="easytierCommandsTitle">采集状态<\/h2>/);
  assert.doesNotMatch(indexMarkup, /<th>说明<\/th>/);
  assert.equal(app.formatUptimeHours(90061), '25 h (约1.04天)');
  assert.equal(
    app.modelBreakdown({model: 'example-model', usage_mode: 'api', provider: 'OpenCode Go'}),
    'example-model / api / OpenCode Go'
  );

  const empty = app.buildViewModel(statsDocument('empty'));
  assert.equal(empty.profiles.length, 0);
  assert.equal(empty.containers.length, 0);
  assert.equal(empty.hardware.cpu_temperature, null);
  assert.equal(app.luckyIsConfigured(empty.lucky), false);

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
  assert.equal(app.cleanCpuModel('Intel Celeron J4125'), 'Intel Celeron J4125');
  assert.equal(app.cleanCpuModel('Example(TM) Processor'), 'Example Processor');

  assert.equal(app.dashboardCondition(normal).kind, 'ready');
  assert.equal(app.dashboardCondition(app.buildViewModel({servers: []})).kind, 'empty');
  assert.equal(app.dashboardCondition(app.buildViewModel(statsDocument('normal', {online4: false, online6: false}))).kind, 'offline');
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
  assert.doesNotMatch(frontendSource, /Bearer|ADMIN_TOKEN|Authorization|api[_ -]?key/i);

  const css = fs.readFileSync(path.join(ROOT, 'web/css/app.css'), 'utf8');
  assert.match(css, /overflow-x:hidden/);
  assert.match(css, /overflow-x:auto/);
  assert.match(css, /max-height:calc\(100dvh - 2rem\)/);
  assert.match(css, /\.resource-value\{[^}]*height:27px;min-height:27px/);
  assert.match(css, /@media \(max-width:1180px\)/);
  assert.match(css, /@media \(max-width:720px\)/);
  assert.match(css, /\.device-buttons\{[^}]*overflow-x:auto/);
  assert.match(css, /@media \(max-width:720px\)\{[\s\S]*\.device-buttons\{display:none\}/);
  assert.match(css, /@media \(max-width:720px\)\{[\s\S]*\.device-select-label\{display:block\}/);

  assert.match(indexMarkup, /id="refreshButton"/);
  assert.match(indexMarkup, /id="deviceSelector"/);
  assert.match(indexMarkup, /id="deviceButtons"/);
  assert.match(indexMarkup, /id="deviceSelect"/);
  assert.match(indexMarkup, /id="deviceSelectionNotice"[^>]*aria-live="polite"/);
  assert.match(indexMarkup, /id="homeTab"[^>]*>主页<\/button>/);
  assert.match(indexMarkup, /id="dockerTab"[^>]*>Docker<\/button>/);
  assert.match(indexMarkup, /id="luckyTab"[^>]*>Lucky<\/button>/);
  assert.doesNotMatch(indexMarkup, /data-page-target="[^"]+"[^>]*>主机<\/button>/);
  assert.match(indexMarkup, /id="homePage"[^>]*data-page="home"/);
  assert.match(indexMarkup, /id="dockerPage"[^>]*data-page="docker"[^>]*hidden/);
  assert.match(indexMarkup, /id="luckyPage"[^>]*data-page="lucky"[^>]*hidden/);
  assert.doesNotMatch(indexMarkup, /id="dockerSummary"/);
  const homeMarkup = indexMarkup.slice(indexMarkup.indexOf('id="homePage"'), indexMarkup.indexOf('id="dockerPage"'));
  const dockerMarkup = indexMarkup.slice(indexMarkup.indexOf('id="dockerPage"'), indexMarkup.indexOf('id="luckyPage"'));
  const luckyMarkup = indexMarkup.slice(indexMarkup.indexOf('id="luckyPage"'), indexMarkup.indexOf('id="profileModal"'));
  assert.match(homeMarkup, /id="overviewCards"/);
  assert.match(homeMarkup, /id="profilesBody"/);
  assert.doesNotMatch(homeMarkup, /id="containersBody"/);
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
