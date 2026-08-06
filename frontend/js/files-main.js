// files-main.js
// FILES PANEL
// ============================================================

// ---- Media preview helper (replaces iframe for audio/video) ----
function renderMediaPreview(rawUrl, filename, container, docId) {
  container.innerHTML = '';
  var ext = (String(filename).split('.').pop() || '').toLowerCase();
  var audioExts = ['mp3','flac','wav','aac','m4a','ogg','opus','wma','amr'];
  var videoExts = ['mp4','avi','mov','mkv','flv','wmv','webm','mpeg','mpg','3gp','m4v'];
  var officeExts = ['csv','xlsx','xls','docx','pptx'];
  var imageExts = ['png','jpg','jpeg','gif','svg','webp','bmp'];

  if (imageExts.indexOf(ext) !== -1) {
    var img = document.createElement('img');
    img.src = rawUrl;
    img.style.cssText = 'max-width:100%;max-height:60vh;object-fit:contain;border-radius:var(--radius-md);';
    img.addEventListener('error', function(){
      container.innerHTML = '<p style="color:#8B8B8B;">图片加载失败。<br><a href="'+rawUrl+'" target="_blank">点击在新标签页打开</a></p>';
    });
    container.appendChild(img);
  } else if (audioExts.indexOf(ext) !== -1) {
    var audio = document.createElement('audio');
    audio.controls = true; audio.src = rawUrl;
    audio.style.cssText = 'width:100%;max-width:100%;outline:none;';
    container.appendChild(audio);
  } else if (videoExts.indexOf(ext) !== -1) {
    var video = document.createElement('video');
    video.controls = true; video.src = rawUrl;
    video.style.cssText = 'width:100%;max-width:100%;max-height:70vh;outline:none;';
    container.appendChild(video);
  } else if (officeExts.indexOf(ext) !== -1 && docId) {
    var token = getToken();
    var htmlUrl = '/api/docs/' + docId + '/preview/html?token=' + encodeURIComponent(token);
    var iframe = document.createElement('iframe');
    iframe.src = htmlUrl;
    iframe.style.cssText = 'width:100%;height:60vh;border:1px solid var(--color-hairline);border-radius:var(--radius-md);';
    iframe.addEventListener('error', function(){
      container.innerHTML = '<p style="color:#8B8B8B;">预览加载失败。<br><a href="'+rawUrl+'" target="_blank">点击在新标签页打开</a> ｜ <a href="'+rawUrl.replace('/preview/raw','/download')+'" download>下载</a></p>';
    });
    container.appendChild(iframe);
  } else {
    var iframe2 = document.createElement('iframe');
    iframe2.src = rawUrl;
    iframe2.style.cssText = 'width:100%;height:60vh;border:1px solid var(--color-hairline);border-radius:var(--radius-md);';
    iframe2.addEventListener('error', function(){
      container.innerHTML = '<p style="color:#8B8B8B;">无法内嵌预览此文件类型。<br><a href="'+rawUrl+'" target="_blank">点击在新标签页打开</a></p>';
    });
    container.appendChild(iframe2);
  }
}

// --- Batch selection & toolbar ---
function updateBatchUI() {
  var toolbar = document.getElementById('batchToolbar');
  var countEl = document.getElementById('batchCount');
  if (selectedDocIds.size > 0) {
    toolbar.classList.add('active');
    countEl.textContent = '已选 ' + selectedDocIds.size + ' 项';
  } else {
    toolbar.classList.remove('active');
    countEl.textContent = '已选 0 项';
  }
}

function clearSelection() {
  selectedDocIds.clear();
  lastClickedDocIndex = null;
  document.querySelectorAll('.file-row.selected, .file-grid-card.selected').forEach(function(el){ el.classList.remove('selected'); });
  document.querySelectorAll('.file-cb, .gc-cb').forEach(function(cb){ cb.checked = false; });
  var selectAll = document.getElementById('cbSelectAll');
  if (selectAll) selectAll.checked = false;
  updateBatchUI();
}

