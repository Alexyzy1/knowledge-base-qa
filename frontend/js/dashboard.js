// dashboard.js
// GLOBAL: DASHBOARD
// ============================================================
var dashDays = 30;

function loadDashboard(days) {
  if (days) dashDays = days;
  // highlight active time tab
  document.querySelectorAll('#dashTimeTabs button').forEach(function(btn){
    btn.classList.toggle('active', parseInt(btn.dataset.days) === dashDays);
  });

  apiFetch('/api/stats/dashboard?days=' + dashDays).then(function(res){
    if (!res.ok) throw new Error('fetch-error');
    return handleBusinessResponse(res);
  }).then(function(json){
    renderDashboard(json.data);
  }).catch(function(err){
    console.error('loadDashboard failed:', err);
    document.getElementById('dashOverview').innerHTML = '<div class="dash-empty">加载失败，请稍后重试</div>';
  });
}

function renderDashboard(d) {
  // ── 概览卡片 ──
  var ov = d.overview || {};
  var cards = [
    {num: ov.total_users || 0, label: '总用户'},
    {num: ov.total_kbs || 0, label: '总知识库'},
    {num: ov.total_documents || 0, label: '总文档'},
    {num: ov.total_qa_messages || 0, label: '总问答量（' + dashDays + '天）'},
  ];
  document.getElementById('dashOverview').innerHTML = cards.map(function(c){
    return '<div class="stat-card"><div class="stat-num">' + c.num.toLocaleString() + '</div><div class="stat-label">' + escapeHtml(c.label) + '</div></div>';
  }).join('');

  // ── 问答趋势 ──
  renderTrend(d.qa_trend || []);

  // ── 活跃用户排行 ──
  renderTopUsers(d.top_active_users || []);

  // ── 知识库使用详情 ──
  renderKbUsage(d.kb_usage || []);
}

function renderTrend(trend) {
  var el = document.getElementById('dashTrendChart');
  if (!trend.length) {
    el.innerHTML = '<div class="dash-empty">暂无数据</div>'; return;
  }
  var maxVal = Math.max.apply(null, trend.map(function(t){ return t.count; })) || 1;
  var bars = trend.map(function(t){
    var pct = Math.round(t.count / maxVal * 100);
    var shortDate = t.date.slice(5); // MM-DD
    return '<div class="chart-bar-wrap">' +
      '<div class="chart-bar-tooltip">' + t.count + '</div>' +
      '<div class="chart-bar-inner" style="height:' + Math.max(pct, 3) + '%;" title="' + t.date + ': ' + t.count + ' 条"></div>' +
      '<div class="chart-bar-label">' + shortDate + '</div>' +
    '</div>';
  }).join('');
  el.innerHTML = '<div class="chart-container">' + bars + '</div>';
}

function renderTopUsers(users) {
  var el = document.getElementById('dashTopUsers');
  if (!users.length) {
    el.innerHTML = '<div class="dash-empty">暂无数据</div>'; return;
  }
  var rows = users.map(function(u, i){
    var cls = i < 3 ? 'rank-num top3' : 'rank-num';
    return '<tr><td class="' + cls + '">' + (i + 1) + '</td><td>' + escapeHtml(u.username) + '</td><td style="text-align:right;">' + u.message_count + ' 条</td></tr>';
  }).join('');
  el.innerHTML = '<table class="rank-table"><thead><tr><th>#</th><th>用户名</th><th style="text-align:right;">问答数</th></tr></thead><tbody>' + rows + '</tbody></table>';
}

function renderKbUsage(usage) {
  var el = document.getElementById('dashKbUsage');
  if (!usage.length) {
    el.innerHTML = '<div class="dash-empty">暂无数据</div>'; return;
  }
  var items = usage.map(function(u){
    return '<div class="kb-usage-item">' +
      '<div class="kb-name" title="' + escapeHtml(u.kb_name || '') + '">' + escapeHtml(u.kb_name || 'KB#' + u.kb_id) + '</div>' +
      '<div class="kb-stats"><span>文档 <strong>' + (u.doc_count || 0) + '</strong></span><span>问答 <strong>' + (u.message_count || 0) + '</strong></span></div>' +
    '</div>';
  }).join('');
  el.innerHTML = '<div class="kb-usage-grid">' + items + '</div>';
}

// Time tab click handler
document.addEventListener('click', function(e){
  var tab = e.target.closest('#dashTimeTabs button');
  if (tab && tab.dataset.days) {
    loadDashboard(parseInt(tab.dataset.days));
  }
});
