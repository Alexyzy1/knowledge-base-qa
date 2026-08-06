# webchat.py —— 浏览器里跟 DeepSeek 对话,零安装(标准库 + 已装的 openai)
import asyncio, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from loguru import logger
from backend.core import llm_client

logger.remove()
PORT = 8000   # 

PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DeepSeek 对话</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:760px;margin:0 auto;padding:16px;background:#f7f7f8}
 #log{height:68vh;overflow-y:auto;background:#fff;border:1px solid #e2e2e2;border-radius:10px;padding:14px}
 .msg{margin:10px 0;line-height:1.6;white-space:pre-wrap;word-wrap:break-word}
 .u{font-weight:600}
 .a{background:#f0f4ff;border-radius:8px;padding:8px 10px}
 #bar{display:flex;gap:8px;margin-top:12px}
 #q{flex:1;padding:10px;border:1px solid #ccc;border-radius:8px;font-size:15px}
 button{padding:10px 18px;border:0;border-radius:8px;background:#2563eb;color:#fff;font-size:15px;cursor:pointer}
 button:disabled{opacity:.5}
</style></head>
<body>
<h3>跟服务器上的 DeepSeek 对话</h3>
<div id="log"></div>
<div id="bar">
 <input id="q" placeholder="输入问题,回车发送" autofocus>
 <button id="send">发送</button>
 <button id="clear">清空</button>
</div>
<script>
let messages=[];
const log=document.getElementById('log');
const q=document.getElementById('q');
const sendBtn=document.getElementById('send');
function add(role,text){
  const d=document.createElement('div');
  d.className='msg '+(role==='user'?'u':'a');
  d.textContent=(role==='user'?'你: ':'DeepSeek: ')+text;
  log.appendChild(d); log.scrollTop=log.scrollHeight;
}
async function send(){
  const text=q.value.trim(); if(!text) return;
  q.value=''; sendBtn.disabled=true;
  add('user',text); messages.push({role:'user',content:text});
  try{
    const r=await fetch('/chat',{method:'POST',body:JSON.stringify(messages)});
    const data=await r.json();
    add('assistant',data.reply); messages.push({role:'assistant',content:data.reply});
  }catch(e){ add('assistant','[出错] '+e); }
  sendBtn.disabled=false; q.focus();
}
sendBtn.onclick=send;
q.addEventListener('keydown',e=>{ if(e.key==='Enter') send(); });
document.getElementById('clear').onclick=()=>{ messages=[]; log.innerHTML=''; };
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
        self.wfile.write(PAGE.encode('utf-8'))
    def do_POST(self):
        length=int(self.headers.get('Content-Length',0))
        messages=json.loads(self.rfile.read(length))
        reply, _ = asyncio.run(llm_client.chat(messages))
        body=json.dumps({"reply":reply},ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type','application/json; charset=utf-8'); self.end_headers()
        self.wfile.write(body)

print(f"服务已起,浏览器访问 http://localhost:{PORT}  (Ctrl+C 停止)")
ThreadingHTTPServer(('0.0.0.0',PORT),H).serve_forever()
