// kb-list.js
// KB LIST
// ============================================================
async function loadKbList() {
  var listEl = document.getElementById('kbList');
  try {
    var res = await apiFetch('/api/kb');
    var body = await handleBusinessResponse(res);
    kbListCache = body.data || [];
    lastClickedKbIndex = null;  // reset anchor on fresh load
    // Build role cache
    kbRoleCache = {};
    (body.data || []).forEach(function(kb){ if (kb.role) kbRoleCache[kb.id] = kb.role; });

    renderKbList(kbListCache);
  } catch(err) {
    if (err.message === 'Unauthorized') return;
  }
}

function renderKbList(kbs) {
  var listEl = document.getElementById('kbList');
  var nav = document.getElementById('kbNav');
  // Toggle batch mode class on the nav container
  if (kbBatchMode) nav.classList.add('kb-batch-mode');
  else nav.classList.remove('kb-batch-mode');

  if (kbs.length === 0) {
    listEl.innerHTML = '<li style="padding:var(--space-lg) 0;text-align:center;color:#8B8B8B;font-size:var(--fs-body-sm);">暂无知识库</li>';
    return;
  }

  listEl.innerHTML = kbs.map(function(kb){
    var role = kbRoleCache[kb.id] || kb.role || '';
    var dotClass = role === 'owner' ? 'role-dot owner' : role === 'editor' ? 'role-dot editor' : 'role-dot reader';
    var delBtn = (!kbBatchMode && (role==='owner'||currentUser.role==='super_admin'))
      ? '<button class="kb-del" title="删除知识库" data-kb-id="'+kb.id+'">'+icon('trash','icon-16')+'</button>'
      : '';
    var activeClass = (kb.id === currentKbId) ? ' active' : '';
    // In batch mode, use batch classes (red); in normal mode, use search classes (blue)
    var checked, batchChecked;
    if (kbBatchMode) {
      checked = selectedBatchKbIds.indexOf(kb.id) !== -1 ? 'checked' : '';
      batchChecked = checked ? ' batch-checked' : '';
    } else {
      checked = selectedKbIds.indexOf(kb.id) !== -1 ? 'checked' : '';
      batchChecked = '';
    }
    return '<li class="kb-item' + activeClass + (checked ? ' checked' : '') + batchChecked + '" data-kb-id="'+kb.id+'">' +
      '<input type="checkbox" class="kb-checkbox" data-kb-id="'+kb.id+'" '+checked+'>' +
      (role ? '<span class="'+dotClass+'" title="'+role+'"></span>' : '') +
      '<span class="kb-name">'+escapeHtml(kb.name)+'</span>' +
      delBtn +
    '</li>';
  }).join('');

  // Click: toggle multi-select; double-click any to focus that single KB
  var clickTimers = {};
  var DOUBLE_CLICK_MS = 400;

  var allKbCbs = listEl.querySelectorAll('.kb-checkbox');
  allKbCbs.forEach(function(cb, index){
    cb.addEventListener('click', function(e){
      e.stopPropagation();
      var kbId = parseInt(this.dataset.kbId);
      if (kbBatchMode) {
        if (e.shiftKey && lastClickedBatchKbIndex !== null) {
          var start = Math.min(lastClickedBatchKbIndex, index);
          var end   = Math.max(lastClickedBatchKbIndex, index);
          for (var i = start; i <= end; i++) {
            var id = parseInt(allKbCbs[i].dataset.kbId);
            if (selectedBatchKbIds.indexOf(id) === -1) selectedBatchKbIds.push(id);
          }
        } else {
          toggleBatchKbSelection(kbId);
          lastClickedBatchKbIndex = index;
        }
        updateBatchKbUI();
        renderKbList(kbListCache);
      } else {
        // Click checkbox → toggle selection, don't enter single KB
        var idx = selectedKbIds.indexOf(kbId);
        if (idx !== -1) selectedKbIds.splice(idx, 1);
        else selectedKbIds.push(kbId);
        updateGlobalSearchChips();
        renderKbList(kbListCache);
      }
    });
  });

  // Row click: single toggles, double focuses that single KB
  listEl.querySelectorAll('.kb-item').forEach(function(item){
    item.addEventListener('click', function(e){
      if (e.target.closest('.kb-del') || e.target.closest('.kb-checkbox')) return;
      var kbId = parseInt(this.dataset.kbId);
      if (kbBatchMode) {
        selectedBatchKbIds = [kbId];
        lastClickedBatchKbIndex = null;
        updateBatchKbUI();
        renderKbList(kbListCache);
      } else {
        // Double-click → enter this KB alone
        if (clickTimers[kbId]) {
          clearTimeout(clickTimers[kbId]);
          delete clickTimers[kbId];
          selectedKbIds = [];
          updateGlobalSearchChips();
          selectKb(kbId);
          renderKbList(kbListCache);
          return;
        }
        // Single click → toggle
        clickTimers[kbId] = setTimeout(function(){ delete clickTimers[kbId]; }, DOUBLE_CLICK_MS);
        var idx = selectedKbIds.indexOf(kbId);
        if (idx !== -1) selectedKbIds.splice(idx, 1);
        else selectedKbIds.push(kbId);
        updateGlobalSearchChips();
        renderKbList(kbListCache);
      }
    });
  });
  // Delete button → confirmation dialog
  listEl.querySelectorAll('.kb-del').forEach(function(btn){
    btn.addEventListener('click', function(e){
      e.stopPropagation();
      var kbId = parseInt(this.dataset.kbId);
      var kb = kbListCache.find(function(k){ return k.id===kbId; });
      deleteKb(kbId, kb ? kb.name : '知识库');
    });
  });
}

