// task-center.js
// TASK CENTER (P2 3.1)
// ============================================================
var taskActiveStatus = 'queued';
var taskPollTimer = null;
function loadTasks(silent) {
  // Demo mode: simulate processing progress increment
  if (DEMO && demoDB) {
    demoDB.tasks.forEach(function(t){
      if (t.status === 'processing') {
        t.progress = Math.min(99, (t.progress || 0) + Math.floor(Math.random() * 8 + 3));
      }
      if (t.status === 'queued' && Math.random() < 0.15) {
        t.status = 'processing'; t.progress = 0;
      }
      if (t.status === 'processing' && t.progress >= 98 && Math.random() < 0.3) {
        t.status = 'done'; t.progress = 100;
      }
    });
  }
  apiFetch('/api/tasks').then(function(res){ return handleBusinessResponse(res); }).then(function(b){
    window.__tasksCache = b.data || [];
    if (!silent) renderTasks();
    updateTaskBadge();
  }).catch(function(){ /* endpoint not deployed */ });
}
function updateTaskBadge() {
  var tasks = window.__tasksCache || [];
  var active = tasks.filter(function(t){ return t.status==='queued' || t.status==='processing'; }).length;
  var badge = document.getElementById('taskBadge');
  if (!badge) return;
  badge.textContent = active;
  badge.classList.toggle('show', active > 0);
  // counts
  var by = function(s){ return tasks.filter(function(t){ return t.status===s; }).length; };
  setText('tcQueued', by('queued')); setText('tcProcessing', by('processing'));
  setText('tcFailed', by('failed')); setText('tcDone', by('done'));
}
function setText(id, v){ var e=document.getElementById(id); if (e) e.textContent = v; }
function renderTasks() {
  var tasks = (window.__tasksCache || []).filter(function(t){ return t.status === taskActiveStatus; });
  var list = document.getElementById('taskList');
  if (tasks.length === 0) {
    list.innerHTML = '<div class="empty-state" style="padding:48px 0;"><span class="icon" style="color:var(--color-hairline);">'+icon('clock','icon-24')+'</span><p>该分类暂无任务</p></div>';
    return;
  }
  list.innerHTML = tasks.map(function(t){
    var iconName = t.status==='failed' ? 'x' : t.status==='done' ? 'check' : t.status==='processing' ? 'spark' : 'clock';
    var pct = t.status==='done' ? 100 : (t.progress||0);
    return '<div class="task-card '+t.status+'">' +
      '<div class="tc-top">' +
        '<span class="tc-icon">'+icon(iconName,'icon-18')+'</span>' +
        '<div style="flex:1;min-width:0;">' +
          '<div class="tc-name" title="'+escapeHtmlAttr(t.filename)+'">'+escapeHtml(t.filename)+'</div>' +
          '<div class="tc-kb">'+escapeHtml(t.kb_name||'')+'</div>' +
        '</div>' +
        '<span class="tc-time">'+escapeHtml(t.started_at||'')+'</span>' +
      '</div>' +
      (t.status==='processing' || t.status==='queued'
        ? '<div class="task-progress-track"><div class="fill" style="width:'+pct+'%;"></div></div>'
        : t.status==='failed'
          ? '<div class="task-progress-track"><div class="fill" style="width:100%;"></div></div>'
          : '') +
      '<div class="tc-foot">' +
        '<span class="tc-pct">'+(t.status==='failed' ? ('失败' + (t.error?'：'+escapeHtml(t.error):'')) : t.status==='done' ? '已完成' : t.status==='queued' ? '排队中' : pct+'%')+'</span>' +
        (t.status==='failed' ? '<button class="btn btn-secondary btn-sm btn-task-retry" data-task-id="'+t.id+'">'+icon('retry','icon-16')+' 重试</button>' : '') +
      '</div>' +
    '</div>';
  }).join('');
  list.querySelectorAll('.btn-task-retry').forEach(function(btn){
    btn.addEventListener('click', function(){
      var tid = parseInt(this.dataset.taskId);
      apiFetch('/api/tasks/'+tid+'/retry', {method:'POST'}).then(function(res){ return handleBusinessResponse(res); }).then(function(){
        toast('已重新加入队列','success'); loadTasks();
      }).catch(function(){});
    });
  });
}
function openTaskDrawer() {
  document.getElementById('drawerTasks').classList.add('open');
  loadTasks();
  // Start polling while drawer is open
  if (!taskPollTimer) {
    taskPollTimer = setInterval(function(){ loadTasks(true); }, 2000);
  }
}
function closeTaskDrawer() {
  document.getElementById('drawerTasks').classList.remove('open');
  if (taskPollTimer) { clearInterval(taskPollTimer); taskPollTimer = null; }
}

