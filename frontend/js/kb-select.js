// kb-select.js
// SELECT KB
// ============================================================
function selectKb(kbId) {
  var isSwitching = currentKbId && currentKbId !== kbId;
  currentKbId = kbId;

  // Highlight sidebar
  document.querySelectorAll('.kb-item').forEach(function(item){
    item.classList.toggle('active', parseInt(item.dataset.kbId) === kbId);
  });

  // Update topbar
  var kb = kbListCache.find(function(k){ return k.id === kbId; });
  document.getElementById('topbarKbName').textContent = kb ? kb.name : '知识库';
  document.getElementById('noKbSelected').classList.add('hidden');

  // Show KB workspace (hide global pages)
  document.getElementById('kbWorkspace').style.display = 'flex';
  document.getElementById('globalPagesContainer').style.display = 'none';

  // Crossfade: briefly dim the content area when switching between KBs
  var main = document.getElementById('mainContent');
  if (isSwitching) main.classList.add('switching');

  // Default to overview tab (showPanel will call loadOverview)
  showPanel('overview');

  // Refresh role-based tab visibility
  updateTabVisibility();

  // Clear multi-select when focusing a single KB
  selectedKbIds = [];
  updateGlobalSearchChips();
  renderKbList(kbListCache);
}

function updateTabVisibility() {
  if (!currentKbId) return;
  var role = kbRoleCache[currentKbId] || 'reader';
  var ownerLike = (role === 'owner' || currentUser.role === 'super_admin');

  // Management menu (成员/设置/审计/分享) — owner / super_admin only
  document.querySelectorAll('#moreMenu .more-item').forEach(function(it){
    it.style.display = ownerLike ? '' : 'none';
  });
  var more = document.getElementById('topbarMore');
  if (more) more.style.display = ownerLike ? '' : 'none';
}