function toggleKbSelection(kbId) {
  var idx = selectedKbIds.indexOf(kbId);
  if (idx !== -1) {
    selectedKbIds.splice(idx, 1);
  } else {
    selectedKbIds.push(kbId);
  }
  updateGlobalSearchChips();
  renderKbList(kbListCache);
}

// ════════════════════════════════════════════════════════
// KB BATCH OPERATIONS (select → delete / export / share)
// ════════════════════════════════════════════════════════
function enterKbBatchMode() {
  // Mutual exclusion: clear search selection when entering batch mode
  selectedKbIds = [];
  updateGlobalSearchChips();
  kbBatchMode = true;
  selectedBatchKbIds = [];
  lastClickedBatchKbIndex = null;
  document.getElementById('btnKbSelect').style.display = 'none';
  document.getElementById('kbBatchInfo').style.display = '';
  document.getElementById('kbBatchBar').classList.remove('active');
  // Hide regular title text, keep batch info visible
  var header = document.getElementById('kbSectionHeader');
  if (header) header.querySelector('span:first-child').style.display = 'none';
  updateBatchKbUI();
  renderKbList(kbListCache);
}
function exitKbBatchMode() {
  kbBatchMode = false;
  selectedBatchKbIds = [];
  document.getElementById('btnKbSelect').style.display = currentUser && currentUser.role !== 'guest' ? '' : 'none';
  document.getElementById('kbBatchInfo').style.display = 'none';
  document.getElementById('kbBatchBar').classList.remove('active');
  var header = document.getElementById('kbSectionHeader');
  if (header) header.querySelector('span:first-child').style.display = '';
  renderKbList(kbListCache);
}
function toggleBatchKbSelection(kbId) {
  var idx = selectedBatchKbIds.indexOf(kbId);
  if (idx !== -1) selectedBatchKbIds.splice(idx, 1);
  else selectedBatchKbIds.push(kbId);
}
function updateBatchKbUI() {
  var count = selectedBatchKbIds.length;
  var total = kbListCache.length;
  document.getElementById('kbBatchCount').textContent = count;
  var bar = document.getElementById('kbBatchBar');
  if (count > 0) bar.classList.add('active');
  else bar.classList.remove('active');
  // Select-all tri-state
  var label = document.getElementById('kbSelectAllLabel');
  var cb = document.getElementById('kbSelectAllCb');
  var text = document.querySelector('#kbSelectAllLabel .kb-select-all-text');
  if (count === 0) {
    label.classList.remove('all');
    if (cb) cb.checked = false;
    if (text) text.textContent = '全选';
  } else if (count === total) {
    label.classList.add('all');
    if (cb) cb.checked = true;
    if (text) text.textContent = '已选 ' + count + ' 项';
  } else {
    label.classList.remove('all');
    if (cb) cb.checked = false;
    if (text) text.textContent = '全选';
  }
}
// Select-all click handler (stop propagation to prevent entering KB)
document.getElementById('kbSelectAllLabel').addEventListener('click', function(e){
  e.stopPropagation();
});
document.getElementById('kbSelectAllCb').addEventListener('change', function(){
  var total = kbListCache.length;
  if (selectedBatchKbIds.length === total) {
    selectedBatchKbIds = [];
  } else {
    selectedBatchKbIds = kbListCache.map(function(k){ return k.id; });
  }
  lastClickedBatchKbIndex = null;
  updateBatchKbUI();
  renderKbList(kbListCache);
});
// Batch delete
function batchDeleteKbs() {
  if (selectedBatchKbIds.length === 0) return;
  // Check all selected KBs are owned by current user
  var notOwned = selectedBatchKbIds.filter(function(id){
    return kbRoleCache[id] !== 'owner' && currentUser.role !== 'super_admin';
  });
  if (notOwned.length > 0) { toast('只能删除自己拥有的知识库（' + notOwned.length + ' 个不符合）', 'error'); return; }
  if (!confirm('确定要删除选中的 ' + selectedBatchKbIds.length + ' 个知识库吗？此操作不可恢复。')) return;
  var remaining = selectedBatchKbIds.slice();
  var failed = [];
  var done = 0;
  remaining.forEach(function(kbId){
    apiFetch('/api/kb/' + kbId, { method: 'DELETE' })
      .then(function(res){ return handleBusinessResponse(res); })
      .then(function(){
        done++;
        if (done >= remaining.length) finish();
      })
      .catch(function(){
        failed.push(kbId); done++;
        if (done >= remaining.length) finish();
      });
  });
  function finish() {
    var msg = '成功删除 ' + (remaining.length - failed.length) + ' 个';
    if (failed.length > 0) msg += '，失败 ' + failed.length + ' 个';
    toast(msg, failed.length > 0 ? 'warning' : 'success');
    exitKbBatchMode();
    loadKbList();
  }
}
// Batch export
function batchExportKbs() {
  if (selectedBatchKbIds.length === 0) return;
  var kbIds = selectedBatchKbIds.join(',');
  toast('正在导出...', 'info');
  var token = getToken();
  fetch('/api/kb/batch-export?kb_ids=' + encodeURIComponent(kbIds), {
    headers: token ? { 'Authorization': 'Bearer ' + token } : {}
  }).then(function(res) {
    if (res.status === 401) { setToken(''); showAuthPage(); toast('登录已过期', 'error'); throw new Error('Unauthorized'); }
    var ct = res.headers.get('content-type') || '';
    if (ct.indexOf('application/json') !== -1) {
      return res.json().then(function(b) {
        throw new Error(b.msg || '导出失败');
      });
    }
    return res.blob();
  }).then(function(blob) {
    if (!blob) return;
    var url = window.URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'kb_export.zip';
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    a.remove();
    toast('导出成功', 'success');
    exitKbBatchMode();
  }).catch(function(err) {
    if (err.message === 'Unauthorized') return;
    toast('导出失败: ' + err.message, 'error');
  });
}
// Batch share — REMOVED (replaced by document-level batch share in files toolbar)