function updateRowSelectionStyles() {
  document.querySelectorAll('.file-row').forEach(function(row){
    var docId = parseInt(row.dataset.docId);
    row.classList.toggle('selected', selectedDocIds.has(docId));
  });
  document.querySelectorAll('.file-grid-card').forEach(function(card){
    if (!card.dataset.docId) return;
    var docId = parseInt(card.dataset.docId);
    card.classList.toggle('selected', selectedDocIds.has(docId));
  });
}

function batchDelete() {
  if (selectedDocIds.size === 0) return;
  if (!confirm('确定要删除选中的 ' + selectedDocIds.size + ' 个文档吗？此操作不可恢复。')) return;
  var ids = Array.from(selectedDocIds);
  apiFetch('/api/kb/' + currentKbId + '/docs/batch-delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({doc_ids: ids})
  }).then(function(res){ return handleBusinessResponse(res); }).then(function(body){
    var d = body.data;
    var msg = '成功 ' + d.succeeded.length + ' 个';
    if (d.failed.length > 0) msg += '，失败 ' + d.failed.length + ' 个';
    toast(msg, d.failed.length > 0 ? 'warning' : 'success');
    clearSelection();
    loadFiles();
  }).catch(function(err){ if (err.message === 'Unauthorized') return; });
}

function retryDoc(docId) {
  if (DEMO) { toast('演示模式：已模拟重新解析','info'); return; }
  apiFetch('/api/docs/' + docId + '/retry', { method: 'POST' })
    .then(function(res){ return handleBusinessResponse(res); })
    .then(function(body){
      toast('已重新加入解析队列','success');
      loadFiles();
      loadTasks();
    }).catch(function(err){ if (err.message === 'Unauthorized') return; });
}

function batchRetry() {
  if (selectedDocIds.size === 0) return;
  if (!confirm('确定要重新解析选中的 ' + selectedDocIds.size + ' 个文档吗？')) return;
  var ids = Array.from(selectedDocIds);
  apiFetch('/api/kb/' + currentKbId + '/docs/batch-retry', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({doc_ids: ids})
  }).then(function(res){ return handleBusinessResponse(res); }).then(function(body){
    var d = body.data;
    var msg = '成功 ' + d.succeeded.length + ' 个';
    if (d.failed.length > 0) msg += '，失败 ' + d.failed.length + ' 个';
    toast(msg, d.failed.length > 0 ? 'warning' : 'success');
    clearSelection();
    loadFiles();
    loadTasks();
  }).catch(function(err){ if (err.message === 'Unauthorized') return; });
}

function showBatchTagsModal() {
  if (selectedDocIds.size === 0) return;
  document.getElementById('modalBatchTagsTitle').textContent = '为 ' + selectedDocIds.size + ' 个文档设置标签';
  document.getElementById('batchTagsInput').value = '';
  batchTagsAction = 'set';
  document.querySelectorAll('#batchTagsToggle button').forEach(function(b){
    b.classList.toggle('active', b.dataset.action === 'set');
  });
  document.getElementById('modalBatchTags').classList.add('open');
}

function confirmBatchTags() {
  var tagsStr = document.getElementById('batchTagsInput').value.trim();
  var tags = tagsStr ? tagsStr.split(',').map(function(t){ return t.trim(); }).filter(Boolean) : [];
  if (batchTagsAction !== 'remove' && tags.length === 0) {
    toast('请输入至少一个标签', 'warning'); return;
  }
  var ids = Array.from(selectedDocIds);
  apiFetch('/api/kb/' + currentKbId + '/docs/batch-tags', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({doc_ids: ids, action: batchTagsAction, tags: tags})
  }).then(function(res){ return handleBusinessResponse(res); }).then(function(body){
    var d = body.data;
    var msg = '成功 ' + d.succeeded.length + ' 个';
    if (d.failed.length > 0) msg += '，失败 ' + d.failed.length + ' 个';
    toast(msg, d.failed.length > 0 ? 'warning' : 'success');
    closeBatchTagsModal();
    clearSelection();
    loadFiles();
  }).catch(function(err){ if (err.message === 'Unauthorized') return; });
}

