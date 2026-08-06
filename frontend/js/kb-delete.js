// kb-delete.js
// DELETE KB (triggered from settings danger zone)
// ============================================================
async function deleteKb(kbId, kbName) {
  if (!confirm('确定要删除知识库「' + kbName + '」吗？此操作将永久删除该知识库及其所有文档和向量数据，且不可恢复。')) return;

  try {
    var res = await apiFetch('/api/kb/' + kbId, { method: 'DELETE' });
    var body = await handleBusinessResponse(res);
    toast('知识库已删除','success');
    currentKbId = null;
    selectedKbIds = [];
    updateGlobalSearchChips();
    await loadKbList();
    if (kbListCache.length > 0) selectKb(kbListCache[0].id);
    else { resetKbUI(); document.getElementById('kbWorkspace').style.display = 'flex'; }
  } catch(err) {
    if (err.message === 'Unauthorized') return;
  }
}
