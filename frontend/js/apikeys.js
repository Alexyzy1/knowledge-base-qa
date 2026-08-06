// apikeys.js
// GLOBAL: API KEYS
// ============================================================
function loadApiKeys() {
  /*
    GET /api/keys → {code:0, data:[{id, name, prefix, created_at, last_used_at}]}
  */
  var listEl = document.getElementById('apiKeyList');
  var loading = document.getElementById('apiKeysLoading');
  var empty = document.getElementById('apiKeysEmpty');

  loading.classList.remove('hidden');
  empty.classList.add('hidden');
  listEl.innerHTML = '';

  apiFetch('/api/keys').then(function(res){ return handleBusinessResponse(res); }).then(function(body){
    var keys = body.data || [];
    loading.classList.add('hidden');
    if (keys.length===0) {
      empty.classList.remove('hidden');
    } else {
      listEl.innerHTML = keys.map(function(k){
        return '<div class="share-link-row">' +
          '<div style="flex:1;">' +
            '<div style="font-weight:480;">'+escapeHtml(k.name)+'</div>' +
            '<div style="font-family:var(--font-mono);font-size:12px;color:#8B8B8B;">'+escapeHtml(k.prefix||'')+'…</div>' +
            '<div style="font-size:12px;color:#8B8B8B;">创建: '+escapeHtml(k.created_at||'')+' · 最近使用: '+escapeHtml(k.last_used_at||'—')+'</div>' +
          '</div>' +
          '<button class="btn btn-tertiary btn-sm btn-revoke-key" data-key-id="'+k.id+'" style="color:var(--color-semantic-danger);">吊销</button>' +
        '</div>';
      }).join('');

      document.querySelectorAll('.btn-revoke-key').forEach(function(btn){
        btn.addEventListener('click', async function(){
          if (!confirm('吊销后使用该 Key 的请求将失效，确定？')) return;
          var keyId = parseInt(this.dataset.keyId);
          try {
            var r = await apiFetch('/api/keys/'+keyId, {method:'DELETE'});
            var b = await handleBusinessResponse(r);
            toast('API Key 已吊销','success');
            loadApiKeys();
          } catch(err) { if (err.message==='Unauthorized') return; }
        });
      });
    }
  }).catch(function(err){ loading.classList.add('hidden'); if (err.message==='Unauthorized') return; });
}

document.getElementById('btnCreateApiKey').addEventListener('click', async function(){
  var name = document.getElementById('apiKeyName').value.trim();
  if (!name) { toast('请输入 Key 名称','info'); return; }

  /*
    POST /api/keys → {code:0, data:{id, name, key, prefix, created_at}}  // key only returned once
  */
  try {
    var res = await apiFetch('/api/keys', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name:name})
    });
    var body = await handleBusinessResponse(res);
    document.getElementById('apiKeyRevealText').textContent = body.data.key;
    document.getElementById('apiKeyReveal').classList.remove('hidden');
    document.getElementById('apiKeyName').value = '';
    loadApiKeys();
  } catch(err) { if (err.message==='Unauthorized') return; }
});

document.getElementById('btnCopyApiKey').addEventListener('click', function(){
  var key = document.getElementById('apiKeyRevealText').textContent;
  copyText(key).then(function(){
    toast('已复制','success');
  }).catch(function(){ toast('复制失败','error'); });
});
