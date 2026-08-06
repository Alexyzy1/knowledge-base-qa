// api.js
// API FETCH — Unified request wrapper
// ============================================================
async function apiFetch(path, options) {
  options = options || {};
  if (DEMO) { return demoApi(path, options); }
  var headers = options.headers || {};
  var token = getToken();
  if (token) { headers['Authorization'] = 'Bearer ' + token; }

  var res;
  try {
    res = await fetch(path, Object.assign({}, options, { headers: headers }));
  } catch (e) {
    toast('网络错误：' + (e.message || '无法连接到服务器'), 'error');
    throw e;
  }

  // Only real HTTP 401 triggers re-login
  if (res.status === 401) {
    setToken('');
    showAuthPage();
    toast('登录已过期，请重新登录', 'error');
    throw new Error('Unauthorized');
  }
  return res;
}
