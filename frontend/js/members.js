// members.js
// MEMBERS PANEL
// ============================================================
var ROLE_CAPS = {
  owner:       { '上传':1, '删除':1, '设置':1, '成员管理':1, '审计':1, '分享':1 },
  editor:      { '上传':1, '删除':1, '设置':0, '成员管理':0, '审计':0, '分享':0 },
  reader:      { '上传':0, '删除':0, '设置':0, '成员管理':0, '审计':0, '分享':0 },
  super_admin: { '上传':1, '删除':1, '设置':1, '成员管理':1, '审计':1, '分享':1 }
};
function renderPermMatrix(members) {
  var card = document.getElementById('permMatrixCard');
  if (!card) return;
  var cols = ['上传','删除','设置','成员管理','审计','分享'];
  var head = '<table class="perm-matrix"><thead><tr><th>用户 / 角色</th>' +
    cols.map(function(c){ return '<th>'+c+'</th>'; }).join('') + '</tr></thead><tbody>';
  var rows = (members || []).map(function(m){
    var caps = ROLE_CAPS[m.role] || ROLE_CAPS.reader;
    return '<tr><td><span class="pm-user">'+roleAvatar(m.username,m.role,'sm')+escapeHtml(m.username)+
      ' <span style="font-family:var(--font-mono);font-size:11px;color:#8B8B8B;">'+escapeHtml(ROLE_CN[m.role]||m.role)+'</span></span></td>' +
      cols.map(function(c){
        return '<td>'+(caps[c]
          ? '<span class="perm-yes">'+icon('check','icon-16')+'</span>'
          : '<span class="perm-no">'+icon('x','icon-16')+'</span>')+'</td>';
      }).join('') + '</tr>';
  }).join('');
  var legend = '<div class="perm-legend">' +
    '<div><strong>所有者 (owner)</strong> — 完全控制：可管理成员、设置、审计与分享。</div>' +
    '<div><strong>编辑 (editor)</strong> — 可上传 / 删除文档，但不能改设置或管理成员。</div>' +
    '<div><strong>只读 (reader)</strong> — 仅可浏览与问答，无任何写入权限。</div>' +
    '<div><strong>超级管理员 (super_admin)</strong> — 平台管理员，对所有知识库拥有全部权限。</div>' +
  '</div>';
  card.innerHTML = head + rows + '</tbody></table>' + legend;
}

async function loadMembers() {
  if (!currentKbId) return;
  var loading = document.getElementById('memberLoading');
  var empty = document.getElementById('memberEmpty');
  var table = document.getElementById('memberTable');
  var addSection = document.getElementById('memberAddSection');
  var permHint = document.getElementById('memberPermHint');

  loading.classList.remove('hidden');
  table.classList.add('hidden');
  empty.classList.add('hidden');
  permHint.classList.add('hidden');

  try {
    var res = await apiFetch('/api/kb/'+currentKbId+'/members');
    var body = await res.json();

    if (body.code === 403) {
      loading.classList.add('hidden');
      permHint.classList.remove('hidden');
      addSection.classList.add('hidden');
      document.getElementById('memberTableBody').innerHTML = '';
      return;
    }
    if (body.code !== 0) { toast(body.msg||'加载失败','error'); loading.classList.add('hidden'); return; }

    var items = body.data || [];
    loading.classList.add('hidden');
    window.__membersCache = window.__membersCache || {};
    window.__membersCache[currentKbId] = items;
    renderPermMatrix(items);

    if (items.length===0) {
      empty.classList.remove('hidden');
      document.getElementById('memberTableBody').innerHTML = '';
    } else {
      table.classList.remove('hidden');
      document.getElementById('memberTableBody').innerHTML = items.map(function(m){
        return '<tr><td><span style="display:inline-flex;align-items:center;gap:8px;">'+roleAvatar(m.username,m.role,'sm')+escapeHtml(m.username)+'</span></td>' +
          '<td><span class="badge '+(m.role==='owner'?'badge-mono':'badge-outline')+'">'+escapeHtml(ROLE_CN[m.role]||m.role)+'</span></td>' +
          '<td><button class="btn btn-tertiary btn-sm btn-rm-member" data-user-id="'+m.user_id+'">移除</button></td></tr>';
      }).join('');

      document.querySelectorAll('.btn-rm-member').forEach(function(btn){
        btn.addEventListener('click', async function(){
          var userId = parseInt(this.dataset.userId);
          if (!confirm('确定要移除该成员吗？')) return;
          try {
            var r = await apiFetch('/api/kb/'+currentKbId+'/members/'+userId, {method:'DELETE'});
            var b = await handleBusinessResponse(r);
            toast('已移除成员','success');
            loadMembers();
          } catch(err) { if (err.message==='Unauthorized') return; }
        });
      });
    }
  } catch(err) {
    loading.classList.add('hidden');
    if (err.message==='Unauthorized') return;
  }
}

document.getElementById('btnAddMember').addEventListener('click', async function(){
  if (!currentKbId) return;
  var username = document.getElementById('memberUsername').value.trim();
  var role = document.getElementById('memberRole').value;
  if (!username) { toast('请输入用户名','info'); return; }

  try {
    var res = await apiFetch('/api/kb/'+currentKbId+'/members', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({username:username, role:role})
    });
    var body = await handleBusinessResponse(res);
    toast('已添加成员: '+body.data.username+' ('+body.data.role+')','success');
    document.getElementById('memberUsername').value = '';
    loadMembers();
  } catch(err) { if (err.message==='Unauthorized') return; }
});