function closeBatchTagsModal() {
  document.getElementById('modalBatchTags').classList.remove('open');
}

function batchMoveToFolder(folderId) {
  if (selectedDocIds.size === 0) return;
  var ids = Array.from(selectedDocIds);
  apiFetch('/api/kb/' + currentKbId + '/docs/batch-move', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({doc_ids: ids, folder_id: folderId || null})
  }).then(function(res){ return handleBusinessResponse(res); }).then(function(body){
    var d = body.data;
    var msg = '成功 ' + d.succeeded.length + ' 个';
    if (d.failed.length > 0) msg += '，失败 ' + d.failed.length + ' 个';
    toast(msg, d.failed.length > 0 ? 'warning' : 'success');
    closeBatchFolderMenu();
    clearSelection();
    loadFiles();
  }).catch(function(err){ if (err.message === 'Unauthorized') return; });
}

function batchDownload() {
  if (selectedDocIds.size === 0) return;
  var ids = Array.from(selectedDocIds);
  var token = getToken();
  fetch('/api/kb/' + currentKbId + '/docs/batch-download', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (token||'')},
    body: JSON.stringify({doc_ids: ids})
  }).then(function(res){
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var disp = res.headers.get('Content-Disposition') || '';
    var match = disp.match(/filename\*=UTF-8''(.+)/);
    var filename = match ? decodeURIComponent(match[1]) : 'docs.zip';
    return res.blob().then(function(blob){ return {blob: blob, filename: filename}; });
  }).then(function(r){
    var url = URL.createObjectURL(r.blob);
    var a = document.createElement('a');
    a.href = url; a.download = r.filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
    toast('下载完成', 'success');
    clearSelection();
  }).catch(function(err){
    toast('下载失败: ' + err.message, 'error');
  });
}

function openBatchFolderMenu() {
  var menu = document.getElementById('batchFolderMenu');
  apiFetch('/api/kb/' + currentKbId + '/folders').then(function(res){ return handleBusinessResponse(res); }).then(function(b){
    var folders = b.data || [];
    menu.innerHTML = '<div class="bfm-item" data-folder-id="">'+icon('folder','icon-16')+' 根目录</div>' +
      folders.map(function(f){ return '<div class="bfm-item" data-folder-id="'+f.id+'" style="padding-left:'+(16+(f.depth||0)*16)+'px;">'+icon('folder','icon-16')+' '+escapeHtml(f.name)+'</div>'; }).join('');
    menu.querySelectorAll('.bfm-item').forEach(function(item){
      item.addEventListener('click', function(){ batchMoveToFolder(this.dataset.folderId || null); });
    });
  }).catch(function(){});
  menu.classList.toggle('open');
}

function closeBatchFolderMenu() {
  document.getElementById('batchFolderMenu').classList.remove('open');
}

// ---

