// auth.js
// AUTH LOGIC
// ============================================================
var authTab = 'login';

document.querySelectorAll('.auth-tab').forEach(function(tab){
  tab.addEventListener('click', function(){
    authTab = this.dataset.authTab;
    document.querySelectorAll('.auth-tab').forEach(function(t){ t.classList.remove('active'); });
    this.classList.add('active');
    document.getElementById('loginForm').classList.toggle('hidden', authTab !== 'login');
    document.getElementById('registerForm').classList.toggle('hidden', authTab !== 'register');
  });
});

// Password toggle
document.addEventListener('click', function(e){
  if (!e.target.classList.contains('pwd-toggle')) return;
  var wrap = e.target.closest('.pwd-wrap');
  var input = wrap.querySelector('input');
  if (input.type === 'password') { input.type = 'text'; e.target.textContent = '隐藏'; }
  else { input.type = 'password'; e.target.textContent = '显示'; }
});

// Login form
document.getElementById('loginForm').addEventListener('submit', async function(e){
  e.preventDefault();
  var btn = document.getElementById('loginBtn');
  btn.disabled = true; btn.textContent = '登录中…';

  var username = this.username.value.trim();
  var password = this.password.value;

  try {
    var res = await apiFetch('/api/auth/login', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({username:username, password:password})
    });
    var body = await handleBusinessResponse(res);
    setToken(body.data.access_token);
    currentUser = body.data.user;
    // Cache user info so sidebar shows real name even before /api/auth/me responds
    localStorage.setItem('kb_user', JSON.stringify(currentUser));
    toast('登录成功', 'success');
    showAppShell();
    await initApp();
  } catch(err) {
    if (err.message === 'Unauthorized') return;
  } finally {
    btn.disabled = false; btn.textContent = '登 录';
  }
});

// Register form
document.getElementById('registerForm').addEventListener('submit', async function(e){
  e.preventDefault();
  var btn = document.getElementById('registerBtn');

  var pwErr = validatePassword(this.password.value);
  if (pwErr) { toast(pwErr, 'error'); return; }

  btn.disabled = true; btn.textContent = '注册中…';

  try {
    var res = await apiFetch('/api/auth/register', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({username:this.username.value.trim(), password:this.password.value})
    });
    var body = await handleBusinessResponse(res);
    toast('注册成功，请登录', 'success');
    // Switch to login tab
    authTab = 'login';
    document.querySelectorAll('.auth-tab').forEach(function(t){ t.classList.remove('active'); });
    document.querySelector('.auth-tab[data-auth-tab="login"]').classList.add('active');
    document.getElementById('loginForm').classList.remove('hidden');
    document.getElementById('registerForm').classList.add('hidden');
    document.querySelector('#loginForm input[name="username"]').value = this.username.value.trim();
  } catch(err) {
    if (err.message === 'Unauthorized') return;
  } finally {
    btn.disabled = false; btn.textContent = '注 册';
  }
});
