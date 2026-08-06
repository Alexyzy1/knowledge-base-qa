// chat.js
// CHAT PANEL
// ============================================================
// P1-T9: Load model options for the chat model bar
async function loadChatModels() {
  // GET /api/models?type=llm&only_enabled=true → {code:0, data:[{id, name}]}
  try {
    var res = await apiFetch('/api/models?type=llm&only_enabled=true');
    var body = await handleBusinessResponse(res);
    var models = body.data || [];
    var sel = document.getElementById('chatLlmModel');
    sel.innerHTML = '<option value="">库默认</option>' +
      models.map(function(m){ return '<option value="'+m.id+'">'+escapeHtml(m.name)+'</option>'; }).join('');
  } catch(e) {}
}

// ---- Multi-turn bubble chat (P1 2.6) ----
// ---- Thinking mode toggle ----
var thinkingOn = true;
var agentOn = false;
function isThinkingOn() {
  var modelSel = document.getElementById('chatLlmModel');
  var modelName = (modelSel.options[modelSel.selectedIndex] || {}).textContent || '';
  if (modelName.indexOf('MiniMax') !== -1 || modelName.indexOf('M2.7') !== -1) return true;
  return thinkingOn;
}
function updateThinkingToggle() {
  var modelSel = document.getElementById('chatLlmModel');
  var modelName = (modelSel.options[modelSel.selectedIndex] || {}).textContent || '';
  var track = document.getElementById('thinkingTrack');
  var isMiniMax = modelName.indexOf('MiniMax') !== -1 || modelName.indexOf('M2.7') !== -1;
  if (isMiniMax) {
    thinkingOn = true;
    track.style.background = 'var(--color-accent)';
    track.firstElementChild.style.left = '22px';
    track.style.opacity = '0.6';
    track.style.cursor = 'not-allowed';
    document.getElementById('thinkingToggleLabel').title = 'MiniMax 默认开启思考模式，无法关闭';
  } else {
    track.style.opacity = '1';
    track.style.cursor = '';
    document.getElementById('thinkingToggleLabel').title = '';
    applyThinkingStyle();
  }
}
function applyThinkingStyle() {
  var track = document.getElementById('thinkingTrack');
  if (thinkingOn) {
    track.style.background = 'var(--color-accent)';
    track.firstElementChild.style.left = '22px';
  } else {
    track.style.background = '#555';
    track.firstElementChild.style.left = '2px';
  }
}
document.getElementById('thinkingToggleLabel').addEventListener('click', function(){
  var modelSel = document.getElementById('chatLlmModel');
  var modelName = (modelSel.options[modelSel.selectedIndex] || {}).textContent || '';
  if (modelName.indexOf('MiniMax') !== -1 || modelName.indexOf('M2.7') !== -1) return;
  thinkingOn = !thinkingOn;
  applyThinkingStyle();
});
document.getElementById('chatLlmModel').addEventListener('change', updateThinkingToggle);

// ── Agent 开关 ──
function applyAgentStyle() {
  var track = document.getElementById('agentTrack');
  if (agentOn) { track.style.background = '#7C3AED'; track.querySelector('span').style.left = '22px'; }
  else { track.style.background = '#555'; track.querySelector('span').style.left = '2px'; }
}
document.getElementById('agentToggleLabel').addEventListener('click', function(){
  agentOn = !agentOn;
  applyAgentStyle();
});
applyAgentStyle();

var ROLE_CN = {super_admin:'超级管理员',owner:'所有者',editor:'编辑',reader:'只读'};
var chatSessions = {}; // kbId -> [{role, text, model, sources}]
var currentConversationId = null; // 当前对话 ID（持久化后由后端分配）