async function loadFiles() {
  clearSelection();
  if (!currentKbId) return;
  var loading = document.getElementById('filesLoading');
  var empty = document.getElementById('filesEmpty');
  var list = document.getElementById('fileList');

  loading.classList.remove('hidden');
  empty.classList.add('hidden');
  list.classList.add('hidden');
  document.getElementById('fileGrid').classList.add('hidden');

  // Load folders
  loadFolders();

  try {
    var res = await apiFetch('/api/kb/'+currentKbId+'/docs' + (currentFolderId ? '?folder_id='+currentFolderId : ''));
    var body = await handleBusinessResponse(res);
    var docs = body.data || [];
    // 兼容分页格式 {items:[], total:N} 和旧格式 [...]
    if (docs && !Array.isArray(docs)) docs = docs.items || [];
    loading.classList.add('hidden');

    if (docs.length === 0) {
      empty.classList.remove('hidden');
    } else {
      if (fileViewMode === 'list') renderFileList(docs);
      else renderFileGrid(docs);
    }

    // Upload permission
    var role = kbRoleCache[currentKbId] || 'reader';
    var canUpload = (role === 'owner' || role === 'editor' || currentUser.role === 'super_admin');
    document.getElementById('dropZone').style.display = canUpload ? '' : 'none';
    document.getElementById('filesPermHint').classList.toggle('hidden', canUpload);

    // Polling
    var hasPending = docs.some(function(d){ return d.status==='pending'||d.status==='processing'; });
    if (hasPending) startPolling();
    else stopPolling();

    // Update tag filter options
    updateTagFilter(docs);
  } catch(err) {
    loading.classList.add('hidden');
    if (err.message === 'Unauthorized') return;
  }
}

function renderFileList(docs) {
  // Preserve open action bars across polling refreshes
  var openActionBars = new Set();
  document.querySelectorAll('.file-action-bar.open').forEach(function(b){ openActionBars.add(parseInt(b.dataset.docId)); });

  var list = document.getElementById('fileList');
  document.getElementById('fileGrid').classList.add('hidden');
  list.classList.remove('hidden');

  var head =
    '<div class="file-col-head">' +
      '<span class="file-cb-head"><input type="checkbox" id="cbSelectAll" title="全选"></span>' +
      '<span style="flex:1;">名称</span>' +
      '<span class="fch-uploader" style="width:130px;">上传人</span>' +
      '<span class="fch-time" style="width:130px;">上传时间</span>' +
      '<span style="width:96px;text-align:right;">操作</span>' +
    '</div>';

  list.innerHTML = head + docs.map(function(d){
    var fic = icon(fileIconName(d.filename), 'icon-20');
    var statusBadge = fileStatusBadge(d);
    var exp = fileExpiryLabel(d);
    var expired = isExpired(d);

    var canEdit = (kbRoleCache[currentKbId]==='owner'||kbRoleCache[currentKbId]==='editor'||currentUser.role==='super_admin');
    return '<div class="file-row'+(expired?' expired':'')+'" data-doc-id="'+d.id+'">' +
      '<span class="file-cb-wrap"><input type="checkbox" class="file-cb" data-doc-id="'+d.id+'"></span>' +
      '<span class="file-icon" style="color:#8B8B8B;">'+fic+'</span>' +
      '<span class="file-name" title="'+escapeHtmlAttr(d.filename)+'">'+escapeHtml(d.filename)+'</span>' +
      statusBadge +
      exp +
      '<span class="file-uploader">'+roleAvatar(d.uploaded_by, docUploaderRole(d), 'sm')+escapeHtml(d.uploaded_by||'—')+'</span>' +
      '<span class="file-time" title="'+escapeHtmlAttr(d.uploaded_at||d.updated_at||'')+'">'+escapeHtml(formatShortTime(d.uploaded_at||d.updated_at||''))+'</span>' +
      '<div class="file-act-icons">' +
        '<button class="file-act-btn act-preview" data-doc-id="'+d.id+'" title="预览">'+icon('eye','icon-18')+'</button>' +
        '<button class="file-act-btn act-download" data-doc-id="'+d.id+'" title="下载">'+icon('download','icon-18')+'</button>' +
        (d.status==='failed'&&canEdit ? '<button class="file-act-btn act-retry" data-doc-id="'+d.id+'" title="重新解析">'+icon('retry','icon-18')+'</button>' : '') +
        '<button class="file-act-btn btn-file-menu" data-doc-id="'+d.id+'" title="更多">'+icon('more','icon-18')+'</button>' +
      '</div>' +
    '</div>' +
    '<div class="file-action-bar" data-doc-id="'+d.id+'">' +
      '<button class="act-bar-btn act-preview">'+icon('eye','icon-18')+'查看详情</button>' +
      '<button class="act-bar-btn act-download">'+icon('download','icon-18')+'下载</button>' +
      (canEdit && d.status==='failed' ? '<button class="act-bar-btn act-retry">'+icon('retry','icon-18')+'重新解析</button>' : '') +
      (canEdit ? '<button class="act-bar-btn act-similar">'+icon('similar','icon-18')+'查找相似</button>' : '') +
      (canEdit ? '<button class="act-bar-btn act-tags">'+icon('tag','icon-18')+'编辑标签</button>' : '') +
      (canEdit && isExpired(d) ? '<button class="act-bar-btn act-reactivate">'+icon('retry','icon-18')+'重新上架</button>' : '') +
      (canEdit ? '<button class="act-bar-btn danger act-delete">'+icon('trash','icon-18')+'删除</button>' : '') +
    '</div>';
  }).join('');

  bindFileRowEvents(docs);

  // Re-open action bars that were open before the refresh
  openActionBars.forEach(function(docId){
    var bar = document.querySelector('.file-action-bar[data-doc-id="'+docId+'"]');
    if (bar) bar.classList.add('open');
  });
}

