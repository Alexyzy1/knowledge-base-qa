// utils.js
// UTILITIES
// ============================================================
function getToken() { return localStorage.getItem('kb_token') || ''; }
function setToken(t) {
  if (t) localStorage.setItem('kb_token', t);
  else localStorage.removeItem('kb_token');
}
function authHeaders() {
  var token = getToken();
  var h = {'Content-Type': 'application/json'};
  if (token) h['Authorization'] = 'Bearer ' + token;
  return h;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function validatePassword(pw) {
  if (!pw || pw.length < 8) return '密码至少 8 位';
  if (!/[A-Z]/.test(pw)) return '密码需包含至少一个大写字母';
  if (!/[0-9]/.test(pw)) return '密码需包含至少一个数字';
  return null;
}
function statusLabel(s) {
  var map = { pending:'等待中', processing:'处理中', done:'已完成', failed:'失败' };
  return map[s] || s;
}
