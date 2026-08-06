// kb-create.js
// NEW KB MODAL
// ============================================================
// GLOBAL SEARCH chip buttons
document.getElementById('btnSelectAll').addEventListener('click', function(){
  selectedKbIds = kbListCache.map(function(k){ return k.id; });
  lastClickedKbIndex = null;
  updateGlobalSearchChips();
  renderKbList(kbListCache);
});
document.getElementById('btnClearChips').addEventListener('click', function(){
  selectedKbIds = [];
  lastClickedKbIndex = null;
  updateGlobalSearchChips();
  renderKbList(kbListCache);
});

// ── KB Batch mode event bindings ──
document.getElementById('btnKbSelect').addEventListener('click', enterKbBatchMode);
document.getElementById('btnKbBatchCancel').addEventListener('click', exitKbBatchMode);
document.getElementById('btnKbBatchDelete').addEventListener('click', batchDeleteKbs);
document.getElementById('btnKbBatchExport').addEventListener('click', batchExportKbs);
document.getElementById('btnKbBatchShare').addEventListener('click', showBatchShareModal);

// Batch share modal
document.getElementById('btnCancelBatchShare').addEventListener('click', closeBatchShareModal);
document.getElementById('btnConfirmBatchShare').addEventListener('click', confirmBatchShare);
document.getElementById('modalBatchShare').addEventListener('click', function(e){
  if (e.target === this) closeBatchShareModal();
});

// Esc key → exit batch mode
document.addEventListener('keydown', function(e){
  if (e.key === 'Escape' && kbBatchMode) exitKbBatchMode();
});

// ============================================================
document.getElementById('btnNewKB').addEventListener('click', function(){
  var m = document.getElementById('modalNewKB');
  m.classList.add('open');
  // Reset form fields
  document.getElementById('newKbName').value = '';
  document.getElementById('newKbDesc').value = '';
  document.getElementById('newKbChunkMethod').value = 'recursive';
  document.getElementById('newKbChunkSize').value = '500';
  document.getElementById('newKbOverlap').value = '50';
  document.getElementById('newKbRetrievalMode').value = 'hybrid';
  document.getElementById('newKbRecallK').value = '20';
  document.getElementById('newKbTopK').value = '5';
  document.getElementById('newKbRerankMode').value = 'fusion';
  // Reset toggle tracks
  var safetyTrack = document.querySelector('#newKbSafetyWrap .toggle-track');
  safetyTrack.classList.add('on');
  safetyTrack.nextElementSibling.textContent = '开启';
  var safetyLlmTrack = document.querySelector('#newKbSafetyLlmWrap .toggle-track');
  safetyLlmTrack.classList.remove('on');
  safetyLlmTrack.nextElementSibling.textContent = '关闭';
  // Load LLM models
  var llmSel = document.getElementById('newKbLlmModel');
  llmSel.innerHTML = '<option value="">加载中…</option>';
  apiFetch('/api/models?type=llm&only_enabled=true').then(function(res){ return handleBusinessResponse(res); }).then(function(body){
    var models = body.data || [];
    llmSel.innerHTML = '<option value="">库默认</option>' + models.map(function(m){ return '<option value="'+m.id+'">'+escapeHtml(m.name)+'</option>'; }).join('');
  }).catch(function(){ llmSel.innerHTML = '<option value="">库默认</option>'; });
  // Show description for default chunk method
  updateNewKbChunkDesc();
  setTimeout(function(){ document.getElementById('newKbName').focus(); }, 100);
});

function closeModal(overlayEl) {
  overlayEl.classList.add('closing');
  setTimeout(function(){ overlayEl.classList.remove('open','closing'); }, 180);
}

document.getElementById('btnCancelNewKB').addEventListener('click', function(){
  closeModal(document.getElementById('modalNewKB'));
});
document.getElementById('modalNewKB').addEventListener('click', function(e){
  if (e.target === this) closeModal(this);
});

document.getElementById('btnConfirmNewKB').addEventListener('click', async function(){
  var name = document.getElementById('newKbName').value.trim();
  var desc = document.getElementById('newKbDesc').value.trim();
  if (!name) { toast('请输入知识库名称','info'); return; }

  var overlapVal = parseInt(document.getElementById('newKbOverlap').value, 10);
  var recallVal = parseInt(document.getElementById('newKbRecallK').value, 10);
  var topKVal = parseInt(document.getElementById('newKbTopK').value, 10);
  var chunkSizeVal = parseInt(document.getElementById('newKbChunkSize').value, 10);

  var payload = {
    name: name,
    description: desc || undefined,
    chunk_size: isNaN(chunkSizeVal) ? 500 : chunkSizeVal,
    overlap: isNaN(overlapVal) ? 50 : overlapVal,
    chunk_method: document.getElementById('newKbChunkMethod').value,
    retrieval_mode: document.getElementById('newKbRetrievalMode').value,
    recall_k: isNaN(recallVal) ? 20 : recallVal,
    top_k: isNaN(topKVal) ? 5 : topKVal,
    rerank_mode: document.getElementById('newKbRerankMode').value,
    llm_model: document.getElementById('newKbLlmModel').value || undefined,
    safety_enabled: document.querySelector('#newKbSafetyWrap .toggle-track').classList.contains('on'),
    safety_llm_check: document.querySelector('#newKbSafetyLlmWrap .toggle-track').classList.contains('on')
  };

  var btn = this;
  btn.disabled = true; btn.textContent = '创建中…';

  try {
    var res = await apiFetch('/api/kb', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    var body = await handleBusinessResponse(res);
    toast('知识库创建成功','success');
    closeModal(document.getElementById('modalNewKB'));
    await loadKbList();
    selectKb(body.data.id);
  } catch(err) {
    if (err.message === 'Unauthorized') return;
  } finally {
    btn.disabled = false; btn.textContent = '创建';
  }
});
