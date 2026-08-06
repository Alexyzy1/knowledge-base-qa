// whitelist.js
// GLOBAL: WHITELIST
// ============================================================
async function loadWhitelist() {
  var loading = document.getElementById('wlLoading');
  var empty = document.getElementById('wlEmpty');
  var table = document.getElementById('wlTable');

  loading.classList.remove('hidden');
  table.classList.add('hidden');
  empty.classList.add('hidden');
  document.getElementById('wlTableBody').innerHTML = '';

  try {
    var res = await apiFetch('/api/whitelist');
    var body = await handleBusinessResponse(res);
    var items = body.data || [];
    loading.classList.add('hidden');

    if (items.length===0) {
      empty.classList.remove('hidden');
    } else {
      table.classList.remove('hidden');
      document.getElementById('wlTableBody').innerHTML = items.map(function(w){
        return '<tr><td>'+escapeHtml(w.username)+'</td>' +
          '<td style="color:#8B8B8B;">'+escapeHtml(w.note||'—')+'</td>' +
          '<td><button class="btn btn-tertiary btn-sm btn-rm-wl" data-username="'+escapeHtmlAttr(w.username)+'">移除</button></td></tr>';
      }).join('');

      document.querySelectorAll('.btn-rm-wl').forEach(function(btn){
        btn.addEventListener('click', async function(){
          if (!confirm('确定将 '+this.dataset.username+' 移出白名单？')) return;
          try {
            var r = await apiFetch('/api/whitelist/'+encodeURIComponent(this.dataset.username), {method:'DELETE'});
            var b = await handleBusinessResponse(r);
            toast('已移除','success');
            loadWhitelist();
          } catch(err) { if (err.message==='Unauthorized') return; }
        });
      });
    }
  } catch(err) {
    loading.classList.add('hidden');
    if (err.message==='Unauthorized') return;
  }
}

document.getElementById('btnAddWhitelist').addEventListener('click', async function(){
  var username = document.getElementById('wlUsername').value.trim();
  var note = document.getElementById('wlNote').value.trim();
  if (!username) { toast('请输入用户名','info'); return; }

  try {
    var res = await apiFetch('/api/whitelist', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({username:username, note:note||undefined})
    });
    var body = await handleBusinessResponse(res);
    toast('已添加: '+body.data.username,'success');
    document.getElementById('wlUsername').value = '';
    document.getElementById('wlNote').value = '';
    loadWhitelist();
  } catch(err) { if (err.message==='Unauthorized') return; }
});