// Task center wiring
(function(){
  var bell = document.getElementById('btnTaskCenter');
  document.getElementById('taskBellIcon').innerHTML = icon('bell','icon-20');
  bell.addEventListener('click', openTaskDrawer);
  var closeBtn = document.getElementById('btnCloseTasks');
  closeBtn.innerHTML = icon('x','icon-18');
  closeBtn.addEventListener('click', closeTaskDrawer);
  document.getElementById('drawerTasks').addEventListener('click', function(e){ if (e.target === this) closeTaskDrawer(); });
  document.querySelectorAll('.task-tab').forEach(function(tab){
    tab.addEventListener('click', function(){
      document.querySelectorAll('.task-tab').forEach(function(t){ t.classList.remove('active'); });
      this.classList.add('active');
      taskActiveStatus = this.dataset.tstatus;
      renderTasks();
    });
  });
})();

// Edit tags
function editDocTags(docId, doc) {
  var tags = prompt('编辑标签（逗号分隔）', (doc&&doc.tags||[]).join(', '));
  if (tags === null) return;
  /*
    PUT /api/kb/{kb_id}/docs/{doc_id}/tags → {code:0, data:{doc_id, tags:[...]}}
    body: {tags: ["tag1","tag2"]}
  */
  apiFetch('/api/kb/'+currentKbId+'/docs/'+docId+'/tags', {
    method: 'PUT',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({tags: tags.split(',').map(function(t){ return t.trim(); }).filter(Boolean)})
  }).then(function(res){ return handleBusinessResponse(res); }).then(function(){
    toast('标签已更新','success');
    loadFiles();
  }).catch(function(err){ if (err.message==='Unauthorized') return; });
}

// Delete doc
async function deleteDoc(docId) {
  if (!confirm('确定要删除该文档吗？')) return;
  try {
    var res = await apiFetch('/api/docs/'+docId, { method:'DELETE' });
    var body = await handleBusinessResponse(res);
    toast('文档已删除','success');
    await loadFiles();
  } catch(err) { if (err.message==='Unauthorized') return; }
}

