const S = {
  data: null,
  activeTab: 'host',
  openProfile: ''
};
const WEB_REFRESH_INTERVAL_MS = 10 * 60 * 1000;

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const num = (v) => typeof v === 'number' && Number.isFinite(v) ? v : 0;
const pct = (used, total) => total ? Math.max(0, Math.min(100, used / total * 100)) : 0;

function humanBytes(bytes){
  if(!Number.isFinite(bytes)) return '-';
  const units = ['B','KB','MB','GB','TB','PB'];
  let value = Math.max(0, bytes);
  let index = 0;
  while(value >= 1000 && index < units.length - 1){ value /= 1000; index++; }
  const out = value >= 100 ? value.toFixed(0) : value >= 10 ? value.toFixed(1) : value.toFixed(2);
  return out.replace(/\.0+$/,'') + ' ' + units[index];
}

function mbToBytes(mb){ return num(mb) * 1000 * 1000; }
function kbToBytes(kb){ return num(kb) * 1000; }

function firstHost(){
  return ((S.data && S.data.servers) || [])[0] || {};
}

function hardware(){
  return firstHost().hardware || {};
}

function docker(){
  return firstHost().docker || { running: 0, total: 0, containers: [] };
}

function hermes(){
  return firstHost().hermes || { profiles: [] };
}

function tempText(item){
  if(!item || item.value === null || item.value === undefined) return '-';
  return `${Number(item.value).toFixed(0)} ℃`;
}

function diskTempText(item){
  if(!item) return '-';
  const current = item.current ?? item.value;
  if(current === null || current === undefined) return '-';
  const highest = item.highest ?? '-';
  const lowest = item.lowest ?? '-';
  const fmt = (v) => v === '-' || v === null || v === undefined ? '-' : Number(v).toFixed(0);
  return `${fmt(current)} / ${fmt(highest)} / ${fmt(lowest)} ℃`;
}

function smartBadge(status){
  const value = String(status || 'unknown').toLowerCase();
  const cls = value === 'passed' ? 'ok' : value === 'failed' ? 'err' : 'muted';
  return `<span class="badge ${cls}">${esc(value)}</span>`;
}

function statusBadge(status){
  const value = String(status || 'unknown').toLowerCase();
  let cls = 'muted';
  if(['active','running','ok','passed','up','online','enabled','completed','complete','success','healthy','idle','none'].includes(value) || value.startsWith('up ')) cls = 'ok';
  else if(['degraded','warning','warn','paused','pending'].includes(value)) cls = 'warn';
  else if(['failed','inactive','down','error'].includes(value)) cls = 'err';
  return `<span class="badge ${cls}">${esc(status || 'unknown')}</span>`;
}

function tokenTotalText(usage, fallback){
  const item = usage && typeof usage === 'object' ? usage : {};
  const total = Number(item.total_tokens || fallback || 0);
  const text = total.toLocaleString();
  return item.estimated ? `${text} est.` : text;
}

function tokenBreakdownText(usage, fallback){
  const item = usage && typeof usage === 'object' ? usage : {};
  const output = Number(item.output_tokens || item.completion_tokens || 0);
  const input = Number(item.input_tokens || item.prompt_tokens || 0);
  const total = Number(item.total_tokens || fallback || output + input || 0);
  const text = `${output.toLocaleString()} / ${input.toLocaleString()} / ${total.toLocaleString()}`;
  return item.estimated ? `${text} est.` : text;
}

function sessionsText(row){
  const active = Number(row.sessions_active || 0);
  const total = Number(row.sessions_total || 0);
  if(total > 0){
    return active > 0 ? `${active} / ${total}` : `${total}`;
  }
  return '0';
}

function overviewCard(label, value, hint, barClass, percent){
  const bar = Number.isFinite(percent) ? `<div class="bar"><i class="${barClass || ''}" style="width:${Math.max(0, Math.min(100, percent)).toFixed(1)}%"></i></div>` : '';
  return `<article class="overview-card">
    <span class="label">${esc(label)}</span>
    <div class="value">${esc(value)}</div>
    ${bar}
    <div class="hint">${esc(hint || '')}</div>
  </article>`;
}

function healthCard(label, value, hint){
  return `<article class="health-card">
    <span class="label">${esc(label)}</span>
    <div class="value">${value}</div>
    <div class="hint">${esc(hint || '')}</div>
  </article>`;
}

