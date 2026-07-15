const REFRESH_INTERVAL_MS = 10 * 60 * 1000;
const FIXTURE_NAMES = new Set(['normal', 'empty', 'degraded', 'long-values']);

const dashboardState = {
  controller: null,
  fixtureName: null,
  lastDocument: null,
  view: null,
  lastSuccessAt: null,
  selectedProfileIndex: null,
  modalTrigger: null,
  pagehideHandler: null,
  resizeHandler: null,
  resizeFrame: null
};

const byId = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[character]));

function finiteNumber(value){
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function clamp(value, minimum, maximum){
  return Math.max(minimum, Math.min(maximum, value));
}

function textOrDash(value){
  return value === null || value === undefined || value === '' ? '-' : String(value);
}

function formatInteger(value){
  const number = finiteNumber(value);
  return number === null ? '-' : Math.round(number).toLocaleString('zh-CN');
}

function approximateDays(hours){
  const number = finiteNumber(hours);
  return number === null || number < 0 ? null : Math.floor(number / 24);
}

function formatBytes(value){
  const number = finiteNumber(value);
  if(number === null || number < 0) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let size = number;
  let unit = 0;
  while(size >= 1000 && unit < units.length - 1){
    size /= 1000;
    unit += 1;
  }
  const digits = size >= 100 ? 0 : size >= 10 ? 1 : 2;
  return `${size.toFixed(digits)} ${units[unit]}`;
}

function percentage(used, total){
  const usedNumber = finiteNumber(used);
  const totalNumber = finiteNumber(total);
  if(usedNumber === null || totalNumber === null || totalNumber <= 0) return null;
  return clamp(usedNumber / totalNumber * 100, 0, 100);
}

function usageBand(value){
  const number = finiteNumber(value);
  if(number === null) return 'unknown';
  if(number <= 60) return 'low';
  if(number <= 80) return 'medium';
  return 'high';
}

function formatPercentage(value){
  const number = finiteNumber(value);
  return number === null ? '-' : `${Math.round(clamp(number, 0, 100))}%`;
}

function cleanCpuModel(value){
  const model = textOrDash(value);
  if(model === '-') return model;
  return model
    .replace(/\((?:R|TM|C)\)/gi, '')
    .replace(/\s+CPU\s*@\s*[\d.]+\s*(?:[GMK]?Hz)?\s*$/i, '')
    .replace(/\s+/g, ' ')
    .trim() || '-';
}

function formatTemperature(value){
  const number = finiteNumber(value);
  if(number === null) return '-';
  return `${Number.isInteger(number) ? number : number.toFixed(1)} °C`;
}

function formatDiskTemperature(temperature){
  if(!temperature || typeof temperature !== 'object') return '-';
  const values = [temperature.current, temperature.highest, temperature.lowest].map(value => {
    const number = finiteNumber(value);
    return number === null ? '-' : Number.isInteger(number) ? String(number) : number.toFixed(1);
  });
  if(values.every(value => value === '-')) return '-';
  return `${values.join(' / ')} °C`;
}

function formatUptime(value){
  if(typeof value === 'string' && value.trim()) return value.trim();
  const seconds = finiteNumber(value);
  if(seconds === null || seconds < 0) return '-';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds % 86400 / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  return `${days} 天 ${hours} 小时 ${minutes} 分`;
}

function formatDateTime(value){
  if(!value) return '-';
  const date = value instanceof Date ? value : new Date(value);
  if(Number.isNaN(date.getTime())) return '-';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  }).format(date).replaceAll('/', '-');
}

function formatPair(active, total){
  const left = finiteNumber(active);
  const right = finiteNumber(total);
  if(left === null && right === null) return '-';
  return `${left === null ? '-' : formatInteger(left)} / ${right === null ? '-' : formatInteger(right)}`;
}

function tokenBreakdown(usage){
  if(!usage || typeof usage !== 'object') return '- / - / -';
  return [usage.input_tokens, usage.output_tokens, usage.total_tokens]
    .map(value => finiteNumber(value) === null ? '-' : formatInteger(value))
    .join(' / ');
}

function modelBreakdown(profile){
  return [profile?.model, profile?.usage_mode, profile?.provider].map(textOrDash).join(' / ');
}

function selectSingleHost(servers){
  if(!Array.isArray(servers) || servers.length === 0) return null;
  return servers.find(server => server && server.disabled !== true) || servers[0] || null;
}

