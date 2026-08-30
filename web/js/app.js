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
	return ['hardware', 'unifi', 'docker', 'lucky', 'easytier'].includes(value) ? value : 'home';
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
	if(!host) return { host: null, devices, document: documentObject, hardware: {}, docker: {}, hermes: {}, lucky: {}, easytier: {}, unifi: {}, easytierExpectation: {}, profiles: [], containers: [] };

  const hardware = safeObject(host.hardware);
  const docker = safeObject(host.docker);
	const hermes = safeObject(host.hermes);
	const lucky = safeObject(host.lucky);
	const easytier = safeObject(host.easytier);
	const unifi = safeObject(host.unifi);
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
		unifi,
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
	if(['passed', 'running', 'ok', 'healthy', 'up', 'active', 'valid', 'available', 'observed'].includes(status)) return 'ok';
	if(['degraded', 'partial', 'stale', 'never_seen', 'expiring', 'not_yet_valid', 'identity_error', 'mismatch', 'unsupported', 'unsupported_version', 'not_collected', 'not_observed'].includes(status)) return 'warn';
	if(['failed', 'down', 'offline', 'disabled', 'stopped', 'unauthorized', 'timeout', 'dead', 'exited', 'error', 'expired', 'invalid', 'unavailable'].includes(status)) return 'err';
  return 'neutral';
}

