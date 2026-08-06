// files-detail.js
// FILE DETAIL DRAWER (P2 3.2)
// ============================================================
var detailDocCache = null;
function openDetailDrawer(docId, doc, initialTab) {
  detailDocCache = doc || { id: docId, filename: '文档' };
  var d = detailDocCache;
  document.getElementById('drawerDetail').classList.add('open');
  document.getElementById('detailIcon').innerHTML = icon(fileIconName(d.filename), 'icon-24');
  document.getElementById('detailTitle').textContent = d.filename || '文档';

  var statusText = { pending:'等待中', processing:'处理中', done:'已完成', failed:'解析失败' }[d.status] || d.status || '—';
  var tagsHtml = (d.tags && d.tags.length) ? d.tags.map(function(t){ return '<span class="tag-chip">'+escapeHtml(t)+'</span>'; }).join(' ') : '<span style="color:#8B8B8B;">无</span>';

  document.getElementById('detailMeta').innerHTML =
    '<dt>'+icon('user','icon-16')+'上传人</dt><dd style="display:flex;align-items:center;gap:6px;">'+roleAvatar(d.uploaded_by, docUploaderRole(d),'sm')+escapeHtml(d.uploaded_by||'—')+'</dd>' +
    '<dt>'+icon('clock','icon-16')+'上传时间</dt><dd>'+escapeHtml(formatShortTime(d.uploaded_at||d.updated_at||''))+'</dd>' +
    '<dt>'+icon('files','icon-16')+'大小</dt><dd>'+escapeHtml(formatBytes(d.file_size||d.size_bytes||0))+'</dd>' +
    '<dt>'+icon('check','icon-16')+'解析状态</dt><dd>'+escapeHtml(statusText)+'</dd>' +
    '<dt>'+icon('tag','icon-16')+'标签</dt><dd>'+tagsHtml+'</dd>';

  // tabs reset — 3 tabs: parsed / original / share
  document.querySelectorAll('.detail-tab').forEach(function(t){ t.classList.toggle('active', t.dataset.dtab===(initialTab||'parsed')); });
  // Show/hide share tab — only owner
  var shareTab = document.querySelector('.detail-tab[data-dtab="share"]');
  if (shareTab) shareTab.style.display = isOwner() ? '' : 'none';

  // body
  var body = document.getElementById('detailBody');
  if ((initialTab||'parsed') === 'share') {
    loadShareForDoc(docId, d.filename);
  } else if ((initialTab||'parsed') === 'parsed') {
    body.innerHTML = '<div class="loading-wrap"><span class="spinner"></span>加载预览…</div>';
    apiFetch('/api/docs/'+docId+'/preview').then(function(res){ return handleBusinessResponse(res); }).then(function(b){
      body.dataset.parsed = b.data.markdown || '（无解析内容）';
      body.textContent = b.data.markdown || '（无解析内容）';
    }).catch(function(){ body.textContent = '预览加载失败'; });
  } else {
    // original tab — load iframe later
  }

  // action bar
  var canEdit = isOwner() || (kbRoleCache[currentKbId]==='editor');
  var actions =
    '<button class="btn btn-secondary btn-sm" onclick="downloadDoc('+docId+')">'+icon('download','icon-18')+' 下载</button>' +
    (canEdit && d.status==='failed' ? '<button class="btn btn-primary btn-sm" id="btnDetailRetry">'+icon('retry','icon-18')+' 重新解析</button>' : '') +
    '<button class="btn btn-secondary btn-sm" id="btnDetailSimilar">'+icon('similar','icon-18')+' 找相似</button>' +
    (isOwner() ? '<button class="btn btn-secondary btn-sm" id="btnDetailShare">'+icon('share','icon-18')+' 分享</button>' : '') +
    (canEdit ? '<button class="btn btn-secondary btn-sm" id="btnDetailTags">'+icon('tag','icon-18')+' 编辑标签</button>' : '');
  document.getElementById('detailActions').innerHTML = actions;

  var sim = document.getElementById('btnDetailSimilar');
  if (sim) sim.onclick = function(){ closeDetailDrawer(); showPanel('similar'); var ti=document.getElementById('similarTextInput'); ti.value=''; ti.dataset.docId=docId; toast('已选择「'+d.filename+'」查找相似','info'); };
  var sh = document.getElementById('btnDetailShare');
  if (sh) sh.onclick = function(){
    // Switch to share tab inside drawer
    document.querySelectorAll('.detail-tab').forEach(function(t){ t.classList.toggle('active', t.dataset.dtab==='share'); });
    loadShareForDoc(docId, d.filename);
  };
  var tg = document.getElementById('btnDetailTags');
  if (tg) tg.onclick = function(){ editDocTags(docId, d); };
  var dr = document.getElementById('btnDetailRetry');
  if (dr) dr.onclick = function(){ retryDoc(docId); };
}
function closeDetailDrawer() { document.getElementById('drawerDetail').classList.remove('open'); }
document.getElementById('btnCloseDetail').innerHTML = icon('x','icon-18');
  tab.addEventListener('click', function(){
    document.querySelectorAll('.detail-tab').forEach(function(t){ t.classList.remove('active'); });
    this.classList.add('active');
    var body = document.getElementById('detailBody');
    if (this.dataset.dtab === 'parsed') {
      body.style.whiteSpace = 'pre-wrap';
      body.textContent = body.dataset.parsed || '（无解析内容）';
    } else if (this.dataset.dtab === 'share') {
      if (detailDocCache) loadShareForDoc(detailDocCache.id, detailDocCache.filename);
    } else {
      if (DEMO) { body.style.whiteSpace='normal'; body.innerHTML = '<div style="color:#8B8B8B;display:flex;flex-direction:column;align-items:center;gap:8px;padding:48px 0;">'+icon('doc','icon-24')+'演示模式下不提供原文件二进制预览</div>'; return; }
      var token = getToken();
      var rawUrl = '/api/docs/' + (detailDocCache?detailDocCache.id:'') + '/preview/raw?token=' + encodeURIComponent(token);
      body.style.whiteSpace = 'normal';
      renderMediaPreview(rawUrl, detailDocCache?detailDocCache.filename||'' : '', body, detailDocCache?detailDocCache.id:null);
    }
  });
});

// Reactivate expired doc (P2 3.3)
function reactivateDoc(docId) {
  apiFetch('/api/docs/'+docId+'/reactivate', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({}) })
    .then(function(res){ return handleBusinessResponse(res); })
    .then(function(){ toast('文档已重新上架','success'); closeDetailDrawer(); loadFiles(); })
    .catch(function(err){ if (err.message==='Unauthorized') return; });
}