function fixtureHost(extension){
  const memoryTotal = 8 * 1024 * 1024;
  const diskTotal = 128 * 1024;
  return {
    name: 'fixture-host',
    disabled: false,
    online4: true,
    online6: false,
    cpu: 10,
    cpu_model: extension?.hardware?.cpu_model,
    memory_used: memoryTotal * 0.7,
    memory_total: memoryTotal,
    hdd_used: diskTotal * 0.9,
    hdd_total: diskTotal,
    uptime: '12 天 3 小时',
    os: 'Example Linux 2.0',
    hardware: extension?.hardware,
    docker: extension?.docker,
    hermes: extension?.hermes
  };
}

function normalizeStatsPayload(documentValue, fixtureMode = false){
  const documentObject = documentValue && typeof documentValue === 'object' ? documentValue : {};
  if(Array.isArray(documentObject.servers)) return documentObject;
  if(fixtureMode && (documentObject.hardware || documentObject.docker || documentObject.hermes)){
    return {
      updated: documentObject.received_at ? Math.floor(new Date(documentObject.received_at).getTime() / 1000) : 0,
      servers: [fixtureHost(documentObject)]
    };
  }
  return { ...documentObject, servers: [] };
}

function safeObject(value){
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function buildViewModel(documentValue, fixtureMode = false){
  const documentObject = normalizeStatsPayload(documentValue, fixtureMode);
  const host = selectSingleHost(documentObject.servers);
  if(!host) return { host: null, document: documentObject, hardware: {}, docker: {}, hermes: {}, profiles: [], containers: [] };

  const hardware = safeObject(host.hardware);
  const docker = safeObject(host.docker);
  const hermes = safeObject(host.hermes);
  const memoryPercent = percentage(host.memory_used, host.memory_total);
  const diskPercent = percentage(host.hdd_used, host.hdd_total);
  const cpuPercent = finiteNumber(host.cpu) === null ? null : clamp(host.cpu, 0, 100);

  return {
    document: documentObject,
    host,
    hardware,
    docker,
    hermes,
    profiles: Array.isArray(hermes.profiles) ? hermes.profiles : [],
    containers: Array.isArray(docker.containers) ? docker.containers : [],
    resources: {
      cpuPercent,
      memoryPercent,
      diskPercent,
      cpuModel: cleanCpuModel(hardware.cpu_model ?? host.cpu_model),
      memoryText: finiteNumber(host.memory_used) === null || finiteNumber(host.memory_total) === null
        ? '-'
        : `${formatBytes(host.memory_used * 1000)} / ${formatBytes(host.memory_total * 1000)}`,
      diskText: finiteNumber(host.hdd_used) === null || finiteNumber(host.hdd_total) === null
        ? '-'
        : `${formatBytes(host.hdd_used * 1000 * 1000)} / ${formatBytes(host.hdd_total * 1000 * 1000)}`
    }
  };
}

function collectWarnings(view){
  if(!view.host) return [];
  return [view.hardware, view.docker, view.hermes]
    .map(domain => domain?.error)
    .filter(error => error && typeof error === 'object')
    .map(error => textOrDash(error.message || error.code))
    .filter(message => message !== '-');
}

function statusTone(value){
  const status = String(value ?? '').toLowerCase();
  if(['passed', 'running', 'ok', 'healthy', 'up', 'active'].includes(status)) return 'ok';
  if(['failed', 'down', 'stopped', 'unauthorized', 'timeout', 'dead', 'exited'].includes(status)) return 'err';
  return 'neutral';
}

function statusText(value){
  const status = String(value ?? '').toLowerCase();
  const labels = {
    passed: '通过', failed: '失败', unknown: '未知', unavailable: '不可用',
    running: '运行中', healthy: '正常', ok: '正常', active: '活动',
    stopped: '已停止', down: '离线', unauthorized: '未授权', timeout: '超时',
    exited: '已退出', dead: '异常'
  };
  return labels[status] || textOrDash(value);
}

function badge(value){
  return `<span class="badge ${statusTone(value)}">${escapeHtml(statusText(value))}</span>`;
}

function resourceBar(value, label){
  const number = finiteNumber(value);
  const width = number === null ? 0 : clamp(number, 0, 100);
  return `<div class="usage-bar" data-band="${usageBand(number)}" aria-label="${escapeHtml(label)} ${escapeHtml(formatPercentage(number))}">
    <i style="width:${width.toFixed(1)}%"></i><span>${escapeHtml(formatPercentage(number))}</span>
  </div>`;
}

function fittedFontSize(preferredSize, minimumSize, availableWidth, naturalWidth){
  if(availableWidth <= 0 || naturalWidth <= availableWidth) return preferredSize;
  return Math.max(minimumSize, Math.floor(preferredSize * availableWidth / naturalWidth * 10) / 10);
}

function fitCpuModelToSingleLine(){
  const element = document.querySelector('[data-fit-single-line="cpu-model"]');
  if(!element || element.clientWidth <= 0) return;
  const preferredSize = 23;
  const minimumSize = 11;
  element.style.fontSize = `${preferredSize}px`;
  if(element.scrollWidth <= element.clientWidth) return;
  let size = fittedFontSize(preferredSize, minimumSize, element.clientWidth, element.scrollWidth);
  element.style.fontSize = `${size}px`;
  while(size > minimumSize && element.scrollWidth > element.clientWidth){
    size = Math.max(minimumSize, size - 0.5);
    element.style.fontSize = `${size}px`;
  }
}

function renderOverview(view){
  const resources = view.resources;
  const dockerRunning = finiteNumber(view.docker.running);
  const dockerTotal = finiteNumber(view.docker.total);
  byId('overviewCards').innerHTML = `
    <article class="summary-card resource-card">
      <h2>CPU</h2>
      <div class="card-detail resource-value" data-fit-single-line="cpu-model" title="${escapeHtml(resources.cpuModel)}">${escapeHtml(resources.cpuModel)}</div>
      ${resourceBar(resources.cpuPercent, 'CPU 使用率')}
    </article>
    <article class="summary-card resource-card">
      <h2>内存</h2>
      <div class="card-detail resource-value">${escapeHtml(resources.memoryText)}</div>
      ${resourceBar(resources.memoryPercent, '内存使用率')}
    </article>
    <article class="summary-card resource-card">
      <h2>硬盘</h2>
      <div class="card-detail resource-value">${escapeHtml(resources.diskText)}</div>
      ${resourceBar(resources.diskPercent, '硬盘使用率')}
    </article>
    <article class="summary-card count-card">
      <h2>运行中/总容器数量</h2>
      <div class="card-value">${dockerRunning === null || dockerTotal === null ? '-' : `${formatInteger(dockerRunning)} / ${formatInteger(dockerTotal)}`}</div>
    </article>
    <article class="summary-card uptime-card">
      <h2>已运行时间</h2>
      <div class="card-value">${escapeHtml(formatUptime(view.host.uptime))}</div>
      <div class="card-detail system-detail" title="${escapeHtml(textOrDash(view.host.os))}">${escapeHtml(textOrDash(view.host.os))}</div>
    </article>`;
  requestAnimationFrame(fitCpuModelToSingleLine);
}

function renderHardware(view){
  const hardware = view.hardware;
  const smartStatus = hardware.disk_smart_status ?? 'unknown';
  const powerOnHours = finiteNumber(hardware.disk_power_on_hours);
  const powerOnDays = approximateDays(powerOnHours);
  const readWrite = finiteNumber(hardware.disk_written_bytes) === null && finiteNumber(hardware.disk_read_bytes) === null
    ? '-'
    : `${formatBytes(hardware.disk_written_bytes)} / ${formatBytes(hardware.disk_read_bytes)}`;
  byId('hardwareHealth').innerHTML = `
    <article class="health-card"><h2>CPU 温度</h2><div class="health-value">${escapeHtml(formatTemperature(hardware.cpu_temperature?.value))}</div></article>
    <article class="health-card"><h2>硬盘当前/最高/最低温度</h2><div class="health-value">${escapeHtml(formatDiskTemperature(hardware.disk_temperature))}</div></article>
    <article class="health-card"><h2>硬盘 SMART 状态</h2><div class="health-value">${badge(smartStatus)}</div></article>
    <article class="health-card"><h2>硬盘通电时间</h2><div class="health-value power-on-value">${powerOnHours === null ? '-' : `${formatInteger(powerOnHours)} h <span class="power-on-days">(约${formatInteger(powerOnDays)}天)</span>`}</div></article>
    <article class="health-card"><h2>硬盘写入/读取量</h2><div class="health-value">${escapeHtml(readWrite)}</div></article>`;
}

function renderProfiles(view){
  byId('profilesMeta').textContent = view.profiles.length ? `${view.profiles.length} 个配置` : '';
  byId('profilesBody').innerHTML = view.profiles.length ? view.profiles.map((profile, index) => `
    <tr class="profile-row" data-profile-index="${index}" tabindex="0" role="button" aria-label="查看 ${escapeHtml(textOrDash(profile.profile))} 详情">
      <td class="strong-cell">${escapeHtml(textOrDash(profile.profile))}</td>
      <td>${badge(profile.service_status)}</td>
      <td>${badge(profile.gateway_service)}</td>
      <td>${badge(profile.api_status)}</td>
      <td class="bounded-cell" title="${escapeHtml(textOrDash(profile.manager_mode))}">${escapeHtml(textOrDash(profile.manager_mode))}</td>
      <td class="wide-cell" title="${escapeHtml(modelBreakdown(profile))}">${escapeHtml(modelBreakdown(profile))}</td>
      <td>${escapeHtml(formatPair(profile.scheduled_jobs_active, profile.scheduled_jobs_total))}</td>
      <td>${escapeHtml(formatPair(profile.sessions_active, profile.sessions_total))}</td>
      <td class="token-cell">${escapeHtml(tokenBreakdown(profile.usage))}${profile.usage?.estimated ? '<span class="estimate-mark" title="估算值">估算</span>' : ''}</td>
    </tr>`).join('') : '<tr><td colspan="9" class="table-empty">暂无 Hermes Profile 数据</td></tr>';
}

function renderContainers(view){
  const running = finiteNumber(view.docker.running);
  const total = finiteNumber(view.docker.total);
  byId('containersMeta').textContent = running === null || total === null ? '' : `${formatInteger(running)} / ${formatInteger(total)} 运行中`;
  byId('containersBody').innerHTML = view.containers.length ? view.containers.map(container => `
    <tr>
      <td class="mono strong-cell">${escapeHtml(textOrDash(container.id))}</td>
      <td class="bounded-cell" title="${escapeHtml(textOrDash(container.names))}">${escapeHtml(textOrDash(container.names))}</td>
      <td>${badge(container.state)}</td>
      <td>${escapeHtml(textOrDash(container.created))}</td>
      <td class="wide-cell mono" title="${escapeHtml(textOrDash(container.image))}">${escapeHtml(textOrDash(container.image))}</td>
      <td class="command-cell mono" title="${escapeHtml(textOrDash(container.command))}">${escapeHtml(textOrDash(container.command))}</td>
      <td class="ports-cell mono" title="${escapeHtml(textOrDash(container.ports))}">${escapeHtml(textOrDash(container.ports))}</td>
    </tr>`).join('') : '<tr><td colspan="7" class="table-empty">暂无 Docker 容器数据</td></tr>';
}

function showNotice(message, tone = 'warn'){
  const notice = byId('notice');
  notice.textContent = message;
  notice.className = `notice ${tone}`;
  notice.hidden = false;
}

function hideNotice(){
  byId('notice').hidden = true;
}

function renderDashboard(view){
  dashboardState.view = view;
  const hasHost = Boolean(view.host);
  byId('dashboard').hidden = !hasHost;
  byId('emptyState').hidden = hasHost;
  if(!hasHost){
    closeProfileModal();
    hideNotice();
    return;
  }
  renderOverview(view);
  renderHardware(view);
  renderProfiles(view);
  renderContainers(view);
  const warnings = collectWarnings(view);
  if(warnings.length) showNotice(`部分采集数据不可用：${warnings.join('；')}`, 'warn');
  else hideNotice();
  if(dashboardState.selectedProfileIndex !== null){
    if(view.profiles[dashboardState.selectedProfileIndex]) renderProfileModal(view.profiles[dashboardState.selectedProfileIndex]);
    else closeProfileModal();
  }
}

function detailRow(label, value, extraClass = ''){
  return `<div class="detail-row"><dt>${escapeHtml(label)}</dt><dd class="${extraClass}">${value}</dd></div>`;
}

function renderProfileModal(profile){
  byId('profileModalTitle').textContent = `${textOrDash(profile.profile)} 详情`;
  const stateBadge = byId('profileModalState');
  stateBadge.className = `badge ${statusTone(profile.service_status)}`;
  stateBadge.textContent = statusText(profile.service_status);
  stateBadge.title = textOrDash(profile.service_status);
  const errorText = profile.error ? textOrDash(profile.error.message || profile.error.code) : '-';
  byId('profileModalContent').innerHTML = `
    <div class="profile-status-grid">
      <div><span>服务状态</span><span class="modal-status-value" title="${escapeHtml(textOrDash(profile.service_status))}">${badge(profile.service_status)}</span></div>
      <div><span>网关状态</span><span class="modal-status-value" title="${escapeHtml(textOrDash(profile.gateway_service))}">${badge(profile.gateway_service)}</span></div>
      <div><span>API 状态</span><span class="modal-status-value" title="${escapeHtml(textOrDash(profile.api_status))}">${badge(profile.api_status)}</span></div>
      <div><span>运行模式</span><strong title="${escapeHtml(textOrDash(profile.manager_mode))}">${escapeHtml(textOrDash(profile.manager_mode))}</strong></div>
    </div>
    <dl class="detail-list">
      ${detailRow('配置/Profile', escapeHtml(textOrDash(profile.profile)), 'mono')}
      ${detailRow('Agent 版本', escapeHtml(textOrDash(profile.agent_version)), 'mono')}
      ${detailRow('主模型', escapeHtml(textOrDash(profile.model)), 'wrap-value')}
      ${detailRow('使用模式', escapeHtml(textOrDash(profile.usage_mode)))}
      ${detailRow('模型提供商', escapeHtml(textOrDash(profile.provider)), 'wrap-value')}
      ${detailRow('认证刷新时间', escapeHtml(formatDateTime(profile.auth_refreshed_at)))}
      ${detailRow('定时任务', escapeHtml(formatPair(profile.scheduled_jobs_active, profile.scheduled_jobs_total)))}
      ${detailRow('会话数', escapeHtml(formatPair(profile.sessions_active, profile.sessions_total)))}
      ${detailRow('输入/输出/总 Token', escapeHtml(tokenBreakdown(profile.usage)) + (profile.usage?.estimated ? ' <span class="estimate-mark">估算</span>' : ''), 'mono')}
      ${detailRow('数据更新时间', escapeHtml(formatDateTime(profile.updated_at)))}
      ${detailRow('数据状态', profile.stale ? '<span class="badge neutral">陈旧</span>' : '<span class="badge ok">最新</span>')}
      ${detailRow('采集错误', escapeHtml(errorText), 'wrap-value')}
    </dl>`;
}

function openProfileModal(index, trigger){
  const profile = dashboardState.view?.profiles?.[index];
  if(!profile) return;
  dashboardState.selectedProfileIndex = index;
  dashboardState.modalTrigger = trigger || document.activeElement;
  renderProfileModal(profile);
  byId('profileModal').hidden = false;
  document.body.classList.add('modal-open');
  byId('profileModalClose').focus();
}

function closeProfileModal(){
  const modal = typeof document === 'undefined' ? null : byId('profileModal');
  if(!modal || modal.hidden) return;
  modal.hidden = true;
  document.body.classList.remove('modal-open');
  dashboardState.selectedProfileIndex = null;
  dashboardState.modalTrigger?.focus?.();
  dashboardState.modalTrigger = null;
}

function fixtureNameFromLocation(locationValue){
  if(!locationValue) return null;
  const localHosts = new Set(['localhost', '127.0.0.1', '::1']);
  if(!localHosts.has(locationValue.hostname)) return null;
  const name = new URLSearchParams(locationValue.search).get('fixture');
  return FIXTURE_NAMES.has(name) ? name : null;
}

function statsUrl(fixtureName){
  if(fixtureName) return `/testdata/migration/stats-${fixtureName}.json?_=${Date.now()}`;
  return `/json/stats.json?_=${Date.now()}`;
}

async function fetchStats(fixtureName, fetchImplementation = fetch){
  const response = await fetchImplementation(statsUrl(fixtureName), { cache: 'no-store' });
  if(!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function createRefreshController(options){
  const fetchStatsDocument = options.fetchStats;
  const onSuccess = options.onSuccess || (() => {});
  const onError = options.onError || (() => {});
  const onBusy = options.onBusy || (() => {});
  const setIntervalImplementation = options.setIntervalFn || setInterval;
  const clearIntervalImplementation = options.clearIntervalFn || clearInterval;
  let intervalId = null;
  let busy = false;

  async function refresh(reason = 'manual'){
    if(busy) return false;
    busy = true;
    onBusy(true, reason);
    try{
      const documentValue = await fetchStatsDocument(reason);
      onSuccess(documentValue, reason);
      return true;
    }catch(error){
      onError(error, reason);
      return false;
    }finally{
      busy = false;
      onBusy(false, reason);
    }
  }

  function stop(){
    if(intervalId !== null){
      clearIntervalImplementation(intervalId);
      intervalId = null;
    }
  }

  function start(){
    stop();
    intervalId = setIntervalImplementation(() => refresh('auto'), REFRESH_INTERVAL_MS);
    return intervalId;
  }

  return { refresh, start, stop, isBusy: () => busy };
}

function updateRefreshState(isBusy){
  const button = byId('refreshButton');
  button.disabled = isBusy;
  button.setAttribute('aria-busy', String(isBusy));
  button.textContent = isBusy ? '刷新中' : '刷新';
}

function applySuccessfulDocument(documentValue){
  dashboardState.lastDocument = documentValue;
  dashboardState.lastSuccessAt = new Date();
  const view = buildViewModel(documentValue, Boolean(dashboardState.fixtureName));
  renderDashboard(view);
  byId('lastUpdate').textContent = `上次刷新 ${formatDateTime(dashboardState.lastSuccessAt)}`;
}

function applyRefreshError(error){
  const suffix = dashboardState.lastDocument ? '，继续显示上一次成功数据' : '';
  showNotice(`数据刷新失败${suffix}：${textOrDash(error?.message)}`, 'err');
}

function bindInteractions(){
  byId('refreshButton').addEventListener('click', () => dashboardState.controller?.refresh('manual'));
  byId('profilesBody').addEventListener('click', event => {
    const row = event.target.closest('.profile-row');
    if(row) openProfileModal(Number(row.dataset.profileIndex), row);
  });
  byId('profilesBody').addEventListener('keydown', event => {
    const row = event.target.closest('.profile-row');
    if(row && (event.key === 'Enter' || event.key === ' ')){
      event.preventDefault();
      openProfileModal(Number(row.dataset.profileIndex), row);
    }
  });
  byId('profileModalClose').addEventListener('click', closeProfileModal);
  byId('profileModal').addEventListener('click', event => {
    if(event.target === byId('profileModal')) closeProfileModal();
  });
  document.addEventListener('keydown', event => {
    if(event.key === 'Escape') closeProfileModal();
  });
}

function initDashboard(){
  dashboardState.controller?.stop();
  dashboardState.fixtureName = fixtureNameFromLocation(window.location);
  bindInteractions();
  dashboardState.controller = createRefreshController({
    fetchStats: () => fetchStats(dashboardState.fixtureName),
    onSuccess: applySuccessfulDocument,
    onError: applyRefreshError,
    onBusy: updateRefreshState
  });
  dashboardState.controller.refresh('initial');
  dashboardState.controller.start();
  if(dashboardState.resizeHandler) window.removeEventListener('resize', dashboardState.resizeHandler);
  dashboardState.resizeHandler = () => {
    if(dashboardState.resizeFrame !== null) cancelAnimationFrame(dashboardState.resizeFrame);
    dashboardState.resizeFrame = requestAnimationFrame(() => {
      dashboardState.resizeFrame = null;
      fitCpuModelToSingleLine();
    });
  };
  window.addEventListener('resize', dashboardState.resizeHandler);
  if(dashboardState.pagehideHandler) window.removeEventListener('pagehide', dashboardState.pagehideHandler);
  dashboardState.pagehideHandler = () => {
    dashboardState.controller?.stop();
    window.removeEventListener('resize', dashboardState.resizeHandler);
    if(dashboardState.resizeFrame !== null) cancelAnimationFrame(dashboardState.resizeFrame);
  };
  window.addEventListener('pagehide', dashboardState.pagehideHandler, { once: true });
}

const exported = {
  REFRESH_INTERVAL_MS,
  approximateDays,
  buildViewModel,
  cleanCpuModel,
  collectWarnings,
  createRefreshController,
  fixtureNameFromLocation,
  fittedFontSize,
  formatBytes,
  formatDiskTemperature,
  formatPair,
  normalizeStatsPayload,
  percentage,
  selectSingleHost,
  statusTone,
  tokenBreakdown,
  usageBand
};

if(typeof module !== 'undefined' && module.exports) module.exports = exported;
if(typeof window !== 'undefined') window.HermesStatusDashboard = exported;
if(typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initDashboard, { once: true });
