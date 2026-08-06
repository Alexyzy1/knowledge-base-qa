// sidebar.js
// SIDEBAR RENDERING
// ============================================================
function renderSidebarLinks() {
  // User bar: avatar
  var av = document.getElementById('sidebarAvatar');
  if (av && currentUser) av.innerHTML = roleAvatar(currentUser.username, currentUser.role);

  // New KB button
  document.getElementById('sidebarNewKB').classList.toggle('hidden', currentUser.role === 'guest');

  // Dropdown: show/hide management entries based on role
  var isAdmin = currentUser.role === 'admin' || currentUser.role === 'super_admin';
  var isSuper = currentUser.role === 'super_admin';
  document.getElementById('mgmtMenuLabel').style.display = isAdmin ? '' : 'none';
  document.getElementById('menuWhitelist').style.display = isAdmin ? '' : 'none';
  document.getElementById('menuModels').style.display = isAdmin ? '' : 'none';
  document.getElementById('menuGlobalAudit').style.display = isSuper ? '' : 'none';

  // KB batch select button (non-guest users)
  document.getElementById('btnKbSelect').style.display = currentUser.role !== 'guest' ? '' : 'none';
  // KB import button (non-guest users)
  var impBtn = document.getElementById('btnKbImport');
  if (impBtn) impBtn.style.display = currentUser.role !== 'guest' ? '' : 'none';
}

// (no longer needed — entries are inline in the dropdown menu)