function fileStatusBadge(d) {
  if (d.status === 'pending')    return '<span class="badge badge-warning">等待中</span>';
  if (d.status === 'processing') return '<span class="badge badge-info"><span class="spinner spinner-sm"></span> 处理中</span>';
  if (d.status === 'failed')     return '<span class="badge badge-danger">失败</span>';
  if (isExpired(d))              return '<span class="badge badge-expired">已过期</span>';
  return '';
}
function isExpired(d) {
  if (!d.expires_at) return false;
  var t = new Date(String(d.expires_at).replace(/-/g,'/'));
  return !isNaN(t) && t.getTime() < Date.now();
}
function fileExpiryLabel(d) {
  if (!d.expires_at) return '';
  var t = new Date(String(d.expires_at).replace(/-/g,'/'));
  if (isNaN(t)) return '';
  var days = Math.ceil((t.getTime() - Date.now()) / 86400000);
  if (days < 0) return '<span class="file-expiry expired">已过期</span>';
  if (days <= 7) return '<span class="file-expiry expired">'+days+'天后到期</span>';
  return '<span class="file-expiry">'+days+'天后到期</span>';
}
function docUploaderRole(d) {
  if (!d.uploaded_by) return 'reader';
  var mem = (DEMO && demoDB) ? null : null;
  try {
    var members = (window.__membersCache && window.__membersCache[currentKbId]) || [];
    var found = members.find(function(m){ return m.username === d.uploaded_by; });
    if (found) return found.role;
  } catch(e){}
  return 'editor';
}

function renderFileGrid(docs) {
  var grid = document.getElementById('fileGrid');
  document.getElementById('fileList').classList.add('hidden');
  grid.classList.remove('hidden');

  grid.innerHTML = docs.map(function(d){
    var expired = isExpired(d);
    return '<div class="file-grid-card'+(expired?' expired':'')+'" data-doc-id="'+d.id+'">' +
      '<input type="checkbox" class="gc-cb" data-doc-id="'+d.id+'">' +
      '<div style="color:#8B8B8B;margin-bottom:6px;">'+icon(fileIconName(d.filename),'icon-24')+'</div>' +
      '<div style="font-size:var(--fs-body-sm);font-weight:480;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="'+escapeHtmlAttr(d.filename)+'">'+escapeHtml(d.filename)+'</div>' +
      '<div style="display:flex;align-items:center;gap:6px;font-size:12px;color:#8B8B8B;">'+roleAvatar(d.uploaded_by, docUploaderRole(d), 'sm')+escapeHtml(d.uploaded_by||'—')+'</div>' +
      '<div style="display:flex;align-items:center;gap:6px;margin-top:2px;">'+(fileStatusBadge(d)||'<span class="badge badge-success">已完成</span>')+fileExpiryLabel(d)+'</div>' +
    '</div>';
  }).join('');

  bindFileRowEvents(docs);
}

