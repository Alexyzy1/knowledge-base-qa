// settings.js
// SETTINGS PANEL
// ============================================================
async function loadSettings() {
  if (!currentKbId) return;
  var container = document.getElementById('settingsContent');
  var permHint = document.getElementById('settingsPermHint');

  // Check permission
  if (!isOwner()) {
    container.innerHTML = '';
    permHint.classList.remove('hidden');
    return;
  }
  permHint.classList.add('hidden');

  // Delayed spinner: only show loading if API takes > 200ms
  var settingsLoadingTimer = setTimeout(function() {
    container.innerHTML = '<div class="loading-wrap"><span class="spinner"></span>加载中…</div>';
  }, 200);

  try {
    var res = await apiFetch('/api/kb/'+currentKbId+'/settings');
    var body = await handleBusinessResponse(res);
    var cfg = body.data || {};

    var kb = kbListCache.find(function(k){ return k.id===currentKbId; });
    var kbName = kb ? kb.name : '';

    // Load model options
    var llmModels = []; var rerankModels = [];
    try {
      var r1 = await apiFetch('/api/models?type=llm');
      llmModels = (await handleBusinessResponse(r1)).data || [];
    } catch(e) {}
    try {
      var r2 = await apiFetch('/api/models?type=rerank');
      rerankModels = (await handleBusinessResponse(r2)).data || [];
    } catch(e) {}

    clearTimeout(settingsLoadingTimer);
    container.innerHTML =
      // Notice banner
      '<div class="notice-banner notice-info">配置修改仅对之后新上传的文档生效，已入库文档不受影响。</div>' +

      // Basic info
      '<div class="settings-section">' +
        '<h4>基本信息</h4>' +
        '<div class="settings-card">' +
          '<div class="settings-row">' +
            '<div><div class="setting-label">知识库名称</div></div>' +
            '<input type="text" style="width:240px;padding:8px 12px;border:1px solid var(--color-hairline);border-radius:var(--radius-md);font-size:var(--fs-body-sm);" id="setName" value="'+escapeHtmlAttr(cfg.name||kbName)+'">' +
          '</div>' +
          '<div class="settings-row">' +
            '<div><div class="setting-label">描述</div></div>' +
            '<input type="text" style="width:240px;padding:8px 12px;border:1px solid var(--color-hairline);border-radius:var(--radius-md);font-size:var(--fs-body-sm);" id="setDesc" value="'+escapeHtmlAttr(cfg.description||'')+'">' +
          '</div>' +
        '</div>' +
      '</div>' +

      // Retrieval params
      '<div class="settings-section">' +
        '<h4>检索 / 入库参数</h4>' +
        '<div class="settings-card">' +
          '<div id="setFixedSizes">' +
            settingRowNumber('分块大小','setChunkSize',cfg.chunk_size||500,'字符') +
            settingRowNumber('重叠大小','setOverlap',cfg.overlap||50,'字符') +
          '</div>' +
          settingRowSelectWithDesc('分段策略','setChunkMethod',cfg.chunk_method||'fixed',CHUNK_METHOD_OPTIONS) +
          settingRowSelect('检索模式','setRetrievalMode',cfg.retrieval_mode||'hybrid',[{v:'dense',l:'稠密'},{v:'sparse',l:'稀疏'},{v:'hybrid',l:'混合'}]) +
          settingRowNumber('召回数量','setRecallK',cfg.recall_k||20) +
          settingRowNumber('返回数量','setTopK',cfg.top_k||5) +
          settingRowSelect('重排','setRerankEnabled',(cfg.rerank_enabled ? (cfg.rerank_mode||'fusion') : 'off'),[{v:'off',l:'关闭'},{v:'fusion',l:'Fusion（本地·快）'},{v:'llm',l:'LLM 打分（云端·准）'}]) +
          settingRowNumber('重排返回数','setRerankTopN',cfg.rerank_top_n||3) +
          settingRowNumber('分数阈值','setScoreThreshold',cfg.score_threshold||0.5,'0.0–1.0') +
          settingRowToggle('OCR 识别','setOcrEnabled',cfg.ocr_enabled) +
          settingRowToggle('表格解析','setTableParseEnabled',cfg.table_parse_enabled) +
          settingRowToggle('公式解析','setFormulaParseEnabled',cfg.formula_parse_enabled) +
        '</div>' +
      '</div>' +

      // File management (P2 3.3 — file expiry)
      '<div class="settings-section">' +
        '<h4>安全审查</h4>' +
        '<div class="settings-card">' +
          settingRowToggle('词库快筛','setSafetyEnabled',cfg.safety_enabled != null ? cfg.safety_enabled : true) +
          settingRowToggle('LLM 复审','setSafetyLlmCheck',cfg.safety_llm_check != null ? cfg.safety_llm_check : false) +
        '</div>' +
      '</div>' +

      // File management (P2 3.3 — file expiry)
      '<div class="settings-section">' +
        '<h4>文件管理</h4>' +
        '<div class="settings-card">' +
          '<div class="settings-row">' +
            '<div><div class="setting-label">文件有效期（天）</div><div class="setting-hint">0 = 永不过期；过期文件将标注「已过期」，可手动重新上架</div></div>' +
            '<input type="number" min="0" style="width:100px;padding:8px 12px;border:1px solid var(--color-hairline);border-radius:var(--radius-md);font-size:var(--fs-body-sm);" id="setFileTtl" value="'+(cfg.file_ttl_days!=null?cfg.file_ttl_days:0)+'">' +
          '</div>' +
        '</div>' +
      '</div>' +

      // Default models
      '<div class="settings-section">' +
        '<h4>默认模型</h4>' +
        '<div class="settings-card">' +
          '<div class="settings-row">' +
            '<div><div class="setting-label">默认 LLM 模型</div></div>' +
            '<select style="width:200px;padding:8px 12px;border:1px solid var(--color-hairline);border-radius:var(--radius-md);font-size:var(--fs-body-sm);" class="form-select" id="setLlmModel">' +
              llmModels.map(function(m){ return '<option value="'+m.id+'"'+(cfg.llm_model===m.name||cfg.llm_model===m.id?' selected':'')+'>'+escapeHtml(m.name)+'</option>'; }).join('') +
            '</select>' +
          '</div>' +
          '<div class="settings-row">' +
            '<div><div class="setting-label">默认 Rerank 模型</div></div>' +
            '<select style="width:200px;padding:8px 12px;border:1px solid var(--color-hairline);border-radius:var(--radius-md);font-size:var(--fs-body-sm);" class="form-select" id="setRerankModel">' +
              rerankModels.map(function(m){ return '<option value="'+m.id+'"'+(cfg.rerank_model===m.name||cfg.rerank_model===m.id?' selected':'')+'>'+escapeHtml(m.name)+'</option>'; }).join('') +
            '</select>' +
          '</div>' +
          '<div class="settings-row">' +
            '<div>' +
              '<div class="setting-label">Embedding 模型</div>' +
              '<div class="setting-hint">建库后不可更改，更换需重建知识库</div>' +
            '</div>' +
            '<span class="badge badge-locked">🔒 '+escapeHtml(cfg.embedding_model||'—')+' (已锁定)</span>' +
          '</div>' +
        '</div>' +
      '</div>' +

      // Save button
      '<div style="margin-bottom:var(--space-lg);">' +
        '<button class="btn btn-primary" id="btnSaveSettings">保存配置</button>' +
        '<span id="settingsSaveStatus" style="margin-left:var(--space-sm);font-size:var(--fs-body-sm);color:#8B8B8B;"></span>' +
      '</div>' +

      // Danger zone
      '<div class="danger-zone">' +
        '<h4 style="font-size:var(--fs-card-title);font-weight:700;margin-bottom:var(--space-sm);">危险区</h4>' +
        '<p style="font-size:var(--fs-body-sm);color:#8B8B8B;margin-bottom:var(--space-md);">删除知识库将级联清除所有文档和向量数据，此操作不可恢复。</p>' +
        '<button class="btn btn-danger" id="btnDeleteKB">删除知识库</button>' +
      '</div>';

    // Enhance settings selects (P1 2.3)
    csEnhanceAll(container);
    updateChunkMethodDesc(); // 显示当前切分方法的描述
    // Bind save
    document.getElementById('btnSaveSettings').addEventListener('click', saveSettings);
    // Bind delete
    document.getElementById('btnDeleteKB').addEventListener('click', function(){
      deleteKb(currentKbId, kbName);
    });

  } catch(err) {
    clearTimeout(settingsLoadingTimer);
    if (err.message==='Unauthorized') return;
    container.innerHTML = '<div class="empty-state"><p>加载设置失败</p></div>';
  }
}

