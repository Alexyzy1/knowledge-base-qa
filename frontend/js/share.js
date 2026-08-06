// share.js
// SHARE MANAGEMENT — in document detail drawer (single doc + batch via files toolbar)
// ============================================================

// ---- Single doc share (called from detail drawer tab) ----
async function loadShareForDoc(docId, filename) {
  if (!currentKbId || !isOwner()) return;
  var body = document.getElementById('detailBody');
  body.style.whiteSpace = 'normal';

  body.innerHTML =
    '<div class="card mb-lg">' +
      '<h4>新建分享链接</h4>' +
      '<p style="font-size:12px;color:#8B8B8B;margin-bottom:8px;">为 <strong>' + escapeHtml(filename) + '</strong> 生成分享链接</p>' +
      '<div style="display:flex;gap:8px;align-items:flex-end;">' +
        '<div><label class="form-label">有效期</label>' +
        '<select class="form-select" id="shareExpiry">' +
          '<option value="">永久</option>' +
          '<option value="7">7 天</option>' +
          '<option value="30">30 天</option>' +
          '<option value="custom">自定义</option>' +
        '</select></div>' +
        '<button class="btn btn-primary btn-sm" id="btnCreateShareInline">生成链接</button>' +
      '</div>' +
      '<div id="inlineShareResult" style="display:none;margin-top:12px;"></div>' +
    '</div>' +
    '<div id="shareLinkList"></div>' +
    '<div id="shareLoading" class="loading-wrap"><span class="spinner"></span>加载中…</div>' +
    '<div id="shareEmpty" class="empty-state hidden"><p>暂无分享链接</p></div>';
// Switch detail tab to indicate sharing
  document.querySelectorAll('.detail-tab').forEach(function (t) {
    t.classList.toggle('active', t.dataset.dtab === 'share');
  });

  var cb = document.getElementById('btnCreateShareInline');
  if (cb) cb.onclick = async function(){
    var expiry = document.getElementById('shareExpiry').value;
    var body_data = {doc_id: parseInt(docId)};
    if (expiry && expiry !== 'custom') body_data.expires_in_days = parseInt(expiry);
    else if (expiry === 'custom') {
      var days = prompt('请输入有效期天数');
      if (days) body_data.expires_in_days = parseInt(days);
    }
    try {
      var res = await apiFetch('/api/kb/'+currentKbId+'/share', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(body_data)
      });
      var b = await handleBusinessResponse(res);
      var url = window.location.origin + (b.data.url || '/share/'+b.data.token);
      var resultDiv = document.getElementById('inlineShareResult');
      resultDiv.style.display = '';
      resultDiv.innerHTML =
        '<div class="key-reveal" style="word-break:break-all;">'+escapeHtml(url)+'</div>' +
        '<div style="margin-top:8px;display:flex;gap:8px;">' +
          '<button class="btn btn-primary btn-sm" id="btnCopyInlineUrl">复制链接</button>' +
          '<button class="btn btn-secondary btn-sm" id="btnCloseInlineResult">关闭</button>' +
        '</div>';
      var cib = document.getElementById('btnCopyInlineUrl');
      if (cib) cib.onclick = function(){
        copyText(url).then(function(){ toast('链接已复制','success'); });
      };
      var cir = document.getElementById('btnCloseInlineResult');
      if (cir) cir.onclick = function(){ resultDiv.style.display='none'; };
      loadShareListForDoc(docId);
    } catch(err) { if (err.message==='Unauthorized') return; }
  };

  loadShareListForDoc(docId);
}

async function loadShareListForDoc(docId) {
  try {
    var res = await apiFetch('/api/kb/'+currentKbId+'/share');
    var body = await handleBusinessResponse(res);
    var shares = body.data || [];

    // Filter shares for this doc: single share (doc_id matches) or batch share (doc_id===0 and doc_ids includes this doc)
    var docShares = shares.filter(function(s){
      if (s.doc_id === docId) return true;
      if (s.doc_id === 0 && s.doc_ids && s.doc_ids.indexOf(parseInt(docId)) !== -1) return true;
      return false;
    });

    var loading = document.getElementById('shareLoading');
    if (loading) loading.style.display = 'none';

    var empty = document.getElementById('shareEmpty');
    var list = document.getElementById('shareLinkList');

    if (docShares.length === 0) {
      if (empty) empty.classList.remove('hidden');
      if (list) list.innerHTML = '';
    } else {
      if (empty) empty.classList.add('hidden');
      if (list) list.innerHTML = docShares.map(function(s){
        var url = window.location.origin + '/share/' + (s.token||'');
        var isBatch = s.doc_id === 0;
        var label = isBatch ? ('批量分享(' + (s.doc_ids ? s.doc_ids.length : '') + '篇)') : '';
        return '<div class="share-link-row">' +
          '<div style="flex:1;min-width:0;">' +
            '<div style="font-weight:480;">' + (label || escapeHtml(filename)) + '</div>' +
            '<div style="font-family:var(--font-mono);font-size:12px;color:#8B8B8B;overflow:hidden;text-overflow:ellipsis;">'+escapeHtml(url)+'</div>' +
            '<div style="font-size:12px;color:#8B8B8B;">过期: '+(s.expires_at?escapeHtml(s.expires_at):'永久')+'</div>' +
          '</div>' +
          '<div style="display:flex;gap:4px;flex-shrink:0;">' +
            '<button class="btn btn-tertiary btn-sm btn-copy-share" data-url="'+escapeHtmlAttr(url)+'">复制</button>' +
            '<button class="btn btn-tertiary btn-sm btn-revoke-share" data-share-id="'+s.id+'">吊销</button>' +
          '</div>' +
        '</div>';
      }).join('');

      document.querySelectorAll('.btn-copy-share').forEach(function(btn){
        btn.addEventListener('click', function(){
          copyText(this.dataset.url).then(function(){ toast('链接已复制','success'); }).catch(function(){ toast('复制失败','error'); });
        });
      });
      document.querySelectorAll('.btn-revoke-share').forEach(function(btn){
        btn.addEventListener('click', async function(){
          var shareId = parseInt(this.dataset.shareId);
          if (!confirm('确定要吊销此分享链接吗？')) return;
          try {
            await apiFetch('/api/kb/'+currentKbId+'/share/'+shareId, {method:'DELETE'});
            await handleBusinessResponse(res);
            toast('链接已吊销','success');
            loadShareListForDoc(docId);
          } catch(err) { if (err.message==='Unauthorized') return; }
        });
      });
    }
  } catch(err) {
    var ld2 = document.getElementById('shareLoading');
    if (ld2) ld2.style.display = 'none';
    if (err && err.message === 'Unauthorized') return;
    console.error('loadShareListForDoc error:', err);
  }
}

