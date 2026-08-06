// global-page.js
// GLOBAL PAGE SWITCHING
// ============================================================
function showGlobalPage(pageId, title) {
  currentKbId = null;
  selectedKbIds = [];
  updateGlobalSearchChips();
  document.getElementById('kbWorkspace').style.display = 'none';
  document.getElementById('globalPagesContainer').style.display = 'flex';
  document.getElementById('globalPageTitle').textContent = title;

  // Hide all global pages
  document.querySelectorAll('.global-page').forEach(function(p){ p.classList.remove('active'); });
  var page = document.getElementById('global-' + pageId);
  if (page) page.classList.add('active');

  // Unhighlight sidebar
  document.querySelectorAll('.kb-item').forEach(function(i){ i.classList.remove('active'); });
  document.getElementById('noKbSelected').classList.add('hidden');
}

document.getElementById('btnBackToKb').addEventListener('click', function(){
  document.getElementById('globalPagesContainer').style.display = 'none';
  document.getElementById('kbWorkspace').style.display = 'flex';
  if (kbListCache.length > 0) {
    selectKb(kbListCache[0].id);
  } else {
    currentKbId = null;
    selectedKbIds = [];
    updateGlobalSearchChips();
    resetKbUI();
  }
});
