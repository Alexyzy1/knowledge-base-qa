// app-init.js
// INIT APP
// ============================================================
async function initApp() {
  // currentUser is already set by login handler (from body.data.user).
  // Only try /api/auth/me as a refresh — if it fails, keep the login value.
  if (!currentUser) {
    try {
      var res = await apiFetch('/api/auth/me');
      if (res.ok) {
        var body = await handleBusinessResponse(res);
        currentUser = body.data;
        localStorage.setItem('kb_user', JSON.stringify(currentUser));
      }
    } catch(e) {}
  } else {
    localStorage.setItem('kb_user', JSON.stringify(currentUser));
  }

  // renderSidebarLinks is already called in the bootstrap path that also
  // restores from localStorage. Avoid double-rendering.

  document.getElementById('sidebarUsername').textContent = currentUser.username;
  var roleBadge = document.getElementById('sidebarRole');
  roleBadge.textContent = ROLE_CN[currentUser.role] || currentUser.role;

  // Role-based visibility
  renderSidebarLinks();
  await loadKbList();
  loadTasks();

  // Auto-select first KB
  if (kbListCache.length > 0) {
    selectKb(kbListCache[0].id);
  }

  // Enhance native selects → custom dropdowns (P1 2.3)
  csEnhanceAll();
}