function chatEmptyHTML() {
  var hint = selectedKbIds.length > 1
    ? ('向已选的 ' + selectedKbIds.length + ' 个知识库提问，开始跨库对话')
    : '向这个知识库提问，开始多轮对话';
  return '<div class="chat-empty" id="chatEmpty">' +
    '<span class="ce-icon">'+icon('chat','icon-24')+'</span>' +
    '<p>'+hint+'</p>' +
    '<p class="text-caption">答案附来源引用 · 对话历史自动保存至服务器</p></div>';
}
function sourceTagsHTML(sources) {
  if (!sources || !sources.length) return '';
  return '<div class="bubble-sources">' + sources.map(function(s){
    var m = String(s).match(/^\[(\d+)\]\s*(.*)/);
    var label = m ? ('<sup class="cite">'+m[1]+'</sup> '+escapeHtml(m[2])) : escapeHtml(s);
    return '<span class="source-tag">'+icon('doc','icon-16')+label+'</span>';
  }).join('') + '</div>';
}
function turnHTML(t) {
  if (t.role === 'user') {
    return '<div class="chat-turn"><div class="bubble-row user"><div class="bubble user">'+escapeHtml(t.text)+'</div></div></div>';
  }
  // 思考模式徽章
  var thinkingBadge = '';
  if (t.thinkingOn) {
    thinkingBadge = '<span class="badge badge-thinking">🧠 思考模式</span>';
  }
  var thinkingHTML = '';
  if (t.thinking || (t.streaming && t.thinking !== undefined)) {
    thinkingHTML = '<details class="thinking-block"'+(t.streaming && !t.text?' open':'')+'>' +
      '<summary>思考过程 '+(t.streaming && !t.text?'<span class="stream-caret"></span>':'')+'</summary>' +
      '<div class="thinking-content">'+escapeHtml(t.thinking||'')+'</div></details>';
  }
  // Agent 追踪面板
  var agentTraceHTML = '';
  if (t.agentTrace && t.agentTrace.length) {
    var steps = '';
    for (var s=0; s<t.agentTrace.length; s++) {
      var step = t.agentTrace[s];
      var stepIcon = {planner:'🎯', searcher:'🔍', verifier:'✅'}[step.type] || '⚙️';
      var label = {planner:'分析问题', searcher:'检索知识库', verifier:'质量检查'}[step.type] || step.type;
      var detail = '';
      if (step.type === 'planner') {
        detail = '<div class="at-step-reason">' + escapeHtml(step.reasoning||'') + '</div>';
        if (step.queries && step.queries.length) {
          detail += '<div class="at-step-queries">' + step.queries.map(function(q){ return '<span class="at-query-tag">'+escapeHtml(q)+'</span>'; }).join('') + '</div>';
        } else {
          detail += '<div class="at-step-note">无需检索，直接回答</div>';
        }
      } else if (step.type === 'searcher') {
        detail = '<div class="at-step-stat">找到 <b>' + (step.chunks_found||0) + '</b> 个相关片段（' + (step.context_len||0) + ' 字）</div>';
      } else if (step.type === 'verifier') {
        var vcls = step.passed ? 'at-pass' : 'at-fail';
        detail = '<div class="at-step-stat ' + vcls + '">' + (step.passed ? '✅ 通过' : '⚠️ 补充检索中...') + '</div>';
        if (step.issues && step.issues.length) {
          detail += '<div class="at-step-issues">' + step.issues.map(function(x){ return '<span class="at-issue-tag">'+escapeHtml(x)+'</span>'; }).join('') + '</div>';
        }
      }
      steps += '<div class="at-step">' +
        '<span class="at-step-icon">' + stepIcon + '</span>' +
        '<span class="at-step-label">' + label + '</span>' +
        detail +
      '</div>';
    }
    agentTraceHTML = '<details class="agent-trace-block" open>' +
      '<summary>🤖 Agent 推理过程</summary>' +
      '<div class="agent-trace-content">' + steps + '</div></details>';
  }
  var meta = '';
  if (!t.streaming) {
    meta = '<div class="bubble-meta"><span class="bm-model">'+icon('model','icon-16')+escapeHtml(t.model||'库默认')+'</span>'+sourceTagsHTML(t.sources)+'</div>';
  }
  return '<div class="bubble-row assistant"><div class="bubble assistant'+(t.streaming?' streaming':'')+'">' +
    (t.streaming ? '' : '<button class="btn-copy-bubble" onclick="copyBubble(this)" title="复制回答">'+icon('copy','icon-14')+'</button>') +
    thinkingBadge +
    thinkingHTML +
    agentTraceHTML +
    '<span class="bubble-text">'+(t.streaming ? escapeHtml(t.text) : renderMd(t.text))+'</span>' +
    (t.streaming ? '<span class="stream-caret"></span>' : '') +
    meta +
  '</div></div>';
}
function renderChatHistory() {
  var hist = document.getElementById('chatHistory');
  if (!hist) return;
  var sessionKey = _chatSessionKey();
  var turns = chatSessions[sessionKey] || [];
  if (turns.length === 0) { hist.innerHTML = chatEmptyHTML(); return; }
  hist.innerHTML = turns.map(turnHTML).join('');
}
function scrollChatBottom() {
  var hist = document.getElementById('chatHistory');
  if (hist) hist.scrollTop = hist.scrollHeight;
}
function setSendBtn(busy) {
  var btn = document.getElementById('btnSend');
  if (busy) {
    btn.innerHTML = icon('stop', 'icon-18') + '<span>停止</span>';
    btn.className = 'btn btn-primary btn-stop';
    btn.style.display = 'inline-flex'; btn.style.alignItems = 'center'; btn.style.gap = '6px';
  } else {
    btn.textContent = '发送';
    btn.className = 'btn btn-primary';
    btn.style.display = ''; btn.style.alignItems = ''; btn.style.gap = '';
  }
}