// Folder tree
async function loadFolders() {
  var tree = document.getElementById('folderTreeChildren');
  try {
    var res = await apiFetch('/api/kb/'+currentKbId+'/folders');
    var body = await handleBusinessResponse(res);
    var folders = body.data || [];
    tree.innerHTML = folders.map(function(f){
      return '<div class="folder-tree-item" data-folder-id="'+f.id+'" style="padding-left:'+(20+(f.depth||0)*16)+'px;display:flex;justify-content:space-between;align-items:center;gap:6px;">' +
        '<span style="display:inline-flex;align-items:center;gap:6px;min-width:0;"><span class="folder-icon">'+icon('folder','icon-16')+'</span> <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'+escapeHtml(f.name)+'</span></span>' +
        '<button class="btn-folder-del" data-folder-id="'+f.id+'" style="background:none;border:none;cursor:pointer;opacity:0.4;padding:0 2px;display:inline-flex;" title="删除文件夹">'+icon('x','icon-16')+'</button>' +
      '</div>';
    }).join('');

    // Bind click for navigation
    tree.querySelectorAll('.folder-tree-item').forEach(function(item){
      item.addEventListener('click', function(e){
        if (e.target.closest('.btn-folder-del')) return; // don't navigate on delete click
        document.querySelectorAll('.folder-tree-item').forEach(function(i){ i.classList.remove('active'); });
        this.classList.add('active');
        currentFolderId = this.dataset.folderId;
        loadFiles();
      });
    });

    // Restore active state after re-render
    if (currentFolderId) {
      var activeItem = tree.querySelector('.folder-tree-item[data-folder-id="'+currentFolderId+'"]');
      if (activeItem) activeItem.classList.add('active');
      var allItem = document.querySelector('#folderTree .folder-tree-item[data-folder-id="all"]');
      if (allItem) allItem.classList.remove('active');
    } else {
      // "全部" is active
      var allItem = document.querySelector('#folderTree .folder-tree-item[data-folder-id="all"]');
      if (allItem) allItem.classList.add('active');
    }

    // P1-T7: bind folder delete buttons
    tree.querySelectorAll('.btn-folder-del').forEach(function(btn){
      btn.addEventListener('click', async function(e){
        e.stopPropagation();
        var folderId = this.dataset.folderId;
        if (!confirm('删除文件夹将使其中的文档回到根目录，确定？')) return;
        /*
          DELETE /api/kb/{id}/folders → {code:0, data:{deleted_id}}
          Exact request shape should be confirmed by grepping backend.
          Tentative: DELETE /api/kb/{kb_id}/folders/{folder_id} or body {folder_id}
        */
        try {
          var r = await apiFetch('/api/kb/' + currentKbId + '/folders/' + folderId, {method:'DELETE'});
          var b = await handleBusinessResponse(r);
          toast('文件夹已删除','success');
          loadFolders();
          loadFiles();
        } catch(err) { if (err.message==='Unauthorized') return; }
      });
    });

    // P1-T7: also populate the uploadFolder dropdown
    var uploadSel = document.getElementById('uploadFolder');
    uploadSel.innerHTML = '<option value="">根目录</option>' +
      folders.map(function(f){ return '<option value="'+f.id+'">'+'　'.repeat(f.depth||0)+escapeHtml(f.name)+'</option>'; }).join('');

  } catch(e) { /* Folders endpoint not implemented yet */ }
}

// P1-T7 / P1 2.2: New folder creation via modal with parent dropdown
function promptNewFolder() {
  var sel = document.getElementById('newFolderParent');
  // populate parent options from current folders
  apiFetch('/api/kb/'+currentKbId+'/folders').then(function(res){ return handleBusinessResponse(res); }).then(function(b){
    var folders = b.data || [];
    sel.innerHTML = '<option value="">根目录</option>' + folders.map(function(f){
      return '<option value="'+f.id+'">'+'　'.repeat(f.depth||0)+escapeHtml(f.name)+'</option>';
    }).join('');
    csSync(sel);
  }).catch(function(){ sel.innerHTML = '<option value="">根目录</option>'; csSync(sel); });
  document.getElementById('newFolderName').value = '';
  document.getElementById('modalNewFolder').classList.add('open');
  setTimeout(function(){ document.getElementById('newFolderName').focus(); }, 100);
}
document.getElementById('btnCancelFolder').addEventListener('click', function(){ closeModal(document.getElementById('modalNewFolder')); });
document.getElementById('modalNewFolder').addEventListener('click', function(e){ if (e.target === this) closeModal(this); });
document.getElementById('btnConfirmFolder').addEventListener('click', function(){
  var name = document.getElementById('newFolderName').value.trim();
  if (!name) { toast('请输入文件夹名称','info'); return; }
  var parentId = document.getElementById('newFolderParent').value;
  var payload = { name: name };
  if (parentId) payload.parent_id = parseInt(parentId);
  apiFetch('/api/kb/'+currentKbId+'/folders', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  }).then(function(res){ return handleBusinessResponse(res); }).then(function(){
    toast('文件夹已创建','success');
    closeModal(document.getElementById('modalNewFolder'));
    loadFolders();
  }).catch(function(err){ if (err.message==='Unauthorized') return; });
});

