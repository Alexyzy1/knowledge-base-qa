// bootstrap.js
// BOOTSTRAP
// ============================================================
function decorateStaticIcons() {
  var tabIcons = { overview:'overview', files:'files', chat:'chat', similar:'similar', members:'members', settings:'settings', audit:'audit' };
  document.querySelectorAll('#topbarTabs .topbar-tab').forEach(function(t){
    var p = t.dataset.panel;
    if (tabIcons[p] && !t.__iconed) {
      t.innerHTML = icon(tabIcons[p],'icon-16') + '<span>' + t.textContent + '</span>';
      t.style.display = 'inline-flex'; t.style.alignItems = 'center'; t.style.gap = '6px';
      t.__iconed = true;
    }
  });
  var set = function(id, name, label){ var b = document.getElementById(id); if (b) b.innerHTML = icon(name,'icon-16') + '<span>' + label + '</span>'; };
  set('btnUploadTrigger','upload','上传');
  set('btnNewFolder','folderPlus','新建文件夹');
  set('btnNewNote','note','新建笔记');
  set('btnNewKB','plus','新建知识库');
  set('btnKbImport','upload','导入知识库');

  // Batch action button icons
  // Batch action button icons
  var bdi = document.getElementById('btnKbBatchDelete'); if (bdi) { var s = bdi.querySelector('.kb-batch-btn-icon'); if (s) s.innerHTML = icon('trash','icon-16'); }
  var bei = document.getElementById('btnKbBatchExport'); if (bei) { var s = bei.querySelector('.kb-batch-btn-icon'); if (s) s.innerHTML = icon('download','icon-16'); }
  var bsi = document.getElementById('btnKbBatchExport'); if (bei) { var s = bei.querySelector('.kb-batch-btn-icon'); if (s) s.innerHTML = icon('download','icon-16'); }

  // Management dropdown icons
  var mt = document.querySelector('#btnTopbarMore .mt-ico'); if (mt) mt.innerHTML = icon('settings','icon-16');
  var mcaret = document.getElementById('moreCaretIcon'); if (mcaret) mcaret.innerHTML = icon('caret','icon-16');
  document.querySelectorAll('#moreMenu .more-item').forEach(function(it){
    var p = it.dataset.panel;
    var ico = it.querySelector('.mi-ico'); if (ico && tabIcons[p]) ico.innerHTML = icon(tabIcons[p],'icon-16');
    var ck = it.querySelector('.mi-check'); if (ck) ck.innerHTML = icon('check','icon-16');
  });

  var dz = document.getElementById('dropZoneIcon'); if (dz) dz.innerHTML = icon('upload','icon-24');
  var allf = document.querySelector('#folderTree .folder-tree-item[data-folder-id="all"]');
  if (allf && !allf.__iconed) { allf.innerHTML = icon('folder','icon-16') + '<span>全部</span>'; allf.style.gap = '6px'; allf.__iconed = true; }
}
decorateStaticIcons();

(function init(){
  // DEMO MODE bootstrap — auto-session with mock data
  if (DEMO) {
    demoInit();
    setToken('demo-token');
    currentUser = demoDB.user;
    localStorage.setItem('kb_user', JSON.stringify(currentUser));
    showAppShell();
    var ribbon = document.createElement('div');
    ribbon.className = 'demo-ribbon';
    ribbon.innerHTML = '<span class="dot"></span> 演示模式 · 模拟数据';
    document.body.appendChild(ribbon);
    initApp();
    return;
  }

  // Check for public share route: /share/{token}
  var path = window.location.pathname;
  var shareMatch = path.match(/^\/share\/([a-zA-Z0-9_-]+)/);
  if (shareMatch) {
    showPublicSharePage(shareMatch[1]);
    return;
  }

  var token = getToken();
  if (!token) {
    showAuthPage();
  } else {
    showAppShell();
    // Try to restore cached user from localStorage (saved on login success)
    var cachedUser = null;
    try { cachedUser = JSON.parse(localStorage.getItem('kb_user')); } catch(e) {}
    currentUser = cachedUser || { id:0, username:'加载中…', role:'user' };
    document.getElementById('sidebarUsername').textContent = currentUser.username;
    document.getElementById('sidebarRole').textContent = currentUser.role;
    renderSidebarLinks();
    // Also try /api/auth/me for fresh user info (will update sidebar on success)
    // NOTE: /api/auth/me may not be deployed yet (returns 404). Silently ignore.
    apiFetch('/api/auth/me').then(function(res){
      if (res.ok) return res.json();
      throw new Error('not-available');
    }).then(function(body){
      if (body && body.code === 0 && body.data) {
        currentUser = body.data;
        localStorage.setItem('kb_user', JSON.stringify(currentUser));
      }
    }).catch(function(){ /* keep cached user — endpoint not deployed or auth failed */ }).finally(function(){
      document.getElementById('sidebarUsername').textContent = currentUser.username;
      document.getElementById('sidebarRole').textContent = currentUser.role;
      renderSidebarLinks();
    });
    loadKbList().then(function(){
      if (kbListCache.length > 0) selectKb(kbListCache[0].id);
    });
  }
// ── User dropdown toggle ──
var ubTrigger = document.getElementById('ubTrigger');
var sidebarUserbar = document.getElementById('sidebarUserbar');
if (ubTrigger) {
  ubTrigger.addEventListener('click', function(e) {
    e.stopPropagation();
    sidebarUserbar.classList.toggle('open');
  });
}
// Close dropdown on outside click
document.addEventListener('click', function(e) {
  if (sidebarUserbar && !sidebarUserbar.contains(e.target)) {
    sidebarUserbar.classList.remove('open');
  }
});

// ── Dropdown menu item clicks ──
document.getElementById('userDropdownMenu').addEventListener('click', function(e) {
  var item = e.target.closest('.menu-item');
  if (!item) return;
  sidebarUserbar.classList.remove('open');
  var nav = item.dataset.nav;
  if (nav === 'dashboard')  { showGlobalPage('dashboard','仪表盘'); loadDashboard(); }
  if (nav === 'apikeys')    { showGlobalPage('apikeys','API·开发者'); loadApiKeys(); }
  if (nav === 'account')    { showGlobalPage('account','账户信息'); loadAccount(); }
  if (nav === 'whitelist')  { showGlobalPage('whitelist','白名单管理'); loadWhitelist(); }
  if (nav === 'models')     { showGlobalPage('models','模型注册表'); loadModels(); }
  if (nav === 'audit')      { showGlobalPage('audit','全局审计'); loadGlobalAudit(); }
});

// ── Logout via dropdown menu ──
document.getElementById('btnLogoutMenu').addEventListener('click', function() {
  stopPolling();
  if (streamingAbort) { streamingAbort.abort(); streamingAbort = null; }
  setToken('');
  document.getElementById('mgmtMenuLabel').style.display = 'none';
  document.getElementById('menuWhitelist').style.display = 'none';
  document.getElementById('menuModels').style.display = 'none';
  document.getElementById('menuGlobalAudit').style.display = 'none';
  currentUser = null;
  currentKbId = null;
  selectedKbIds = [];
  showAuthPage();
  localStorage.removeItem('kb_user');
  toast('已登出', 'info');
});
})();
