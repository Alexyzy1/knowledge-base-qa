// utils2.js - utilities (part 2) - global event handlers
// utils2.js
// UTILITIES (part 2) + BOOTSTRAP
// ============================================================
// ============================================================
// UTILITIES
// ============================================================
function debounce(fn, ms) {
  var timer;
  return function(){
    var ctx = this, args = arguments;
    clearTimeout(timer);
    timer = setTimeout(function(){ fn.apply(ctx, args); }, ms);
  };
}

// Close modals on Escape
document.addEventListener('keydown', function(e){
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.open').forEach(function(m){ closeModal(m); });
    document.getElementById('contextMenu').classList.add('hidden');
    document.getElementById('drawerPreview').classList.remove('open');
  }
});

// Mobile menu toggle
document.getElementById('btnMenuToggle').addEventListener('click', function(){
  document.getElementById('sidebar').classList.toggle('open');
});

// P0-T1: Logout now handled via user dropdown menu (#btnLogoutMenu) — see bottom of file

// P0-T1: btnUploadTrigger event binding (was missing)
document.getElementById('btnUploadTrigger').addEventListener('click', function () {
  document.getElementById('fileInput').click();
});

// P1-T7: btnNewFolder event binding
document.getElementById('btnNewFolder').addEventListener('click', function () {
  if (!currentKbId) { toast('请先选择知识库','info'); return; }
  promptNewFolder();
});

// Batch operations toolbar
document.getElementById('btnBatchDelete').addEventListener('click', batchDelete);
document.getElementById('btnBatchTags').addEventListener('click', showBatchTagsModal);
document.getElementById('btnBatchMove').addEventListener('click', function(e){ e.stopPropagation(); openBatchFolderMenu(); });
document.getElementById('btnBatchDownload').addEventListener('click', batchDownload);
document.getElementById('btnBatchRetry').addEventListener('click', batchRetry);
document.getElementById('btnCancelSelection').addEventListener('click', clearSelection);

// Batch tags modal
document.getElementById('btnBatchTagsCancel').addEventListener('click', closeBatchTagsModal);
document.getElementById('btnBatchTagsConfirm').addEventListener('click', confirmBatchTags);
document.getElementById('modalBatchTags').addEventListener('click', function(e){
  if (e.target === this) closeBatchTagsModal();
});

// Batch tags toggle pills
document.querySelectorAll('#batchTagsToggle button').forEach(function(btn){
  btn.addEventListener('click', function(){
    document.querySelectorAll('#batchTagsToggle button').forEach(function(b){ b.classList.remove('active'); });
    this.classList.add('active');
    batchTagsAction = this.dataset.action;
  });
});

// Close folder menu on outside click
document.addEventListener('click', function(e){
  if (!e.target.closest('#btnBatchMove') && !e.target.closest('#batchFolderMenu')) {
    closeBatchFolderMenu();
  }
});

// Select-all checkbox (delegated)
document.addEventListener('change', function(e){
  if (e.target.id === 'cbSelectAll') {
    var checked = e.target.checked;
    document.querySelectorAll('.file-cb').forEach(function(cb){
      cb.checked = checked;
      var docId = parseInt(cb.dataset.docId);
      if (checked) selectedDocIds.add(docId); else selectedDocIds.delete(docId);
    });
    document.querySelectorAll('.gc-cb').forEach(function(cb){
      cb.checked = checked;
      var docId = parseInt(cb.dataset.docId);
      if (checked) selectedDocIds.add(docId); else selectedDocIds.delete(docId);
    });
    updateBatchUI();
    updateRowSelectionStyles();
  }
});

// Individual checkbox change (delegated) — Explorer-style: click=select, Ctrl=toggle, Shift=range
document.addEventListener('change', function(e){
  if (e.target.classList.contains('file-cb') || e.target.classList.contains('gc-cb')) {
    var docId = parseInt(e.target.dataset.docId);
    var allCbs = Array.from(document.querySelectorAll('.file-cb, .gc-cb'));
    var currentIndex = allCbs.indexOf(e.target);

    if (e.target._shiftClick && lastClickedDocIndex !== null && currentIndex !== -1) {
      // Shift: range from anchor to current (merge with existing)
      var start = Math.min(lastClickedDocIndex, currentIndex);
      var end   = Math.max(lastClickedDocIndex, currentIndex);
      for (var i = start; i <= end; i++) {
        allCbs[i].checked = true;
        selectedDocIds.add(parseInt(allCbs[i].dataset.docId));
      }
    } else if (e.target._ctrlClick) {
      // Ctrl: toggle this item, set anchor
      if (e.target.checked) selectedDocIds.add(docId); else selectedDocIds.delete(docId);
      lastClickedDocIndex = currentIndex;
    } else {
      // Plain click: select ONLY this item, set anchor
      selectedDocIds.clear();
      allCbs.forEach(function(c){ c.checked = false; });
      e.target.checked = true;
      selectedDocIds.add(docId);
      lastClickedDocIndex = currentIndex;
    }
    updateBatchUI();
    updateRowSelectionStyles();
  }
});

// Detect Shift/Ctrl+click on checkboxes (before the 'change' event fires)
document.addEventListener('click', function(e){
  if (e.target.classList.contains('file-cb') || e.target.classList.contains('gc-cb')) {
    if (e.shiftKey) {
      e.target._shiftClick = true;
      setTimeout(function(){ e.target._shiftClick = false; }, 0);
    }
    if (e.ctrlKey || e.metaKey) {
      e.target._ctrlClick = true;
      setTimeout(function(){ e.target._ctrlClick = false; }, 0);
    }
  }
});

// ============================================================