function renderOverview(){
  const host = firstHost();
  const d = docker();
  const memPct = pct(num(host.memory_used), num(host.memory_total));
  const hddPct = pct(num(host.hdd_used), num(host.hdd_total));
  $('overviewCards').innerHTML = [
    overviewCard('CPU', `${num(host.cpu).toFixed(0)}%`, [host.name || 'J4125', host.os || ''].filter(Boolean).join(' / '), 'cpu', num(host.cpu)),
    overviewCard('内存', `${humanBytes(kbToBytes(host.memory_used))} / ${humanBytes(kbToBytes(host.memory_total))}`, `${memPct.toFixed(0)}% used`, 'mem', memPct),
    overviewCard('硬盘', `${humanBytes(mbToBytes(host.hdd_used))} / ${humanBytes(mbToBytes(host.hdd_total))}`, `${hddPct.toFixed(0)}% used`, 'hdd', hddPct),
    overviewCard('运行中/总容器数量', `${num(d.running)} / ${num(d.total)}`, '', '', null),
    overviewCard('已运行时间', host.uptime || '-', host.host || host.location || '', '', null)
  ].join('');
}

function renderHardware(){
  const hw = hardware();
  const cpuTemp = hw.cpu_temperature;
  const diskTemp = hw.disk_temperature;
  const hours = hw.disk_power_on_hours;
  const written = hw.disk_written_bytes;
  const read = hw.disk_read_bytes;
  $('hardwareCards').innerHTML = [
    healthCard('CPU 温度', esc(tempText(cpuTemp)), cpuTemp && cpuTemp.source),
    healthCard('硬盘温度', esc(diskTempText(diskTemp)), diskTemp ? '当前 / 最高 / 最低' : ''),
    healthCard('硬盘 SMART', smartBadge(hw.disk_smart_status), '健康状态检查'),
    healthCard('硬盘通电时间', esc(hours === null || hours === undefined ? '-' : `${hours.toLocaleString()} h`), hours ? `约 ${Math.floor(hours / 24)} 天` : ''),
    healthCard(
      '硬盘写入/读取量',
      esc(`${written ? humanBytes(Number(written)) : '-'} / ${read ? humanBytes(Number(read)) : '-'}`),
      ''
    )
  ].join('');
}

function renderHermes(){
  const rows = (hermes().profiles || []);
  $('hermesBody').innerHTML = rows.length ? rows.map(row => {
    const jobsActive = row.scheduled_jobs_active ?? row.yesterday_success ?? 0;
    const jobsTotal = row.scheduled_jobs_total ?? row.yesterday_total ?? 0;
    const modelProfile = [row.model, row.usage_mode, row.provider].filter(Boolean).join(' / ') || '-';
    return `<tr class="row-click" data-profile="${esc(row.profile || '')}" title="查看辅助模型配置">
      <td class="mono">${esc(row.profile || '-')}</td>
      <td>${statusBadge(row.service_status)}</td>
      <td>${statusBadge(row.gateway_service || row.service_status)}</td>
      <td>${statusBadge(row.api_status || 'unknown')}</td>
      <td>${esc(row.manager_mode || '-')}</td>
      <td class="mono wrap-cell">${esc(modelProfile)}</td>
      <td class="mono">${esc(jobsActive)} / ${esc(jobsTotal)}</td>
      <td class="mono">${esc(sessionsText(row))}</td>
      <td class="mono">${esc(tokenBreakdownText(row.usage, row.yesterday_tokens))}</td>
    </tr>`;
  }).join('') : '<tr><td colspan="9" class="muted">暂无 Hermes profile 数据</td></tr>';
  document.querySelectorAll('#hermesBody .row-click').forEach(row => row.addEventListener('click', () => openProfileModal(row.dataset.profile)));
}

function renderDocker(){
  const d = docker();
  const rows = d.containers || [];
  if(!rows.length){
    $('dockerBody').innerHTML = `<tr><td colspan="7" class="muted">${esc(d.error ? 'Docker 数据获取失败: ' + d.error : '暂无容器数据')}</td></tr>`;
    return;
  }
  const html = rows.map(row => `<tr>
    <td class="mono">${esc(row.id || '-')}</td>
    <td>${esc(row.names || '-')}</td>
    <td>${statusBadge(row.state === 'running' ? row.status || 'running' : row.status || row.state)}</td>
    <td class="muted">${esc(row.created || '-')}</td>
    <td class="mono">${esc(row.image || '-')}</td>
    <td class="mono muted" title="${esc(row.command || '')}">${esc(row.command || '-')}</td>
    <td class="mono muted" title="${esc(row.ports || '')}">${esc(row.ports || '-')}</td>
  </tr>`).join('');
  const total = num(d.total);
  const tail = total > rows.length ? `<tr><td colspan="7" class="muted">仅展示前 ${rows.length} / ${total} 个容器</td></tr>` : '';
  $('dockerBody').innerHTML = html + tail;
}

function profileRows(){
  return (hermes().profiles || []);
}

function findProfile(profile){
  return profileRows().find(row => String(row.profile || '') === String(profile || ''));
}

