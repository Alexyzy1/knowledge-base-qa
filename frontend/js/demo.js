// demo.js
// DEMO MODE — in-browser mock backend (preview without server)
// Activate by adding ?demo=1 to the URL. Production path untouched.
// ============================================================
var DEMO = /[?&]demo=1\b/.test(window.location.search);
var demoDB = null;
function demoNow(offsetMin) {
  var d = new Date(Date.now() - (offsetMin||0)*60000);
  var p = function(n){ return (n<10?'0':'')+n; };
  return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+' '+p(d.getHours())+':'+p(d.getMinutes());
}
function demoInit() {
  demoDB = {
    user: { id: 1, username: 'demo_admin', role: 'super_admin', created_at: '2026-03-01 10:00' },
    kbs: [
      { id: 1, name: '产品知识库', role: 'owner',  owner_username: 'demo_admin', created_at: '2026-05-12 09:30', description: '产品文档、FAQ 与发布说明的统一入口。' },
      { id: 2, name: '工程 Wiki',  role: 'editor', owner_username: 'li_wei',     created_at: '2026-04-02 14:10', description: '架构决策、编码规范与线上排障手册。' },
      { id: 3, name: '市场素材库',  role: 'reader', owner_username: 'zhang_min',  created_at: '2026-06-01 11:00', description: '品牌视觉、活动文案与图片资源。' }
    ],
    settings: {
      1: { name:'产品知识库', description:'产品文档、FAQ 与发布说明的统一入口。', chunk_size:500, overlap:50, retrieval_mode:'hybrid', recall_k:20, top_k:5, rerank_enabled:true, rerank_top_n:3, score_threshold:0.5, ocr_enabled:true, table_parse_enabled:true, formula_parse_enabled:false, llm_model:'Qwen2.5-72B', rerank_model:'bge-reranker-v2', embedding_model:'bge-large-zh-v1.5', file_ttl_days:0 },
      2: { name:'工程 Wiki', description:'架构决策、编码规范与线上排障手册。', chunk_size:800, overlap:80, retrieval_mode:'dense', recall_k:30, top_k:6, rerank_enabled:false, rerank_top_n:3, score_threshold:0.45, ocr_enabled:false, table_parse_enabled:true, formula_parse_enabled:true, llm_model:'DeepSeek-V3', rerank_model:'bge-reranker-v2', embedding_model:'bge-large-zh-v1.5', file_ttl_days:90 },
      3: { name:'市场素材库', description:'品牌视觉、活动文案与图片资源。', chunk_size:400, overlap:40, retrieval_mode:'hybrid', recall_k:15, top_k:5, rerank_enabled:true, rerank_top_n:3, score_threshold:0.5, ocr_enabled:true, table_parse_enabled:false, formula_parse_enabled:false, llm_model:'Qwen2.5-72B', rerank_model:'bge-reranker-v2', embedding_model:'text-embedding-3-large', file_ttl_days:30 }
    },
    folders: {
      1: [ {id:11,name:'产品手册',parent_id:null,depth:0}, {id:12,name:'2026 发布',parent_id:11,depth:1}, {id:13,name:'FAQ',parent_id:null,depth:0} ],
      2: [ {id:21,name:'架构',parent_id:null,depth:0}, {id:22,name:'排障',parent_id:null,depth:0} ],
      3: []
    },
    docs: [
      { id:101, kb_id:1, folder_id:12, filename:'产品发布说明 v2.0.pdf', status:'done', size_bytes:2516582, uploaded_by:'demo_admin', uploaded_at:demoNow(60), updated_at:demoNow(60), tags:['发布','PDF'], expires_at:null, markdown:'# 产品发布说明 v2.0\n\n本次更新带来多轮对话、任务中心与文件有效期管理。\n\n## 亮点\n- 气泡式问答\n- 全局任务中心\n- 文件分级体积限制' },
      { id:102, kb_id:1, folder_id:13, filename:'常见问题 FAQ.md', status:'done', size_bytes:48213, uploaded_by:'li_wei', uploaded_at:demoNow(220), updated_at:demoNow(220), tags:['FAQ'], expires_at:null, markdown:'# FAQ\n\n**Q: 支持哪些文件格式？**\nA: PDF、Word、表格、图片、TXT/MD/JSON/HTML/XML。\n\n**Q: 单文件多大？**\nA: 图片 10MB，PDF 20MB，Word/表格 15MB，文本 5MB。' },
      { id:103, kb_id:1, folder_id:11, filename:'用户调研记录.docx', status:'processing', size_bytes:1283910, uploaded_by:'demo_admin', uploaded_at:demoNow(8), updated_at:demoNow(8), tags:['调研'], expires_at:null, markdown:'解析中…' },
      { id:104, kb_id:1, folder_id:null, filename:'竞品定价对比.csv', status:'done', size_bytes:18402, uploaded_by:'zhang_min', uploaded_at:demoNow(1500), updated_at:demoNow(1500), tags:['竞品','表格'], expires_at:demoNow(-60), markdown:'name,price\nA,99\nB,129\nC,79' },
      { id:105, kb_id:1, folder_id:null, filename:'首页 Banner.png', status:'done', size_bytes:842311, uploaded_by:'demo_admin', uploaded_at:demoNow(2880), updated_at:demoNow(2880), tags:['图片','视觉'], expires_at:demoNow(43200), markdown:'(图片文件 — 已 OCR)\n限时大促，全场 8 折。' },
      { id:106, kb_id:1, folder_id:null, filename:'路线图草稿.txt', status:'failed', size_bytes:9120, uploaded_by:'demo_admin', uploaded_at:demoNow(40), updated_at:demoNow(40), tags:[], expires_at:null, markdown:'' },
      { id:201, kb_id:2, folder_id:21, filename:'系统架构总览.pdf', status:'done', size_bytes:3920122, uploaded_by:'li_wei', uploaded_at:demoNow(700), updated_at:demoNow(700), tags:['架构'], expires_at:null, markdown:'# 架构总览\n网关 → 服务层 → 向量库。' },
      { id:202, kb_id:2, folder_id:22, filename:'线上排障手册.md', status:'done', size_bytes:64200, uploaded_by:'demo_admin', uploaded_at:demoNow(900), updated_at:demoNow(900), tags:['排障','SRE'], expires_at:null, markdown:'# 排障手册\n1. 看监控\n2. 查日志\n3. 回滚' }
    ],
    members: {
      1: [ {user_id:1,username:'demo_admin',role:'owner'}, {user_id:2,username:'li_wei',role:'editor'}, {user_id:3,username:'zhang_min',role:'reader'} ],
      2: [ {user_id:2,username:'li_wei',role:'owner'}, {user_id:1,username:'demo_admin',role:'editor'} ],
      3: [ {user_id:3,username:'zhang_min',role:'owner'}, {user_id:1,username:'demo_admin',role:'reader'} ]
    },
    audit: [
      {id:1,kb_id:1,username:'demo_admin',action:'doc_upload',target:'产品发布说明 v2.0.pdf',created_at:demoNow(60)},
      {id:2,kb_id:1,username:'li_wei',action:'config_change',target:'rerank_enabled=true',created_at:demoNow(180)},
      {id:3,kb_id:1,username:'demo_admin',action:'member_add',target:'zhang_min (reader)',created_at:demoNow(400)},
      {id:4,kb_id:1,username:'demo_admin',action:'share_create',target:'常见问题 FAQ.md',created_at:demoNow(800)}
    ],
    shares: { 1: [ {id:1,doc_id:102,doc_filename:'常见问题 FAQ.md',token:'demoFAQ123',expires_at:null} ] },
    models: [
      {id:1,name:'Qwen2.5-72B',type:'llm',endpoint:'https://api.local/v1',enabled:true},
      {id:2,name:'DeepSeek-V3',type:'llm',endpoint:'https://api.local/v1',enabled:true},
      {id:3,name:'bge-reranker-v2',type:'rerank',endpoint:'https://api.local/rerank',enabled:true},
      {id:4,name:'bge-large-zh-v1.5',type:'embedding',endpoint:'https://api.local/embed',enabled:true}
    ],
    keys: [ {id:1,name:'我的脚本',prefix:'kb_live_a1b2',created_at:'2026-06-10 09:00',last_used_at:demoNow(120)} ],
    whitelist: [ {username:'li_wei',note:'工程团队'}, {username:'zhang_min',note:'市场团队'} ],
    tasks: [
      {id:1,filename:'用户调研记录.docx',kb_name:'产品知识库',status:'processing',progress:62,started_at:demoNow(8)},
      {id:2,filename:'年度财报.pdf',kb_name:'工程 Wiki',status:'queued',progress:0,started_at:demoNow(3)},
      {id:3,filename:'活动海报合集.zip',kb_name:'市场素材库',status:'queued',progress:0,started_at:demoNow(2)},
      {id:4,filename:'路线图草稿.txt',kb_name:'产品知识库',status:'failed',progress:0,started_at:demoNow(40),error:'解析超时'},
      {id:5,filename:'产品发布说明 v2.0.pdf',kb_name:'产品知识库',status:'done',progress:100,started_at:demoNow(60)}
    ],
    seq: 9000
  };
}
function demoMatch(path, re) { var m = path.split('?')[0].match(re); return m; }
function demoQuery(path) {
  var q = {}; var i = path.indexOf('?');
  if (i === -1) return q;
  path.slice(i+1).split('&').forEach(function(kv){ var p = kv.split('='); q[decodeURIComponent(p[0])] = decodeURIComponent(p[1]||''); });
  return q;
}
function demoResp(data, code) {
  return Promise.resolve({ ok:true, status:200, json: function(){ return Promise.resolve({ code: code||0, data: data }); } });
}
// Mock router — returns a thenable mimicking fetch Response
function demoApi(path, options) {
  if (!demoDB) demoInit();
  options = options || {};
  var method = (options.method || 'GET').toUpperCase();
  var bodyObj = {};
  try { if (options.body && typeof options.body === 'string') bodyObj = JSON.parse(options.body); } catch(e){}
  var m, q = demoQuery(path);
  var d = demoDB;

  // auth/account
  if (/\/api\/auth\/me$/.test(path) || /\/api\/account$/.test(path)) return demoResp(d.user);
  if (/\/api\/account\/password$/.test(path)) return demoResp({updated:true});

  // KB list
  if (/\/api\/kb$/.test(path) && method === 'GET') return demoResp(d.kbs);
  if (/\/api\/kb$/.test(path) && method === 'POST') {
    var nk = { id: ++d.seq, name: bodyObj.name, role:'owner', owner_username:d.user.username, created_at:demoNow(0), description:bodyObj.description||'' };
    d.kbs.push(nk);
    d.settings[nk.id] = Object.assign({}, d.settings[1], {
      name: nk.name, description: nk.description||'',
      chunk_method: bodyObj.chunk_method || 'recursive',
      chunk_size: bodyObj.chunk_size || 500,
      overlap: bodyObj.overlap || 50,
      retrieval_mode: bodyObj.retrieval_mode || 'hybrid',
      recall_k: bodyObj.recall_k || 20,
      top_k: bodyObj.top_k || 5,
      rerank_mode: bodyObj.rerank_mode || 'fusion',
      rerank_enabled: (bodyObj.rerank_mode || 'fusion') !== 'off',
      llm_model: bodyObj.llm_model || '',
      safety_enabled: bodyObj.safety_enabled != null ? bodyObj.safety_enabled : true,
      safety_llm_check: bodyObj.safety_llm_check != null ? bodyObj.safety_llm_check : false
    });
    d.folders[nk.id]=[]; d.members[nk.id]=[{user_id:1,username:d.user.username,role:'owner'}];
    return demoResp(nk);
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)$/)) && method === 'DELETE') {
    var kid = +m[1]; d.kbs = d.kbs.filter(function(k){ return k.id !== kid; }); return demoResp({deleted:kid});
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/stats$/))) {
    var kid = +m[1]; var ds = d.docs.filter(function(x){ return x.kb_id===kid; });
    var bytes = ds.reduce(function(a,x){ return a + (x.size_bytes||0); }, 0);
    return demoResp({ doc_count:ds.length, chunk_count:ds.length*7+3, member_count:(d.members[kid]||[]).length, size_bytes:bytes, updated_at:demoNow(60) });
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/settings$/))) {
    var kid = +m[1];
    if (method === 'PUT') { d.settings[kid] = Object.assign({}, d.settings[kid], bodyObj); var kb=d.kbs.find(function(k){return k.id===kid;}); if(kb){kb.name=bodyObj.name||kb.name;kb.description=bodyObj.description!=null?bodyObj.description:kb.description;} return demoResp(d.settings[kid]); }
    return demoResp(d.settings[kid] || {});
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/audit/))) {
    var kid = +m[1]; var rows = d.audit.filter(function(a){ return a.kb_id===kid; });
    if (q.action) rows = rows.filter(function(a){ return a.action===q.action; });
    if (q.user) rows = rows.filter(function(a){ return a.username.indexOf(q.user)!==-1; });
    return demoResp({items: rows, total: rows.length});
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/docs$/)) || (m = demoMatch(path, /\/api\/kb\/(\d+)\/docs\?/))) {
    if (method === 'GET') {
      var kid = +m[1]; var rows = d.docs.filter(function(x){ return x.kb_id===kid; });
      if (q.folder_id) rows = rows.filter(function(x){ return String(x.folder_id)===String(q.folder_id); });
      if (q.tag) rows = rows.filter(function(x){ return (x.tags||[]).indexOf(q.tag)!==-1; });
      rows = rows.map(function(x){ return Object.assign({}, x, {size:formatBytes(x.size_bytes)}); });
      return demoResp(rows);
    }
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/folders$/))) {
    var kid = +m[1];
    if (method === 'POST') { var nf={id:++d.seq,name:bodyObj.name,parent_id:bodyObj.parent_id||null,depth:0}; if(nf.parent_id){var par=(d.folders[kid]||[]).find(function(f){return f.id===nf.parent_id;}); nf.depth=par?par.depth+1:1;} (d.folders[kid]=d.folders[kid]||[]).push(nf); return demoResp(nf); }
    return demoResp(d.folders[kid] || []);
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/folders\/(\d+)$/)) && method === 'DELETE') {
    var kid=+m[1], fid=+m[2]; d.folders[kid]=(d.folders[kid]||[]).filter(function(f){return f.id!==fid;}); d.docs.forEach(function(x){ if(x.kb_id===kid&&x.folder_id===fid) x.folder_id=null; }); return demoResp({deleted_id:fid});
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/members$/))) {
    var kid = +m[1];
    if (method === 'POST') { var nm={user_id:++d.seq,username:bodyObj.username,role:bodyObj.role}; (d.members[kid]=d.members[kid]||[]).push(nm); return demoResp(nm); }
    return demoResp(d.members[kid] || []);
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/members\/(\d+)$/)) && method === 'DELETE') {
    var kid=+m[1], uid=+m[2]; d.members[kid]=(d.members[kid]||[]).filter(function(x){return x.user_id!==uid;}); return demoResp({removed:uid});
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/similar$/))) {
    var kid = +m[1]; var rows = d.docs.filter(function(x){ return x.kb_id===kid && x.status==='done'; }).slice(0,4).map(function(x,i){ return {doc_id:x.id, doc_name:x.filename, kb_id:kid, kb_name:(d.kbs.find(function(k){return k.id===kid;})||{}).name, similarity:0.92-i*0.11, snippet:(x.markdown||'').slice(0,90).replace(/\n/g,' ')}; });
    return demoResp(rows);
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/share$/))) {
    var kid = +m[1];
    if (method === 'POST') { var doc=d.docs.find(function(x){return x.id===bodyObj.doc_id;}); var sh={id:++d.seq,doc_id:bodyObj.doc_id,doc_filename:doc?doc.filename:'文档',token:'demo'+d.seq,expires_at:bodyObj.expires_in_days?demoNow(-bodyObj.expires_in_days*1440):null}; sh.url=window.location.origin+'/share/'+sh.token; (d.shares[kid]=d.shares[kid]||[]).push(sh); return demoResp(sh); }
    return demoResp(d.shares[kid] || []);
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/share\/(\d+)$/)) && method === 'DELETE') {
    var kid=+m[1], sid=+m[2]; d.shares[kid]=(d.shares[kid]||[]).filter(function(s){return s.id!==sid;}); return demoResp({revoked:sid});
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/notes$/)) && method === 'POST') {
    var kid=+m[1]; var nd={id:++d.seq,kb_id:kid,folder_id:bodyObj.folder_id||null,filename:bodyObj.title+'.md',status:'done',size_bytes:(bodyObj.content||'').length,uploaded_by:d.user.username,uploaded_at:demoNow(0),updated_at:demoNow(0),tags:['笔记'],expires_at:null,markdown:bodyObj.content}; d.docs.push(nd); return demoResp(nd);
  }
  if ((m = demoMatch(path, /\/api\/kb\/\d+\/docs\/(\d+)\/tags$/)) && method === 'PUT') {
    var did=+m[1]; var doc=d.docs.find(function(x){return x.id===did;}); if(doc) doc.tags=bodyObj.tags||[]; return demoResp({doc_id:did,tags:doc?doc.tags:[]});
  }
  if ((m = demoMatch(path, /\/api\/docs\/(\d+)\/preview$/))) {
    var did=+m[1]; var doc=d.docs.find(function(x){return x.id===did;}); return demoResp({markdown:doc?doc.markdown:'', chunks:[]});
  }
  if ((m = demoMatch(path, /\/api\/docs\/(\d+)$/)) && method === 'DELETE') {
    var did=+m[1]; d.docs=d.docs.filter(function(x){return x.id!==did;}); return demoResp({deleted:did});
  }
  if ((m = demoMatch(path, /\/api\/docs\/(\d+)\/retry$/))) {
    var did=+m[1]; var doc=d.docs.find(function(x){return x.id===did;}); if(doc) {doc.status='processing'; var tid=++d.seq; d.tasks.push({id:tid,filename:doc.filename,kb_name:(d.kbs.find(function(k){return k.id===doc.kb_id;})||{}).name||'',status:'queued',progress:0,started_at:demoNow(0)}); return demoResp({doc_id:did,task_id:tid,status:'queued'});} return demoResp(null,404);
  }
  if ((m = demoMatch(path, /\/api\/kb\/(\d+)\/docs\/batch-retry$/))) {
    var ids=bodyObj.doc_ids||[]; var ok=[],fail=[]; ids.forEach(function(did){ var doc=d.docs.find(function(x){return x.id===did;}); if(doc){doc.status='processing'; var tid=++d.seq; d.tasks.push({id:tid,filename:doc.filename,kb_name:(d.kbs.find(function(k){return k.id===doc.kb_id;})||{}).name||'',status:'queued',progress:0,started_at:demoNow(0)}); ok.push({doc_id:did,task_id:tid});} else { fail.push({doc_id:did,reason:'文档不存在'});} }); return demoResp({total:ids.length,succeeded:ok,failed:fail});
  }
  // tasks
  if (/\/api\/tasks/.test(path)) {
    if ((m = demoMatch(path, /\/api\/tasks\/(\d+)\/retry$/))) { var tid=+m[1]; var t=d.tasks.find(function(x){return x.id===tid;}); if(t){t.status='queued';t.progress=0;t.error=null;} return demoResp(t); }
    return demoResp(d.tasks);
  }
  // models / keys / whitelist / global audit
  if (/\/api\/models/.test(path)) {
    if ((m = demoMatch(path, /\/api\/models\/(\d+)$/)) && method === 'PUT') { var mid=+m[1]; var mo=d.models.find(function(x){return x.id===mid;}); if(mo) Object.assign(mo,bodyObj); return demoResp(mo); }
    if (/\/api\/models$/.test(path) && method === 'POST') { var nmo=Object.assign({id:++d.seq,enabled:true},bodyObj); d.models.push(nmo); return demoResp(nmo); }
    var ms = d.models.slice(); if (q.type) ms = ms.filter(function(x){return x.type===q.type;}); if (q.only_enabled) ms = ms.filter(function(x){return x.enabled;});
    return demoResp(ms);
  }
  if (/\/api\/keys/.test(path)) {
    if ((m = demoMatch(path, /\/api\/keys\/(\d+)$/)) && method === 'DELETE') { var kid2=+m[1]; d.keys=d.keys.filter(function(x){return x.id!==kid2;}); return demoResp({revoked:kid2}); }
    if (method === 'POST') { var nkey={id:++d.seq,name:bodyObj.name,prefix:'kb_live_'+Math.random().toString(36).slice(2,6),created_at:demoNow(0),last_used_at:null,key:'kb_live_'+Math.random().toString(36).slice(2)+Math.random().toString(36).slice(2)}; d.keys.push({id:nkey.id,name:nkey.name,prefix:nkey.prefix,created_at:nkey.created_at,last_used_at:null}); return demoResp(nkey); }
    return demoResp(d.keys);
  }
  if (/\/api\/whitelist/.test(path)) {
    if ((m = demoMatch(path, /\/api\/whitelist\/(.+)$/)) && method === 'DELETE') { var un=decodeURIComponent(m[1]); d.whitelist=d.whitelist.filter(function(x){return x.username!==un;}); return demoResp({removed:un}); }
    if (method === 'POST') { var nw={username:bodyObj.username,note:bodyObj.note||''}; d.whitelist.push(nw); return demoResp(nw); }
    return demoResp(d.whitelist);
  }
  if (/\/api\/audit/.test(path)) {
    var rows2 = d.audit.map(function(a){ var kb=d.kbs.find(function(k){return k.id===a.kb_id;}); return Object.assign({kb_name:kb?kb.name:a.kb_id}, a); });
    if (q.action) rows2 = rows2.filter(function(a){return a.action===q.action;});
    if (q.user) rows2 = rows2.filter(function(a){return a.username.indexOf(q.user)!==-1;});
    return demoResp({items: rows2, total: rows2.length});
  }
  if (/\/api\/stats\/dashboard/.test(path)) {
    var ddays = parseInt(q.days) || 30;
    var dtrend = [];
    for (var di = 0; di < ddays; di++) {
      var dt = new Date(Date.now() - (ddays - 1 - di) * 86400000);
      dtrend.push({ date: dt.toISOString().slice(0,10), count: Math.floor(Math.random() * 20) + 2 });
    }
    return demoResp({
      overview: {
        total_users: 3, total_kbs: 3, total_documents: 8,
        total_qa_messages: ddays === 7 ? 42 : ddays === 30 ? 156 : 380,
        total_conversations: ddays === 7 ? 18 : ddays === 30 ? 65 : 150,
      },
      qa_trend: dtrend,
      top_active_users: [
        { user_id: 1, username: 'demo_admin', message_count: 42 },
        { user_id: 2, username: 'li_wei', message_count: 28 },
        { user_id: 3, username: 'zhang_min', message_count: 15 }
      ],
      kb_usage: [
        { kb_id: 1, kb_name: '产品知识库', doc_count: 6, message_count: 68 },
        { kb_id: 2, kb_name: '工程 Wiki', doc_count: 4, message_count: 45 },
        { kb_id: 3, kb_name: '市场素材库', doc_count: 2, message_count: 12 }
      ],
      doc_status_distribution: { done: 7, processing: 1, failed: 1 },
      daily_active_users: 2,
    });
  }
  if ((m = demoMatch(path, /\/api\/share\/(.+)$/))) {
    var tok=m[1]; var doc=d.docs.find(function(x){return x.id===102;});
    return demoResp({doc_id:102,doc_name:doc.filename,kb_name:'产品知识库',markdown:doc.markdown,expires_at:null});
  }
  // default empty
  return demoResp([]);
}
function demoAddTask(filename) {
  if (!DEMO) return;
  if (!demoDB) demoInit();
  var t = { id: ++demoDB.seq, filename: filename, kb_name: (kbListCache.find(function(k){return k.id===currentKbId;})||{}).name || '知识库', status:'processing', progress: 5, started_at: demoNow(0) };
  demoDB.tasks.unshift(t);
  updateTaskBadge();
}
