const REFRESH_INTERVAL_MS = 10 * 60 * 1000;
const MAX_UI_DEVICES = 16;
const DEVICE_STORAGE_KEY = 'hermesstatus.selectedDeviceId';
const DEVICE_ID_PATTERN = /^[a-z0-9][a-z0-9._-]{0,62}$/;
const DEVICE_STATUSES = new Set([
  'online', 'degraded', 'stale', 'offline', 'never_seen', 'disabled',
  'identity_error'
]);

const dashboardState = {
  controller: null,
  currentStats: null,
  view: null,
  lastSuccessAt: null,
  selectedDeviceId: null,
  deviceSelectionNotice: '',
  selectedProfileIndex: null,
  modalTrigger: null,
  deviceDiagnosticsTrigger: null,
  aboutTrigger: null,
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

function formatTrafficBytes(value){
  const number = finiteNumber(value);
  if(number === null || number < 0) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let size = number;
  let unit = 0;
  while(size >= 1000 && unit < units.length - 1){
    size /= 1000;
    unit += 1;
  }
  return `${size.toFixed(1)}${units[unit]}`;
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
    .replace(/\s+@\s*[\d.]+\s*(?:[GMK]?Hz)?\s*$/i, '')
    .replace(/\s+/g, ' ')
    .trim() || '-';
}

function formatTemperature(value){
  const number = finiteNumber(value);
  if(number === null) return '-';
  return `${Number.isInteger(number) ? number : number.toFixed(1)} °C`;
}

function formatCelsius(value){
  const number = finiteNumber(value);
  if(number === null) return '-';
  return `${Number.isInteger(number) ? number : number.toFixed(1)}℃`;
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

function formatUptimeHours(seconds){
  const number = finiteNumber(seconds);
  if(number === null || number < 0) return '-';
  const hours = number / 3600;
  return `${formatInteger(Math.floor(hours))} h (约${(hours / 24).toFixed(2)}天)`;
}

function uptimeHoursMetric(seconds){
  const number = finiteNumber(seconds);
  if(number === null || number < 0) return null;
  const hours = number / 3600;
  return {hours: Math.floor(hours), days: (hours / 24).toFixed(2)};
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
	return ['hardware', 'docker', 'lucky', 'easytier'].includes(value) ? value : 'home';
}

function valueAt(objectValue, keys){
  const object = safeObject(objectValue);
  for(const key of keys){
    const value = finiteNumber(object[key]);
    if(value !== null) return value;
  }
  return null;
}

function deviceShortName(value){
  const text = textOrDash(value);
  if(text === '-') return text;
  const segments = text.split('/').filter(Boolean);
  return segments.length ? segments[segments.length - 1] : text;
}

function diskName(disk){
  return textOrDash(disk?.id || deviceShortName(disk?.device));
}

function diskTemperatureC(disk){
  return valueAt(disk, ['temperature_c', 'temperature', 'current_temperature_c']) ??
    valueAt(disk?.temperature, ['current', 'value', 'temperature_c']);
}

function diskPowerOnHours(disk){
  return valueAt(disk, ['power_on_hours', 'power_on_time_hours']);
}

function diskWrittenBytes(disk){
  return valueAt(disk, ['written_bytes', 'bytes_written']);
}

function diskReadBytes(disk){
  return valueAt(disk, ['read_bytes', 'bytes_read']);
}

function isSynologyHost(hardware){
  const identity = safeObject(hardware?.system_identity);
  return /synology\s+dsm/i.test(String(identity.distribution || identity.pretty_name || '')) ||
    String(identity.source || '').toLowerCase() === 'dsm-version';
}

function largestDiskByCapacity(disks){
  return maxDiskBy(disks, disk => finiteNumber(disk?.capacity_bytes));
}

function synologyVolumeLabel(filesystems){
  const candidate = (Array.isArray(filesystems) ? filesystems : [])
    .map(filesystem => ({filesystem, total: finiteNumber(filesystem?.total_bytes)}))
    .filter(item => item.total !== null)
    .sort((left, right) => right.total - left.total)[0]?.filesystem;
  const mountpoint = String(candidate?.mountpoint || '');
  const match = /^\/volume(\d+)(?:\/|$)/.exec(mountpoint);
  return match ? `vol${match[1]}` : '-';
}

function homeDiskUsage(host, hardware){
  const used = finiteNumber(host?.hdd_used);
  const total = finiteNumber(host?.hdd_total);
  if(used === null || total === null) return {text: '-', valueText: '-', label: null, percent: null};
  const filesystems = dataFilesystemItemsForView(hardware);
  const selectedFilesystem = filesystems
    .filter(item => item?.collection_status === 'healthy' && finiteNumber(item?.total_bytes) !== null && finiteNumber(item?.used_bytes) !== null)
    .sort((left, right) => finiteNumber(right.total_bytes) - finiteNumber(left.total_bytes))[0];
  const reportedTotalBytes = total * 1000 * 1000;
  const matchesSelectedFilesystem = selectedFilesystem && Math.abs(finiteNumber(selectedFilesystem.total_bytes) - reportedTotalBytes) < 1000 * 1000;
  const label = matchesSelectedFilesystem
    ? (isSynologyHost(hardware)
      ? synologyVolumeLabel([selectedFilesystem])
      : (filesystemBackingDisks(selectedFilesystem).text))
    : '-';
  const valueText = `${formatBytes(used * 1000 * 1000)} / ${formatBytes(total * 1000 * 1000)}`;
  return {
    text: `${valueText}${label === '-' ? '' : ` (${label})`}`,
    valueText,
    label: label === '-' ? null : label,
    percent: percentage(used, total)
  };
}

function conciseOsVersion(host, hardware){
  const identity = safeObject(hardware?.system_identity);
  if(isSynologyHost(hardware)){
    const version = String(identity.version || host?.os || '');
    const match = /(?:dsm\s*)?(\d+\.\d+(?:\.\d+)?)/i.exec(version);
    return match ? `DSM ${match[1]}` : 'DSM';
  }
  return textOrDash(host?.os);
}

function storageState(hardware){
  const storage = safeObject(hardware?.storage);
  const physicalDisks = Array.isArray(storage.physical_disks)
    ? storage.physical_disks.filter(item => item && typeof item === 'object')
    : [];
  const filesystems = Array.isArray(storage.filesystems)
    ? storage.filesystems.filter(item => item && typeof item === 'object')
    : [];
  return {storage, physicalDisks, filesystems};
}

function legacyPhysicalDisk(hardware){
  const temperature = safeObject(hardware?.disk_temperature);
  const hasLegacyValue = [
    hardware?.disk_device,
    hardware?.disk_smart_status,
    hardware?.disk_power_on_hours,
    hardware?.disk_written_bytes,
    hardware?.disk_read_bytes,
    temperature.current,
    temperature.value
  ].some(value => value !== null && value !== undefined && value !== 'unknown');
  if(!hasLegacyValue) return null;
  const device = textOrDash(hardware?.disk_device);
  return {
    id: deviceShortName(device),
    device: device === '-' ? null : device,
    model: null,
    capacity_bytes: null,
    temperature_c: valueAt(temperature, ['current', 'value', 'highest']),
    smart_status: hardware?.disk_smart_status,
    power_on_hours: hardware?.disk_power_on_hours,
    written_bytes: hardware?.disk_written_bytes,
    read_bytes: hardware?.disk_read_bytes,
    smart_source: hardware?.disk_smart_source
  };
}

function physicalDisksForView(hardware){
  const state = storageState(hardware);
  if(state.physicalDisks.length) return state.physicalDisks;
  const legacy = legacyPhysicalDisk(hardware);
  return legacy ? [legacy] : [];
}

function filesystemItemsForView(hardware){
  return storageState(hardware).filesystems;
}

function dataFilesystemItemsForView(hardware){
  const filesystems = filesystemItemsForView(hardware);
  if(!isSynologyHost(hardware)) return filesystems;
  // DSM exposes small internal, boot and package filesystems too. The
  // explicitly configured /volumeN probes are its operator data volumes.
  return filesystems.filter(filesystem => /^\/volume\d+(?:\/|$)/.test(String(filesystem?.mountpoint || '')));
}

function temperatureSensorEntries(hardware){
  const cpuTemperature = safeObject(hardware?.cpu_temperature);
  const groups = [
    hardware?.cpu_temperatures,
    hardware?.cpu_temperature_sensors,
    cpuTemperature.sensors,
    safeObject(hardware?.sensors).cpu
  ];
  const entries = groups.flatMap(group => Array.isArray(group) ? group : [])
    .filter(item => item && typeof item === 'object')
    .map(item => ({
      value: valueAt(item, ['value', 'temperature_c', 'temperature', 'current']),
      label: textOrDash(item.label || item.name || item.sensor || item.id)
    }))
    .filter(item => item.value !== null);
  if(entries.length) return entries;
  const value = valueAt(cpuTemperature, ['value', 'temperature_c', 'current', 'highest']);
  if(value === null) return [];
  return [{value, label: textOrDash(cpuTemperature.label || cpuTemperature.sensor || cpuTemperature.name)}];
}

function maximumTemperature(entries){
  const valid = entries.filter(entry => finiteNumber(entry?.value) !== null);
  if(!valid.length) return null;
  return valid.reduce((highest, entry) => entry.value > highest.value ? entry : highest);
}

function maxDiskBy(disks, metric){
  const candidates = disks
    .map(disk => ({disk, value: metric(disk)}))
    .filter(item => item.value !== null);
  if(!candidates.length) return null;
  return candidates.reduce((highest, entry) => entry.value > highest.value ? entry : highest).disk;
}

function diskIoCandidate(disks){
  return maxDiskBy(disks, diskWrittenBytes) || maxDiskBy(disks, diskReadBytes);
}

function parenthesizedMeta(value){
  const text = textOrDash(value);
  return text === '-' ? '' : `<span class="power-on-days">(${escapeHtml(text)})</span>`;
}

function smartHomeMarkup(disks, hardware){
  if(disks.length === 1){
    const disk = disks[0];
    const state = disk.smart_status ?? hardware?.disk_smart_status;
    const fallback = disk?.completeness === 'partial' && disk?.health_source === 'attribute_check';
    return escapeHtml(fallback ? `${statusText(state)}（属性检查）` : statusText(state));
  }
  if(disks.length > 1){
    const passed = disks.filter(disk => String(disk.smart_status ?? '').toLowerCase() === 'passed');
    const attributeFallback = passed
      .filter(disk => disk?.completeness === 'partial' && disk?.health_source === 'attribute_check')
      .length;
    const failed = disks
      .filter(disk => String(disk.smart_status ?? '').toLowerCase() === 'failed')
      .map(diskName)
      .filter(name => name !== '-');
    const unknown = disks.filter(disk => {
      const status = String(disk.smart_status ?? '').toLowerCase();
      return status !== 'passed' && status !== 'failed';
    }).length;
    const details = failed.length
      ? `${failed.join('、')}故障`
      : unknown ? `${unknown} 块未知`
      : attributeFallback ? `${attributeFallback} 块属性检查` : '';
    return `${escapeHtml(`${passed.length} / ${disks.length} 通过`)}${parenthesizedMeta(details)}`;
  }
  return escapeHtml(statusText(hardware?.disk_smart_status ?? 'unknown'));
}

function diskSmartMarkup(disk){
  const state = String(disk?.smart_status ?? 'unknown').toLowerCase();
  const fallback = disk?.completeness === 'partial' && disk?.health_source === 'attribute_check';
  const label = fallback ? `${statusText(state)}（属性检查）` : statusText(state);
  const detail = fallback ? '原生 SMART RETURN STATUS 不可用；已使用属性阈值检查结果。' : '';
  return `<span class="badge ${statusTone(state)}"${detail ? ` title="${escapeHtml(detail)}"` : ''}>${escapeHtml(label)}</span>`;
}

function validDeviceId(value){
  return typeof value === 'string' && DEVICE_ID_PATTERN.test(value);
}

function parseDashboardHash(hashValue){
  const raw = String(hashValue ?? '').replace(/^#/, '');
  const separator = raw.indexOf('?');
  const rawPage = separator === -1 ? raw : raw.slice(0, separator);
  const query = separator === -1 ? '' : raw.slice(separator + 1);
  const page = normalizePageName(rawPage.toLowerCase());
  const parameters = new URLSearchParams(query);
  const values = parameters.getAll('device');
  const unknownParameters = [...parameters.keys()].some(key => key !== 'device');
  const deviceId = values.length === 1 && validDeviceId(values[0]) ? values[0] : null;
  return {
    page,
    deviceId,
    needsRewrite:
      (rawPage !== '' && rawPage !== page) ||
      unknownParameters ||
      values.length > 1 ||
      (values.length === 1 && deviceId === null)
  };
}

function pageFromHash(hashValue){
  return parseDashboardHash(hashValue).page;
}

function canonicalDashboardHash(page, deviceId){
  const normalizedPage = normalizePageName(page);
  return validDeviceId(deviceId)
    ? `#${normalizedPage}?device=${encodeURIComponent(deviceId)}`
    : `#${normalizedPage}`;
}

function selectableDevices(documentValue){
  const servers = Array.isArray(documentValue?.servers) ? documentValue.servers : [];
  if(servers.length > MAX_UI_DEVICES) return [];
  const validIDs = servers
    .filter(server => server && typeof server === 'object' && validDeviceId(server.device_id))
    .map(server => server.device_id);
  if(new Set(validIDs).size !== validIDs.length) return [];
  return servers.filter(server => {
    if(!server || typeof server !== 'object' || !validDeviceId(server.device_id)) return false;
    const status = String(server.status ?? '').toLowerCase();
    return DEVICE_STATUSES.has(status) &&
      server.disabled !== true &&
      status !== 'disabled';
  });
}

function resolveDeviceSelection(documentValue, routeDeviceId, storedDeviceId){
  const devices = selectableDevices(documentValue);
  const allowed = new Set(devices.map(device => device.device_id));
  const candidates = [
    routeDeviceId,
    storedDeviceId,
    documentValue?.default_device_id,
    devices[0]?.device_id
  ];
  const selectedDeviceId = candidates.find(value => allowed.has(value)) || null;
  const requestedInvalid = (
    (routeDeviceId !== null && routeDeviceId !== undefined && !allowed.has(routeDeviceId)) ||
    (!routeDeviceId && storedDeviceId && !allowed.has(storedDeviceId))
  );
  return {selectedDeviceId, devices, recovered: requestedInvalid};
}

function readStoredDeviceId(storage){
  try{
    const value = storage?.getItem?.(DEVICE_STORAGE_KEY);
    return validDeviceId(value) ? value : null;
  }catch(_error){
    return null;
  }
}

function writeStoredDeviceId(storage, deviceId){
  try{
    if(validDeviceId(deviceId)) storage?.setItem?.(DEVICE_STORAGE_KEY, deviceId);
    else storage?.removeItem?.(DEVICE_STORAGE_KEY);
  }catch(_error){
    // Browser storage may be disabled; selection remains in memory.
  }
}

function browserStorage(){
  try{
    return typeof window === 'undefined' ? null : window.localStorage;
  }catch(_error){
    return null;
  }
}

function selectSingleHost(servers){
  if(!Array.isArray(servers) || servers.length === 0) return null;
  return servers.find(server => server && server.disabled !== true) || servers[0] || null;
}

function normalizeStatsPayload(documentValue){
  const documentObject = documentValue && typeof documentValue === 'object' ? documentValue : {};
  if(Array.isArray(documentObject.servers) &&
    documentObject.servers.length <= MAX_UI_DEVICES) return documentObject;
  return { ...documentObject, servers: [] };
}

function safeObject(value){
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function buildViewModel(documentValue, selectedDeviceId = null){
  const documentObject = normalizeStatsPayload(documentValue);
  const devices = selectableDevices(documentObject);
  const hasV2Devices = documentObject.servers.some(
    server => server && typeof server === 'object' && validDeviceId(server.device_id)
  );
  const host = devices.find(device => device.device_id === selectedDeviceId) ||
    (selectedDeviceId === null ? devices[0] : null) ||
    (!hasV2Devices ? selectSingleHost(documentObject.servers) : null);
	if(!host) return { host: null, devices, document: documentObject, hardware: {}, docker: {}, hermes: {}, lucky: {}, easytier: {}, easytierExpectation: {}, profiles: [], containers: [] };

  const hardware = safeObject(host.hardware);
  const docker = safeObject(host.docker);
	const hermes = safeObject(host.hermes);
	const lucky = safeObject(host.lucky);
	const easytier = safeObject(host.easytier);
  const memoryPercent = percentage(host.memory_used, host.memory_total);
  const diskUsage = homeDiskUsage(host, hardware);
  const cpuPercent = finiteNumber(host.cpu) === null ? null : clamp(host.cpu, 0, 100);

  return {
    document: documentObject,
    devices,
    host,
    hardware,
    docker,
		hermes,
		lucky,
		easytier,
		easytierExpectation: safeObject(host.easytier_expectation),
    profiles: Array.isArray(hermes.profiles) ? hermes.profiles : [],
    containers: Array.isArray(docker.containers) ? docker.containers : [],
    resources: {
      cpuPercent,
      memoryPercent,
      diskPercent: diskUsage.percent,
      cpuModel: cleanCpuModel(hardware.cpu_model ?? host.cpu_model),
      memoryText: finiteNumber(host.memory_used) === null || finiteNumber(host.memory_total) === null
        ? '-'
        : `${formatBytes(host.memory_used * 1000)} / ${formatBytes(host.memory_total * 1000)}`,
      diskText: diskUsage.text,
      diskValueText: diskUsage.valueText,
      diskLabel: diskUsage.label
    }
  };
}

function collectWarnings(view){
	if(!view.host) return [];
	const domains = [view.hardware, view.docker, view.hermes, ...view.profiles];
	if(luckyIsConfigured(view.lucky)) domains.push(view.lucky);
	if(easytierIsConfigured(view.easytier)) domains.push(view.easytier);
	return domains
    .map(domain => domain?.error)
    .filter(error => error && typeof error === 'object' && error.code !== 'not_installed')
    .map(error => textOrDash(error.message || error.code))
    .filter(message => message !== '-');
}

function statusTone(value){
  const status = String(value ?? '').toLowerCase();
  if(status.startsWith('up ') || status.includes('(healthy)')) return 'ok';
  if(status.startsWith('exited') || status.startsWith('dead')) return 'err';
  if(status.startsWith('created') || status.startsWith('paused') || status.startsWith('restarting') || status.startsWith('removing')) return 'warn';
	if(['passed', 'running', 'ok', 'healthy', 'up', 'active', 'valid'].includes(status)) return 'ok';
	if(['degraded', 'partial', 'stale', 'never_seen', 'expiring', 'not_yet_valid', 'identity_error', 'mismatch', 'unsupported', 'unsupported_version'].includes(status)) return 'warn';
	if(['failed', 'down', 'offline', 'disabled', 'stopped', 'unauthorized', 'timeout', 'dead', 'exited', 'error', 'expired', 'invalid', 'unavailable'].includes(status)) return 'err';
  return 'neutral';
}

function statusText(value){
  const status = String(value ?? '').toLowerCase();
  const labels = {
    passed: '通过', failed: '失败', unknown: '未知', unavailable: '不可用',
    running: '运行中', healthy: '正常', ok: '正常', active: '活动',
    stopped: '已停止', down: '离线', unauthorized: '未授权', timeout: '超时',
		exited: '已退出', dead: '异常', degraded: '部分异常', partial: '部分采集', stale: '已陈旧',
		not_configured: '未配置', error: '异常', valid: '有效', expiring: '即将到期',
		expired: '已过期', not_yet_valid: '尚未生效', invalid: '无效',
		supported: '支持', unsupported: '不支持', matched: '匹配', mismatch: '不匹配', not_observable: '未观察到',
    online: '在线', offline: '离线', never_seen: '从未上线', disabled: '已禁用',
    identity_error: '身份异常', matched: '身份匹配', missing_fqdn: '缺少身份信息',
    fqdn_mismatch: '身份不匹配'
  };
  return labels[status] || textOrDash(value);
}

function badge(value){
  return `<span class="badge ${statusTone(value)}">${escapeHtml(statusText(value))}</span>`;
}

function expectationBadge(value){
  const labels = {matched: '匹配', mismatch: '不匹配', not_observable: '未观察到', not_configured: '未配置'};
  return `<span class="badge ${statusTone(value)}">${escapeHtml(labels[value] || textOrDash(value))}</span>`;
}

function domainIsUnknown(value){
  return !value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length === 0;
}

function luckyIsConfigured(lucky){
	return !domainIsUnknown(lucky) && lucky.status !== 'not_configured' && lucky.error?.code !== 'not_reported';
}

function easytierIsConfigured(easytier){
	return !domainIsUnknown(easytier) && easytier.status !== 'not_configured' && easytier.error?.code !== 'not_reported';
}

function dashboardCondition(view, refreshError = null){
  if(refreshError) return {kind: 'error', title: '刷新失败', message: textOrDash(refreshError.message || refreshError)};
  if(!view.host) return {kind: 'empty', title: '暂无主机数据', message: 'stats.json 暂无可显示的主机。'};
  const deviceStatus = String(view.host.status ?? '').toLowerCase();
  if(deviceStatus === 'never_seen'){
    return {kind: 'never-seen', title: '设备从未上线', message: '该设备尚未提交任何有效状态。'};
  }
  if(deviceStatus === 'offline'){
    return {kind: 'offline', title: '设备离线', message: '当前显示该设备最后一次可用的状态数据。'};
  }
  if(deviceStatus === 'identity_error'){
    return {kind: 'error', title: '设备身份异常', message: '该设备最近的身份信息未通过验证。'};
  }
  if(deviceStatus === 'stale'){
    return {kind: 'stale', title: '设备数据已陈旧', message: '该设备的数据已超过刷新时限。'};
  }
  if(deviceStatus === 'degraded'){
    return {kind: 'error', title: '设备部分数据不可用', message: '该设备仍在线，但至少一个业务域异常。'};
  }
  // Device v2 has an authoritative server-side lifecycle status. Its legacy
  // IPv4/IPv6 probe fields are informational and must not mark an online
  // authenticated device as offline.
  const isDeviceV2 = String(view.host.protocol_mode ?? '').toLowerCase() === 'device_v2';
  if(!isDeviceV2 && view.host.online4 === false && view.host.online6 === false){
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
	if(easytierIsConfigured(view.easytier) && view.easytier?.stale === true) staleDomains.push('EasyTier');
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
  const icons = {loading: '↻', empty: '—', offline: '×', error: '!', stale: '◷', unknown: '?', 'never-seen': '○'};
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

function fitSingleLineValue(selector, preferredSize = 23, minimumSize = 10){
  const element = document.querySelector(selector);
  if(!element || element.clientWidth <= 0) return;
  element.style.fontSize = `${preferredSize}px`;
  if(element.scrollWidth <= element.clientWidth) return;
  let size = fittedFontSize(preferredSize, minimumSize, element.clientWidth, element.scrollWidth);
  element.style.fontSize = `${size}px`;
  while(size > minimumSize && element.scrollWidth > element.clientWidth){
    size = Math.max(minimumSize, size - 0.5);
    element.style.fontSize = `${size}px`;
  }
}

function fitSingleLineValues(selector, preferredSize = 23, minimumSize = 10){
  for(const element of document.querySelectorAll(selector)){
    if(element.clientWidth <= 0) continue;
    element.style.fontSize = `${preferredSize}px`;
    if(element.scrollWidth <= element.clientWidth) continue;
    let size = fittedFontSize(preferredSize, minimumSize, element.clientWidth, element.scrollWidth);
    element.style.fontSize = `${size}px`;
    while(size > minimumSize && element.scrollWidth > element.clientWidth){
      size = Math.max(minimumSize, size - 0.5);
      element.style.fontSize = `${size}px`;
    }
  }
}

function fitOverviewSingleLineValues(){
  fitSingleLineValue('[data-fit-single-line="cpu-model"]', 23, 11);
  fitSingleLineValue('[data-fit-single-line="easytier-traffic"]', 23, 10);
  fitSingleLineValues('[data-fit-single-line="hardware-home"]', 23, 10);
}

function easytierCommandAvailable(easytier, name){
  return safeObject(safeObject(easytier).command_status[name]).status === 'healthy';
}

function easytierOverviewText(easytier){
  const peers = safeObject(easytier?.peers);
  const traffic = safeObject(easytier?.traffic);
  return {
    peers: easytierCommandAvailable(easytier, 'peer_list')
      ? `${formatInteger(peers.direct)} / ${formatInteger(peers.relay)} / ${formatInteger(peers.unknown_path)}`
      : '数据不可用',
    traffic: easytierCommandAvailable(easytier, 'stats_show')
      ? `${formatTrafficBytes(traffic.bytes_rx)} / ${formatTrafficBytes(traffic.bytes_tx)} / ${formatTrafficBytes(traffic.bytes_forwarded)}`
      : '数据不可用'
  };
}

function renderOverview(view){
  const resources = view.resources;
  const easytierOverview = easytierOverviewText(view.easytier);
  const peerText = easytierOverview.peers;
  const trafficText = easytierOverview.traffic;
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
      <div class="card-detail resource-value single-line-value" data-fit-single-line="overview-disk" title="${escapeHtml(resources.diskText)}">${escapeHtml(resources.diskValueText)}${parenthesizedMeta(resources.diskLabel)}</div>
      ${resourceBar(resources.diskPercent, '硬盘使用率')}
    </article>
    <article class="summary-card metric-card">
      <h2>EasyTier远端节点数</h2>
      <div class="card-value">${escapeHtml(peerText)}</div>
      <div class="card-mini-meta">直连 / 中继 / 未知</div>
    </article>
    <article class="summary-card metric-card">
      <h2>EasyTier流量统计</h2>
      <div class="card-value traffic-value" data-fit-single-line="easytier-traffic" title="${escapeHtml(trafficText)}">${escapeHtml(trafficText)}</div>
      <div class="card-mini-meta">接收 / 发送 / 转发</div>
    </article>`;
  requestAnimationFrame(fitOverviewSingleLineValues);
}

function renderHardware(view){
  const hardware = view.hardware;
  const docker = view.docker;
  const physicalDisks = physicalDisksForView(hardware);
  const ioDisk = diskIoCandidate(physicalDisks);
  const powerOnDisk = maxDiskBy(physicalDisks, diskPowerOnHours);
  const hottestDisk = maxDiskBy(physicalDisks, diskTemperatureC);
  const hottestCpuSensor = maximumTemperature(temperatureSensorEntries(hardware));
  const readWrite = ioDisk
    ? `${formatBytes(diskWrittenBytes(ioDisk))} / ${formatBytes(diskReadBytes(ioDisk))}`
    : '-';
  const powerOnHours = powerOnDisk ? diskPowerOnHours(powerOnDisk) : null;
  const powerOnDays = approximateDays(powerOnHours);
  const uptime = uptimeHoursMetric(view.host.uptime_seconds);
  byId('hardwareHealth').innerHTML = `
    <article class="health-card"><h2>硬盘 SMART 状态</h2><div class="health-value single-line-value" data-fit-single-line="hardware-home">${smartHomeMarkup(physicalDisks, hardware)}</div></article>
    <article class="health-card"><h2>硬盘写入/读取量</h2><div class="health-value power-on-value single-line-value" data-fit-single-line="hardware-home" title="${escapeHtml(ioDisk ? `${readWrite} (${diskName(ioDisk)})` : readWrite)}">${escapeHtml(readWrite)}${parenthesizedMeta(ioDisk ? diskName(ioDisk) : null)}</div></article>
    <article class="health-card"><h2>硬盘通电时间</h2><div class="health-value power-on-value single-line-value" data-fit-single-line="hardware-home" title="${escapeHtml(powerOnDisk ? `${formatInteger(powerOnHours)} h (约${formatInteger(powerOnDays)}天，${diskName(powerOnDisk)})` : '-')}">${powerOnHours === null ? '-' : `${formatInteger(powerOnHours)} h <span class="power-on-days">(约${formatInteger(powerOnDays)}天，${escapeHtml(diskName(powerOnDisk))})</span>`}</div></article>
    <article class="health-card"><h2>CPU温度</h2><div class="health-value power-on-value single-line-value" data-fit-single-line="hardware-home">${hottestCpuSensor === null ? '-' : `${escapeHtml(formatCelsius(hottestCpuSensor.value))}${parenthesizedMeta(hottestCpuSensor.label)}`}</div></article>
    <article class="health-card"><h2>硬盘温度</h2><div class="health-value power-on-value single-line-value" data-fit-single-line="hardware-home">${hottestDisk === null ? '-' : `${escapeHtml(formatCelsius(diskTemperatureC(hottestDisk)))}${parenthesizedMeta(diskName(hottestDisk))}`}</div></article>
    <article class="health-card"><h2>运行中/容器总数</h2><div class="health-value">${escapeHtml(formatPair(docker.running, docker.total))}</div></article>
    <article class="health-card"><h2>Lucky运行状态/版本</h2><div class="health-value power-on-value">${escapeHtml(statusText(view.lucky.status))}<span class="power-on-days">(${escapeHtml(textOrDash(view.lucky.version?.current))})</span></div></article>
    <article class="health-card"><h2>EasyTier运行状态/版本</h2><div class="health-value power-on-value">${escapeHtml(statusText(view.easytier.status))}<span class="power-on-days">(${escapeHtml(textOrDash(view.easytier.node?.version))})</span></div></article>
    <article class="health-card"><h2>系统已运行时间</h2><div class="health-value power-on-value">${uptime === null ? '-' : `${formatInteger(uptime.hours)} h <span class="power-on-days">(约${uptime.days}天)</span>`}</div></article>
    <article class="health-card"><h2>操作系统版本</h2><div class="health-value health-text" title="${escapeHtml(conciseOsVersion(view.host, view.hardware))}">${escapeHtml(conciseOsVersion(view.host, view.hardware))}</div></article>`;
  requestAnimationFrame(fitOverviewSingleLineValues);
}

function filesystemBackingDisks(filesystem){
  const ids = Array.isArray(filesystem?.backing_disk_ids)
    ? filesystem.backing_disk_ids.map(value => deviceShortName(value)).filter(value => value !== '-')
    : [];
  if(!ids.length) return {text: '-', title: '-'};
  return {
    text: ids.length === 1 ? ids[0] : `${ids.length} 块磁盘`,
    title: ids.join(' / ')
  };
}

function filesystemUsage(filesystem){
  const used = valueAt(filesystem, ['used_bytes']);
  const total = valueAt(filesystem, ['total_bytes', 'capacity_bytes']);
  if(used === null && total === null) return '-';
  return `${formatBytes(used)} / ${formatBytes(total)}`;
}

function cpuDetailsForView(hardware){
  return safeObject(hardware?.cpu_details);
}

function memoryDetailsForView(hardware){
  return safeObject(hardware?.memory_details);
}

function formatMHz(value){
  const number = finiteNumber(value);
  if(number === null) return '-';
  return `${Number.isInteger(number) ? number : number.toFixed(1)} MHz`;
}

function cpuLogicalProcessorText(cpu){
  const logical = finiteNumber(cpu.logical_cpus);
  const sockets = finiteNumber(cpu.sockets);
  const coresPerSocket = finiteNumber(cpu.cores_per_socket);
  const threadsPerCore = finiteNumber(cpu.threads_per_core);
  if(logical === null && sockets === null && coresPerSocket === null && threadsPerCore === null) return '-';
  const cores = sockets !== null && coresPerSocket !== null ? sockets * coresPerSocket : null;
  const threads = logical ?? (cores !== null && threadsPerCore !== null ? cores * threadsPerCore : null);
  const parts = [
    sockets === null ? null : `${formatInteger(sockets)} 插槽`,
    cores === null ? null : `${formatInteger(cores)} 核心`,
    threads === null ? null : `${formatInteger(threads)} 线程`
  ].filter(Boolean);
  const topology = parts.length ? `（${parts.join(' / ')}）` : '';
  return logical === null ? (parts.join(' / ') || '-') : `${formatInteger(logical)}${topology}`;
}

function memoryUsedPercent(memory){
  return percentage(memory?.used_bytes, memory?.total_bytes);
}

function hardwareUsageMarkup(label, value){
  const number = finiteNumber(value);
  return `<article class="hardware-usage-item"><strong>${escapeHtml(label)}</strong>${resourceBar(number, label)}</article>`;
}

function cpuInstructionDetailRow(value){
  return `<div class="detail-row hardware-cpu-instruction-row"><dt>指令集</dt><dd class="wrap-value">${escapeHtml(textOrDash(value))}</dd></div>`;
}

function diskPowerOnText(disk){
  const hours = diskPowerOnHours(disk);
  if(hours === null) return '-';
  return `${formatInteger(hours)} h (约${(hours / 24).toFixed(2)}天)`;
}

function renderPhysicalDiskRows(hardware){
  const physicalDisks = physicalDisksForView(hardware);
  if(!physicalDisks.length) return '<tr><td colspan="6" class="table-empty">暂无可显示的物理磁盘数据</td></tr>';
  return physicalDisks.map(disk => {
    const device = textOrDash(disk.device || disk.id);
    const model = textOrDash(disk.model);
    return `<tr><td class="mono">${escapeHtml(device)}</td><td class="wide-cell" title="${escapeHtml(model)}">${escapeHtml(model)}</td><td>${escapeHtml(formatBytes(valueAt(disk, ['capacity_bytes', 'size_bytes'])))}</td><td>${escapeHtml(formatCelsius(diskTemperatureC(disk)))}</td><td>${diskSmartMarkup(disk)}</td><td>${escapeHtml(diskPowerOnText(disk))}</td></tr>`;
  }).join('');
}

function renderFilesystemDetails(hardware){
  const filesystems = dataFilesystemItemsForView(hardware);
  if(!filesystems.length) return '<tr><td colspan="7" class="table-empty">暂无可显示的卷或文件系统数据</td></tr>';
  return filesystems.map(filesystem => {
    const usage = valueAt(filesystem, ['usage_percent', 'used_percent']);
    const status = filesystem?.collection_status;
    const backing = filesystemBackingDisks(filesystem);
    return `<tr><td class="mono">${escapeHtml(textOrDash(filesystem.mountpoint))}</td><td class="wide-cell mono" title="${escapeHtml(textOrDash(filesystem.source))}">${escapeHtml(textOrDash(filesystem.source))}</td><td>${escapeHtml(textOrDash(filesystem.fs_type || filesystem.filesystem_type))}</td><td title="${escapeHtml(backing.title)}">${escapeHtml(backing.text)}</td><td>${escapeHtml(filesystemUsage(filesystem))}</td><td class="table-usage">${resourceBar(usage, '文件系统使用率')}</td><td>${status === null || status === undefined || status === '' ? '-' : badge(status)}</td></tr>`;
  }).join('');
}

function renderHardwareDetails(view){
  const hardware = view.hardware;
  const cpu = cpuDetailsForView(hardware);
  const cpuUsage = safeObject(cpu.usage);
  const memory = memoryDetailsForView(hardware);
  const identity = safeObject(hardware.system_identity);
  const system = Object.keys(identity).length ? identity : safeObject(hardware.system);
  const prettyName = textOrDash(system.pretty_name || view.host.os);
  const cpuInfo = [
    ['架构', textOrDash(cpu.architecture)],
    ['频率（最低 / 最高）', `${formatMHz(cpu.min_mhz)} / ${formatMHz(cpu.max_mhz)}`],
    ['逻辑处理器', cpuLogicalProcessorText(cpu)],
    ['当前频率', formatMHz(cpu.current_mhz)]
  ];
  byId('hardwareCpuInfo').innerHTML = cpuInfo
    .map(([label, value]) => detailRow(label, escapeHtml(value), 'wrap-value'))
    .concat(cpuInstructionDetailRow(cpu.instruction_sets)).join('');

  const usageItems = [
    ['总使用率', cpuUsage.total_percent], ['I/O 等待', cpuUsage.iowait_percent],
    ['用户态', cpuUsage.user_percent], ['内核态', cpuUsage.system_percent]
  ].filter(([, value]) => finiteNumber(value) !== null);
  byId('hardwareCpuUsageMeta').textContent = usageItems.length ? '短时采样' : '数据不可用';
  byId('hardwareCpuUsage').innerHTML = usageItems.length
    ? usageItems.map(([label, value]) => hardwareUsageMarkup(label, value)).join('')
    : '<div class="table-empty">暂无可显示的 CPU 使用率数据</div>';
  const memoryRows = [
    ['物理内存已用 / 可用 / 总量', finiteNumber(memory.used_bytes) === null && finiteNumber(memory.available_bytes) === null && finiteNumber(memory.total_bytes) === null ? '-' : `${formatBytes(memory.used_bytes)} / ${formatBytes(memory.available_bytes)} / ${formatBytes(memory.total_bytes)} (${formatPercentage(memoryUsedPercent(memory))})`],
    ['活动 / 非活动', `${formatBytes(memory.active_bytes)} / ${formatBytes(memory.inactive_bytes)}`],
    ['可回收 Slab', formatBytes(memory.reclaimable_bytes)],
    ['Swap 内存已用 / 可用 / 总量', finiteNumber(memory.swap_used_bytes) === null && finiteNumber(memory.swap_free_bytes) === null && finiteNumber(memory.swap_total_bytes) === null ? '-' : `${formatBytes(memory.swap_used_bytes)} / ${formatBytes(memory.swap_free_bytes)} / ${formatBytes(memory.swap_total_bytes)} (${formatPercentage(percentage(memory.swap_used_bytes, memory.swap_total_bytes))})`],
    ['Buffers', formatBytes(memory.buffers_bytes)],
    ['Slab', formatBytes(memory.slab_bytes)],
    ['空闲内存', formatBytes(memory.free_bytes)],
    ['页面缓存', formatBytes(memory.cached_bytes)],
    ['Swap Cache', formatBytes(memory.swap_cached_bytes)],
    ['Dirty / Writeback', `${formatBytes(memory.dirty_bytes)} / ${formatBytes(memory.writeback_bytes)}`]
  ];
  const memoryPlaceholders = Array.from({length: Math.max(0, 12 - memoryRows.length)}, () => '<div class="hardware-memory-placeholder" aria-hidden="true"></div>');
  byId('hardwareMemoryInfo').innerHTML = memoryRows
    .map(([label, value]) => detailRow(label, escapeHtml(value), 'memory-value'))
    .concat(memoryPlaceholders).join('');

  byId('hardwareSystemInfo').innerHTML = [
    ['操作系统版本', prettyName],
    ['架构', textOrDash(system.architecture || hardware.architecture)],
    ['内核', textOrDash(system.kernel_release || hardware.kernel_release)]
  ].map(([label, value]) => detailRow(label, escapeHtml(value), 'wrap-value')).join('');

  byId('hardwareDisksBody').innerHTML = renderPhysicalDiskRows(hardware);
  byId('hardwareFilesystemsBody').innerHTML = renderFilesystemDetails(hardware);
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

function luckyServiceSummaryItems(lucky){
	const normalized = safeObject(lucky);
	if(normalized.status === 'not_configured'){
		return [['进程状态', '未配置'], ['API 可用性', '未配置'], ['API 错误', '-']];
	}
	const service = safeObject(normalized.service);
	const serviceError = safeObject(service.error);
	const apiError = serviceError.http_status
		? `HTTP ${serviceError.http_status}`
		: textOrDash(serviceError.code || serviceError.message);
	return [
		['进程状态', service.process_running === null || service.process_running === undefined ? '未知' : service.process_running ? '运行中' : '未运行'],
		['API 可用性', service.api_reachable ? '可用' : '不可用'],
		['API 错误', service.api_reachable ? '-' : apiError]
	];
}

function renderLucky(view){
	byId('luckyServiceSummary').innerHTML = luckyServiceSummaryItems(view.lucky)
		.map(([label, value]) => detailRow(label, escapeHtml(value), 'wrap-value')).join('');
	renderLuckyTables(view);
}

function ipv6UdpDirectText(peers, peerListAvailable){
	if(!peerListAvailable) return '数据不可用';
	return peers.ipv6_udp_direct === null || peers.ipv6_udp_direct === undefined
		? '未观察到'
		: peers.ipv6_udp_direct ? '是' : '否';
}

function renderEasyTier(view){
	const easytier = view.easytier;
	const node = safeObject(easytier.node);
	const peers = safeObject(easytier.peers);
	const routes = safeObject(easytier.routes);
	const connectors = safeObject(easytier.connectors);
	const traffic = safeObject(easytier.traffic);
	const commands = safeObject(easytier.command_status);
	const commandAvailable = name => easytierCommandAvailable(easytier, name);
	const tcpListenerText = commandAvailable('node_info') || commandAvailable('stats_show')
		? booleanText(connectors.tcp_listener_available)
		: '数据不可用';
	const tcpConnectorText = commandAvailable('connector_list')
		? booleanText(connectors.tcp_configured)
		: '数据不可用';
	const tcpActiveText = commandAvailable('connector_list')
		? booleanText(connectors.tcp_active)
		: '数据不可用';
	const trafficText = commandAvailable('stats_show')
		? `${formatBytes(traffic.bytes_rx)} / ${formatBytes(traffic.bytes_tx)} / ${formatBytes(traffic.bytes_forwarded)}`
		: '数据不可用';
	const peerSummary = !commandAvailable('peer_list')
		? '数据不可用'
		: peers.total === 0
		? '0（直连：— / 中继：— / 未知：—）'
		: `${formatInteger(peers.total)}（直连：${formatInteger(peers.direct)} / 中继：${formatInteger(peers.relay)} / 未知：${formatInteger(peers.unknown_path)}）`;
	const details = [
		['网络', escapeHtml(textOrDash(node.network_name))],
		['Overlay IPv4', escapeHtml(textOrDash(node.overlay_ipv4))],
		['节点状态', badge(node.state)],
		['版本兼容性', escapeHtml(easyTierCompatibilityText(node.schema_compatibility))],
		['远端节点', escapeHtml(peerSummary)],
		['IPv6 UDP Direct', escapeHtml(ipv6UdpDirectText(peers, commandAvailable('peer_list')))],
		['路由数', escapeHtml(commandAvailable('route_list') ? formatInteger(routes.total) : '数据不可用')],
		['TCP Listener / Connector / Active', escapeHtml(`${tcpListenerText} / ${tcpConnectorText} / ${tcpActiveText}`)],
		['接收 / 发送 / 转发', escapeHtml(trafficText)]
	];
	byId('easytierSummary').innerHTML = details.map(([label, value]) => detailRow(label, value)).join('');
	byId('easytierMeta').textContent = `更新时间：${formatDateTime(easytier.updated_at)}${easytier.error ? ` · ${textOrDash(easytier.error.message || easytier.error.code)}` : ''}`;
	const expectation = safeObject(view.easytierExpectation);
	const expected = safeObject(expectation.expected);
	const observed = safeObject(expectation.observed);
	const expectationRows = expectation.configured === true ? [
		['Network', textOrDash(expected.network_name), textOrDash(observed.network_name)],
		['Overlay IP', textOrDash(expected.overlay_ipv4), textOrDash(observed.overlay_ipv4)],
		['Proxy CIDRs', listText(expected.proxy_cidrs), listText(observed.proxy_cidrs)],
		['Administrative Role', textOrDash(expected.administrative_role), textOrDash(observed.administrative_role)]
	] : [['EasyTier expectation', '未配置', '—']];
	byId('easytierExpectationBody').innerHTML = expectationRows.map(([label, expectedValue, observedValue], index) => `<tr><td class="strong-cell">${escapeHtml(label)}</td><td>${escapeHtml(expectedValue)}</td><td>${escapeHtml(observedValue)}</td>${index === 0 ? `<td rowspan="${expectationRows.length}">${expectationBadge(expectation.result || 'not_configured')}</td>` : ''}</tr>`).join('');
	const peerItems = Array.isArray(peers.items) ? peers.items : [];
	byId('easytierPeersBody').innerHTML = !commandAvailable('peer_list') ? '<tr><td colspan="10" class="table-empty">节点数据当前不可用。</td></tr>' : peerItems.length ? peerItems.map(peer => `<tr><td>${escapeHtml(textOrDash(peer.hostname || peer.peer_id))}</td><td>${escapeHtml(textOrDash(peer.overlay_ipv4))}</td><td>${escapeHtml(easyTierPathText(peer.path_state))}</td><td>${escapeHtml(listText(peer.established_tunnels))}</td><td>${escapeHtml(textOrDash(peer.address_family))}</td><td>${escapeHtml(formatLatency(peer.latency_ms))}</td><td>${escapeHtml(formatLoss(peer.loss_rate))}</td><td>${escapeHtml(textOrDash(peer.rx_display || formatBytes(peer.rx_bytes)))}</td><td>${escapeHtml(textOrDash(peer.tx_display || formatBytes(peer.tx_bytes)))}</td><td>${escapeHtml(textOrDash(peer.version))}</td></tr>`).join('') : '<tr><td colspan="10" class="table-empty">当前未观察到 EasyTier 节点。</td></tr>';
	const routeItems = Array.isArray(routes.items) ? routes.items : [];
	byId('easytierRoutesBody').innerHTML = !commandAvailable('route_list') ? '<tr><td colspan="7" class="table-empty">路由数据当前不可用。</td></tr>' : routeItems.length ? routeItems.map(route => `<tr><td>${escapeHtml(route.is_local ? '本地' : textOrDash(route.hostname || route.peer_id))}</td><td>${escapeHtml(textOrDash(route.overlay_ipv4))}</td><td>${escapeHtml(listText(route.proxy_cidrs))}</td><td class="mono">${escapeHtml(textOrDash(route.next_hop_peer_id))}</td><td>${escapeHtml(easyTierPathText(route.path_state))}</td><td>${escapeHtml(formatLatency(route.path_latency_ms))}</td><td>${escapeHtml(formatInteger(route.cost))}</td></tr>`).join('') : '<tr><td colspan="7" class="table-empty">当前未观察到 EasyTier 路由。</td></tr>';
	const connectorItems = Array.isArray(connectors.items) ? connectors.items : [];
	byId('easytierConnectorsBody').innerHTML = !commandAvailable('connector_list') ? '<tr><td colspan="3" class="table-empty">连接器数据当前不可用。</td></tr>' : connectorItems.length ? connectorItems.map(connector => `<tr><td>${escapeHtml(textOrDash(connector.transport))}</td><td>${escapeHtml(textOrDash(connector.endpoint || connector.url))}</td><td>${badge(connector.status)}</td></tr>`).join('') : '<tr><td colspan="3" class="table-empty">未配置出站连接器。</td></tr>';
}

function listText(value){ return Array.isArray(value) && value.length ? value.map(textOrDash).join('、') : '-'; }
function easyTierPathText(value){ return ({direct: '直连', relayed: '中继', unknown: '未观察到'})[String(value || '').toLowerCase()] || '-'; }
function easyTierCompatibilityText(value){ return ({supported: '支持', unsupported: '不支持', unknown: '未知'})[String(value || '').toLowerCase()] || '未知'; }
function formatLatency(value){ const number = finiteNumber(value); return number === null ? '-' : `${number.toFixed(1)} ms`; }
function formatLoss(value){ const number = finiteNumber(value); return number === null ? '-' : `${number.toFixed(2)}%`; }

function profileSummary(profiles){
  if(!profiles.length) return '';
  const versions = [...new Set(profiles
    .map(profile => textOrDash(profile.agent_version))
    .filter(version => version !== '-'))];
  const version = versions.length === 1 ? versions[0] : versions.length > 1 ? '多个版本' : '-';
  return `Agent版本: ${version}，${profiles.length}个配置`;
}

function renderProfiles(view){
  byId('profilesMeta').textContent = profileSummary(view.profiles);
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
    </tr>`).join('') : `<tr><td colspan="9" class="table-empty">${view.hermes?.error?.code === 'not_installed' ? '未安装 Hermes Agent' : '暂无 Hermes Profile 数据'}</td></tr>`;
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

function normalizedDeviceStatus(device){
  const status = String(device?.status ?? '').toLowerCase();
  return DEVICE_STATUSES.has(status) ? status : 'unknown';
}

function deviceDisplayName(device){
  const label = textOrDash(device?.display_name || device?.name || device?.device_id);
  return [...label].slice(0, 128).join('');
}

function renderDeviceSelector(view){
  const selector = byId('deviceSelector');
  const buttons = byId('deviceButtons');
  const select = byId('deviceSelect');
  const notice = byId('deviceSelectionNotice');
  const diagnosticsButton = byId('deviceDiagnosticsButton');
  if(!selector || !buttons || !select || !notice || !diagnosticsButton) return;
  buttons.replaceChildren();
  select.replaceChildren();
  const devices = view.devices || [];
  selector.hidden = devices.length === 0;
  for(const device of devices){
    const active = device.device_id === dashboardState.selectedDeviceId;
    const label = deviceDisplayName(device);
    const status = normalizedDeviceStatus(device);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'device-button';
    button.dataset.deviceId = device.device_id;
    button.setAttribute('aria-pressed', String(active));
    button.title = `${label} (${device.device_id})`;
    const name = document.createElement('span');
    name.className = 'device-button-name';
    name.textContent = label;
    const state = document.createElement('span');
    state.className = `device-status ${statusTone(status)}`;
    state.textContent = statusText(status);
    button.append(name, state);
    buttons.append(button);

    const option = document.createElement('option');
    option.value = device.device_id;
    option.textContent = `${label} — ${statusText(status)}`;
    option.selected = active;
    select.append(option);
  }
  select.disabled = devices.length < 2;
  notice.textContent = dashboardState.deviceSelectionNotice;
  notice.hidden = !dashboardState.deviceSelectionNotice;
  diagnosticsButton.disabled = !view.host;
}

function renderDashboard(view){
  dashboardState.view = view;
  renderDeviceSelector(view);
  const hasHost = Boolean(view.host);
  byId('dashboard').hidden = !hasHost;
  if(!hasHost){
    closeProfileModal();
		closeDeviceDiagnostics();
		closeAbout();
    setPageState(dashboardCondition(view));
    return;
  }
  renderOverview(view);
	renderHardware(view);
  renderHardwareDetails(view);
  renderProfiles(view);
	renderContainers(view);
	renderLucky(view);
	renderEasyTier(view);
  if(!byId('deviceDiagnosticsModal').hidden) renderDeviceDiagnostics(view);
  if(!byId('aboutModal').hidden) renderBuildProvenance(view);
  applyPageVisibility();
  setPageState(dashboardCondition(view));
  if(dashboardState.selectedProfileIndex !== null){
    if(view.profiles[dashboardState.selectedProfileIndex]) renderProfileModal(view.profiles[dashboardState.selectedProfileIndex]);
    else closeProfileModal();
  }
}

function replaceDashboardHash(){
  if(typeof window === 'undefined') return;
  const nextHash = canonicalDashboardHash(
    dashboardState.activePage,
    dashboardState.selectedDeviceId
  );
  if(window.location.hash !== nextHash) window.history.replaceState(null, '', nextHash);
}

function selectDevice(deviceId, options = {}){
  const devices = selectableDevices(dashboardState.currentStats);
  if(!devices.some(device => device.device_id === deviceId)) return false;
  dashboardState.selectedDeviceId = deviceId;
  dashboardState.deviceSelectionNotice = options.notice || '';
  writeStoredDeviceId(
    options.storage || browserStorage(),
    deviceId
  );
  renderDashboard(buildViewModel(dashboardState.currentStats, deviceId));
  if(options.updateHash !== false) replaceDashboardHash();
  return true;
}

function applyPageVisibility(){
  const activePage = normalizePageName(dashboardState.activePage);
  dashboardState.activePage = activePage;
	for(const page of ['home', 'hardware', 'docker', 'lucky', 'easytier']){
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
    replaceDashboardHash();
  }
  if(nextPage === 'home') requestAnimationFrame(fitOverviewSingleLineValues);
  return nextPage;
}

function detailRow(label, value, extraClass = ''){
  return `<div class="detail-row"><dt>${escapeHtml(label)}</dt><dd class="${extraClass}">${value}</dd></div>`;
}

function shortRevision(value){
  const revision = textOrDash(value);
  return revision === '-' ? revision : [...revision].slice(0, 12).join('');
}

function revisionMarkup(value){
  const revision = textOrDash(value);
  return revision === '-'
    ? '-'
    : `<span class="mono" title="${escapeHtml(revision)}">${escapeHtml(shortRevision(revision))}</span>`;
}

function deviceDiagnosticsMarkup(view){
  const host = safeObject(view?.host);
  const expectation = safeObject(view?.easytierExpectation);
  const expected = safeObject(expectation.expected);
  const proxyCidrs = Array.isArray(expected.proxy_cidrs)
    ? expected.proxy_cidrs.map(textOrDash).join(' / ')
    : '-';
  const expectationConfigured = expectation.configured === true;
  const lastSeen = host.last_seen_at || host.last_seen || host.received_at;
  const lastAccepted = host.last_accepted_at || host.accepted_at || host.collected_at || host.last_collected_at || view?.hardware?.updated_at;
  return [
    ['Device ID', textOrDash(host.device_id)],
    ['显示名称', deviceDisplayName(host)],
    ['状态', statusText(normalizedDeviceStatus(host))],
    ['身份状态', statusText(host.identity_status)],
    ['协议模式', textOrDash(host.protocol_mode)],
    ['已启用', host.enabled === false || host.disabled === true ? '否' : '是'],
    ['接入模式', textOrDash(host.ingestion_mode)],
    ['最后上线', formatDateTime(lastSeen)],
    ['最后接受 / 采集', formatDateTime(lastAccepted)],
    ['EasyTier 预期已配置', expectationConfigured ? '是' : '否'],
    ['预期网络', expectationConfigured ? textOrDash(expected.network_name) : '-'],
    ['预期 Overlay IP', expectationConfigured ? textOrDash(expected.overlay_ipv4) : '-'],
    ['预期 Proxy CIDRs', proxyCidrs || '-']
  ].map(([label, value]) => detailRow(label, escapeHtml(value), 'wrap-value')).join('');
}

function buildProvenanceMarkup(view){
  const build = safeObject(view?.document?.build);
  const server = Object.keys(safeObject(build.server)).length ? safeObject(build.server) : build;
  const client = safeObject(view?.hardware?.client_build || view?.host?.client_build);
  const environment = textOrDash(build.deployment || build.environment || build.deployment_env || server.environment);
  const protocol = textOrDash(client.protocol || view?.host?.protocol_mode || server.protocol);
  const schema = textOrDash(build.stats_schema || build.schema_version || view?.document?.schema_version);
  return [
    ['环境', escapeHtml(environment)],
    ['服务端版本', escapeHtml(textOrDash(server.version || server.server_version))],
    ['服务端 Revision', revisionMarkup(server.revision || server.server_revision)],
    ['客户端版本', escapeHtml(textOrDash(client.version || client.client_version))],
    ['客户端 Revision', revisionMarkup(client.revision || client.client_revision)],
    ['协议', escapeHtml(protocol)],
    ['Stats Schema', escapeHtml(schema)]
  ].map(([label, value]) => detailRow(label, value, 'wrap-value')).join('');
}

function renderDeviceDiagnostics(view){
  byId('deviceDiagnosticsContent').innerHTML = deviceDiagnosticsMarkup(view);
}

function renderBuildProvenance(view){
  byId('aboutContent').innerHTML = buildProvenanceMarkup(view);
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
	closeDeviceDiagnostics();
	closeAbout();
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

function openDeviceDiagnostics(trigger){
  if(!dashboardState.view?.host) return;
  closeProfileModal();
  closeAbout();
  dashboardState.deviceDiagnosticsTrigger = trigger || document.activeElement;
  renderDeviceDiagnostics(dashboardState.view);
  byId('deviceDiagnosticsModal').hidden = false;
  document.body.classList.add('modal-open');
  byId('deviceDiagnosticsClose').focus();
}

function closeDeviceDiagnostics(){
  const modal = typeof document === 'undefined' ? null : byId('deviceDiagnosticsModal');
  if(!modal || modal.hidden) return;
  modal.hidden = true;
  document.body.classList.remove('modal-open');
  dashboardState.deviceDiagnosticsTrigger?.focus?.();
  dashboardState.deviceDiagnosticsTrigger = null;
}

function openAbout(trigger){
  closeProfileModal();
  closeDeviceDiagnostics();
  dashboardState.aboutTrigger = trigger || document.activeElement;
  renderBuildProvenance(dashboardState.view || {document: {}, host: {}, hardware: {}});
  byId('aboutModal').hidden = false;
  document.body.classList.add('modal-open');
  byId('aboutClose').focus();
}

function closeAbout(){
  const modal = typeof document === 'undefined' ? null : byId('aboutModal');
  if(!modal || modal.hidden) return;
  modal.hidden = true;
  document.body.classList.remove('modal-open');
  dashboardState.aboutTrigger?.focus?.();
  dashboardState.aboutTrigger = null;
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
  const currentStats = normalizeStatsPayload(documentValue);
  const route = parseDashboardHash(
    typeof window === 'undefined' ? '' : window.location.hash
  );
  const storedDeviceId = readStoredDeviceId(browserStorage());
  const selection = resolveDeviceSelection(
    currentStats,
    route.deviceId,
    dashboardState.selectedDeviceId || storedDeviceId
  );
  dashboardState.currentStats = currentStats;
  dashboardState.activePage = route.page;
  dashboardState.selectedDeviceId = selection.selectedDeviceId;
  dashboardState.deviceSelectionNotice = selection.recovered || route.needsRewrite
    ? '原设备选择已失效，已恢复到可用设备。'
    : '';
  writeStoredDeviceId(browserStorage(), selection.selectedDeviceId);
  dashboardState.lastSuccessAt = new Date();
  const view = buildViewModel(currentStats, selection.selectedDeviceId);
  renderDashboard(view);
  replaceDashboardHash();
  byId('lastUpdate').textContent = `上次刷新 ${formatDateTime(dashboardState.lastSuccessAt)}`;
}

function applyRefreshError(error){
  if(!dashboardState.currentStats) byId('dashboard').hidden = true;
  setPageState(dashboardCondition(dashboardState.view || {host: null}, error));
}

function bindInteractions(){
  byId('refreshButton').addEventListener('click', () => dashboardState.controller?.refresh('manual'));
  byId('deviceDiagnosticsButton').addEventListener('click', event => openDeviceDiagnostics(event.currentTarget));
  byId('aboutButton').addEventListener('click', event => openAbout(event.currentTarget));
  for(const tab of document.querySelectorAll('[data-page-target]')){
    tab.addEventListener('click', () => setActivePage(tab.dataset.pageTarget));
    tab.addEventListener('keydown', event => {
      if(!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
			const pages = ['home', 'hardware', 'docker', 'lucky', 'easytier'];
			const current = pages.indexOf(dashboardState.activePage);
			const nextPage = event.key === 'Home' ? pages[0] : event.key === 'End' ? pages[pages.length - 1] : event.key === 'ArrowLeft' ? pages[(current - 1 + pages.length) % pages.length] : pages[(current + 1) % pages.length];
      setActivePage(nextPage);
      byId(`${nextPage}Tab`).focus();
    });
  }
  byId('deviceButtons').addEventListener('click', event => {
    const button = event.target.closest('.device-button');
    if(button) selectDevice(button.dataset.deviceId);
  });
  byId('deviceSelect').addEventListener('change', event => {
    selectDevice(event.target.value);
  });
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
  byId('deviceDiagnosticsClose').addEventListener('click', closeDeviceDiagnostics);
  byId('deviceDiagnosticsModal').addEventListener('click', event => {
    if(event.target === byId('deviceDiagnosticsModal')) closeDeviceDiagnostics();
  });
  byId('aboutClose').addEventListener('click', closeAbout);
  byId('aboutModal').addEventListener('click', event => {
    if(event.target === byId('aboutModal')) closeAbout();
  });
  document.addEventListener('keydown', event => {
    if(event.key === 'Escape'){
      if(!byId('deviceDiagnosticsModal').hidden) closeDeviceDiagnostics();
      else if(!byId('aboutModal').hidden) closeAbout();
      else closeProfileModal();
    }
  });
}

function initDashboard(){
  dashboardState.controller?.stop();
  const initialRoute = parseDashboardHash(window.location.hash);
  dashboardState.activePage = initialRoute.page;
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
      fitOverviewSingleLineValues();
    });
  };
  window.addEventListener('resize', dashboardState.resizeHandler);
  if(dashboardState.hashchangeHandler) window.removeEventListener('hashchange', dashboardState.hashchangeHandler);
  dashboardState.hashchangeHandler = () => {
    const route = parseDashboardHash(window.location.hash);
    setActivePage(route.page, {updateHash: false});
    if(!dashboardState.currentStats) return;
    const selection = resolveDeviceSelection(
      dashboardState.currentStats,
      route.deviceId,
      dashboardState.selectedDeviceId || readStoredDeviceId(browserStorage())
    );
    dashboardState.deviceSelectionNotice = selection.recovered || route.needsRewrite
      ? '原设备选择已失效，已恢复到可用设备。'
      : '';
    if(selection.selectedDeviceId){
      selectDevice(selection.selectedDeviceId, {
        updateHash: false,
        notice: dashboardState.deviceSelectionNotice
      });
    }else{
      dashboardState.selectedDeviceId = null;
      writeStoredDeviceId(browserStorage(), null);
      renderDashboard(buildViewModel(dashboardState.currentStats, null));
    }
    replaceDashboardHash();
  };
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
  DEVICE_STORAGE_KEY,
  MAX_UI_DEVICES,
  approximateDays,
  buildViewModel,
	buildProvenanceMarkup,
  canonicalDashboardHash,
  cleanCpuModel,
  conciseOsVersion,
  collectWarnings,
  cpuLogicalProcessorText,
  createRefreshController,
  dashboardCondition,
  deviceDisplayName,
	deviceDiagnosticsMarkup,
	deviceShortName,
	luckyIsConfigured,
	easytierIsConfigured,
  fittedFontSize,
  formatBytes,
	formatCelsius,
  formatTrafficBytes,
  formatUptimeHours,
	filesystemBackingDisks,
	easytierCommandAvailable,
	easytierOverviewText,
	filesystemItemsForView,
	dataFilesystemItemsForView,
	luckyServiceSummaryItems,
  diskPowerOnText,
  homeDiskUsage,
	memoryDetailsForView,
	memoryUsedPercent,
	ipv6UdpDirectText,
  maximumTemperature,
  physicalDisksForView,
  renderFilesystemDetails,
  renderPhysicalDiskRows,
  formatPair,
  profileSummary,
  modelBreakdown,
  normalizeStatsPayload,
  normalizedDeviceStatus,
  percentage,
  pageFromHash,
  parseDashboardHash,
  profileModalMarkup,
  readStoredDeviceId,
  resolveDeviceSelection,
  normalizePageName,
  selectableDevices,
  selectSingleHost,
  statsUrl,
  statusTone,
	smartHomeMarkup,
  tokenSourceText,
  tokenBreakdown,
	temperatureSensorEntries,
  usageBand,
  validDeviceId,
  writeStoredDeviceId
};

if(typeof module !== 'undefined' && module.exports) module.exports = exported;
if(typeof window !== 'undefined') window.HermesStatusDashboard = exported;
if(typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initDashboard, { once: true });