function configSummary(row){
  return row && row.config_summary && typeof row.config_summary === 'object' ? row.config_summary : null;
}

function displayValue(value){
  if(Array.isArray(value)) return value.length ? value.join(', ') : '-';
  if(value === null || value === undefined || value === '') return '-';
  return String(value);
}

function keyValue(label, value, mono = true){
  return `<div class="kv"><span>${esc(label)}</span><span class="${mono ? 'mono' : ''}">${esc(displayValue(value))}</span></div>`;
}

function auxTable(auxiliary){
  const entries = Object.entries(auxiliary && typeof auxiliary === 'object' ? auxiliary : {});
  if(!entries.length){
    return '<div class="muted">未配置 auxiliary，字段缺失时返回空对象</div>';
  }
  return `<div class="table-wrap"><table class="mini-table aux-table">
    <thead><tr><th>名称</th><th>模型显示</th><th>Base URL</th><th>Timeout</th><th>下载超时</th><th>并发</th><th>语言</th><th>extra_body</th><th>密钥字段</th></tr></thead>
    <tbody>${entries.map(([key, item]) => {
    item = item && typeof item === 'object' ? item : {};
    const secretConfigured = Object.keys(item).filter(name => /_(configured)$/.test(name) && !['extra_body_configured'].includes(name) && item[name]);
    return `<tr>
      <td class="mono">${esc(key)}</td>
      <td class="mono">${esc(item.display || '-')}</td>
      <td class="mono">${esc(item.base_url_display || item.base_url || 'provider default')}</td>
      <td class="mono">${esc(displayValue(item.timeout_seconds))}</td>
      <td class="mono">${esc(displayValue(item.download_timeout_seconds))}</td>
      <td class="mono">${esc(displayValue(item.max_concurrency))}</td>
      <td class="mono">${esc(displayValue(item.language))}</td>
      <td class="mono">${item.extra_body_configured ? 'configured' : 'false'}</td>
      <td class="mono">${secretConfigured.length ? 'configured' : 'false'}</td>
    </tr>`;
  }).join('')}</tbody>
  </table></div>`;
}

function volumeRows(volumes){
  const rows = Array.isArray(volumes) ? volumes : [];
  if(!rows.length){
    return '<div class="muted">未配置 docker_volumes</div>';
  }
  return `<table class="mini-table">
    <thead><tr><th>宿主机路径</th><th>容器路径</th><th>模式</th></tr></thead>
    <tbody>${rows.map(item => {
      const parts = String(item || '').split(':');
      const host = parts[0] || '-';
      const target = parts[1] || '-';
      const mode = parts.slice(2).join(':') || 'rw';
      return `<tr><td class="mono">${esc(host)}</td><td class="mono">${esc(target)}</td><td class="mono">${esc(mode)}</td></tr>`;
    }).join('')}</tbody>
  </table>`;
}

function openProfileModal(profile){
  const row = findProfile(profile);
  if(!row) return;
  S.openProfile = String(profile || '');
  const summary = configSummary(row);
  $('profileTitle').textContent = `${row.profile || 'Hermes'} 辅助模型配置`;
  if(!summary){
    $('profileContent').innerHTML = '<section class="detail-section"><h4>配置摘要</h4><div class="muted">暂无 config_summary 数据</div></section>';
    $('profileModal').style.display = 'flex';
    return;
  }
  const main = summary.main_model || {};
  const delegation = summary.delegation || {};
  const runtime = summary.runtime_related || {};
  const warnings = Array.isArray(summary.warnings) ? summary.warnings : [];
  $('profileContent').innerHTML = `
    <div class="detail-grid">
      <section class="detail-section"><h4>主模型</h4>
        ${keyValue('Provider', main.provider)}
        ${keyValue('Model', main.model)}
        ${keyValue('Base URL', main.base_url || 'provider default')}
        ${keyValue('刷新时间', row.auth_refreshed_at || row.refreshed_at || '-')}
      </section>
      <section class="detail-section"><h4>Delegation</h4>
        ${keyValue('Display', delegation.display || 'inherit main model')}
        ${keyValue('并发 / 深度', `${displayValue(delegation.max_concurrent_children)} / ${displayValue(delegation.max_spawn_depth)}`)}
        ${keyValue('Timeout', `${displayValue(delegation.child_timeout_seconds)} s`)}
      </section>
      <section class="detail-section"><h4>运行相关</h4>
        ${keyValue('Config', summary.config_path || summary.error || '-')}
        ${keyValue('Version', summary.config_version)}
        ${keyValue('Approvals', runtime.approvals_mode)}
      </section>
      <section class="detail-section"><h4>开关</h4>
        ${keyValue('toolsets', runtime.toolsets)}
        ${keyValue('compression', runtime.compression_enabled)}
        ${keyValue('memory / curator', `${displayValue(runtime.memory_enabled)} / ${displayValue(runtime.curator_enabled)}`)}
      </section>
    </div>
    <section class="detail-section"><h4>辅助模型</h4>${auxTable(summary.auxiliary_models)}</section>
    <section class="detail-section"><h4>容器挂载点</h4>${volumeRows(summary.docker_volumes)}</section>
    ${warnings.length ? `<section class="detail-section"><h4>Warnings</h4>${warnings.map(item => `<div><span class="badge warn">warn</span> ${esc(item)}</div>`).join('')}</section>` : ''}
    <section class="detail-section"><h4>结构化 JSON 预览</h4><pre class="json-preview">${esc(JSON.stringify(summary, null, 2))}</pre></section>`;
  $('profileModal').style.display = 'flex';
}