// ---- Batch share (called from files toolbar) ----
function showBatchShareModal() {
  if (!window.selectedDocIds || window.selectedDocIds.size === 0) { console.log('showBatchShareModal: no selectedDocIds'); return; }
  console.log('showBatchShareModal: selectedDocIds=', window.selectedDocIds.size);
  var cnt = document.getElementById('batchShareCount');
  if (cnt) cnt.textContent = window.selectedDocIds.size;
  var bsr = document.getElementById('batchShareResult');
  var bse = document.getElementById('batchShareExpiry');
  var mbs = document.getElementById('modalBatchShare');
  if (bsr) bsr.style.display = 'none';
  if (bse) bse.value = '';
  if (mbs) mbs.classList.add('open');
}

async function confirmBatchShare() {
  var expiryEl = document.getElementById('batchShareExpiry');
  var expiryVal = expiryEl ? expiryEl.value : '';
  var expiryDays = expiryVal ? parseInt(expiryVal) : null;
  var ids = Array.from(selectedDocIds);
  var resultWrap = document.getElementById('batchShareResult');
  var resultDiv = document.getElementById('batchShareLinks');
  if (resultDiv) resultDiv.innerHTML = '生成中…';
  if (resultWrap) resultWrap.style.display = '';

  try {
    var res = await apiFetch('/api/kb/'+currentKbId+'/share/batch', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({doc_ids: ids, expires_in_days: expiryDays})
    });
    var body = await handleBusinessResponse(res);
    var data = body.data || {};
    var url = window.location.origin + (data.url || '/share/'+data.token);
    var docs = data.docs || [];
    resultDiv.innerHTML =
      '<div style="margin-bottom:8px;font-weight:480;">分享链接已生成</div>' +
      '<div class="key-reveal" style="word-break:break-all;margin-bottom:8px;">'+escapeHtml(url)+'</div>' +
      '<div style="font-size:12px;color:#8B8B8B;margin-bottom:12px;">涵盖 ' + data.doc_count + ' 个文档：' +
        docs.map(function(d){ return escapeHtml(d.filename); }).join('、') +
      '</div>' +
      '<div style="display:flex;gap:8px;">' +
        '<button class="btn btn-primary btn-sm" id="btnCopyBatchUrl">复制链接</button>' +
        '<button class="btn btn-secondary btn-sm" id="btnCloseBatchResult">关闭</button>' +
      '</div>';
    var bcu = document.getElementById('btnCopyBatchUrl');
    if (bcu) bcu.onclick = function(){
      copyText(url).then(function(){ toast('链接已复制','success'); });
    };
    var bcb = document.getElementById('btnCloseBatchResult');
    if (bcb) bcb.onclick = function(){ closeBatchShareModal(); };
  } catch(err) {
    resultDiv.innerHTML = '<span style="color:#F44;">生成失败</span>';
  }
}

function closeBatchShareModal() {
  var mb = document.getElementById('modalBatchShare');
  if (mb) mb.classList.remove('open');
}

// Bind batch share (document-level) events — deferred to share.js so functions exist
document.getElementById('btnCancelBatchShare').addEventListener('click', closeBatchShareModal);
document.getElementById('btnConfirmBatchShare').addEventListener('click', confirmBatchShare);
document.getElementById('modalBatchShare').addEventListener('click', function(e){
  if (e.target === this) closeBatchShareModal();
});

// Bind batch share button in files toolbar
var _btnBatchShare = document.getElementById('btnBatchShare');
if (_btnBatchShare) _btnBatchShare.addEventListener('click', showBatchShareModal);