function bindFileRowEvents(docs) {
  function findDoc(id){ return docs.find(function(d){ return d.id===id; }); }
  // Row / card — Explorer-style: click=select, Ctrl=toggle, Shift=range, dblclick=preview
  document.querySelectorAll('.file-row, .file-grid-card').forEach(function(row){
    row.addEventListener('click', function(e){
      if (e.target.closest('.file-act-icons') || e.target.closest('.btn-file-menu') || e.target.closest('.context-menu')) return;
      if (e.target.closest('.file-cb') || e.target.closest('.gc-cb')) return;
      var cb = this.querySelector('.file-cb, .gc-cb');
      if (!cb) return;
      var docId = parseInt(cb.dataset.docId);
      var allCbs = Array.from(document.querySelectorAll('.file-cb, .gc-cb'));
      var idx = allCbs.indexOf(cb);
      if (e.shiftKey && lastClickedDocIndex !== null) {
        // Shift: range from anchor to current (merge with existing)
        var start = Math.min(lastClickedDocIndex, idx);
        var end   = Math.max(lastClickedDocIndex, idx);
        for (var i = start; i <= end; i++) {
          allCbs[i].checked = true;
          selectedDocIds.add(parseInt(allCbs[i].dataset.docId));
        }
      } else if (e.ctrlKey || e.metaKey) {
        // Ctrl: toggle this item, set anchor
        cb.checked = !cb.checked;
        if (cb.checked) selectedDocIds.add(docId); else selectedDocIds.delete(docId);
        lastClickedDocIndex = idx;
      } else {
        // Plain click: select ONLY this item
        selectedDocIds.clear();
        allCbs.forEach(function(c){ c.checked = false; });
        cb.checked = true;
        selectedDocIds.add(docId);
        lastClickedDocIndex = idx;
      }
      updateBatchUI();
      updateRowSelectionStyles();
    });
    row.addEventListener('dblclick', function(e){
      if (e.target.closest('.file-act-icons') || e.target.closest('.btn-file-menu') || e.target.closest('.context-menu')) return;
      if (e.target.closest('.file-cb') || e.target.closest('.gc-cb')) return;
      var docId = parseInt(this.dataset.docId);
      openDetailDrawer(docId, findDoc(docId));
    });
  });
  // Inline preview icon
  document.querySelectorAll('.act-preview').forEach(function(btn){
    btn.addEventListener('click', function(e){
      e.stopPropagation();
      var docId = parseInt(this.dataset.docId);
      openDetailDrawer(docId, findDoc(docId));
    });
  });
  // Inline download icon
  document.querySelectorAll('.act-download').forEach(function(btn){
    btn.addEventListener('click', function(e){
      e.stopPropagation();
      downloadDoc(parseInt(this.dataset.docId));
    });
  });
  // Inline retry icon
  document.querySelectorAll('.act-retry').forEach(function(btn){
    btn.addEventListener('click', function(e){
      e.stopPropagation();
      retryDoc(parseInt(this.dataset.docId));
    });
  });
  // Three-dots → toggle action bar
  document.querySelectorAll('.btn-file-menu').forEach(function(btn){
    btn.addEventListener('click', function(e){
      e.stopPropagation();
      var docId = parseInt(this.dataset.docId);
      var bar = document.querySelector('.file-action-bar[data-doc-id="'+docId+'"]');
      if (!bar) return;
      var wasOpen = bar.classList.contains('open');
      closeAllFileActionBars();
      if (!wasOpen) bar.classList.add('open');
    });
  });
  // Action bar button clicks
  document.querySelectorAll('.file-action-bar .act-bar-btn').forEach(function(btn){
    btn.addEventListener('click', function(e){
      e.stopPropagation();
      var bar = this.closest('.file-action-bar');
      var docId = parseInt(bar.dataset.docId);
      var doc = findDoc(docId);
      if (this.classList.contains('act-preview'))   { openDetailDrawer(docId, doc); closeAllFileActionBars(); }
      if (this.classList.contains('act-download'))   { downloadDoc(docId); closeAllFileActionBars(); }
      if (this.classList.contains('act-retry'))     { retryDoc(docId); closeAllFileActionBars(); }
      if (this.classList.contains('act-similar'))    { showPanel('similar'); document.getElementById('similarTextInput').value=''; document.getElementById('similarTextInput').dataset.docId=docId; closeAllFileActionBars(); }
      if (this.classList.contains('act-tags'))       { editDocTags(docId, doc); closeAllFileActionBars(); }
      if (this.classList.contains('act-reactivate')) { reactivateDoc(docId); closeAllFileActionBars(); }
      if (this.classList.contains('act-delete'))     { deleteDoc(docId); closeAllFileActionBars(); }
    });
  });
}