function updateGlobalSearchChips() {
  var panel = document.getElementById('globalSearchChips');
  var container = document.getElementById('chipsContainer');
  var countEl = document.getElementById('chipsCount');
  if (!panel) return;
  if (selectedKbIds.length === 0) {
    panel.style.display = 'none';
    return;
  }
  panel.style.display = '';
  if (countEl) countEl.textContent = selectedKbIds.length;
  container.innerHTML = selectedKbIds.map(function(id){
    var kb = kbListCache.find(function(k){ return k.id===id; });
    var name = kb ? kb.name : '#'+id;
    return '<span class="chip">'+escapeHtml(name)+
      '<span class="chip-remove" data-kb-id="'+id+'" title="移除">'+icon('x','icon-16')+'</span></span>';
  }).join('');
  // 绑定移除事件
  container.querySelectorAll('.chip-remove').forEach(function(x){
    x.addEventListener('click', function(e){
      e.stopPropagation();
      toggleKbSelection(parseInt(this.dataset.kbId));
    });
  });
}

// KB search filter
document.getElementById('kbSearchInput').addEventListener('input', function(){
  var q = this.value.trim().toLowerCase();
  if (!q) { renderKbList(kbListCache); return; }
  var filtered = kbListCache.filter(function(kb){ return kb.name.toLowerCase().indexOf(q) !== -1; });
  renderKbList(filtered);
});