// Folder tree "All" click
document.querySelector('#folderTree .folder-tree-item[data-folder-id="all"]').addEventListener('click', function(){
  document.querySelectorAll('.folder-tree-item').forEach(function(i){ i.classList.remove('active'); });
  this.classList.add('active');
  currentFolderId = null;
  loadFiles();
});

// View toggle
document.getElementById('btnToggleView').addEventListener('click', function(){
  fileViewMode = fileViewMode === 'list' ? 'grid' : 'list';
  this.textContent = fileViewMode === 'list' ? '列表/网格' : '网格/列表';
  loadFiles();
});

// Upload — click
document.getElementById('dropZone').addEventListener('click', function(e){
  if (e.target === document.getElementById('fileInput')) return;
  document.getElementById('fileInput').click();
});

// Upload — file select
document.getElementById('fileInput').addEventListener('change', function(){
  if (this.files.length > 0) handleIncomingFiles(this.files);
  this.value = '';
});

// Upload — drag & drop
['dragenter','dragover','dragleave','drop'].forEach(function(evt){
  document.addEventListener(evt, function(e){ e.preventDefault(); e.stopPropagation(); }, false);
});

var dropZone = document.getElementById('dropZone');
dropZone.addEventListener('dragenter', function(e){ e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragover', function(e){ e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', function(e){
  e.preventDefault();
  if (!dropZone.contains(e.relatedTarget)) dropZone.classList.remove('drag-over');
});
dropZone.addEventListener('drop', function(e){
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  var files = e.dataTransfer.files;
  if (files.length > 0) handleIncomingFiles(files);
});

// ---- Upload pipeline (P1 2.1 size guard + P2 3.4 progress/cancel) ----
var uploadSeq = 0;
function handleIncomingFiles(fileList) {
  if (!currentKbId) { toast('请先选择知识库','info'); return; }
  var files = Array.prototype.slice.call(fileList);
  // Filter invalid files
  var valid = [];
  files.forEach(function(file){
    var check = validateUploadFile(file);
    if (!check.ok) { toast(check.msg, 'error'); return; }
    valid.push(file);
  });
  if (valid.length === 0) return;

  // Add upload summary
  var cardsWrap = document.getElementById('uploadCards');
  var summary = document.createElement('div');
  summary.className = 'upload-summary';
  summary.id = 'uploadSummary';
  summary.textContent = '正在上传 0/' + valid.length + '…';
  if (!document.getElementById('uploadSummary')) {
    cardsWrap.insertBefore(summary, cardsWrap.firstChild);
  }

  // Parallel upload queue (max 3 concurrent)
  var concurrency = 3;
  var running = 0;
  var idx = 0;
  var done = 0;

  function updateSummary() {
    var s = document.getElementById('uploadSummary');
    if (s) s.textContent = '正在上传 ' + done + '/' + valid.length + '…';
  }

  function nextUpload() {
    while (running < concurrency && idx < valid.length) {
      var f = valid[idx++];
      running++;
      uploadFile(f).then(function(){
        done++;
        updateSummary();
      }).catch(function(){}).finally(function(){
        running--;
        nextUpload();
      });
    }
    if (running === 0 && idx >= valid.length) {
      var s = document.getElementById('uploadSummary');
      if (s) setTimeout(function(){ if (s.parentNode) s.remove(); }, 1500);
      loadFiles();
    }
  }
  nextUpload();
}

function uploadFile(file) {
  return new Promise(function(resolve, reject) {
  var id = 'up' + (++uploadSeq);
  var cardsWrap = document.getElementById('uploadCards');
  var card = document.createElement('div');
  card.className = 'upload-card';
  card.id = id;
  card.innerHTML =
    '<div class="uc-top">' +
      '<span class="uc-icon">'+icon(fileIconName(file.name),'icon-18')+'</span>' +
      '<span class="uc-name">'+escapeHtml(file.name)+'</span>' +
      '<span class="uc-pct">0%</span>' +
      '<button class="uc-cancel" title="取消">'+icon('x','icon-16')+'</button>' +
    '</div>' +
    '<div class="uc-track"><div class="fill"></div></div>';
  cardsWrap.appendChild(card);

  var pctEl = card.querySelector('.uc-pct');
  var fillEl = card.querySelector('.fill');
  var cancelBtn = card.querySelector('.uc-cancel');

  // Demo mode: simulate smooth progress
  if (DEMO) {
    var pct = 0;
    var targetDuration = 1500 + Math.random() * 2500; // 1.5-4s total
    var interval = 100; // update every 100ms
    var steps = targetDuration / interval;
    var step = 0;
    var timer = setInterval(function(){
      step++;
      var t = step / steps;
      if (t >= 1) {
        pct = 100; fillEl.style.width = '100%'; pctEl.textContent = '100%';
        clearInterval(timer);
        card.classList.add('done');
        cancelBtn.innerHTML = icon('check','icon-16');
        toast('上传成功，已加入处理队列','success');
        demoAddTask(file.name);
        setTimeout(function(){ card.remove(); resolve(); }, 1200);
      } else {
        // Ease-out curve: smooth progression with subtle jitter
        var eased = 1 - Math.pow(1 - t, 2.5);
        pct = eased * 100 + (Math.random() - 0.5) * 5;
        pct = Math.max(0, Math.min(99, pct));
        fillEl.style.width = pct + '%';
        pctEl.textContent = Math.floor(pct) + '%';
      }
    }, interval);
    cancelBtn.addEventListener('click', function(){
      clearInterval(timer); card.remove(); toast('已取消上传','info'); reject(new Error('cancelled'));
    });
    return;
  }

  // Real upload via XHR for true progress + abort
  var formData = new FormData();
  formData.append('file', file);
  var folderId = document.getElementById('uploadFolder') ? document.getElementById('uploadFolder').value : '';
  if (folderId) formData.append('folder_id', folderId);
  var tagsEl = document.getElementById('uploadTags');
  if (tagsEl && tagsEl.value.trim()) formData.append('tags', tagsEl.value.trim());

  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/kb/' + currentKbId + '/upload');
  var token = getToken();
  if (token) xhr.setRequestHeader('Authorization', 'Bearer ' + token);

  xhr.upload.addEventListener('progress', function(e){
    if (e.lengthComputable) {
      var pct = Math.round((e.loaded / e.total) * 100);
      fillEl.style.width = pct + '%';
      pctEl.textContent = pct + '%';
    }
  });
  xhr.addEventListener('load', function(){
    var ok = false, body = null;
    try { body = JSON.parse(xhr.responseText); ok = (xhr.status === 200 && body.code === 0); } catch(e) {}
    if (xhr.status === 401) { setToken(''); showAuthPage(); toast('登录已过期','error'); card.remove(); reject(new Error('Unauthorized')); return; }
    if (ok) {
      fillEl.style.width = '100%'; pctEl.textContent = '100%';
      card.classList.add('done'); cancelBtn.innerHTML = icon('check','icon-16');
      toast('上传成功，开始处理…','success');
      setTimeout(function(){ card.remove(); loadFiles(); resolve(); }, 900);
    } else {
      card.classList.add('error');
      pctEl.textContent = '失败';
      toast((body && body.msg) || ('上传失败 (HTTP ' + xhr.status + ')'), 'error');
      cancelBtn.innerHTML = icon('x','icon-16');
      reject(new Error((body && body.msg) || ('HTTP ' + xhr.status)));
    }
  });
  xhr.addEventListener('error', function(){
    card.classList.add('error'); pctEl.textContent = '失败';
    toast('网络错误，上传失败','error');
    reject(new Error('network error'));
  });
  cancelBtn.addEventListener('click', function(){
    if (!card.classList.contains('done')) { xhr.abort(); card.remove(); toast('已取消上传','info'); reject(new Error('cancelled')); }
  });
  xhr.send(formData);
  }); // Promise end
}

// Polling
function startPolling() {
  if (pollingTimer) return;
  pollingTimer = setInterval(async function(){
    if (!currentKbId) { stopPolling(); return; }
    try {
      var url = '/api/kb/'+currentKbId+'/docs' + (currentFolderId ? '?folder_id='+currentFolderId : '');
      var res = await apiFetch(url);
      var json = await res.json();
      if (json.code !== 0) return;
      var docs = json.data || [];
      if (docs && !Array.isArray(docs)) docs = docs.items || [];
      var hasPending = docs.some(function(d){ return d.status==='pending'||d.status==='processing'; });
      // Refresh UI
      if (document.getElementById('panel-files').classList.contains('active')) {
        if (fileViewMode === 'list') renderFileList(docs);
        else renderFileGrid(docs);
      }
      if (!hasPending) stopPolling();
    } catch(err) { if (err.message==='Unauthorized') stopPolling(); }
  }, 2000);
}

function stopPolling() {
  if (pollingTimer) { clearInterval(pollingTimer); pollingTimer = null; }
}

// File search
document.getElementById('fileSearchInput').addEventListener('input', function(){
  // TODO: debounce and call API with search param
  // GET /api/kb/{id}/docs?search=keyword
});

// Tag filter
function updateTagFilter(docs) {
  var allTags = new Set();
  docs.forEach(function(d){ (d.tags||[]).forEach(function(t){ allTags.add(t); }); });
  var sel = document.getElementById('fileTagFilter');
  sel.innerHTML = '<option value=""># 全部标签</option>' +
    Array.from(allTags).map(function(t){ return '<option value="'+escapeHtml(t)+'">'+escapeHtml(t)+'</option>'; }).join('');

  sel.onchange = function(){
    var tag = this.value;
    if (!tag) { loadFiles(); return; }
    // Re-filter based on tag
    var url = '/api/kb/'+currentKbId+'/docs?tag='+encodeURIComponent(tag) + (currentFolderId ? '&folder_id='+currentFolderId : '');
    apiFetch(url).then(function(res){
      return handleBusinessResponse(res);
    }).then(function(body){
      if (fileViewMode==='list') renderFileList(body.data||[]);
      else renderFileGrid(body.data||[]);
    }).catch(function(err){});
  };
}

// New note modal
document.getElementById('btnNewNote').addEventListener('click', function(){
  document.getElementById('modalNewNote').classList.add('open');
  document.getElementById('noteTitle').value = '';
  document.getElementById('noteContent').value = '';
});
document.getElementById('btnCancelNote').addEventListener('click', function(){
  closeModal(document.getElementById('modalNewNote'));
});
document.getElementById('modalNewNote').addEventListener('click', function(e){
  if (e.target === this) closeModal(this);
});
document.getElementById('btnSaveNote').addEventListener('click', async function(){
  var title = document.getElementById('noteTitle').value.trim();
  var content = document.getElementById('noteContent').value;
  if (!title) { toast('请输入笔记标题','info'); return; }
  /*
    POST /api/kb/{id}/notes → {code:0, data:{id, filename, status:"done"}}
    body: {title, content}
  */
  try {
    var res = await apiFetch('/api/kb/'+currentKbId+'/notes', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({title:title, content:content, folder_id: currentFolderId || null})
    });
    var body = await handleBusinessResponse(res);
    toast('笔记已保存','success');
    closeModal(document.getElementById('modalNewNote'));
    loadFiles();
  } catch(err) { if (err.message==='Unauthorized') return; }
});