function closeAllFileActionBars() {
  document.querySelectorAll('.file-action-bar.open').forEach(function(b){ b.classList.remove('open'); });
}
// Global click → close any open action bar
document.addEventListener('click', function(e){
  if (e.target.closest('.file-row') || e.target.closest('.file-action-bar')) return;
  closeAllFileActionBars();
});

function fileIcon(filename) {
  return icon(fileIconName(filename), 'icon-20');
}

function showFileContextMenu(e, docId, doc) {
  var menu = document.getElementById('contextMenu');
  var role = kbRoleCache[currentKbId] || 'reader';
  var canEdit = (role==='owner'||role==='editor'||currentUser.role==='super_admin');
  var canDelete = canEdit;

  menu.innerHTML = '';
  addCtxItem(menu, 'eye', '查看详情', function(){ openDetailDrawer(docId, doc); menu.classList.add('hidden'); });
  addCtxItem(menu, 'download', '下载', function(){ downloadDoc(docId); menu.classList.add('hidden'); });
  if (canEdit) {
    if (doc && doc.status === 'failed') addCtxItem(menu, 'retry', '重新解析', function(){ retryDoc(docId); menu.classList.add('hidden'); });
    addCtxItem(menu, 'similar', '查找相似', function(){ showPanel('similar'); document.getElementById('similarTextInput').value=''; document.getElementById('similarTextInput').dataset.docId=docId; menu.classList.add('hidden'); });
    addCtxItem(menu, 'tag', '编辑标签', function(){ editDocTags(docId, doc); menu.classList.add('hidden'); });
    if (doc && isExpired(doc)) addCtxItem(menu, 'retry', '重新上架', function(){ reactivateDoc(docId); menu.classList.add('hidden'); });
  }
  if (canDelete) {
    addCtxItem(menu, 'trash', '删除', function(){ deleteDoc(docId); menu.classList.add('hidden'); }, true);
  }

  menu.style.left = e.clientX + 'px';
  menu.style.top = e.clientY + 'px';
  menu.style.right = 'auto';
  menu.style.bottom = 'auto';
  // Viewport boundary check: flip if would overflow
  menu.classList.remove('hidden');
  var rect = menu.getBoundingClientRect();
  if (rect.right > window.innerWidth - 8) {
    menu.style.left = 'auto';
    menu.style.right = (window.innerWidth - e.clientX + 8) + 'px';
  }
  if (rect.bottom > window.innerHeight - 8) {
    menu.style.top = 'auto';
    menu.style.bottom = (window.innerHeight - e.clientY + 8) + 'px';
  }

  setTimeout(function(){
    document.addEventListener('click', function hide(){ menu.classList.add('hidden'); document.removeEventListener('click',hide); }, {once:true});
  }, 10);
}