function statusText(value){
  const status = String(value ?? '').toLowerCase();
  const labels = {
    passed: '通过', failed: '失败', unknown: '未知', unavailable: '不可用', available: '可用', not_collected: '尚未采集', not_observed: '未观察到', observed: '已观察到', observed_zero_rpm: '已观察到 0 RPM',
    running: '运行中', healthy: '正常', ok: '正常', active: '活动',
    stopped: '已停止', down: '离线', unauthorized: '未授权', timeout: '超时',
		exited: '已退出', dead: '异常', degraded: '部分异常', partial: '部分采集', stale: '已陈旧',
		not_configured: '未配置', error: '异常', valid: '有效', expiring: '即将到期',
		expired: '已过期', not_yet_valid: '尚未生效', invalid: '无效',
		supported: '支持', unsupported: '不支持', matched: '匹配', mismatch: '不匹配', not_observable: '未观察到',
    online: '在线', offline: '离线', up: '在线', connected: '在线', adopted: '在线', active: '在线', down: '离线', disconnected: '离线', never_seen: '从未上线', disabled: '已禁用',
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

function unifiIsConfigured(unifi){
  return !domainIsUnknown(unifi) && unifi.configured === true;
}

function unifiTransportSummary(unifi){
  if(!unifiIsConfigured(unifi)) return {status: 'disabled', text: '未配置'};
  const transport = safeObject(unifi.transport);
  const status = String(transport.status || 'not_collected').toLowerCase();
  if(status === 'available') return {status: unifi.stale ? 'stale' : 'available', text: unifi.stale ? '数据陈旧' : '可用'};
  if(status === 'not_collected') return {status, text: '尚未采集'};
  if(status === 'disabled') return {status, text: '已禁用'};
  return {status: 'unavailable', text: '不可用'};
}

function unifiErrorText(unifi){
  const code = String(safeObject(unifi.error).code || '').toLowerCase();
  const labels = {
    host_key_failure: 'SSH 主机密钥验证失败',
    ssh_auth_failure: 'SSH 身份验证失败',
    ssh_timeout: 'SSH 采集超时',
    ssh_transport_failure: 'SSH 传输不可用',
    parse_failure: '遥测解析失败',
    not_collected: '尚未完成首次采集',
    stale: '遥测数据已陈旧'
  };
  return labels[code] || (code ? 'UniFi 遥测暂不可用' : '-');
}

function unifiPresenceText(value){
  return ({present: '已安装', not_present: '未安装', not_populated: '未装配', unknown: '未知'})[String(value || '').toLowerCase()] || '未知';
}

function unifiObservationText(value, rpm = null){
  const state = String(value || '').toLowerCase();
  if(state === 'observed_zero_rpm') return '已观察到 0 RPM';
  if(state === 'observed') return finiteNumber(rpm) === null ? '已观察到' : `${formatInteger(rpm)} RPM`;
  if(state === 'not_observed') return '未观察到';
  return '未知';
}

function unifiErrorDisplay(unifi){
  const error = unifiErrorText(unifi);
  return error === '-' ? '无' : error;
}

function unifiApiStatusText(unifi){
  const api = safeObject(unifi?.api);
  if(api.status){
    const status = String(api.status).toLowerCase();
    if(status === 'available') return '可用';
    if(status === 'unavailable') return api.error?.code === 'api_auth_failure' ? '认证失败' : '不可用';
    if(status === 'disabled') return '已禁用';
  }
  const explicit = unifi?.api_status ?? unifi?.api_reachable;
  if(typeof explicit === 'boolean') return explicit ? '可用' : '不可用';
  if(explicit && typeof explicit === 'object'){
    const status = String(explicit.status || '').toLowerCase();
    if(['healthy', 'available', 'ok', 'pass'].includes(status)) return '可用';
    if(['unavailable', 'error', 'failed', 'fail'].includes(status)) return '不可用';
  }
  const transport = String(safeObject(unifi?.transport).status || '').toLowerCase();
  if(transport === 'available') return '可用（SSH）';
  if(transport === 'unavailable') return '不可用';
  if(transport === 'not_collected') return '尚未采集';
  return '不适用（SSH）';
}

function unifiCollectionStatus(unifi){
  const transport = safeObject(unifi?.transport);
  const transportStatus = String(transport.status || '').toLowerCase();
  const ssh = transportStatus === 'available' && unifi.stale !== true
    ? '成功'
    : transportStatus === 'disabled' || transportStatus === 'not_configured'
      ? '未配置'
      : transportStatus === 'not_collected'
        ? '未采集'
        : '失败';
  const api = safeObject(unifi?.api);
  const apiStatus = String(api.status || '').toLowerCase();
  const apiText = apiStatus === 'available'
    ? '成功'
    : apiStatus === 'partial'
      ? '部分成功'
      : apiStatus === 'disabled' || (!apiStatus && unifi?.api_reachable === undefined)
        ? '未配置'
        : apiStatus === 'not_collected'
          ? '未采集'
          : '失败';
  return {ssh, api: apiText};
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

function fitUniFiSingleLineValues(){
  fitSingleLineValues('[data-fit-single-line="unifi-primary-value"]', 23, 11);
  fitSingleLineValue('[data-fit-single-line="unifi-load"]', 23, 11);
}

function easytierCommandAvailable(easytier, name){
  const commands = safeObject(safeObject(easytier).command_status);
  return safeObject(commands[name]).status === 'healthy';
}

function easytierOverviewText(easytier){
  const peers = safeObject(easytier?.peers);
  const traffic = safeObject(easytier?.traffic);
  return {
    peers: easytierCommandAvailable(easytier, 'peer_list')
      ? finiteNumber(peers.total) === 0
        ? '0（— / — / —）'
        : `${formatInteger(peers.direct)} / ${formatInteger(peers.relay)} / ${formatInteger(peers.unknown_path)}`
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


function unifiSystemValues(unifi){
  const system = safeObject(unifi.system);
  const memory = safeObject(system.memory);
  const load = safeObject(system.load_average);
  const cpu = finiteNumber(system.cpu_usage_percent);
  const memoryPercent = finiteNumber(memory.used_percent);
  const loadValues = [load.one_minute, load.five_minutes, load.fifteen_minutes]
    .map(value => finiteNumber(value) === null ? null : finiteNumber(value));
  const loadText = loadValues.map(value => value === null ? '-' : value.toFixed(2)).join(' / ');
  return {
    system,
    memory,
    cpu,
    memoryPercent,
    loadValues,
    loadText,
    cpuText: cpu === null ? '-' : formatPercentage(cpu),
    memoryText: finiteNumber(memory.used_bytes) === null || finiteNumber(memory.total_bytes) === null
      ? '-'
      : `${formatBytes(memory.used_bytes)} / ${formatBytes(memory.total_bytes)}`,
    memorySource: memory.available_source === 'fallback_memfree_buffers_cached'
      ? '（可用内存回退估算）' : ''
  };
}

function unifiSystemRows(unifi){
  const values = unifiSystemValues(unifi);
  const {system, memory, cpu, cpuText, memoryText, memorySource, loadText} = values;
  return [
    ['CPU 使用率', resourceBar(cpu, 'UniFi CPU 使用率')],
    ['CPU 温度', escapeHtml(formatCelsius(system.cpu_temperature_c))],
    ['内存已用 / 总量', `${escapeHtml(memoryText)}${memorySource ? `<span class="health-inline-meta">${escapeHtml(memorySource)}</span>` : ''}`],
    ['内存使用率', values.memoryPercent === null ? '-' : resourceBar(values.memoryPercent, 'UniFi 内存使用率')],
    ['运行时间', escapeHtml(formatUptime(system.uptime_seconds))],
    ['负载 (1 / 5 / 15m)', escapeHtml(loadText)]
  ];
}

function unifiCpuModel(unifi){
  const system = safeObject(unifi?.system);
  const candidate = system.cpu_model ?? system.processor_model ?? unifi?.cpu_model;
  const model = textOrDash(candidate);
  return model === '-' ? 'CPU 型号未提供' : model;
}

function unifiSystemCards(unifi){
  const values = unifiSystemValues(unifi);
  const {system, cpu, memoryPercent, loadText, cpuText, memoryText} = values;
  const hasSystem = Object.keys(system).length > 0;
  if(!hasSystem) return '<div class="table-empty">暂无可显示的 UniFi 遥测。</div>';
  const api = safeObject(unifi?.api);
  const telemetry = safeObject(api.telemetry);
  const identity = safeObject(telemetry.identity);
  const controller = safeObject(telemetry.controller);
  const clients = safeObject(telemetry.clients);
  const networks = safeObject(telemetry.networks);
  const deviceName = textOrDash(identity.display_name || identity.name || identity.model);
  const deviceModel = textOrDash(identity.model);
  const deviceStatus = identity.status ? statusText(identity.status) : '-';
  const deviceVersion = textOrDash(identity.firmware);
  const appStatus = controller.state ? statusText(controller.state) : '-';
  const appVersion = textOrDash(controller.application_version);
  const connectedClientParts = [clients.total, clients.wired, clients.wireless].map(formatInteger);
  const connectedClientText = `${connectedClientParts[0]} (${connectedClientParts[1]} / ${connectedClientParts[2]})`;
  const networkSummary = [networks.total, networks.vlan].map(formatInteger).join(' / ');
  const uptime = formatUptimeHours(system.uptime_seconds);
  const model = unifiCpuModel(unifi);
  const memoryValue = memoryText === '-' ? '内存数据不可用' : memoryText;
  const secondary = value => `<div class="card-mini-meta">${escapeHtml(value)}</div>`;
  const version = value => value === '-' ? '' : ` <span class="unifi-status-version">(${escapeHtml(value)})</span>`;
  return `<div class="unifi-system-cards overview-grid" aria-label="UniFi 摘要">
    <article class="summary-card metric-card unifi-device-card">
      <h2>设备名称/型号</h2>
      <div class="card-value" data-fit-single-line="unifi-device-name" title="${escapeHtml(deviceName)}">${escapeHtml(deviceName)}</div>
      <div class="card-subvalue" title="${escapeHtml(deviceModel)}">${escapeHtml(deviceModel)}</div>
    </article>
    <article class="summary-card resource-card">
      <h2>CPU</h2>
      <div class="card-detail resource-value unifi-primary-value" data-fit-single-line="unifi-primary-value" title="${escapeHtml(model)}">${escapeHtml(model)}</div>
      ${resourceBar(cpu, 'UniFi CPU 使用率')}
    </article>
    <article class="summary-card resource-card">
      <h2>内存</h2>
      <div class="card-detail resource-value unifi-memory-detail" title="${escapeHtml(memoryValue)}">${escapeHtml(memoryValue)}</div>
      ${memoryPercent === null ? '<div class="card-value unifi-card-unavailable">数据不可用</div>' : resourceBar(memoryPercent, 'UniFi 内存使用率')}
    </article>
    <article class="summary-card metric-card unifi-load-card">
      <h2>负载</h2>
      <div class="card-value" data-fit-single-line="unifi-load" title="${escapeHtml(loadText)}">${escapeHtml(loadText)}</div>
      ${secondary('1m / 5m / 15m')}
    </article>
    <article class="summary-card metric-card unifi-client-card">
      <h2>连接客户端</h2>
      <div class="card-value" data-fit-single-line="unifi-client-counts" title="${escapeHtml(connectedClientText)}">${escapeHtml(connectedClientText)}</div>
      ${secondary('总数 (有线 / 无线)')}
    </article>
    <article class="summary-card metric-card">
      <h2>CPU 温度</h2>
      <div class="card-value unifi-primary-value" data-fit-single-line="unifi-primary-value">${escapeHtml(formatCelsius(system.cpu_temperature_c))}</div>
    </article>
    <article class="summary-card metric-card">
      <h2>运行时间</h2>
      <div class="card-value unifi-uptime-value">${escapeHtml(uptime.split(' (')[0])}${uptime.includes(' (') ? ` <span class="power-on-days">(${escapeHtml(uptime.split(' (')[1].replace(/\)$/, ''))})</span>` : ''}</div>
    </article>
    <article class="summary-card metric-card unifi-status-card">
      <h2>控制器状态 (版本)</h2>
      <div class="card-value">${escapeHtml(deviceStatus)}${version(deviceVersion)}</div>
    </article>
    <article class="summary-card metric-card unifi-status-card">
      <h2>网络应用状态 (版本)</h2>
      <div class="card-value">${escapeHtml(appStatus)}${version(appVersion)}</div>
    </article>
    <article class="summary-card metric-card unifi-network-card">
      <h2>网络摘要</h2>
      <div class="card-value" data-fit-single-line="unifi-network-summary">${escapeHtml(networkSummary)} <span class="card-mini-meta">(网络 / VLAN)</span></div>
    </article>
  </div>`;
}

function unifiFanRows(unifi){
  const fans = Array.isArray(unifi.fans) ? unifi.fans : [];
  if(!fans.length) return '<tr><td colspan="5" class="table-empty">暂无可显示的风扇观测。</td></tr>';
  return fans.map(fan => {
    const rpm = finiteNumber(fan.rpm);
    const rpmText = rpm === null ? '—' : `${formatInteger(rpm)} RPM`;
    return `<tr><td class="strong-cell mono">${escapeHtml(textOrDash(fan.id))}</td><td>${badge(fan.supported)}</td><td>${escapeHtml(unifiPresenceText(fan.present))}</td><td>${escapeHtml(rpmText)}</td><td>${fan.error ? escapeHtml(unifiErrorText({error: fan.error})) : '无'}</td></tr>`;
  }).join('');
}

function unifiPoeProfile(unifi){
  return safeObject(unifi?.poe);
}

function unifiPowerProfile(unifi){
  return safeObject(unifi?.power);
}

function unifiPowerRows(unifi){
  const supplies = Array.isArray(unifi.power_supplies) ? unifi.power_supplies : [];
  const powerProfile = unifiPowerProfile(unifi);
  if(unifi?.profile !== 'udw' || powerProfile.supported !== true) return '<tr><td colspan="6" class="table-empty">该机型无相关参数可供展示</td></tr>';
  if(!supplies.length) return '<tr><td colspan="6" class="table-empty">暂无可显示的电源观测。</td></tr>';
  return supplies.map(supply => {
    const watts = finiteNumber(supply.power_watts ?? supply.power_w ?? supply.watts);
    const maximum = finiteNumber(supply.max_power_w ?? supply.power_max_w ?? supply.max_watts ?? powerProfile.max_power_w);
    const fanRpm = finiteNumber(supply.fan_rpm ?? supply.cooling_fan_rpm);
    const unsupported = supply.supported === 'unsupported' || supply.supported === false;
    const powerText = unsupported ? '-' : watts === null && maximum === null ? '-' : `${watts === null ? '-' : unifiPowerText(watts)}${maximum === null ? '' : ` / ${unifiPowerText(maximum)}`}`;
    const powerPercent = !unsupported && watts !== null && maximum !== null && maximum > 0 ? (watts / maximum) * 100 : null;
    const powerMarkup = `<div class="unifi-power-inline"><div class="unifi-power-value">${escapeHtml(powerText)}</div>${powerPercent === null ? '' : resourceBar(powerPercent, '电源功率使用率')}</div>`;
    const fanText = fanRpm === null ? '未提供' : `${formatInteger(fanRpm)} RPM`;
    return `<tr><td class="strong-cell mono">${escapeHtml(textOrDash(supply.id))}</td><td>${badge(supply.supported)}</td><td>${escapeHtml(unifiPresenceText(supply.present))}</td><td>${powerMarkup}</td><td>${escapeHtml(fanText)}</td><td>${supply.error ? escapeHtml(unifiErrorText({error: supply.error})) : '无'}</td></tr>`;
  }).join('');
}

function unifiStorageUsage(capability){
  const used = valueAt(capability, ['used_bytes', 'bytes_used']);
  const total = valueAt(capability, ['total_bytes', 'capacity_bytes']);
  const percent = valueAt(capability, ['usage_percent', 'used_percent']);
  return {
    usedText: used === null || total === null ? '未采集' : `${formatBytes(used)} / ${formatBytes(total)}`,
    percentMarkup: percent === null ? '未采集' : resourceBar(percent, '存储使用率')
  };
}

function unifiStorageRows(unifi){
  const storage = safeObject(unifi?.storage);
  const labels = {nvme: 'NVMe', sata_ssd: 'SATA SSD', tf: 'TF'};
  return Object.entries(labels).filter(([key]) => Object.prototype.hasOwnProperty.call(storage, key)).map(([key, label]) => {
    const capability = safeObject(storage[key]);
    const unsupported = capability.supported === 'unsupported';
    const notInstalled = capability.present === 'not_present' || capability.present === 'not_populated';
    const capacity = finiteNumber(capability.capacity_bytes);
    const capacityText = unsupported || notInstalled ? '-' : capacity === null ? '容量未知' : formatBytes(capacity);
    const observation = unsupported || notInstalled ? '-' : capability.observed === true ? '已观察到' : '未观察到';
    const usage = unsupported || notInstalled ? {usedText: '-', percentMarkup: '-'} : unifiStorageUsage(capability);
    const value = [
      badge(capability.supported),
      escapeHtml(unsupported ? '-' : unifiPresenceText(capability.present)),
      escapeHtml(observation),
      `<span class="health-inline-meta">${escapeHtml(capacityText)}</span>`,
      `<span class="health-inline-meta">${escapeHtml(usage.usedText)}</span>`
    ].join(' · ');
    return [label, value];
  });
}

function unifiStorageMarkup(unifi){
  const storage = safeObject(unifi?.storage);
  const labels = {nvme: 'NVMe', sata_ssd: 'SATA SSD', tf: 'TF'};
  const entries = Object.entries(labels).filter(([key]) => Object.prototype.hasOwnProperty.call(storage, key));
  if(!entries.length) return '<div class="table-empty">暂无可显示的存储能力。</div>';
  const rows = entries.map(([key, label]) => {
    const capability = safeObject(storage[key]);
    const unsupported = capability.supported === 'unsupported';
    const notInstalled = capability.present === 'not_present' || capability.present === 'not_populated';
    const usage = unsupported || notInstalled ? {usedText: '-', percentMarkup: '-'} : unifiStorageUsage(capability);
    const capacity = finiteNumber(capability.capacity_bytes);
    const presence = unsupported ? '-' : unifiPresenceText(capability.present);
    const observation = unsupported || notInstalled ? '-' : capability.observed === true ? '已观察到' : '未观察到';
    const capacityText = unsupported || notInstalled ? '-' : capacity === null ? '容量未知' : formatBytes(capacity);
    return `<tr><td class="strong-cell">${escapeHtml(label)}</td><td>${badge(capability.supported)}</td><td>${escapeHtml(presence)}</td><td>${escapeHtml(observation)}</td><td>${escapeHtml(capacityText)}</td><td>${escapeHtml(usage.usedText)}</td><td class="table-usage">${usage.percentMarkup}</td></tr>`;
  }).join('');
  return `<div class="table-wrap"><table class="data unifi-storage-table"><thead><tr><th>类型</th><th>支持能力</th><th>在位</th><th>观测</th><th>容量</th><th>已用 / 总容量</th><th>使用率</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function unifiApiBoolean(value){
  return value === true ? '在线' : value === false ? '离线' : '未知';
}

function unifiApiNumber(value, suffix = ''){
  const number = finiteNumber(value);
  return number === null ? '-' : `${formatInteger(number)}${suffix}`;
}

function unifiApiTelemetryMarkup(unifi){
  const api = safeObject(unifi?.api);
  if(!api.enabled || api.status === 'disabled') return '<div class="unifi-api-unavailable">API 未启用；SSH 遥测仍作为主数据源。</div>';
  const telemetry = safeObject(api.telemetry);
  if(!Object.keys(telemetry).length) return `<div class="unifi-api-unavailable">API ${api.status === 'partial' ? '部分可用' : '暂无可用'}，未取得可显示摘要。</div>`;
  const identity = safeObject(telemetry.identity);
  const rawUplinks = Array.isArray(telemetry.uplinks) ? telemetry.uplinks : [];
  const uplinks = rawUplinks.length ? rawUplinks : (identity.model ? [{name: identity.model, link_state: identity.status}] : []);
  if(!uplinks.length) return '<div class="unifi-api-unavailable">API 已连接，但当前响应未提供可显示的 UniFi 设备。</div>';
  const rows = uplinks.map(item => `<tr><td class="strong-cell">${escapeHtml(textOrDash(item.name))}</td><td>${escapeHtml(item.link_state ? statusText(item.link_state) : '-')}</td><td>${escapeHtml(unifiLinkBandwidth(item.speed_mbps))}</td></tr>`).join('');
  return `<div class="table-wrap"><table class="data unifi-api-table"><thead><tr><th>UniFi 设备型号</th><th>状态</th><th>链路</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function unifiLinkBandwidth(value){
  const number = finiteNumber(value);
  if(number === null || number <= 0) return '-';
  if(number >= 10000) return '10 GbE';
  if(number >= 2500) return '2.5 GbE';
  if(number >= 1000) return `${Number.isInteger(number / 1000) ? number / 1000 : (number / 1000).toFixed(1)} GbE`;
  if(number >= 100) return 'FE';
  return `${formatInteger(number)} Mbps`;
}

function unifiPortRate(value){
  const number = finiteNumber(value);
  if(number === null || number < 0) return '-';
  if(number >= 1e9) return `${(number / 1e9).toFixed(number >= 1e10 ? 0 : 1)} Gbps`;
  if(number >= 1e6) return `${(number / 1e6).toFixed(number >= 1e7 ? 0 : 1)} Mbps`;
  if(number >= 1e3) return `${(number / 1e3).toFixed(number >= 1e4 ? 0 : 1)} Kbps`;
  return `${formatInteger(number)} bps`;
}

function unifiPortStatus(port){
  if(port?.uplink === true) return '上行';
  if(port?.up === true) return '已连接';
  if(port?.up === false || port?.enabled === false) return '未连接';
  return '未知';
}

function unifiPortStatusMarkup(port){
  const text = unifiPortStatus(port);
  const tone = text === '已连接' || text === '上行' ? 'ok' : text === '未连接' ? 'warn' : 'neutral';
  return `<span class="badge ${tone}">${text}</span>`;
}

function unifiPowerText(value){
  const number = finiteNumber(value);
  if(number === null || number <= 0) return '-';
  return `${Number(number.toFixed(number >= 10 ? 1 : 2))} W`;
}

function unifiPortPoeText(port, profile = null){
  const profilePoe = profile && Object.keys(profile).length ? profile : null;
  const poe = safeObject(port?.poe);
  if(profilePoe?.supported === false) return '-';
  if(!Object.keys(poe).length && profilePoe?.supported !== true) return '-';
  if(poe.supported === false && profilePoe?.supported !== true) return '-';
  const current = unifiPowerText(poe.power_w);
  const configuredMaximum = profilePoe?.port_max_power_w?.[String(port?.port_idx)] ?? profilePoe?.port_max_power_w?.[port?.port_idx];
  const maximum = unifiPowerText(poe.max_power_w ?? configuredMaximum);
  if(current === '-' && maximum === '-') return '-';
  return `${current} / ${maximum}`;
}

function unifiPortLinkText(port){
  const maximum = unifiLinkBandwidth(port?.max_speed_mbps);
  if(port?.up !== true) return maximum === '-' ? '未连接' : `未连接 / ${maximum}`;
  const current = unifiLinkBandwidth(port.speed_mbps);
  if(current === '-' && maximum === '-') return '-';
  return `${current} / ${maximum}`;
}

function unifiPortTraffic(value){
  const number = finiteNumber(value);
  return number === null || number < 0 ? '-' : formatBytes(number);
}

function unifiPortErrorText(port){
  const values = [port?.tx_errors, port?.tx_dropped, port?.rx_errors, port?.rx_dropped]
    .map(value => finiteNumber(value));
  if(values.every(value => value === null)) return '-';
  return values.map(value => value === null ? '-' : formatInteger(value)).join(' / ');
}

function unifiWanMarkup(unifi){
  const telemetry = safeObject(safeObject(unifi?.api).telemetry);
  const wans = Array.isArray(telemetry.wans) ? telemetry.wans : [];
  if(!wans.length) return '<div class="unifi-api-unavailable">未观察到 WAN 数据。</div>';
  const roleText = role => role === 'active' ? '主用' : role === 'backup' ? '备用' : '未知';
  const speedTestText = speedtest => {
    if(!speedtest || speedtest.observed !== true) return '-';
    const parts = [];
    const latency = finiteNumber(speedtest.latency_ms);
    const download = finiteNumber(speedtest.download_mbps);
    const upload = finiteNumber(speedtest.upload_mbps);
    if(latency !== null) parts.push(`${latency.toFixed(1)} ms`);
    if(download !== null) parts.push(`↓ ${download.toFixed(1)} Mbps`);
    if(upload !== null) parts.push(`↑ ${upload.toFixed(1)} Mbps`);
    return parts.length ? `最近测速 ${parts.join(' / ')}` : '-';
  };
  const rows = wans.map(wan => {
    const state = textOrDash(wan.link_state || (wan.online === true ? 'ONLINE' : wan.online === false ? 'OFFLINE' : null));
    const provider = [textOrDash(wan.isp), wan.asn ? `AS${String(wan.asn)}` : null].filter(value => value && value !== '-').join(' / ') || '-';
    const link = unifiLinkBandwidth(wan.link_speed_mbps);
    return `<tr><td class="strong-cell">${escapeHtml(textOrDash(wan.name || wan.id))}</td><td>${escapeHtml(statusText(state))}</td><td>${escapeHtml(roleText(wan.role))}</td><td>${escapeHtml(provider)}</td><td>${escapeHtml(link)}</td><td>${escapeHtml(speedTestText(wan.speedtest))}</td></tr>`;
  }).join('');
  return `<div class="table-wrap"><table class="data unifi-wan-table"><thead><tr><th>WAN</th><th>状态</th><th>角色</th><th>ISP / ASN</th><th>链路</th><th>最近测速</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function unifiIpSortKey(value){
  let text = typeof value === 'string' ? value.trim() : '';
  if(!text) return null;
  const zone = text.indexOf('%');
  if(zone >= 0) text = text.slice(0, zone);
  if(text.startsWith('[') && text.endsWith(']')) text = text.slice(1, -1);
  const ipv4 = text.split('.');
  if(ipv4.length === 4 && ipv4.every(part => /^(0|[1-9][0-9]*)$/.test(part) && Number(part) <= 255)){
    return {family: 4, value: ipv4.reduce((sum, part) => sum * 256n + BigInt(Number(part)), 0n), text};
  }
  const lower = text.toLowerCase();
  const sections = lower.split('::');
  if(sections.length > 2) return null;
  const expand = part => {
    if(!part) return [];
    const values = part.split(':');
    const result = [];
    for(const value of values){
      if(value.includes('.')){
        const octets = value.split('.');
        if(octets.length !== 4 || !octets.every(item => /^(0|[1-9][0-9]*)$/.test(item) && Number(item) <= 255)) return null;
        result.push((Number(octets[0]) * 256 + Number(octets[1])).toString(16));
        result.push((Number(octets[2]) * 256 + Number(octets[3])).toString(16));
      }else if(/^[0-9a-f]{1,4}$/.test(value)){
        result.push(value);
      }else{
        return null;
      }
    }
    return result;
  };
  const left = expand(sections[0]);
  const right = sections.length === 2 ? expand(sections[1]) : [];
  if(!left || !right || (sections.length === 1 && left.length !== 8) || (sections.length === 2 && left.length + right.length >= 8)) return null;
  const groups = sections.length === 2 ? left.concat(Array(8 - left.length - right.length).fill('0'), right) : left;
  if(groups.length !== 8) return null;
  const valueNumber = groups.reduce((sum, part) => sum * 65536n + BigInt(parseInt(part, 16)), 0n);
  return {family: 6, value: valueNumber, text: lower};
}

function compareUnifiManagementIp(left, right){
  const leftKey = unifiIpSortKey(left);
  const rightKey = unifiIpSortKey(right);
  if(!leftKey && !rightKey) return String(left || '').localeCompare(String(right || ''));
  if(!leftKey) return 1;
  if(!rightKey) return -1;
  if(leftKey.family !== rightKey.family) return leftKey.family - rightKey.family;
  if(leftKey.value < rightKey.value) return -1;
  if(leftKey.value > rightKey.value) return 1;
  return leftKey.text.localeCompare(rightKey.text);
}

function unifiPortTelemetryMarkup(unifi){

  const api = safeObject(unifi?.api);
  if(!api.enabled || api.status === 'disabled') return '<div class="unifi-api-unavailable">API 未启用；端口遥测不可用。</div>';
  const telemetry = safeObject(api.telemetry);
  const ports = Array.isArray(telemetry.ports) ? telemetry.ports.slice(0, 64) : [];
  const sortedPorts = ports.sort((a, b) => (finiteNumber(a?.port_idx) ?? Number.MAX_SAFE_INTEGER) - (finiteNumber(b?.port_idx) ?? Number.MAX_SAFE_INTEGER));
  const identity = safeObject(telemetry.identity);
  const descriptors = new Map();
  const uplinks = Array.isArray(telemetry.uplinks) ? telemetry.uplinks : [];
  uplinks.forEach(item => {
    const id = typeof item?.device_id === 'string' ? item.device_id.trim() : '';
    if(!id) return;
    const current = descriptors.get(id) || {device_id: id};
    for(const field of ['name', 'model', 'device_type', 'management_ip']){
      if((current[field] === undefined || current[field] === null || current[field] === '') && item?.[field] !== undefined && item?.[field] !== null) current[field] = String(item[field]);
    }
    if(typeof item?.online === 'boolean') current.online = item.online;
    descriptors.set(id, current);
  });
  const groups = new Map();
  ports.forEach((port, index) => {
    const id = typeof port?.device_id === 'string' ? port.device_id.trim() : '';
    const key = id || 'default';
    if(!groups.has(key)) groups.set(key, []);
    groups.get(key).push({port, index});
  });
  if(!groups.size) groups.set('default', []);
  const deviceLabel = (key, descriptor) => {
    let label = descriptor?.name || descriptor?.model || (key === 'default' ? identity.display_name || identity.model : key);
    label = textOrDash(label);
    if(descriptor?.online === false) label += '（离线）';
    return label;
  };
  const orderedGroups = [...groups.entries()].sort((left, right) => {
    const leftDescriptor = descriptors.get(left[0]);
    const rightDescriptor = descriptors.get(right[0]);
    const ipOrder = compareUnifiManagementIp(leftDescriptor?.management_ip, rightDescriptor?.management_ip);
    if(ipOrder) return ipOrder;
    const idOrder = String(left[0]).localeCompare(String(right[0]));
    if(idOrder) return idOrder;
    return left[1][0]?.index - right[1][0]?.index;
  }).map(([key, entries]) => {
    entries.sort((left, right) => {
      const leftPort = finiteNumber(left.port?.port_idx) ?? Number.MAX_SAFE_INTEGER;
      const rightPort = finiteNumber(right.port?.port_idx) ?? Number.MAX_SAFE_INTEGER;
      return leftPort - rightPort || left.index - right.index;
    });
    return [key, entries.map(entry => entry.port)];
  });
  const groupEntries = orderedGroups.map(([key, items], index) => ({
    key: 'unifi-device-' + index,
    sourceKey: key,
    label: deviceLabel(key, descriptors.get(key)),
    ports: items
  }));
  const tabs = groupEntries.map((group, index) => `<button id="${group.key}-tab" class="unifi-network-tab" type="button" role="tab" aria-selected="${index === 0 ? 'true' : 'false'}" aria-controls="${group.key}-panel" data-unifi-device-tab="${group.key}" tabindex="${index === 0 ? '0' : '-1'}">${escapeHtml(group.label)}</button>`).join('');
  const globalSummary = safeObject(telemetry.port_summary);
  const profilePoe = unifiPoeProfile(unifi);
  const groupPoeSummary = ports => {
    const poe = ports.map(port => safeObject(port?.poe)).filter(item => item.supported !== false);
    const current = poe.map(item => finiteNumber(item.power_w)).filter(value => value !== null);
    const maximum = poe.map(item => finiteNumber(item.max_power_w)).filter(value => value !== null);
    return {
      current: current.length ? current.reduce((sum, value) => sum + value, 0) : null,
      maximum: maximum.length ? maximum.reduce((sum, value) => sum + value, 0) : null
    };
  };
  const poeSummaryMarkup = (summary, fallback = false) => {
    if(profilePoe.supported !== true) return '';
    const currentValue = summary.current ?? (fallback ? globalSummary.poe_total_power_w : null);
    if(!fallback && summary.current === null && summary.maximum === null) return '';
    const maximumValue = fallback
      ? (finiteNumber(globalSummary.poe_max_power_w) ?? finiteNumber(profilePoe.total_max_power_w) ?? finiteNumber(summary.maximum))
      : finiteNumber(summary.maximum);
    const current = unifiPowerText(currentValue);
    const maximum = unifiPowerText(maximumValue);
    const poeText = current === '-' && maximum === '-' ? '-' : `${current}${maximum === '-' ? '' : ` / ${maximum}`}`;
    const percent = finiteNumber(currentValue) !== null && finiteNumber(maximumValue) > 0 ? (finiteNumber(currentValue) / finiteNumber(maximumValue)) * 100 : null;
    return `<div class="unifi-port-summary"><div class="unifi-poe-summary-value">PoE 总功率 ${escapeHtml(poeText)}</div>${percent === null ? '' : resourceBar(percent, 'PoE 总功率使用率')}</div>`;
  };
  const panels = groupEntries.map((group, index) => {
    const rows = group.ports.map(port => {
    const portName = textOrDash(port.name) === '-' ? `Port ${formatInteger(port.port_idx)}` : textOrDash(port.name);
    return `<tr><td class="strong-cell">${escapeHtml(portName)}</td><td>${escapeHtml(formatInteger(port.port_idx))}</td><td>${unifiPortStatusMarkup(port)}</td><td>${escapeHtml(unifiPortLinkText(port))}</td><td>${escapeHtml(unifiPortPoeText(port, profilePoe))}</td><td>${escapeHtml(unifiPortTraffic(port.tx_bytes))}</td><td>${escapeHtml(unifiPortTraffic(port.rx_bytes))}</td><td>${escapeHtml(unifiPortErrorText(port))}</td></tr>`;
    }).join('');
    const body = rows || '<tr><td colspan="8" class="table-empty">当前未取得该设备端口数据。</td></tr>';
    const summary = groupPoeSummary(group.ports);
    const fallback = groupEntries.length === 1 || index === 0;
    return `<section id="${group.key}-panel" class="unifi-device-panel" role="tabpanel" aria-labelledby="${group.key}-tab" data-unifi-device-panel="${group.key}"${index === 0 ? '' : ' hidden'}>${poeSummaryMarkup(summary, fallback)}<div class="table-wrap"><table class="data unifi-ports-table"><thead><tr><th>端口名称</th><th>端口编号</th><th>状态</th><th>链路</th><th>PoE</th><th>累计发送流量</th><th>累计接收流量</th><th>发送 / 接收 (错误/丢弃)</th></tr></thead><tbody>${body}</tbody></table></div></section>`;
  }).join('');
  return `<div class="unifi-device-tabs" role="tablist" aria-label="UniFi 设备"><div class="unifi-network-tabs">${tabs}</div>${panels}</div>`;
}
function unifiCollectionStatusText(unifi){
  const status = unifiCollectionStatus(unifi);
  if(status.ssh === '成功' && status.api === '成功') return '成功';
  if(status.ssh === '未配置' && status.api === '未配置') return '未配置';
  if(status.ssh === '未采集' || status.api === '未采集') return '未采集';
  if(status.ssh === '失败' && status.api === '失败') return '失败';
  return '部分成功';
}

function unifiCollectionStatusMarkup(unifi, channel = null){
  const status = unifiCollectionStatus(unifi);
  const text = channel ? status[channel] : unifiCollectionStatusText(unifi);
  const tone = text === '成功' ? 'ok' : text === '未配置' || text === '未采集' ? 'neutral' : 'warn';
  return `<span class="badge ${tone}">${text}</span>`;
}

function renderUniFi(view){
  const unifi = safeObject(view.unifi);
  const summary = unifiTransportSummary(unifi);
  const transport = safeObject(unifi.transport);
  const configured = unifiIsConfigured(unifi);
  const hasSystem = Object.keys(safeObject(unifi.system)).length > 0;
  const pageUnavailable = !configured || !hasSystem;
  const emptyState = byId('unifiEmptyState');
  if(emptyState){
    emptyState.hidden = !pageUnavailable;
    emptyState.textContent = configured
      ? '已配置 UniFi 目标，但访问失败，请检查 SSH 密码和 API Key'
      : '未配置 UniFi 目标';
  }
  for(const section of document.querySelectorAll('#unifiPage > section')) section.hidden = pageUnavailable;
  const summaryRows = [
    ['配置状态/机器配置', configured ? `已配置 / ${textOrDash(unifi.profile)}` : '未配置 / -', '传输状态', `<span class="badge ${statusTone(summary.status)}">${escapeHtml(summary.text)}</span>`, '数据状态', unifi.stale ? '<span class="badge warn">已陈旧</span>' : configured && summary.status === 'available' ? '<span class="badge ok">最新</span>' : '-'],
    ['上次尝试', formatDateTime(transport.last_attempt), '最近成功', formatDateTime(transport.last_success), '数据更新时间', formatDateTime(unifi.updated_at)],
    ['SSH采集状态', unifiCollectionStatusMarkup(unifi, 'ssh'), 'API采集状态', unifiCollectionStatusMarkup(unifi, 'api'), '采集错误', escapeHtml(unifiErrorDisplay(unifi))]
  ];
  byId('unifiSystem').innerHTML = configured && hasSystem
    ? unifiSystemCards(unifi)
    : `<div class="table-empty">${escapeHtml(summary.text === '尚未采集' ? '等待首次 UniFi 采集。' : summary.text === '未配置' ? '未配置 UniFi 目标。' : '暂无可显示的通用遥测。')}</div>`;
  byId('unifiSummary').innerHTML = summaryRows.flatMap(row => [0, 2, 4].map(index => detailRow(row[index], row[index + 1], 'wrap-value'))).join('');
  byId('unifiMeta').textContent = configured ? `Profile：${textOrDash(unifi.profile)} · ${summary.text}` : '未配置 UniFi 目标';
  const apiTelemetry = byId('unifiApiTelemetry');
  if(apiTelemetry) apiTelemetry.innerHTML = '';
  byId('unifiPorts').innerHTML = configured ? unifiPortTelemetryMarkup(unifi) : '<div class="unifi-api-unavailable">未配置 UniFi 目标。</div>';
  byId('unifiWan').innerHTML = configured ? unifiWanMarkup(unifi) : '<div class="table-empty">未配置 UniFi 目标。</div>';
  byId('unifiStorage').innerHTML = configured ? unifiStorageMarkup(unifi) : '<div class="table-empty">未配置 UniFi 目标。</div>';
  byId('unifiFansBody').innerHTML = configured ? unifiFanRows(unifi) : '<tr><td colspan="6" class="table-empty">未配置 UniFi 目标。</td></tr>';
  byId('unifiPowerBody').innerHTML = configured ? unifiPowerRows(unifi) : '<tr><td colspan="7" class="table-empty">未配置 UniFi 目标。</td></tr>';
  requestAnimationFrame(fitUniFiSingleLineValues);
}

function setUniFiDeviceTab(container, tabName){
  for(const tab of container.querySelectorAll('[data-unifi-device-tab]')){
    const active = tab.dataset.unifiDeviceTab === tabName;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  }
  for(const panel of container.querySelectorAll('[data-unifi-device-panel]')){
    panel.hidden = panel.dataset.unifiDevicePanel !== tabName;
  }
}

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
  renderUniFi(view);
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
	for(const page of ['home', 'hardware', 'unifi', 'docker', 'lucky', 'easytier']){
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
    ['预期 Proxy CIDRs', expectationConfigured ? (proxyCidrs || '-') : '-']
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
			const pages = ['home', 'hardware', 'unifi', 'docker', 'lucky', 'easytier'];
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
  const unifiPorts = byId('unifiPorts');
  unifiPorts.addEventListener('click', event => {
    const tab = event.target.closest('[data-unifi-device-tab]');
    if(tab) setUniFiDeviceTab(unifiPorts, tab.dataset.unifiDeviceTab);
  });
  unifiPorts.addEventListener('keydown', event => {
    const tab = event.target.closest('[data-unifi-device-tab]');
    if(!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...unifiPorts.querySelectorAll('[data-unifi-device-tab]')];
    const current = tabs.indexOf(tab);
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (current + (event.key === 'ArrowLeft' ? -1 : 1) + tabs.length) % tabs.length;
    const next = tabs[nextIndex];
    setUniFiDeviceTab(unifiPorts, next.dataset.unifiDeviceTab);
    next.focus();
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
  unifiIsConfigured,
  unifiTransportSummary,
  unifiApiStatusText,
  unifiCollectionStatus,
  unifiCollectionStatusText,
  unifiCollectionStatusMarkup,
  unifiApiTelemetryMarkup,
  unifiPortTelemetryMarkup,
  unifiPortStatusMarkup,
  unifiPortErrorText,
  unifiWanMarkup,
  unifiPortLinkText,
  unifiPortPoeText,
  unifiPortRate,
  unifiLinkBandwidth,
  unifiSystemRows,
  unifiSystemCards,
  unifiFanRows,
  unifiPowerRows,
  unifiStorageRows,
  unifiStorageMarkup,
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
