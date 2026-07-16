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

function statsDocument(name, overrides = {}){
  const extension = fixture(name);
  return {
    updated: Math.floor(new Date(extension.received_at).getTime() / 1000),
    servers: [{
      name: 'fixture-host', disabled: false, online4: true, online6: false,
      cpu: 10, memory_used: 7 * 1024 * 1024, memory_total: 10 * 1024 * 1024,
      hdd_used: 90 * 1024, hdd_total: 100 * 1024, uptime: '12 天 3 小时',
      os: 'Example Linux 2.0', hardware: extension.hardware, docker: extension.docker,
      hermes: extension.hermes, ...overrides
    }]
  };
}

async function run(){
  const normal = app.buildViewModel(statsDocument('normal'));
  assert.equal(normal.host.name, 'fixture-host');
  assert.equal(normal.profiles.length, 2);
  assert.equal(normal.containers.length, 3);
  assert.equal(app.usageBand(normal.resources.cpuPercent), 'low');
  assert.equal(app.usageBand(normal.resources.memoryPercent), 'medium');
  assert.equal(app.usageBand(normal.resources.diskPercent), 'high');

  const empty = app.buildViewModel(statsDocument('empty'));
  assert.equal(empty.profiles.length, 0);
  assert.equal(empty.containers.length, 0);
  assert.equal(empty.hardware.cpu_temperature, null);

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

  assert.match(indexMarkup, /id="refreshButton"/);
  assert.deepEqual(
    [...indexMarkup.matchAll(/<th>([^<]+)<\/th>/g)]
      .map(match => match[1])
      .slice(-4),
    ['容器名称', '镜像', '状态', '端口']
  );
  assert.match(appSource, /refresh\('initial'\)/);
  assert.doesNotMatch(appSource, /WebSocket|EventSource|\/api\/|\/testdata\//);
  assert.equal((appSource.match(/\/json\/stats\.json/g) || []).length, 1);
  assert.equal((appSource.match(/setIntervalImplementation\(/g) || []).length, 1);
  assert.match(appSource, /event\.key === 'Escape'/);
  assert.match(appSource, /event\.target === byId\('profileModal'\)/);

  console.log('HermesStatus dashboard tests passed');
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
