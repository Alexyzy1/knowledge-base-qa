// response.js
// BUSINESS RESPONSE HANDLER
// ============================================================
async function handleBusinessResponse(res) {
  var body;
  try { body = await res.json(); } catch (e) {
    toast('响应解析失败', 'error');
    throw e;
  }
  if (body.code !== 0) {
    var errMsg = body.msg || ('请求失败 (code=' + body.code + ')');
    toast(errMsg, 'error');
    throw new Error(errMsg);
  }
  return body;
}

// P0-T2: Clipboard helper with HTTP fallback
// navigator.clipboard is only available on HTTPS / localhost; fall back to
// document.execCommand('copy') when running on plain HTTP + IP.
function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text);
  }
  // Fallback: temporary textarea hack
  return new Promise(function (resolve, reject) {
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      ta.style.top = '-9999px';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      var ok = document.execCommand('copy');
      document.body.removeChild(ta);
      if (ok) resolve();
      else reject(new Error('execCommand failed'));
    } catch (e) {
      reject(e);
    }
  });
}
// ============================================================
function showAuthPage() {
  document.getElementById('authPage').style.display = 'flex';
  document.getElementById('appShell').classList.remove('logged-in');
  document.getElementById('publicShareExpired').classList.remove('active');
  // DO NOT hide publicSharePage — share page should stay visible as login backdrop
  currentKbId = null;
  resetKbUI();
}

function showAppShell() {
  document.getElementById('authPage').style.display = 'none';
  document.getElementById('appShell').classList.add('logged-in');
}

function resetKbUI() {
  document.getElementById('kbList').innerHTML = '<li style="padding:var(--space-lg) 0;text-align:center;color:#8B8B8B;font-size:var(--fs-body-sm);">暂无知识库</li>';
  hideAllPanels();
  document.getElementById('noKbSelected').classList.remove('hidden');
  document.getElementById('topbarKbName').textContent = '选择一个知识库';
  // Reset topbar tabs
  document.querySelectorAll('#topbarTabs .topbar-tab').forEach(function(t){ t.classList.remove('active'); });
  var ot = document.querySelector('#topbarTabs .topbar-tab[data-panel="overview"]');
  if (ot) ot.classList.add('active');
}

// Audit target display helper: strip "doc:" prefix from legacy records
function formatAuditTarget(target) {
  if (!target) return '';
  // Legacy format: "doc:42" → just show the ID
  if (/^doc:\d+$/.test(target)) return target.replace('doc:', '文档 #');
  return target;
}
