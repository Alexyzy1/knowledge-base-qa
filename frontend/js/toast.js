// toast.js
// TOAST
// ============================================================
function toast(msg, type) {
  type = type || 'info';
  var c = document.getElementById('toastContainer');
  var el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  c.appendChild(el);
  var t = setTimeout(function(){ dismissToast(el); }, 3500);
  el.addEventListener('click', function(){ clearTimeout(t); dismissToast(el); });
}
function dismissToast(el) {
  if (el.classList.contains('removing')) return;
  el.classList.add('removing');
  el.addEventListener('animationend', function(){ el.remove(); });
}
