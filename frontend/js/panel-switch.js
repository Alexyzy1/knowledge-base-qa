// panel-switch.js
// PANEL SWITCHING
// ============================================================
function hideAllPanels() {
  document.querySelectorAll('.panel').forEach(function(p){ p.classList.remove('active'); });
  document.querySelectorAll('#topbarTabs .topbar-tab').forEach(function(t){ t.classList.remove('active'); });
}

function showPanel(panelId) {
  hideAllPanels();
  var panel = document.getElementById('panel-' + panelId);
  if (panel) panel.classList.add('active');
  var tab = document.querySelector('#topbarTabs .topbar-tab[data-panel="'+panelId+'"]');
  if (tab) tab.classList.add('active');

  // Management dropdown active-state (members/settings/audit/share live in the 管理 menu)
  var mgmtPanels = ['members','settings','audit'];
  var moreTrig = document.getElementById('btnTopbarMore');
  if (moreTrig) moreTrig.classList.toggle('active', mgmtPanels.indexOf(panelId) !== -1);
  document.querySelectorAll('#moreMenu .more-item').forEach(function(it){ it.classList.toggle('active', it.dataset.panel === panelId); });

  // Load data for the panel
  if (!currentKbId) return;
  switch (panelId) {
    case 'overview': loadOverview(); break;
    case 'files': loadFiles(); break;
    case 'chat': renderChatHistory(); loadChatModels(); loadConversationList(); break;
    case 'similar': break; // Lazy
    case 'members': loadMembers(); break;
    case 'settings': loadSettings(); break;
    case 'audit': loadAudit(); break;
  }
}

// Topbar tab clicks + management dropdown (consolidated nav)
document.getElementById('topbarTabs').addEventListener('click', function(e){
  var moreBtn = e.target.closest('#btnTopbarMore');
  if (moreBtn) { e.stopPropagation(); document.getElementById('topbarMore').classList.toggle('open'); return; }
  var item = e.target.closest('.more-item');
  if (item) { showPanel(item.dataset.panel); document.getElementById('topbarMore').classList.remove('open'); return; }
  var tab = e.target.closest('.topbar-tab[data-panel]');
  if (tab) showPanel(tab.dataset.panel);
});
// Close management dropdown on outside click
document.addEventListener('click', function(e){
  var more = document.getElementById('topbarMore');
  if (more && !more.contains(e.target)) more.classList.remove('open');
});
