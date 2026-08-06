// audit-kb.js
// AUDIT PANEL
// ============================================================
var auditPage = 0, auditPageSize = 50, auditTotal = 0;
var AUDIT_ACTION_CN = {
  'chat':'问答','login':'登录成功','login_failed':'登录失败','login_denied':'登录被拒',
  'create_kb':'创建知识库','delete_kb':'删除知识库','upload_doc':'文档上传',
  'delete_doc':'文档删除','update_tags':'更新标签','create_note':'创建笔记',
  'create_folder':'创建目录','delete_folder':'删除目录','add_member':'添加成员',
  'remove_member':'移除成员','add_whitelist':'添加白名单','remove_whitelist':'移除白名单',
  'create_share':'创建分享','revoke_share':'吊销分享','update_settings':'修改设置',
  'change_password':'修改密码','create_key':'创建API Key','revoke_key':'吊销API Key'
};
function resetAuditPage() { auditPage = 0; loadAudit(); }

async function loadAudit() {
  if (!currentKbId) return;
  if (!isOwner()) {
    document.getElementById('auditPermHint').classList.remove('hidden');
    document.getElementById('auditTable').classList.add('hidden');
    return;
  }
  document.getElementById('auditPermHint').classList.add('hidden');

  var loading = document.getElementById('auditLoading');
  var empty = document.getElementById('auditEmpty');
  var table = document.getElementById('auditTable');
  loading.classList.remove('hidden');
  table.classList.add('hidden');
  empty.classList.add('hidden');

  var actionFilter = document.getElementById('auditActionFilter').value;
  var userFilter = document.getElementById('auditUserFilter').value.trim();
  var dateFrom = document.getElementById('auditDateFrom').value;
  var dateTo = document.getElementById('auditDateTo').value;

  try {
    var params = ['limit='+auditPageSize, 'offset='+(auditPage*auditPageSize)];
    if (actionFilter) params.push('action='+encodeURIComponent(actionFilter));
    if (userFilter) params.push('user='+encodeURIComponent(userFilter));
    if (dateFrom) params.push('date_from='+encodeURIComponent(dateFrom));
    if (dateTo) params.push('date_to='+encodeURIComponent(dateTo+'T23:59:59'));
    var qs = '?'+params.join('&');

    var res = await apiFetch('/api/kb/'+currentKbId+'/audit'+qs);
    var body = await handleBusinessResponse(res);
    var items = body.data && body.data.items ? body.data.items : [];
    auditTotal = body.data && body.data.total != null ? body.data.total : items.length;
    loading.classList.add('hidden');

    if (items.length===0) {
      empty.classList.remove('hidden');
      document.getElementById('auditTableBody').innerHTML = '';
    } else {
      table.classList.remove('hidden');
      document.getElementById('auditTableBody').innerHTML = items.map(function(a){
        return '<tr><td style="font-family:var(--font-mono);font-size:12px;">'+escapeHtml(String(a.created_at||'').replace('T',' ').slice(0,19))+'</td>' +
          '<td>'+escapeHtml(a.username||'')+'</td>' +
          '<td>'+escapeHtml(AUDIT_ACTION_CN[a.action]||a.action||'')+'</td>' +
          '<td>'+escapeHtml(formatAuditTarget(a.target||''))+'</td>' +
          '<td style="font-family:var(--font-mono);font-size:11px;">'+escapeHtml(a.ip||'')+'</td></tr>';
      }).join('');
    }
    // 分页
    var totalPages = Math.ceil(auditTotal / auditPageSize) || 1;
    document.getElementById('auditPageInfo').textContent = '第'+(auditPage+1)+'/'+totalPages+'页 (共'+auditTotal+'条)';
    document.getElementById('auditPrevPage').disabled = auditPage <= 0;
    document.getElementById('auditNextPage').disabled = auditPage >= totalPages - 1;
  } catch(err) {
    loading.classList.add('hidden');
    if (err.message==='Unauthorized') return;
  }
}

// Audit filters
document.getElementById('auditActionFilter').addEventListener('change', resetAuditPage);
document.getElementById('auditUserFilter').addEventListener('input', debounce(resetAuditPage, 500));
document.getElementById('auditDateFrom').addEventListener('change', resetAuditPage);
document.getElementById('auditDateTo').addEventListener('change', resetAuditPage);
document.getElementById('auditPrevPage').addEventListener('click', function(){ if (auditPage>0) { auditPage--; loadAudit(); } });
document.getElementById('auditNextPage').addEventListener('click', function(){ auditPage++; loadAudit(); });

// Export CSV
document.getElementById('btnAuditExport').addEventListener('click', function(){
  var rows = document.querySelectorAll('#auditTableBody tr');
  var csv = '时间,操作人,动作,对象,IP\n';
  rows.forEach(function(row){
    var cells = row.querySelectorAll('td');
    csv += Array.from(cells).map(function(c){ return '"'+c.textContent.replace(/"/g,'""')+'"'; }).join(',') + '\n';
  });
  var blob = new Blob(['﻿'+csv], {type:'text/csv;charset=utf-8;'});
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = 'audit_kb'+currentKbId+'.csv'; a.click();
  URL.revokeObjectURL(url);
});