function settingRowNumber(label, id, value, hint) {
  return '<div class="settings-row">' +
    '<div><div class="setting-label">'+label+'</div>'+(hint?'<div class="setting-hint">'+hint+'</div>':'')+'</div>' +
    '<input type="number" style="width:100px;padding:8px 12px;border:1px solid var(--color-hairline);border-radius:var(--radius-md);font-size:var(--fs-body-sm);" id="'+id+'" value="'+value+'">' +
  '</div>';
}

function settingRowSelect(label, id, value, options) {
  return '<div class="settings-row">' +
    '<div><div class="setting-label">'+label+'</div></div>' +
    '<select class="form-select" style="width:140px;padding:8px 12px;border:1px solid var(--color-hairline);border-radius:var(--radius-md);font-size:var(--fs-body-sm);" id="'+id+'">' +
      options.map(function(o){ return '<option value="'+o.v+'"'+(value===o.v?' selected':'')+'>'+o.l+'</option>'; }).join('') +
    '</select>' +
  '</div>';
}

function settingRowSelectWithDesc(label, id, value, options) {
  var sel = '<select class="form-select" style="width:180px;padding:8px 12px;border:1px solid var(--color-hairline);border-radius:var(--radius-md);font-size:var(--fs-body-sm);" id="'+id+'" onchange="updateChunkMethodDesc()">' +
    options.map(function(o){ return '<option value="'+o.v+'"'+(value===o.v?' selected':'')+'>'+o.l+'</option>'; }).join('') +
    '</select>';
  return '<div class="settings-row">' +
    '<div><div class="setting-label" style="margin-bottom:4px;">'+label+'</div>' +
    '<div id="'+id+'Desc" style="font-size:12px;color:var(--color-text-secondary);"></div></div>' +
    sel +
  '</div>';
}
var CHUNK_METHOD_OPTIONS = [
  {v:'fixed',l:'固定大小',d:'按字符数硬切+重叠。简单可靠，适合通用文本'},
  {v:'recursive',l:'递归切分',d:'优先段落→句子→逗号逐级回退。生成的 chunk 语义更完整'},
  {v:'markdown',l:'标题感知',d:'按 # 标题层级切分，保留标题路径。适合结构化笔记/文档'},
  {v:'semantic',l:'语义切分',d:'用 embedding 计算相邻句子相似度，在「意思变了」处断开。检索精度高但入库较慢'},
  {v:'sentence_window',l:'句子窗口',d:'每条句子独立成块，附带前后句作上下文。细粒度匹配'},
];
function updateChunkMethodDesc(selId, descId) {
  selId = selId || 'setChunkMethod';
  descId = descId || 'setChunkMethodDesc';
  var sel = document.getElementById(selId);
  var desc = document.getElementById(descId);
  if (sel && desc) {
    var v = sel.value;
    var opt = CHUNK_METHOD_OPTIONS.find(function(o){ return o.v===v; });
    desc.textContent = opt ? opt.d : '';
  }
  // 只有固定大小切分才显示分块大小和重叠
  var sizesId = (selId === 'newKbChunkMethod') ? 'newKbFixedSizes' : 'setFixedSizes';
  var sizes = document.getElementById(sizesId);
  if (sizes) sizes.style.display = (v === 'fixed') ? '' : 'none';
}
function updateNewKbChunkDesc() { updateChunkMethodDesc('newKbChunkMethod', 'newKbChunkDesc'); }
function settingRowToggle(label, id, value) {
  return '<div class="settings-row">' +
    '<div><div class="setting-label">'+label+'</div></div>' +
    '<label class="toggle-wrap" id="'+id+'Wrap">' +
      '<div class="toggle-track'+(value?' on':'')+'"></div>' +
      '<span style="font-size:13px;">'+(value?'开启':'关闭')+'</span>' +
    '</label>' +
  '</div>';
}