// ── 对话记录管理 ──
function loadConversationList() {
  var kbId = currentKbId || null;
  var params = kbId ? '?kb_id=' + kbId : '';
  fetch('/api/conversations' + params, { headers: authHeaders() })
    .then(function(r){ return r.json(); })
    .then(function(d){
      if (d.code === 0) renderConvList(d.data.items);
    }).catch(function(){});
}
function renderConvList(items) {
  var ul = document.getElementById('convList');
  var empty = document.getElementById('convEmpty');
  if (!ul) return;
  if (!items || items.length === 0) {
    ul.innerHTML = '';
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';
  ul.innerHTML = items.map(function(c){
    var activeClass = (c.id === currentConversationId) ? ' active' : '';
    var timeStr = c.updated_at ? formatRelativeTime(c.updated_at) : '';
    return '<li class="conv-item'+activeClass+'" data-conv-id="'+c.id+'" onclick="switchConversation('+c.id+')">' +
      '<span class="conv-info">' +
        '<span class="conv-title" id="convTitle_'+c.id+'">'+escapeHtml(c.title||'新对话')+'</span>' +
        '<input class="conv-edit-input" id="convEdit_'+c.id+'" value="'+escapeHtml(c.title||'新对话')+'" style="display:none;" maxlength="60">' +
        '<span class="conv-meta">' + (c.message_count||0) + ' 条消息 · ' + timeStr + '</span>' +
      '</span>' +
      '<button class="conv-rename" onclick="event.stopPropagation();startRenameConversation('+c.id+')" title="重命名">'+icon('rename','icon-18')+'</button>' +
      '<button class="conv-del" onclick="event.stopPropagation();deleteConversation('+c.id+')" title="删除">×</button>' +
    '</li>';
  }).join('');
}
function switchConversation(convId) {
  if (convId === currentConversationId) return;
  apiFetch('/api/conversations/' + convId)
    .then(function(r) {
      if (r.status === 404 || r.status === 403) {
        // Conversation deleted or not owned — silently remove and reset
        currentConversationId = null;
        loadConversationList();
        return null;
      }
      return handleBusinessResponse(r);
    })
    .then(function(d) {
      if (d === null) return; // 404/403 handled above
      currentConversationId = convId;
      var sessionKey = _chatSessionKey();
      chatSessions[sessionKey] = [];
      var turns = chatSessions[sessionKey];
      var messages = d.data.messages || [];
      messages.forEach(function(m) {
        turns.push({
          role: m.role,
          text: m.content,
          model: m.model || null,
          sources: m.sources || [],
          thinking: m.thinking || ''
        });
      });
      renderChatHistory(); scrollChatBottom();
      renderConvListFromCache();
    }).catch(function(e) { /* Silently retry on next click */ });
}
function renderConvListFromCache() {
  // 重新渲染对话列表的 active 状态（不重新请求网络）
  var items = document.querySelectorAll('#convList .conv-item');
  items.forEach(function(li){
    var cid = parseInt(li.getAttribute('data-conv-id'));
    if (cid === currentConversationId) li.classList.add('active');
    else li.classList.remove('active');
  });
}
function deleteConversation(convId) {
  if (!confirm('删除此对话？')) return;
  fetch('/api/conversations/' + convId, { method: 'DELETE', headers: authHeaders() })
    .then(function(r){ return r.json(); })
    .then(function(d){
      if (d.code !== 0) { toast('删除失败: ' + (d.msg||'未知错误'), 'error'); return; }
      if (convId === currentConversationId) newConversation();
      loadConversationList();
      toast('对话已删除', 'info');
    }).catch(function(e){ toast('删除失败: '+e.message,'error'); });
}
function startRenameConversation(convId) {
  var titleEl = document.getElementById('convTitle_'+convId);
  var inputEl = document.getElementById('convEdit_'+convId);
  if (!titleEl || !inputEl) return;
  // Show input, hide title
  titleEl.style.display = 'none';
  inputEl.style.display = '';
  inputEl.focus();
  inputEl.select();
  // Save on Enter
  inputEl.onkeydown = function(e) {
    if (e.key === 'Enter') { e.preventDefault(); saveRenameConversation(convId); }
    if (e.key === 'Escape') { cancelRenameConversation(convId); }
  };
  // Save on blur (click outside)
  inputEl.onblur = function() { saveRenameConversation(convId); };
}
function saveRenameConversation(convId) {
  var inputEl = document.getElementById('convEdit_'+convId);
  var titleEl = document.getElementById('convTitle_'+convId);
  if (!inputEl || !titleEl) return;
  var newTitle = inputEl.value.trim();
  // If blank or unchanged, just cancel
  if (!newTitle || newTitle === titleEl.textContent) {
    cancelRenameConversation(convId);
    return;
  }
  // Save to server
  fetch('/api/conversations/'+convId, {
    method: 'PATCH',
    headers: authHeaders(),
    body: JSON.stringify({title: newTitle})
  }).then(function(r){ return r.json(); })
    .then(function(d){
      if (d.code === 0) {
        titleEl.textContent = newTitle;
        toast('对话已重命名', 'success');
      } else {
        toast('重命名失败: '+(d.msg||'未知错误'), 'error');
      }
    }).catch(function(e){ toast('重命名失败: '+e.message, 'error'); });
  // Restore title view
  titleEl.style.display = '';
  inputEl.style.display = 'none';
}
function cancelRenameConversation(convId) {
  var inputEl = document.getElementById('convEdit_'+convId);
  var titleEl = document.getElementById('convTitle_'+convId);
  if (!inputEl || !titleEl) return;
  inputEl.value = titleEl.textContent;
  titleEl.style.display = '';
  inputEl.style.display = 'none';
}
function newConversation() {
  currentConversationId = null;
  var sessionKey = _chatSessionKey();
  chatSessions[sessionKey] = [];
  renderChatHistory();
  loadConversationList();
}
function formatRelativeTime(isoStr) {
  if (!isoStr) return '';
  var d = new Date(isoStr);
  var now = new Date();
  var diff = now - d;
  if (diff < 60000) return '刚刚';
  if (diff < 3600000) return Math.floor(diff/60000) + ' 分钟前';
  if (diff < 86400000) return Math.floor(diff/3600000) + ' 小时前';
  if (diff < 604800000) return Math.floor(diff/86400000) + ' 天前';
  return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate());
}
function pad2(n) { return n < 10 ? '0'+n : ''+n; }

