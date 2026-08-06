// models.js
// GLOBAL: MODEL REGISTRY
// ============================================================
function loadModels() {
  /*
    GET /api/models → {code:0, data:[{id, name, type, endpoint, enabled}]}
  */
  var loading = document.getElementById('modelsLoading');
  var empty = document.getElementById('modelsEmpty');
  var table = document.getElementById('modelsTable');

  loading.classList.remove('hidden');
  table.classList.add('hidden');
  empty.classList.add('hidden');
  document.getElementById('modelsTableBody').innerHTML = '';

  apiFetch('/api/models').then(function(res){ return handleBusinessResponse(res); }).then(function(body){
    var models = body.data || [];
    loading.classList.add('hidden');
    if (models.length===0) {
      empty.classList.remove('hidden');
    } else {
      table.classList.remove('hidden');
      document.getElementById('modelsTableBody').innerHTML = models.map(function(m){
        return '<tr>' +
          '<td><strong>'+escapeHtml(m.name)+'</strong></td>' +
          '<td><span class="badge badge-outline">'+escapeHtml(m.type)+'</span></td>' +
          '<td style="font-family:var(--font-mono);font-size:12px;">'+escapeHtml(m.endpoint||'')+'</td>' +
          '<td><span class="badge '+(m.enabled?'badge-success':'badge-danger')+'">'+(m.enabled?'启用':'停用')+'</span></td>' +
          '<td>' +
            '<button class="btn btn-tertiary btn-sm btn-edit-model" data-model=\''+JSON.stringify(m)+'\'>编辑</button>' +
            '<button class="btn btn-tertiary btn-sm btn-toggle-model" data-model-id="'+m.id+'" data-enabled="'+m.enabled+'">'+(m.enabled?'停用':'启用')+'</button>' +
          '</td>' +
        '</tr>';
      }).join('');

      document.querySelectorAll('.btn-edit-model').forEach(function(btn){
        btn.addEventListener('click', function(){
          var m = JSON.parse(this.dataset.model);
          editingModelId = m.id;
          document.getElementById('modalModelTitle').textContent = '编辑模型';
          document.getElementById('modelName').value = m.name;
          document.getElementById('modelType').value = m.type;
          document.getElementById('modelEndpoint').value = m.endpoint||'';
          document.getElementById('modalModel').classList.add('open');
        });
      });

      document.querySelectorAll('.btn-toggle-model').forEach(function(btn){
        btn.addEventListener('click', async function(){
          var modelId = parseInt(this.dataset.modelId);
          var enabled = this.dataset.enabled === 'true';
          try {
            var r = await apiFetch('/api/models/'+modelId, {
              method:'PUT',
              headers:{'Content-Type':'application/json'},
              body: JSON.stringify({enabled:!enabled})
            });
            var b = await handleBusinessResponse(r);
            toast(enabled?'模型已停用':'模型已启用','success');
            loadModels();
          } catch(err) { if (err.message==='Unauthorized') return; }
        });
      });
    }
  }).catch(function(err){ loading.classList.add('hidden'); if (err.message==='Unauthorized') return; });
}

// Model modal
document.getElementById('btnAddModel').addEventListener('click', function(){
  editingModelId = null;
  document.getElementById('modalModelTitle').textContent = '新增模型';
  document.getElementById('modelName').value = '';
  document.getElementById('modelType').value = 'llm';
  document.getElementById('modelEndpoint').value = '';
  document.getElementById('modalModel').classList.add('open');
});

document.getElementById('btnCancelModel').addEventListener('click', function(){
  closeModal(document.getElementById('modalModel'));
});
document.getElementById('modalModel').addEventListener('click', function(e){
  if (e.target === this) closeModal(this);
});

document.getElementById('btnSaveModel').addEventListener('click', async function(){
  var data = {
    name: document.getElementById('modelName').value.trim(),
    type: document.getElementById('modelType').value,
    endpoint: document.getElementById('modelEndpoint').value.trim()
  };
  if (!data.name) { toast('请输入模型名称','info'); return; }

  try {
    var res;
    if (editingModelId) {
      res = await apiFetch('/api/models/'+editingModelId, {
        method:'PUT',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(data)
      });
    } else {
      res = await apiFetch('/api/models', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(Object.assign({enabled:true}, data))
      });
    }
    var body = await handleBusinessResponse(res);
    toast(editingModelId?'模型已更新':'模型已创建','success');
    closeModal(document.getElementById('modalModel'));
    loadModels();
  } catch(err) { if (err.message==='Unauthorized') return; }
});
