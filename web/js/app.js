const REFRESH_INTERVAL_MS = 10 * 60 * 1000;

const dashboardState = {
  controller: null,
  lastDocument: null,
  view: null,
  lastSuccessAt: null,
  selectedProfileIndex: null,
  modalTrigger: null,
  activePage: 'home',
  pagehideHandler: null,
  hashchangeHandler: null,
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

function normalizePageName(value){
	return ['docker', 'lucky'].includes(value) ? value : 'home';
}

function pageFromHash(hashValue){
  const value = String(hashValue ?? '').replace(/^#/, '').toLowerCase();
  return normalizePageName(value);
}

function selectSingleHost(servers){
  if(!Array.isArray(servers) || servers.length === 0) return null;
  return servers.find(server => server && server.disabled !== true) || servers[0] || null;
}

function normalizeStatsPayload(documentValue){
  const documentObject = documentValue && typeof documentValue === 'object' ? documentValue : {};
  if(Array.isArray(documentObject.servers)) return documentObject;
  return { ...documentObject, servers: [] };
}

function safeObject(value){
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function buildViewModel(documentValue){
  const documentObject = normalizeStatsPayload(documentValue);
  const host = selectSingleHost(documentObject.servers);
	if(!host) return { host: null, document: documentObject, hardware: {}, docker: {}, hermes: {}, lucky: {}, profiles: [], containers: [] };

  const hardware = safeObject(host.hardware);
  const docker = safeObject(host.docker);
	const hermes = safeObject(host.hermes);
	const lucky = safeObject(host.lucky);
  const memoryPercent = percentage(host.memory_used, host.memory_total);
  const diskPercent = percentage(host.hdd_used, host.hdd_total);
  const cpuPercent = finiteNumber(host.cpu) === null ? null : clamp(host.cpu, 0, 100);

  return {
    document: documentObject,
    host,
    hardware,
    docker,
		hermes,
		lucky,
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
	const domains = [view.hardware, view.docker, view.hermes, ...view.profiles];
	if(luckyIsConfigured(view.lucky)) domains.push(view.lucky);
	return domains
    .map(domain => domain?.error)
    .filter(error => error && typeof error === 'object')
    .map(error => textOrDash(error.message || error.code))
    .filter(message => message !== '-');
}

function statusTone(value){
  const status = String(value ?? '').toLowerCase();
  if(status.startsWith('up ') || status.includes('(healthy)')) return 'ok';
  if(status.startsWith('exited') || status.startsWith('dead')) return 'err';
  if(status.startsWith('created') || status.startsWith('paused') || status.startsWith('restarting') || status.startsWith('removing')) return 'warn';
	if(['passed', 'running', 'ok', 'healthy', 'up', 'active', 'valid'].includes(status)) return 'ok';
	if(['degraded', 'stale', 'expiring', 'not_yet_valid'].includes(status)) return 'warn';
	if(['failed', 'down', 'stopped', 'unauthorized', 'timeout', 'dead', 'exited', 'error', 'expired', 'invalid', 'unavailable'].includes(status)) return 'err';
  return 'neutral';
}

function statusText(value){
  const status = String(value ?? '').toLowerCase();
  const labels = {
    passed: '通过', failed: '失败', unknown: '未知', unavailable: '不可用',
    running: '运行中', healthy: '正常', ok: '正常', active: '活动',
    stopped: '已停止', down: '离线', unauthorized: '未授权', timeout: '超时',
		exited: '已退出', dead: '异常', degraded: '部分异常', stale: '已陈旧',
		not_configured: '未配置', error: '异常', valid: '有效', expiring: '即将到期',
		expired: '已过期', not_yet_valid: '尚未生效', invalid: '无效'
  };
  return labels[status] || textOrDash(value);
}

function badge(value){
  return `<span class="badge ${statusTone(value)}">${escapeHtml(statusText(value))}</span>`;
}

function domainIsUnknown(value){
  return !value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length === 0;
}

function luckyIsConfigured(lucky){
	return !domainIsUnknown(lucky) && lucky.status !== 'not_configured' && lucky.error?.code !== 'not_reported';
}

function dashboardCondition(view, refreshError = null){
  if(refreshError) return {kind: 'error', title: '刷新失败', message: textOrDash(refreshError.message || refreshError)};
  if(!view.host) return {kind: 'empty', title: '暂无主机数据', message: 'stats.json 暂无可显示的主机。'};
  if(view.host.online4 === false && view.host.online6 === false){
    return {kind: 'offline', title: '主机离线', message: '当前显示最后一次可用的状态数据。'};
  }
  const warnings = collectWarnings(view);
  if(warnings.length){
    return {kind: 'error', title: '部分数据不可用', message: warnings.join('；')};
  }
	const staleDomains = [
		['硬件', view.hardware], ['Docker', view.docker], ['Hermes', view.hermes]
	].filter(([, domain]) => domain?.stale === true).map(([name]) => name);
	if(luckyIsConfigured(view.lucky) && view.lucky?.stale === true) staleDomains.push('Lucky');
  if(view.profiles.some(profile => profile?.stale === true)) staleDomains.push('Profile');
  if(staleDomains.length){
    return {kind: 'stale', title: '数据已陈旧', message: `${[...new Set(staleDomains)].join('、')} 数据超过刷新时限。`};
  }
  if([view.hardware, view.docker, view.hermes].some(domainIsUnknown)){
    return {kind: 'unknown', title: '状态未知', message: 'stats.json 未包含完整扩展状态。'};
  }
  return {kind: 'ready', title: '', message: ''};
}

function setPageState(condition){
  const state = condition || {kind: 'ready', title: '', message: ''};
  const element = byId('pageState');
  element.hidden = state.kind === 'ready';
  element.dataset.state = state.kind;
  const icons = {loading: '↻', empty: '—', offline: '×', error: '!', stale: '◷', unknown: '?'};
  byId('pageStateIcon').textContent = icons[state.kind] || '';
  byId('pageStateTitle').textContent = state.title;
  byId('pageStateMessage').textContent = state.message;
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
  const hardware = view.hardware;
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
    <article class="summary-card stacked-card temperature-card">
      <h2>CPU温度/硬盘温度</h2>
      <div class="card-value">${escapeHtml(formatTemperature(hardware.cpu_temperature?.value))}</div>
      <div class="card-subvalue">${escapeHtml(formatTemperature(hardware.disk_temperature?.current))}</div>
    </article>
    <article class="summary-card stacked-card uptime-system-card">
      <h2>已运行时间/操作系统</h2>
      <div class="card-value">${escapeHtml(formatUptime(view.host.uptime))}</div>
      <div class="card-subvalue" title="${escapeHtml(textOrDash(view.host.os))}">${escapeHtml(textOrDash(view.host.os))}</div>
    </article>`;
  requestAnimationFrame(fitCpuModelToSingleLine);
}

function renderHardware(view){
  const hardware = view.hardware;
  const docker = view.docker;
  const lucky = view.lucky;
  const smartStatus = hardware.disk_smart_status ?? 'unknown';
  const powerOnHours = finiteNumber(hardware.disk_power_on_hours);
  const powerOnDays = approximateDays(powerOnHours);
  const readWrite = finiteNumber(hardware.disk_written_bytes) === null && finiteNumber(hardware.disk_read_bytes) === null
    ? '-'
    : `${formatBytes(hardware.disk_written_bytes)} / ${formatBytes(hardware.disk_read_bytes)}`;
  byId('hardwareHealth').innerHTML = `
    <article class="health-card"><h2>运行中/容器总数</h2><div class="health-value">${escapeHtml(formatPair(docker.running, docker.total))}</div></article>
    <article class="health-card"><h2>Lucky运行状态/版本</h2><div class="health-value lucky-home-value">${escapeHtml(statusText(lucky.status))}<span class="health-inline-meta">(${escapeHtml(textOrDash(lucky.version?.current))})</span></div></article>
    <article class="health-card"><h2>硬盘 SMART 状态</h2><div class="health-value">${badge(smartStatus)}</div></article>
    <article class="health-card"><h2>硬盘通电时间</h2><div class="health-value power-on-value">${powerOnHours === null ? '-' : `${formatInteger(powerOnHours)} h <span class="power-on-days">(约${formatInteger(powerOnDays)}天)</span>`}</div></article>
    <article class="health-card"><h2>硬盘写入/读取量</h2><div class="health-value">${escapeHtml(readWrite)}</div></article>`;
}

function renderLuckyTables(view){
	const lucky = view.lucky;
	const ddns = safeObject(lucky.dynamic_dns);
	const records = Array.isArray(ddns.records) ? ddns.records : [];
	const web = safeObject(lucky.web_services);
	const services = Array.isArray(web.services) ? web.services : [];
	const forwards = safeObject(lucky.port_forwards);
	const rules = Array.isArray(forwards.rules) ? forwards.rules : [];
	const configRows = records.length ? records : (services.length || rules.length ? [{}] : []);
	const ports = [...new Set(services.map(item => Number(item.listen_port)).filter(Number.isFinite))].sort((left, right) => left - right);
	const connections = sumLuckyValues(services, 'connection_count');
	const enabledSubrules = sumLuckyValues(services, 'enabled_subrules');
	const totalSubrules = sumLuckyValues(services, 'total_subrules');
	byId('luckyConfigBody').innerHTML = configRows.length ? configRows.map(item => `<tr><td class="strong-cell">${escapeHtml(textOrDash(item.provider))}</td><td>${escapeHtml(textOrDash(item.address_method))}</td><td>${escapeHtml(luckyChangeStatus(item.local_record_change_status))}</td><td class="lucky-sync-cell"><span>${escapeHtml(formatDateTime(item.last_update_at))}</span><span>${escapeHtml(formatDateTime(item.next_sync_at))}</span></td><td>${escapeHtml(formatLuckyCount(item.updated_records, item.total_records))}</td><td>${escapeHtml(ports.length ? ports.join('、') : '-')}</td><td>${escapeHtml(formatInteger(connections))}</td><td>${escapeHtml(formatLuckyCount(enabledSubrules, totalSubrules))}</td><td>${escapeHtml(formatLuckyCount(forwards.enabled, forwards.total))}</td></tr>`).join('') : '<tr><td colspan="9" class="table-empty">暂无配置信息</td></tr>';

	const certs = safeObject(lucky.certificates);
	const items = Array.isArray(certs.items) ? certs.items : [];
	byId('luckyCertificateBody').innerHTML = items.length ? items.map(item => `<tr><td class="strong-cell">${escapeHtml(textOrDash(item.display_name))}</td><td class="bounded-cell">${escapeHtml(textOrDash(item.issuer))}</td><td>${escapeHtml(formatDateTime(item.not_before))}</td><td>${escapeHtml(formatDateTime(item.not_after))}</td><td>${escapeHtml(formatInteger(item.remaining_days))}</td><td>${escapeHtml(item.auto_renew === null || item.auto_renew === undefined ? '-' : item.auto_renew ? '是' : '否')}</td><td>${badge(item.status)}</td></tr>`).join('') : '<tr><td colspan="7" class="table-empty">暂无证书数据</td></tr>';
}

function luckyChangeStatus(value){
	const normalized = String(value ?? '').trim().toLowerCase();
	if(normalized === 'changed' || normalized === 'true') return '已变化';
	if(normalized === 'unchanged' || normalized === 'false') return '无变化';
	return textOrDash(value);
}

function formatLuckyCount(current, total){
	if((current === null || current === undefined) && (total === null || total === undefined)) return '-';
	return `${formatInteger(current)} / ${formatInteger(total)}`;
}

function sumLuckyValues(items, field){
	const values = items.map(item => item?.[field]).filter(value => value !== null && value !== undefined).map(Number).filter(value => Number.isFinite(value) && value >= 0);
	return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
}

function renderLucky(view){
	renderLuckyTables(view);
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
      <td class="strong-cell" title="${escapeHtml(textOrDash(container.names))}">${escapeHtml(textOrDash(container.names))}</td>
      <td class="wide-cell mono" title="${escapeHtml(textOrDash(container.image))}">${escapeHtml(textOrDash(container.image))}</td>
      <td class="bounded-cell" title="${escapeHtml(textOrDash(container.status))}">${badge(container.status)}</td>
      <td class="ports-cell mono" title="${escapeHtml(textOrDash(container.ports))}">${escapeHtml(textOrDash(container.ports))}</td>
    </tr>`).join('') : '<tr><td colspan="4" class="table-empty">暂无 Docker 容器数据</td></tr>';
}

function renderDashboard(view){
  dashboardState.view = view;
  const hasHost = Boolean(view.host);
  byId('dashboard').hidden = !hasHost;
  if(!hasHost){
    closeProfileModal();
    setPageState(dashboardCondition(view));
    return;
  }
  renderOverview(view);
	renderHardware(view);
  renderProfiles(view);
	renderContainers(view);
	renderLucky(view);
  applyPageVisibility();
  setPageState(dashboardCondition(view));
  if(dashboardState.selectedProfileIndex !== null){
    if(view.profiles[dashboardState.selectedProfileIndex]) renderProfileModal(view.profiles[dashboardState.selectedProfileIndex]);
    else closeProfileModal();
  }
}

function applyPageVisibility(){
  const activePage = normalizePageName(dashboardState.activePage);
  dashboardState.activePage = activePage;
	for(const page of ['home', 'docker', 'lucky']){
    const active = page === activePage;
    const tab = byId(`${page}Tab`);
    const panel = byId(`${page}Page`);
    if(tab){
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', String(active));
      tab.setAttribute('tabindex', active ? '0' : '-1');
      if(active) tab.setAttribute('aria-current', 'page');
      else tab.removeAttribute('aria-current');
    }
    if(panel) panel.hidden = !active;
  }
}

function setActivePage(page, options = {}){
  const nextPage = normalizePageName(page);
  dashboardState.activePage = nextPage;
  if(nextPage !== 'home') closeProfileModal();
  applyPageVisibility();
  if(options.updateHash !== false && typeof window !== 'undefined'){
		const nextHash = `#${nextPage}`;
    if(window.location.hash !== nextHash) window.history.replaceState(null, '', nextHash);
  }
  if(nextPage === 'home') requestAnimationFrame(fitCpuModelToSingleLine);
  return nextPage;
}

function detailRow(label, value, extraClass = ''){
  return `<div class="detail-row"><dt>${escapeHtml(label)}</dt><dd class="${extraClass}">${value}</dd></div>`;
}

function booleanText(value){
  if(value === true) return '是';
  if(value === false) return '否';
  return '-';
}

function tokenSourceText(value){
  const labels = {
    hermes_api_payload: 'Hermes API',
    local_session_state: '本地会话状态',
    local_logs: '本地运行快照',
    unavailable: '不可用'
  };
  return labels[value] || textOrDash(value);
}

function modalMetric(label, value, extraClass = ''){
  return `<div><span>${escapeHtml(label)}</span><strong class="${extraClass}" title="${escapeHtml(textOrDash(value))}">${escapeHtml(textOrDash(value))}</strong></div>`;
}

function auxiliaryModelRows(config){
  const rows = Array.isArray(config?.auxiliary_models) ? config.auxiliary_models : [];
  if(!rows.length) return '<tr><td colspan="7" class="table-empty">暂无辅助模型配置</td></tr>';
  return rows.map(item => `
    <tr>
      <td class="strong-cell">${escapeHtml(textOrDash(item.name))}</td>
      <td class="bounded-cell" title="${escapeHtml(textOrDash(item.effective_model))}">${escapeHtml(textOrDash(item.effective_model))}</td>
      <td class="bounded-cell" title="${escapeHtml(textOrDash(item.effective_provider))}">${escapeHtml(textOrDash(item.effective_provider))}</td>
      <td>${escapeHtml(item.source === 'main_model' ? '继承主模型' : '独立配置')}</td>
      <td>${escapeHtml(textOrDash(item.timeout_seconds))}</td>
      <td>${escapeHtml(textOrDash(item.max_concurrency))}</td>
      <td>${escapeHtml(textOrDash(item.base_url_display))}</td>
    </tr>`).join('');
}

function volumeRows(config){
  const rows = Array.isArray(config?.docker_volumes) ? config.docker_volumes : [];
  if(!rows.length) return '<tr><td class="table-empty">暂无容器挂载配置</td></tr>';
  return rows.map(value => `<tr><td class="mono wrap-value">${escapeHtml(textOrDash(value))}</td></tr>`).join('');
}

function profileModalMarkup(profile){
  const config = safeObject(profile?.config_summary);
  const main = safeObject(config.main_model);
  const delegation = safeObject(config.delegation);
  const moa = safeObject(profile?.mixture_of_agents);
  const usage = safeObject(profile?.usage);
  const errorText = profile?.error ? textOrDash(profile.error.message || profile.error.code) : '-';
  const tokenWindow = usage.window_start || usage.window_end
    ? `${formatDateTime(usage.window_start)} / ${formatDateTime(usage.window_end)}`
    : '-';
  const delegationText = [delegation.provider, delegation.model].map(textOrDash).join(' / ');
  const moaStatus = moa.available ? (moa.enabled === false ? '可用 / 未启用' : '可用') : '不可用';
  const moaTools = Array.isArray(moa.tools) && moa.tools.length ? moa.tools.join(', ') : '-';
  return `
    <div class="profile-status-grid">
      <div><span>服务状态</span><span class="modal-status-value" title="${escapeHtml(textOrDash(profile.service_status))}">${badge(profile.service_status)}</span></div>
      <div><span>网关状态</span><span class="modal-status-value" title="${escapeHtml(textOrDash(profile.gateway_service))}">${badge(profile.gateway_service)}</span></div>
      <div><span>API 状态</span><span class="modal-status-value" title="${escapeHtml(textOrDash(profile.api_status))}">${badge(profile.api_status)}</span></div>
      <div><span>运行模式</span><strong title="${escapeHtml(textOrDash(profile.manager_mode))}">${escapeHtml(textOrDash(profile.manager_mode))}</strong></div>
    </div>
    <section class="modal-section">
      <h3>运行概览</h3>
      <dl class="detail-list">
        ${detailRow('配置/Profile', escapeHtml(textOrDash(profile.profile)), 'mono')}
        ${detailRow('Agent 版本', escapeHtml(textOrDash(profile.agent_version)), 'mono')}
        ${detailRow('主模型', escapeHtml(textOrDash(profile.model)), 'wrap-value')}
        ${detailRow('模型提供商', escapeHtml(textOrDash(profile.provider)), 'wrap-value')}
        ${detailRow('使用模式', escapeHtml(textOrDash(profile.usage_mode)))}
        ${detailRow('Provider/模型配置刷新时间', escapeHtml(formatDateTime(profile.auth_refreshed_at)))}
        ${detailRow('定时任务 活动/总数', escapeHtml(formatPair(profile.scheduled_jobs_active, profile.scheduled_jobs_total)))}
        ${detailRow('会话 活动/总数', escapeHtml(formatPair(profile.sessions_active, profile.sessions_total)) + (profile.sessions_has_more ? ' <span class="estimate-mark">分页上限</span>' : ''))}
        ${detailRow('输入/输出/总 Token', escapeHtml(tokenBreakdown(usage)) + (usage.estimated ? ' <span class="estimate-mark">估算</span>' : ''), 'mono')}
        ${detailRow('Token 来源', escapeHtml(tokenSourceText(usage.source)))}
        ${detailRow('Token 窗口 起/止', escapeHtml(tokenWindow), 'wrap-value')}
      </dl>
    </section>
    <section class="modal-section">
      <h3>配置摘要</h3>
      <div class="modal-metric-grid">
        ${modalMetric('主模型', main.model || profile.model)}
        ${modalMetric('提供商', main.provider || profile.provider)}
        ${modalMetric('Base URL', main.base_url, 'mono')}
        ${modalMetric('并发 / 超时', `${textOrDash(main.concurrency)} / ${textOrDash(main.timeout_seconds)} s`)}
      </div>
      <dl class="detail-list compact-details">
        ${detailRow('Delegation 模型', escapeHtml(delegationText), 'wrap-value')}
        ${detailRow('Delegation 推理强度', escapeHtml(textOrDash(delegation.reasoning_effort)))}
        ${detailRow('子任务并发 / 深度 / 超时', escapeHtml(`${textOrDash(delegation.max_concurrent_children)} / ${textOrDash(delegation.max_spawn_depth)} / ${textOrDash(delegation.child_timeout_seconds)} s`))}
      </dl>
      <div class="modal-table-wrap">
        <table class="data modal-data-table auxiliary-table">
          <thead><tr><th>辅助模型</th><th>模型</th><th>提供商</th><th>来源</th><th>超时(s)</th><th>并发</th><th>Base URL</th></tr></thead>
          <tbody>${auxiliaryModelRows(config)}</tbody>
        </table>
      </div>
    </section>
    <section class="modal-section modal-two-column">
      <div>
        <h3>容器挂载点</h3>
        <div class="modal-table-wrap"><table class="data modal-data-table volumes-table"><thead><tr><th>挂载路径</th></tr></thead><tbody>${volumeRows(config)}</tbody></table></div>
      </div>
      <div>
        <h3>Mixture of Agents</h3>
        <dl class="detail-list compact-details">
          ${detailRow('状态', escapeHtml(moaStatus))}
          ${detailRow('名称', escapeHtml(textOrDash(moa.label || moa.name)), 'wrap-value')}
          ${detailRow('已配置', escapeHtml(booleanText(moa.configured)))}
          ${detailRow('工具', escapeHtml(moaTools), 'wrap-value mono')}
          ${detailRow('错误', escapeHtml(textOrDash(moa.error)), 'wrap-value')}
        </dl>
      </div>
    </section>
    <section class="modal-section">
      <h3>采集状态</h3>
      <dl class="detail-list compact-details">
        ${detailRow('数据更新时间', escapeHtml(formatDateTime(profile.updated_at)))}
        ${detailRow('快照接收时间', escapeHtml(formatDateTime(profile.received_at)))}
        ${detailRow('数据状态', profile.stale ? '<span class="badge warn">陈旧</span>' : '<span class="badge ok">最新</span>')}
        ${detailRow('采集错误', escapeHtml(errorText), 'wrap-value')}
      </dl>
    </section>`;
}

function renderProfileModal(profile){
  byId('profileModalTitle').textContent = `${textOrDash(profile.profile)} 详情`;
  const stateBadge = byId('profileModalState');
  stateBadge.className = `badge ${statusTone(profile.service_status)}`;
  stateBadge.textContent = statusText(profile.service_status);
  stateBadge.title = textOrDash(profile.service_status);
  byId('profileModalContent').innerHTML = profileModalMarkup(profile);
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

function statsUrl(){
  return `/json/stats.json?_=${Date.now()}`;
}

async function fetchStats(fetchImplementation = fetch){
  const response = await fetchImplementation(statsUrl(), { cache: 'no-store' });
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
  button.classList.toggle('is-loading', isBusy);
  button.title = isBusy ? '正在刷新' : '刷新数据';
  button.setAttribute('aria-label', button.title);
}

function applySuccessfulDocument(documentValue){
  dashboardState.lastDocument = documentValue;
  dashboardState.lastSuccessAt = new Date();
  const view = buildViewModel(documentValue);
  renderDashboard(view);
  byId('lastUpdate').textContent = `上次刷新 ${formatDateTime(dashboardState.lastSuccessAt)}`;
}

function applyRefreshError(error){
  if(!dashboardState.lastDocument) byId('dashboard').hidden = true;
  setPageState(dashboardCondition(dashboardState.view || {host: null}, error));
}

function bindInteractions(){
  byId('refreshButton').addEventListener('click', () => dashboardState.controller?.refresh('manual'));
  for(const tab of document.querySelectorAll('[data-page-target]')){
    tab.addEventListener('click', () => setActivePage(tab.dataset.pageTarget));
    tab.addEventListener('keydown', event => {
      if(!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
			const pages = ['home', 'docker', 'lucky'];
			const current = pages.indexOf(dashboardState.activePage);
			const nextPage = event.key === 'Home' ? pages[0] : event.key === 'End' ? pages[pages.length - 1] : event.key === 'ArrowLeft' ? pages[(current - 1 + pages.length) % pages.length] : pages[(current + 1) % pages.length];
      setActivePage(nextPage);
      byId(`${nextPage}Tab`).focus();
    });
  }
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
  const initialHash = window.location.hash;
  dashboardState.activePage = pageFromHash(initialHash);
	if(initialHash && !['#home', '#docker', '#lucky'].includes(initialHash.toLowerCase())){
    window.history.replaceState(null, '', '#home');
  }
  applyPageVisibility();
  setPageState({kind: 'loading', title: '正在加载', message: '正在读取 stats.json'});
  bindInteractions();
  dashboardState.controller = createRefreshController({
    fetchStats: () => fetchStats(),
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
  if(dashboardState.hashchangeHandler) window.removeEventListener('hashchange', dashboardState.hashchangeHandler);
  dashboardState.hashchangeHandler = () => setActivePage(pageFromHash(window.location.hash), {updateHash: false});
  window.addEventListener('hashchange', dashboardState.hashchangeHandler);
  if(dashboardState.pagehideHandler) window.removeEventListener('pagehide', dashboardState.pagehideHandler);
  dashboardState.pagehideHandler = () => {
    dashboardState.controller?.stop();
    window.removeEventListener('resize', dashboardState.resizeHandler);
    window.removeEventListener('hashchange', dashboardState.hashchangeHandler);
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
  dashboardCondition,
	luckyIsConfigured,
  fittedFontSize,
  formatBytes,
  formatPair,
  modelBreakdown,
  normalizeStatsPayload,
  percentage,
  pageFromHash,
  profileModalMarkup,
  normalizePageName,
  selectSingleHost,
  statsUrl,
  statusTone,
  tokenSourceText,
  tokenBreakdown,
  usageBand
};

if(typeof module !== 'undefined' && module.exports) module.exports = exported;
if(typeof window !== 'undefined') window.HermesStatusDashboard = exported;
if(typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initDashboard, { once: true });
