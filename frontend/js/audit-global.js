// audit-global.js
// GLOBAL: AUDIT (SUPER_ADMIN)
// ============================================================
var gAuditPage = 0, gAuditPageSize = 50, gAuditTotal = 0;
function resetGAuditPage() { gAuditPage = 0; loadGlobalAudit(); }

function loadGlobalAudit() {
  if (currentUser.role !== 'super_admin') {
    document.getElementById('gAuditEmpty').classList.remove('hidden');
    document.getElementById('gAuditTable').classList.add('hidden');
    return;
  }

  // 初始化 action 下拉（首次加载）
  var sel = document.getElementById('gAuditActionFilter');
  if (sel.options.length <= 1) {
    Object.keys(AUDIT_ACTION_CN).forEach(function(k){
      var opt = document.createElement('option');
      opt.value = k; opt.textContent = AUDIT_ACTION_CN[k];
      sel.appendChild(opt);
    });
  }

  var loading = document.getElementById('gAuditLoading');
  var empty = document.getElementById('gAuditEmpty');
  var table = document.getElementById('gAuditTable');

  loading.classList.remove('hidden');
  table.classList.add('hidden');
  empty.classList.add('hidden');

  var actionFilter = sel.value;
  var userFilter = document.getElementById('gAuditUserFilter').value.trim();
  var kbFilter = document.getElementById('gAuditKbFilter').value.trim();
  var dateFrom = document.getElementById('gAuditDateFrom').value;
  var dateTo = document.getElementById('gAuditDateTo').value;

  var params = ['limit='+gAuditPageSize, 'offset='+(gAuditPage*gAuditPageSize)];
  if (actionFilter) params.push('action='+encodeURIComponent(actionFilter));
  if (userFilter) params.push('user='+encodeURIComponent(userFilter));
  if (kbFilter) params.push('kb_id='+encodeURIComponent(kbFilter));
  if (dateFrom) params.push('date_from='+encodeURIComponent(dateFrom));
  if (dateTo) params.push('date_to='+encodeURIComponent(dateTo+'T23:59:59'));
  var qs = '?'+params.join('&');

  apiFetch('/api/audit'+qs).then(function(res){ return handleBusinessResponse(res); }).then(function(body){
    var items = body.data && body.data.items ? body.data.items : [];
    gAuditTotal = body.data && body.data.total != null ? body.data.total : items.length;
    loading.classList.add('hidden');
    if (items.length===0) {
      empty.classList.remove('hidden');
    } else {
      table.classList.remove('hidden');
      document.getElementById('gAuditTableBody').innerHTML = items.map(function(a){
        return '<tr><td style="font-family:var(--font-mono);font-size:12px;">'+escapeHtml(String(a.created_at||'').replace('T',' ').slice(0,19))+'</td>' +
          '<td>'+escapeHtml(a.kb_name||a.kb_id||'—')+'</td>' +
          '<td>'+escapeHtml(a.username||'')+'</td>' +
          '<td>'+escapeHtml(AUDIT_ACTION_CN[a.action]||a.action||'')+'</td>' +
          '<td>'+escapeHtml(formatAuditTarget(a.target||''))+'</td>' +
          '<td style="font-family:var(--font-mono);font-size:11px;">'+escapeHtml(a.ip||'')+'</td></tr>';
      }).join('');
    }
    var totalPages = Math.ceil(gAuditTotal / gAuditPageSize) || 1;
    document.getElementById('gAuditPageInfo').textContent = '第'+(gAuditPage+1)+'/'+totalPages+'页 (共'+gAuditTotal+'条)';
    document.getElementById('gAuditPrevPage').disabled = gAuditPage <= 0;
    document.getElementById('gAuditNextPage').disabled = gAuditPage >= totalPages - 1;
  }).catch(function(err){ loading.classList.add('hidden'); if (err.message==='Unauthorized') return; });
}

document.getElementById('gAuditActionFilter').addEventListener('change', resetGAuditPage);
document.getElementById('gAuditUserFilter').addEventListener('input', debounce(resetGAuditPage, 500));
document.getElementById('gAuditKbFilter').addEventListener('input', debounce(resetGAuditPage, 500));
document.getElementById('gAuditDateFrom').addEventListener('change', resetGAuditPage);
document.getElementById('gAuditDateTo').addEventListener('change', resetGAuditPage);
document.getElementById('gAuditPrevPage').addEventListener('click', function(){ if (gAuditPage>0) { gAuditPage--; loadGlobalAudit(); } });
document.getElementById('gAuditNextPage').addEventListener('click', function(){ gAuditPage++; loadGlobalAudit(); });

document.getElementById('btnGAuditExport').addEventListener('click', function(){
  var rows = document.querySelectorAll('#gAuditTableBody tr');
  var csv = '时间,知识库,操作人,动作,对象,IP\n';
  rows.forEach(function(row){
    var cells = row.querySelectorAll('td');
    csv += Array.from(cells).map(function(c){ return '"'+c.textContent.replace(/"/g,'""')+'"'; }).join(',') + '\n';
  });
  var blob = new Blob(['﻿'+csv], {type:'text/csv;charset=utf-8;'});
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = 'global_audit.csv'; a.click();
  URL.revokeObjectURL(url);
});
