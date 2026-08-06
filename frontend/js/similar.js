// similar.js
// SIMILAR PANEL
// ============================================================
document.getElementById('btnSimilarSearch').addEventListener('click', async function(){
  var textInput = document.getElementById('similarTextInput');
  var text = textInput.value.trim();

  /*
    POST /api/kb/{id}/similar → {code:0, data:[{doc_id, doc_name, kb_id, kb_name, similarity, snippet, highlight_range}]}
    body: {text? doc_id? kb_ids?}  kb_ids 为空时仅搜索当前库，非空时在选定库范围内搜索
  */
  document.getElementById('similarLoading').classList.remove('hidden');
  document.getElementById('similarResults').innerHTML = '';
  document.getElementById('similarEmpty').classList.add('hidden');

  // 确定搜索范围：用户多选了知识库 → 在选定范围内搜；否则仅当前库
  var searchKbIds = selectedKbIds.length > 0 ? selectedKbIds.slice() : [currentKbId];
  if (!currentKbId && searchKbIds.length === 0) return;

  var targetKbId = currentKbId || searchKbIds[0];

  try {
    var body_data = {};
    if (text) body_data.text = text;
    else if (textInput.dataset.docId) body_data.doc_id = parseInt(textInput.dataset.docId);
    else { toast('请输入搜索文本或从文件菜单选择查找相似','info'); return; }
    body_data.kb_ids = searchKbIds;

    var res = await apiFetch('/api/kb/'+targetKbId+'/similar', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body_data)
    });
    var body = await handleBusinessResponse(res);
    var results = body.data || [];

    document.getElementById('similarLoading').classList.add('hidden');

    if (results.length===0) {
      document.getElementById('similarEmpty').classList.remove('hidden');
    } else {
      document.getElementById('similarResults').innerHTML = results.map(function(r){
        var fromOtherKb = (r.kb_id && r.kb_id !== currentKbId);
        return '<div class="similar-result-card">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;">' +
            '<strong style="font-size:var(--fs-body);font-weight:480;">'+escapeHtml(r.doc_name)+'</strong>' +
            '<span class="sim-score">相似度: '+(r.similarity != null ? (r.similarity*100).toFixed(1)+'%' : '—')+'</span>' +
          '</div>' +
          (fromOtherKb
            ? '<div style="font-size:var(--fs-body-sm);color:#8B8B8B;">来自知识库: <em>'+escapeHtml(r.kb_name||'未命名')+'</em></div>'
            : '<div style="font-size:var(--fs-body-sm);color:#8B8B8B;">当前知识库</div>') +
          (r.snippet ? '<div style="font-size:var(--fs-body-sm);margin-top:4px;padding:var(--space-sm);background:var(--color-surface-soft);border-radius:var(--radius-sm);">'+escapeHtml(r.snippet)+'</div>' : '') +
        '</div>';
      }).join('');
    }
  } catch(err) {
    document.getElementById('similarLoading').classList.add('hidden');
    if (err.message==='Unauthorized') return;
  }
});