function addCtxItem(menu, iconName, label, fn, danger) {
  var btn = document.createElement('button');
  btn.style.cssText = 'display:flex;align-items:center;gap:8px;';
  btn.innerHTML = icon(iconName,'icon-16') + '<span>' + escapeHtml(label) + '</span>';
  if (danger) btn.style.color = 'var(--color-semantic-danger)';
  btn.addEventListener('click', fn);
  menu.appendChild(btn);
}

// File preview drawer
var drawerPreviewDocId = null;  // P0-T6: store docId so the "original" tab can build raw URL
var drawerPreviewFilename = '';
function openPreviewDrawer(docId, filename) {
  drawerPreviewDocId = docId;
  drawerPreviewFilename = filename || '';
  var drawer = document.getElementById('drawerPreview');
  drawer.classList.add('open');
  document.getElementById('drawerTabParsed').classList.add('active');
  document.getElementById('drawerTabOriginal').classList.remove('active');
  document.getElementById('drawerParsedContent').innerHTML = '<div class="loading-wrap"><span class="spinner"></span>加载预览…</div>';
  document.getElementById('drawerParsedContent').classList.remove('hidden');
  document.getElementById('drawerOriginalContent').classList.add('hidden');

  // Load preview
  /*
    GET /api/docs/{id}/preview/raw?token= → inline (iframe), needs ?token= for auth
  */
  apiFetch('/api/docs/'+docId+'/preview').then(function(res){
    return handleBusinessResponse(res);
  }).then(function(body){
    var data = body.data;
    document.getElementById('drawerParsedContent').innerHTML =
      '<div style="white-space:pre-wrap;word-break:break-word;font-size:var(--fs-body);line-height:var(--lh-body);">' +
      escapeHtml(data.markdown||'') +
      '</div>' +
      (data.chunks && data.chunks.length > 0 ? '<div style="margin-top:var(--space-md);"><span class="text-caption">文本块 ('+data.chunks.length+')</span></div>' : '');
    // Store chunks for highlight toggle
    document.getElementById('drawerParsedContent').dataset.chunks = JSON.stringify(data.chunks||[]);
  }).catch(function(err){
    if (err.message === 'Unauthorized') return;
    document.getElementById('drawerParsedContent').innerHTML = '<p style="color:#8B8B8B;">预览加载失败</p>';
  });
}

document.getElementById('btnCloseDrawer').addEventListener('click', function(){
  document.getElementById('drawerPreview').classList.remove('open');
});
document.getElementById('drawerPreview').addEventListener('click', function(e){
  if (e.target === this) this.classList.remove('open');
});

// Drawer tabs
document.getElementById('drawerTabParsed').addEventListener('click', function(){
  this.classList.add('active');
  document.getElementById('drawerTabOriginal').classList.remove('active');
  document.getElementById('drawerParsedContent').classList.remove('hidden');
  document.getElementById('drawerOriginalContent').classList.add('hidden');
});
document.getElementById('drawerTabOriginal').addEventListener('click', function(){
  this.classList.add('active');
  document.getElementById('drawerTabParsed').classList.remove('active');
  document.getElementById('drawerParsedContent').classList.add('hidden');
  var rawContainer = document.getElementById('drawerOriginalContent');
  rawContainer.classList.remove('hidden');
  var token = getToken();
  var rawUrl = '/api/docs/' + drawerPreviewDocId + '/preview/raw?token=' + encodeURIComponent(token);
  renderMediaPreview(rawUrl, drawerPreviewFilename || '', rawContainer, drawerPreviewDocId);
});

// Download doc
function downloadDoc(docId) {
  if (DEMO) { toast('演示模式：已模拟下载','info'); return; }
  // P0-T3: GET /api/docs/{id}/download → binary file, needs ?token= for auth
  var token = getToken();
  window.open('/api/docs/' + docId + '/download?token=' + encodeURIComponent(token), '_blank');
}