function _chatSessionKey() {
  var base;
  if (selectedKbIds.length > 0) base = 'multi:' + selectedKbIds.slice().sort().join(',');
  else base = currentKbId || '';
  if (currentConversationId) base = base + '@conv:' + currentConversationId;
  return base;
}

async function sendChat() {
  // 确定搜索范围：勾选的 kb_ids 优先，否则退化为当前主库
  var searchKbIds = selectedKbIds.length > 0 ? selectedKbIds.slice() :
                    (currentKbId ? [currentKbId] : []);
  if (searchKbIds.length === 0) { toast('请先选择知识库','info'); return; }
  var isMultiKb = searchKbIds.length > 1;
  if (isStreaming) return;
  var input = document.getElementById('chatInput');
  var query = input.value.trim();
  if (!query) return;
  input.value = ''; input.style.height = 'auto';

  var sessionKey = _chatSessionKey();
  var turns = chatSessions[sessionKey] = chatSessions[sessionKey] || [];
  turns.push({ role:'user', text: query });
  if (turns.length > 50) { turns.splice(0, 10); }  // 防止内存无限增长

  var llmSel = document.getElementById('chatLlmModel');
  var modelLabel = (llmSel.options[llmSel.selectedIndex] && llmSel.value) ? llmSel.options[llmSel.selectedIndex].textContent : '库默认';
  var asst = { role:'assistant', text:'', model: modelLabel, sources: [], streaming: true };
  turns.push(asst);
  renderChatHistory();
  scrollChatBottom();

  isStreaming = true; setSendBtn(true);
  var textEl = document.querySelector('#chatHistory .bubble-row.assistant:last-child .bubble-text');

  if (DEMO) {
    var demoKbId = isMultiKb ? searchKbIds[0] : (currentKbId || searchKbIds[0]);
    var docs = (demoDB.docs || []).filter(function(x){ return x.kb_id===demoKbId && x.status==='done'; });
    asst.sources = docs.slice(0,2).map(function(x){ return x.filename; });
    var answer = '根据知识库内容，关于「' + query.replace(/[？?]$/,'') + '」的要点如下：\n\n' +
      '· 系统已支持多轮气泡式问答，可连续追问。\n' +
      '· 每条回答都会标注所用模型与来源文档。\n' +
      '· 你可以在下方切换 LLM 模型与 Rerank 开关。\n\n以上回答基于检索到的相关片段生成。';
    var chars = answer.split('');
    var i = 0;
    var timer = setInterval(function(){
      if (i >= chars.length) {
        clearInterval(timer);
        asst.streaming = false; isStreaming = false; setSendBtn(false);
        renderChatHistory(); scrollChatBottom();
        return;
      }
      asst.text += chars.slice(i, i+2).join(''); i += 2;
      if (textEl) { textEl.textContent = asst.text; scrollChatBottom(); }
    }, 22);
    return;
  }

  streamingAbort = new AbortController();
  var llmModel = llmSel.value;
  var rerank = document.getElementById('chatRerank').value;
  console.log('sendChat thinking=', isThinkingOn(), 'agentOn=', agentOn, 'isStreaming=', isStreaming);
  var history = turns.slice(0, turns.length - 2)
    .filter(function(t){ return t.text && t.text.trim(); })
    .map(function(t){ return { role: t.role, content: t.text }; })
    .slice(-6);
  var token = getToken();
  var chatUrl = agentOn ? '/api/chat/agent' : '/api/chat';
  var chatBody = agentOn
    ? JSON.stringify({ kb_ids: searchKbIds, query: query, stream: true, history: history, thinking: isThinkingOn(), conversation_id: currentConversationId || undefined })
    : JSON.stringify({ kb_ids: searchKbIds, query: query, stream: true, model: llmModel ? parseInt(llmModel) : undefined, rerank_enabled: rerank==='on'?true:rerank==='off'?false:undefined, history: history, thinking: isThinkingOn(), conversation_id: currentConversationId || undefined });
  try {
    var res = await fetch(chatUrl, {
      method: 'POST',
      headers: Object.assign({'Content-Type':'application/json','Accept':'text/event-stream'}, token ? {'Authorization':'Bearer '+token} : {}),
      body: chatBody,
      signal: streamingAbort.signal
    });
    console.log('fetch response status=', res.status, 'ok=', res.ok);
    if (res.status === 401) { setToken(''); showAuthPage(); toast('登录已过期','error'); return; }
    if (!res.ok) { toast('请求失败 (HTTP '+res.status+')','error'); return; }
    var reader = res.body.getReader();
    var chunkCount = 0;
    var decoder = new TextDecoder('utf-8');
    var buffer = '';
    var streamDone = false;
    while (true) {
      var result = await reader.read();
      var done = result.done, value = result.value;
      if (value) buffer += decoder.decode(value, {stream:!done});
      buffer = buffer.replace(/\r/g, '').replace(/^\n+/, '');
      var parts = buffer.split('\n\n');
      buffer = parts.pop();
      for (var j=0; j<parts.length; j++) {
        var raw = parts[j];
        var data = raw.replace(/^data: ?/,'').trim();
        if (!data) continue;
        console.log('sse data:', data.substring(0,80));
        // ── Agent 事件 ──
        if (data.indexOf('[PLANNER]') === 0) {
          try { var planner = JSON.parse(data.slice(9)); asst.agentTrace = asst.agentTrace || [];
            asst.agentTrace.push({type:'planner', reasoning:planner.reasoning, queries:planner.queries}); } catch(e){}
          renderChatHistory(); scrollChatBottom();
          textEl = document.querySelector('#chatHistory .bubble-row.assistant:last-child .bubble-text');
          continue;
        }
        if (data.indexOf('[SEARCHER]') === 0) {
          try { var sr = JSON.parse(data.slice(10)); asst.agentTrace = asst.agentTrace || [];
            asst.agentTrace.push({type:'searcher', chunks_found:sr.chunks_found, context_len:sr.context_len}); } catch(e){}
          renderChatHistory(); scrollChatBottom();
          textEl = document.querySelector('#chatHistory .bubble-row.assistant:last-child .bubble-text');
          continue;
        }
        if (data.indexOf('[VERIFIER]') === 0) {
          try { var vf = JSON.parse(data.slice(10)); asst.agentTrace = asst.agentTrace || [];
            asst.agentTrace.push({type:'verifier', passed:vf.passed, issues:vf.issues, iteration:vf.iteration}); } catch(e){}
          renderChatHistory(); scrollChatBottom();
          textEl = document.querySelector('#chatHistory .bubble-row.assistant:last-child .bubble-text');
          continue;
        }
        if (data.indexOf('[VERIFIED]') === 0) {
          try { var vd = JSON.parse(data.slice(10)); asst.agentVerified = vd.passed; asst.agentIssues = vd.issues; } catch(e){}
          continue;
        }
        if (data.indexOf('[INFO]') === 0) { continue; }
        if (data.indexOf('[PLANNER]') === 0) {
          try { var planner = JSON.parse(data.slice(9)); asst.agentTrace = asst.agentTrace || [];
            asst.agentTrace.push({type:'planner', reasoning:planner.reasoning, queries:planner.queries}); } catch(e){}
          renderChatHistory(); scrollChatBottom();
          textEl = document.querySelector('#chatHistory .bubble-row.assistant:last-child .bubble-text');
          continue;
        }
        if (data.indexOf('[SEARCHER]') === 0) {
          try { var sr = JSON.parse(data.slice(10)); asst.agentTrace = asst.agentTrace || [];
            asst.agentTrace.push({type:'searcher', chunks_found:sr.chunks_found, context_len:sr.context_len}); } catch(e){}
          renderChatHistory(); scrollChatBottom();
          textEl = document.querySelector('#chatHistory .bubble-row.assistant:last-child .bubble-text');
          continue;
        }
        if (data.indexOf('[VERIFIER]') === 0) {
          try { var vf = JSON.parse(data.slice(10)); asst.agentTrace = asst.agentTrace || [];
            asst.agentTrace.push({type:'verifier', passed:vf.passed, issues:vf.issues, iteration:vf.iteration}); } catch(e){}
          renderChatHistory(); scrollChatBottom();
          textEl = document.querySelector('#chatHistory .bubble-row.assistant:last-child .bubble-text');
          continue;
        }
        if (data.indexOf('[VERIFIED]') === 0) {
          try { var vd = JSON.parse(data.slice(10)); asst.agentVerified = vd.passed; asst.agentIssues = vd.issues; } catch(e){}
          continue;
        }
        if (data.indexOf('[INFO]') === 0) { continue; }
        if (data === '[DONE]') { streamDone = true; try { reader.cancel(); } catch(e){} break; }
        if (data.indexOf('[ERROR]') === 0) { toast(data.slice(8).trim()||'流式请求出错','error'); streamDone = true; try { reader.cancel(); } catch(e){} break; }
        if (data.indexOf('[CONV_ID]') === 0) {
          var newConvId = parseInt(data.slice(10));
          if (newConvId !== currentConversationId) {
            var oldKey = _chatSessionKey();
            currentConversationId = newConvId;
            var newKey = _chatSessionKey();
            if (oldKey !== newKey && chatSessions[oldKey]) {
              chatSessions[newKey] = chatSessions[oldKey];
              delete chatSessions[oldKey];
            }
          }
          loadConversationList(); continue;
        }
        if (data.indexOf('[SOURCES]') === 0) { try { asst.sources = JSON.parse(data.slice(9)); } catch(e){} continue; }
        // 思考模式：一次性发送完整思考内容
        if (data === '__THINKING_ON__') {
          asst.thinkingOn = true;
          continue;
        }
        if (data.indexOf('__THINK__:') === 0) {
          asst.thinking = data.substring(10).replace(/\\n/g, '\n');
          renderChatHistory(); scrollChatBottom();
          textEl = document.querySelector('#chatHistory .bubble-row.assistant:last-child .bubble-text');
          continue;
        }
        // 普通文本
        data = data.replace(/\\n/g, '\n');
        asst.text += data;
        chunkCount++;
        if (!textEl) { textEl = document.querySelector('#chatHistory .bubble-row.assistant:last-child .bubble-text'); console.log('textEl init:', !!textEl); }
        if (textEl) { textEl.textContent = asst.text; scrollChatBottom(); }
        else { renderChatHistory(); scrollChatBottom(); textEl = document.querySelector('#chatHistory .bubble-row.assistant:last-child .bubble-text'); }
      }
      if (streamDone || done) break;
    }
  } catch(err) {
    console.error('sendChat catch:', err.name, err.message, err);
    if (err.name === 'AbortError') {} else if (err.message === 'Unauthorized') {} else { toast('流式请求异常：'+(err.message||'未知错误'),'error'); }
  } finally {
    console.log('stream end: chunkCount=', chunkCount, 'textLength=', asst.text.length);
    asst.streaming = false; isStreaming = false; setSendBtn(false);
    streamingAbort = null;
    renderChatHistory(); scrollChatBottom();
  }
}

document.getElementById('btnSend').addEventListener('click', function(){
  if (isStreaming) { streamingAbort.abort(); return; }
  sendChat();
});
document.getElementById('btnClearChat').addEventListener('click', function(){
  newConversation();
});
document.getElementById('btnNewConv').addEventListener('click', function(e){
  e.stopPropagation();  // 防止触发父级 sb-collapse 的展开
  newConversation();
});

// Sidebar collapsible sections: click title to toggle
document.getElementById('sidebar').addEventListener('click', function(e){
  var title = e.target.closest('.sb-collapse-title');
  if (!title) return;
  var section = title.closest('.sb-collapse');
  if (!section) return;
  // 如果点击的是按钮/链接等交互元素，不触发折叠
  if (e.target.closest('button, a, input')) return;
  section.classList.toggle('open');
});

document.getElementById('chatInput').addEventListener('keydown', function(e){
  if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});
document.getElementById('chatInput').addEventListener('input', function(){
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 140) + 'px';
});