function toggleClick(el) {
  var track = el.querySelector('.toggle-track');
  var span = el.querySelector('span');
  var isOn = track.classList.contains('on');
  if (isOn) { track.classList.remove('on'); span.textContent = '关闭'; }
  else { track.classList.add('on'); span.textContent = '开启'; }
}

// Delegate toggle clicks
document.addEventListener('click', function(e){
  var wrap = e.target.closest('.toggle-wrap');
  if (!wrap) return;
  toggleClick(wrap);
});

async function saveSettings() {
  /*
    PUT /api/kb/{id}/settings → {code:0, data:{...updated fields}}
  */
  var data = {
    name: document.getElementById('setName').value.trim(),
    description: document.getElementById('setDesc').value.trim(),
    chunk_size: parseInt(document.getElementById('setChunkSize').value)||undefined,
    overlap: parseInt(document.getElementById('setOverlap').value)||undefined,
    chunk_method: document.getElementById('setChunkMethod').value,
    retrieval_mode: document.getElementById('setRetrievalMode').value,
    recall_k: parseInt(document.getElementById('setRecallK').value)||undefined,
    top_k: parseInt(document.getElementById('setTopK').value)||undefined,
    rerank_enabled: (function(){ var v = document.getElementById('setRerankEnabled').value; return v !== 'off'; })(),
    rerank_mode: document.getElementById('setRerankEnabled').value,
    rerank_top_n: parseInt(document.getElementById('setRerankTopN').value)||undefined,
    score_threshold: parseFloat(document.getElementById('setScoreThreshold').value)||undefined,
    ocr_enabled: document.querySelector('#setOcrEnabledWrap .toggle-track').classList.contains('on'),
    table_parse_enabled: document.querySelector('#setTableParseEnabledWrap .toggle-track').classList.contains('on'),
    formula_parse_enabled: document.querySelector('#setFormulaParseEnabledWrap .toggle-track').classList.contains('on'),
    llm_model: document.getElementById('setLlmModel').value,
    rerank_model: document.getElementById('setRerankModel').value,
    safety_enabled: document.querySelector('#setSafetyEnabledWrap .toggle-track').classList.contains('on'),
    safety_llm_check: document.querySelector('#setSafetyLlmCheckWrap .toggle-track').classList.contains('on'),
    file_ttl_days: (function(){ var el=document.getElementById('setFileTtl'); return el?(parseInt(el.value)||0):undefined; })()
  };

  try {
    var res = await apiFetch('/api/kb/'+currentKbId+'/settings', {
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(data)
    });
    var body = await handleBusinessResponse(res);
    document.getElementById('settingsSaveStatus').textContent = '✓ 已保存';
    setTimeout(function(){ document.getElementById('settingsSaveStatus').textContent = ''; }, 3000);
  } catch(err) {
    if (err.message==='Unauthorized') return;
    document.getElementById('settingsSaveStatus').textContent = '✕ 保存失败';
  }
}

