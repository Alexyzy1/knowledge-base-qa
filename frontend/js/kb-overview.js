// kb-overview.js
// OVERVIEW PANEL
// ============================================================
async function loadOverview() {
  if (!currentKbId) return;
  var container = document.getElementById('overviewContent');
  var kb = kbListCache.find(function(k){ return k.id === currentKbId; });
  var kbName = kb ? kb.name : '知识库';

  // Delayed spinner: only show loading if API takes > 200ms, avoiding flash
  var loadingTimer = setTimeout(function() {
    container.innerHTML = '<div class="loading-wrap"><span class="spinner"></span>加载中…</div>';
  }, 200);

  try {
    // Fetch stats and settings in parallel
    /*
      GET /api/kb/{id}/stats → {code:0, data:{doc_count, chunk_count, member_count, size_bytes, updated_at}}
      GET /api/kb/{id}/settings → {code:0, data:{name, description, chunk_size, overlap, retrieval_mode, recall_k, top_k, rerank_enabled, rerank_top_n, score_threshold, ocr_enabled, table_parse_enabled, formula_parse_enabled, llm_model, rerank_model, embedding_model, embedding_locked}}
      GET /api/kb/{id}/audit?limit=8 → {code:0, data:[{id, username, action, target, created_at}]}
    */
    var stats = {code:0, data:{doc_count:0, chunk_count:0, member_count:0, size_bytes:0, updated_at:'—'}};
    var settings = {code:0, data:{}};
    var recent = {code:0, data:[]};

    try {
      var r1 = await apiFetch('/api/kb/'+currentKbId+'/stats');
      stats = await handleBusinessResponse(r1);
    } catch(e) { /* 接口未实现时用默认值 */ }

    try {
      var r2 = await apiFetch('/api/kb/'+currentKbId+'/settings');
      settings = await handleBusinessResponse(r2);
    } catch(e) {}

    try {
      // P0-T4: catch 404 from audit endpoint gracefully (endpoint not yet deployed)
      var r3 = await apiFetch('/api/kb/'+currentKbId+'/audit?limit=8');
      if (r3.status === 404) {
        // Audit endpoint not implemented yet; quietly use empty list
        recent = {code:0, data:[]};
      } else {
        recent = await handleBusinessResponse(r3);
      }
    } catch(e) {
      // Network error or non-404: degrade gracefully
      recent = {code:0, data:[]};
    }

    clearTimeout(loadingTimer);

    var s = stats.data;
    var cfg = settings.data || {};

    container.innerHTML =
      // Meta card
      '<div class="card mb-lg">' +
        '<div class="headline" style="margin-bottom:var(--space-xs);">'+escapeHtml(kbName)+'</div>' +
        (cfg.description ? '<p style="font-size:var(--fs-body);font-weight:320;margin-bottom:var(--space-sm);">'+escapeHtml(cfg.description)+'</p>' : '') +
        '<div style="display:flex;gap:var(--space-lg);font-size:var(--fs-body-sm);color:#8B8B8B;">' +
          '<span>所有者：<strong style="color:var(--color-ink);">'+(kb ? escapeHtml(kb.owner_username||'—') : '—')+'</strong></span>' +
          '<span>创建时间: <strong style="color:var(--color-ink);">'+(kb&&kb.created_at ? escapeHtml(String(kb.created_at).replace('T',' ').slice(0,16)) : '—')+'</strong></span>' +
        '</div>' +
      '</div>' +

      // Stat cards
      '<div class="overview-grid">' +
        statCard(s.doc_count, '文档') +
        statCard(s.chunk_count, '文本块') +
        statCard(s.member_count, '成员') +
        statCard(formatBytes(s.size_bytes), '占用大小') +
      '</div>' +

      // Config summary (lime color block)
      '<div class="color-block color-block-lime mb-lg">' +
        '<div class="headline" style="margin-bottom:var(--space-md);">配置摘要</div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-sm) var(--space-xl);font-size:var(--fs-body-sm);">' +
          '<span>分块大小：<strong>'+escapeHtml(cfg.chunk_size||'—')+'</strong></span>' +
          '<span>重叠大小：<strong>'+escapeHtml(cfg.overlap||'—')+'</strong></span>' +
          '<span>检索模式: <strong>'+escapeHtml(cfg.retrieval_mode||'—')+'</strong></span>' +
          '<span>重排: <strong>'+(cfg.rerank_enabled ? ((cfg.rerank_mode==='llm'?'LLM 打分':'Fusion')) : '关闭')+'</strong></span>' +
          '<span>默认 LLM: <strong>'+escapeHtml(cfg.llm_model||'—')+'</strong></span>' +
          '<span>默认 Rerank: <strong>'+escapeHtml(cfg.rerank_model||'—')+'</strong></span>' +
          '<span style="grid-column:1/-1;">Embedding 模型: <span class="badge badge-locked" title="建库后不可更改">🔒 '+escapeHtml(cfg.embedding_model||'—')+' (已锁定)</span></span>' +
        '</div>' +
      '</div>' +

      // Recent activity
      '<div class="card">' +
        '<div class="card-title" style="margin-bottom:var(--space-sm);">最近活动</div>' +
        (recent.data.items && recent.data.items.length > 0
          ? '<table class="data-table"><tbody>' +
            recent.data.items.map(function(a){ return '<tr><td style="font-family:var(--font-mono);font-size:12px;">'+escapeHtml(a.created_at||'')+'</td><td>'+escapeHtml(a.username||'')+'</td><td>'+escapeHtml(a.action||'')+'</td><td>'+escapeHtml(formatAuditTarget(a.target||''))+'</td></tr>'; }).join('') +
            '</tbody></table>'
          : '<p style="color:#8B8B8B;font-size:var(--fs-body-sm);">暂无活动</p>') +
      '</div>' +

      // Owner quick actions
      (isOwner() ? '<div style="margin-top:var(--space-md);display:flex;gap:var(--space-sm);">' +
        '<button class="btn btn-secondary btn-sm" onclick="showPanel(\'settings\')">编辑配置</button>' +
        '<button class="btn btn-secondary btn-sm" onclick="showPanel(\'share\')">管理分享</button>' +
        '<button class="btn btn-secondary btn-sm" onclick="showPanel(\'members\')">管理成员</button>' +
      '</div>' : '');
  } catch(err) {
    clearTimeout(loadingTimer);
    if (err.message === 'Unauthorized') {
      document.getElementById('mainContent').classList.remove('switching');
      return;
    }
    container.innerHTML = '<div class="empty-state"><p>加载失败</p></div>';
  }
  // Always remove crossfade after rendering
  document.getElementById('mainContent').classList.remove('switching');
}

function statCard(value, label) {
  return '<div class="stat-card">' +
    '<div class="stat-value">'+escapeHtml(String(value))+'</div>' +
    '<div class="stat-label">'+label+'</div>' +
  '</div>';
}

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  var k=1024, s=['B','KB','MB','GB'], i=Math.floor(Math.log(bytes)/Math.log(k));
  return parseFloat((bytes/Math.pow(k,i)).toFixed(1))+' '+s[i];
}

function isOwner() {
  if (!currentKbId) return false;
  if (currentUser.role === 'super_admin') return true;
  return (kbRoleCache[currentKbId] || '') === 'owner';
}
