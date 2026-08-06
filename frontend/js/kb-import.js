// kb-import.js
// KB IMPORT MODAL
// ============================================================

// Open import modal
document.getElementById('btnKbImport').addEventListener('click', function(){
  var m = document.getElementById('modalKbImport');
  m.classList.add('open');
  // Reset form
  document.getElementById('importKbName').value = '';
  document.getElementById('importKbFile').value = '';
  document.getElementById('importKbFileName').textContent = '未选择文件';
  document.getElementById('importProgress').style.display = 'none';
  document.getElementById('importProgressBar').style.width = '0%';
  document.getElementById('importStatusText').textContent = '';
  document.getElementById('btnConfirmKbImport').disabled = false;
  document.getElementById('btnConfirmKbImport').textContent = '导入';
});

// File input change → show selected filename
document.getElementById('importKbFile').addEventListener('change', function(){
  var fname = this.files.length > 0 ? this.files[0].name : '未选择文件';
  document.getElementById('importKbFileName').textContent = fname;
});

// Cancel button
document.getElementById('btnCancelKbImport').addEventListener('click', function(){
  closeModal(document.getElementById('modalKbImport'));
});

// Click overlay to close
document.getElementById('modalKbImport').addEventListener('click', function(e){
  if (e.target === this) closeModal(this);
});

// Confirm import
document.getElementById('btnConfirmKbImport').addEventListener('click', async function(){
  var fileInput = document.getElementById('importKbFile');
  var file = fileInput.files[0];
  if (!file) { toast('请选择 ZIP 文件', 'info'); return; }
  if (!file.name.toLowerCase().endsWith('.zip')) { toast('请选择 .zip 文件', 'info'); return; }

  var newName = document.getElementById('importKbName').value.trim() || undefined;
  var formData = new FormData();
  formData.append('file', file);
  if (newName) formData.append('new_name', newName);

  // Show progress UI
  var progressWrap = document.getElementById('importProgress');
  var progressBar = document.getElementById('importProgressBar');
  var statusText = document.getElementById('importStatusText');
  progressWrap.style.display = '';
  progressBar.style.width = '10%';
  statusText.textContent = '上传中...';

  var btn = this;
  btn.disabled = true; btn.textContent = '导入中...';

  try {
    var res = await fetch('/api/kb/import', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + getToken() },
      body: formData
    });
    if (res.status === 401) { setToken(''); showAuthPage(); toast('登录已过期', 'error'); return; }
    var body = await handleBusinessResponse(res);
    progressBar.style.width = '100%';
    statusText.textContent = '导入完成';
    var data = body.data || {};
    var docCount = data.doc_count || 0;
    var errors = data.errors || [];
    var msg = '导入成功：创建了 ' + (data.kb_count || 1) + ' 个知识库，共 ' + docCount + ' 个文档';
    if (errors.length > 0) msg += '（' + errors.length + ' 个文档失败）';
    msg += '，后台处理中';
    toast(msg, 'success');
    closeModal(document.getElementById('modalKbImport'));
    await loadKbList();
    // Select the newly created KB if single
    if (data.kb_ids && data.kb_ids.length === 1) {
      selectKb(data.kb_ids[0]);
    }
  } catch(err) {
    progressBar.style.width = '0%';
    statusText.textContent = '导入失败';
    if (err.message && err.message.indexOf('Unauthorized') === -1) {
      toast('导入失败: ' + err.message, 'error');
    }
  } finally {
    btn.disabled = false; btn.textContent = '导入';
  }
});