function closeProfileModal(){
  S.openProfile = '';
  const modal = $('profileModal');
  if(modal) modal.style.display = 'none';
}

function render(){
  $('notice').style.display = 'none';
  renderOverview();
  renderHardware();
  renderHermes();
  renderDocker();
  updateTime();
  if(S.openProfile) openProfileModal(S.openProfile);
}

async function fetchData(manual = false){
  const refresh = $('manualRefresh');
  if(manual && refresh){
    refresh.disabled = true;
    refresh.textContent = '刷新中';
  }
  try{
    const res = await fetch('json/stats.json?_=' + Date.now(), { cache: 'no-store' });
    if(!res.ok) throw new Error(String(res.status));
    S.data = await res.json();
    if(S.data.reload) location.reload();
    render();
  }catch(err){
    const notice = $('notice');
    notice.style.display = 'flex';
    notice.textContent = '数据获取失败: ' + err.message;
  }finally{
    if(manual && refresh){
      refresh.disabled = false;
      refresh.textContent = '刷新';
    }
  }
}

function updateTime(){
  const updated = Number(S.data && S.data.updated);
  if(!updated){
    $('lastUpdate').textContent = '等待数据';
    return;
  }
  const date = new Date(updated * 1000);
  $('lastUpdate').textContent = '上次刷新 ' + date.toLocaleString('zh-CN', { hour12: false });
}

function switchTab(tab){
  S.activeTab = tab;
  document.querySelectorAll('#navTabs button').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tab));
  document.querySelectorAll('.panel').forEach(panel => panel.classList.toggle('active', panel.id === `panel-${tab}`));
}

function setAdminStatus(text, cls){
  const el = $('adminStatus');
  if(!el) return;
  el.className = 'admin-status' + (cls ? ` ${cls}` : '');
  el.textContent = text || '';
}

function adminToken(){
  let token = localStorage.getItem('serverstatusAdminToken') || '';
  if(token) return token;
  token = window.prompt('请输入管理 Token') || '';
  token = token.trim();
  if(token) localStorage.setItem('serverstatusAdminToken', token);
  return token;
}

async function postAdmin(path, successText){
  const token = adminToken();
  if(!token){
    setAdminStatus('未提供管理 Token。', 'err');
    return;
  }
  setAdminStatus('正在执行...', '');
  try{
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json().catch(() => ({}));
    if(!res.ok || data.ok === false) throw new Error(data.error || data.message || res.statusText);
    setAdminStatus(successText, 'ok');
  }catch(err){
    if(/unauthorized|forbidden|401|403/i.test(String(err.message))){
      localStorage.removeItem('serverstatusAdminToken');
    }
    setAdminStatus('操作失败: ' + err.message, 'err');
  }
}

function bindAdminActions(){
  const reload = $('adminReload');
  const restart = $('adminRestart');
  if(reload) reload.addEventListener('click', () => postAdmin('/api/reload', '配置重载已触发。'));
  if(restart) restart.addEventListener('click', () => {
    if(window.confirm('确认重启服务？')) postAdmin('/api/restart', '服务重启已触发。');
  });
}

function init(){
  document.querySelectorAll('#navTabs button').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
  const refresh = $('manualRefresh');
  if(refresh) refresh.addEventListener('click', () => fetchData(true));
  const profileClose = $('profileClose');
  const profileModal = $('profileModal');
  if(profileClose) profileClose.addEventListener('click', closeProfileModal);
  if(profileModal) profileModal.addEventListener('click', e => { if(e.target === profileModal) closeProfileModal(); });
  document.addEventListener('keydown', e => { if(e.key === 'Escape') closeProfileModal(); });
  bindAdminActions();
  fetchData();
  setInterval(fetchData, WEB_REFRESH_INTERVAL_MS);
}

document.addEventListener('DOMContentLoaded', init);
