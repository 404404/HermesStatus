#!/usr/bin/env node

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const app = require('./app.js');
const ROOT = path.resolve(__dirname, '../..');

function fixture(name){
  return JSON.parse(fs.readFileSync(path.join(ROOT, `testdata/migration/stats-${name}.json`), 'utf8'));
}

async function run(){
  const normal = app.buildViewModel(fixture('normal'), true);
  assert.equal(normal.host.name, 'fixture-host');
  assert.equal(normal.profiles.length, 2);
  assert.equal(normal.containers.length, 3);
  assert.equal(app.usageBand(normal.resources.cpuPercent), 'low');
  assert.equal(app.usageBand(normal.resources.memoryPercent), 'medium');
  assert.equal(app.usageBand(normal.resources.diskPercent), 'high');

  const empty = app.buildViewModel(fixture('empty'), true);
  assert.equal(empty.profiles.length, 0);
  assert.equal(empty.containers.length, 0);
  assert.equal(empty.hardware.cpu_temperature, null);

  const degraded = app.buildViewModel(fixture('degraded'), true);
  assert.equal(app.collectWarnings(degraded).length, 3);
  assert.equal(degraded.hardware.disk_smart_status, 'unknown');
  assert.deepEqual(degraded.profiles.map(profile => profile.api_status), ['unauthorized', 'timeout']);

  const longValues = app.buildViewModel(fixture('long-values'), true);
  assert.ok(longValues.profiles[0].model.length > 180);
  assert.ok(longValues.containers[0].command.length > 350);
  assert.ok(longValues.containers[0].image.length > 160);

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

  assert.equal(app.fixtureNameFromLocation({ hostname: '127.0.0.1', search: '?fixture=normal' }), 'normal');
  assert.equal(app.fixtureNameFromLocation({ hostname: 'example.invalid', search: '?fixture=normal' }), null);
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

  console.log('HermesStatus dashboard tests passed');
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