function escapeHtmlAttr(s) { return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function renderMd(text) {
  var raw = marked.parse(String(text||''));
  // XSS 防御：使用 DOMPurify 清洗 LLM 生成的 HTML
  if (typeof DOMPurify !== 'undefined') {
    raw = DOMPurify.sanitize(raw, {ALLOWED_TAGS: ['p','br','strong','em','u','s','del','a','code','pre','blockquote','ul','ol','li','h1','h2','h3','h4','h5','h6','table','thead','tbody','tr','th','td','hr','img','sup','sub','span','div'], ALLOWED_ATTR: ['href','src','alt','title','class','id','target','rel']});
  }
  // [1][2] 引用角标
  raw = raw.replace(/\[(\d+)\]/g, '<sup class="cite">$1</sup>');
  return raw;
}
function copyBubble(btn) {
  var textEl = btn.closest('.bubble.assistant').querySelector('.bubble-text');
  var text = textEl ? textEl.textContent : '';
  navigator.clipboard.writeText(text).then(function() {
    btn.innerHTML = '已复制';
    setTimeout(function() { btn.innerHTML = icon('copy','icon-14'); }, 1500);
  }).catch(function(){});
}
function formatShortTime(s) {
  if (!s) return '—';
  // Normalize: replace T with space, keep only YYYY-MM-DD HH:MM
  var t = String(s).replace('T',' ').slice(0,16);
  return t;
}
