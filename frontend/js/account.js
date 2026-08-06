// account.js
// GLOBAL: ACCOUNT
// ============================================================
function loadAccount() {
  /*
    GET /api/account → {code:0, data:{id, username, role, created_at}}
    May return 404 if not yet deployed — degrade gracefully.
  */
  apiFetch('/api/account').then(function(res){
    if (!res.ok) throw new Error('not-available');
    return handleBusinessResponse(res);
  }).then(function(body){
    var u = body.data;
    document.getElementById('accountInfo').innerHTML =
      '<div style="display:flex;align-items:center;gap:var(--space-md);margin-bottom:var(--space-sm);">' +
        '<span style="font-size:40px;">👤</span>' +
        '<div>' +
          '<div style="font-size:var(--fs-card-title);font-weight:700;">'+escapeHtml(u.username)+'</div>' +
          '<div><span class="badge badge-mono">'+escapeHtml(ROLE_CN[u.role]||u.role)+'</span></div>' +
          '<div style="font-size:13px;color:#8B8B8B;margin-top:4px;">注册时间: '+(u&&u.created_at?escapeHtml(String(u.created_at).replace('T',' ').slice(0,16)):'—')+'</div>' +
        '</div>' +
      '</div>';
  }).catch(function(err){ if (err.message==='Unauthorized') return; });
}

document.getElementById('btnChangePassword').addEventListener('click', async function(){
  var oldPwd = document.getElementById('accountOldPwd').value;
  var newPwd = document.getElementById('accountNewPwd').value;
  if (!oldPwd || !newPwd) { toast('请填写完整','info'); return; }
  var pwErr = validatePassword(newPwd);
  if (pwErr) { toast(pwErr, 'error'); return; }

  /*
    PUT /api/account/password → {code:0, data:{updated:true}}
    body: {old_password, new_password}
  */
  try {
    // P1-T10: PUT /api/account/password (backend: verify old + bcrypt new, ≥8 chars enforced server-side)
    var res = await apiFetch('/api/account/password', {
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({old_password:oldPwd, new_password:newPwd})
    });
    var body = await handleBusinessResponse(res);
    toast('密码修改成功','success');
    document.getElementById('accountOldPwd').value = '';
    document.getElementById('accountNewPwd').value = '';
  } catch(err) { if (err.message==='Unauthorized') return; }
});
