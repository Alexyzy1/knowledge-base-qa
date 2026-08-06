"""
一键创建 3 个知识库 + 上传文档，用于测试全局搜索功能。
使用方法：
  1. docker-compose up -d
  2. python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
  3. python setup_global_search_demo.py
"""
import asyncio, json, requests, sys

BASE = "http://localhost:8000"
USERNAME = "admin"
PASSWORD = "YOUR_ADMIN_PASSWORD"  # <-- 改成你的实际密码

# ============================================================
# 1. Login
# ============================================================
print("=" * 50)
print("1. 登录...")
r = requests.post(f"{BASE}/api/auth/login",
                  json={"username": USERNAME, "password": PASSWORD})
if r.status_code != 200 or r.json().get("code") != 0:
    print(f"登录失败: {r.status_code} {r.text[:200]}")
    sys.exit(1)
token = r.json()["data"]["token"]
headers = {"Authorization": f"Bearer {token}"}
print(f"   登录成功: {USERNAME}")

# ============================================================
# 2. Create 3 KBs
# ============================================================
print("=" * 50)
print("2. 创建知识库...")

kb_defs = [
    {"name": "🍃 温室技术手册", "description": "温室种植、环境控制、灌溉技术相关资料"},
    {"name": "🚇 地铁票价规则",   "description": "城市轨道交通票价政策、计价规则"},
    {"name": "📝 日常笔记",       "description": "杂项笔记、个人记录"},
]

kb_ids = []
for kb_def in kb_defs:
    r = requests.post(f"{BASE}/api/kb", json={
        "name": kb_def["name"],
        "description": kb_def["description"],
    }, headers=headers)
    data = r.json()
    if data.get("code") == 0:
        kid = data["data"]["id"]
        kb_ids.append(kid)
        print(f"   ✓ {kb_def['name']} → kb_id={kid}")
    else:
        print(f"   ✗ {kb_def['name']}: {data.get('msg', data)}")

if not kb_ids:
    print("没有成功创建知识库，请先手动创建或检查是否已存在")
    sys.exit(1)

# ============================================================
# 3. Upload documents
# ============================================================
print("=" * 50)
print("3. 上传文档...")

uploads = [
    # (kb_index, file_path, display_name) — 示例文档已删除
    # 上传前先准备文件，或运行 seed_data.py 生成种子数据
]

for kb_idx, filepath, display_name in uploads:
    kid = kb_ids[kb_idx]
    try:
        with open(filepath, "rb") as f:
            r = requests.post(
                f"{BASE}/api/kb/{kid}/upload",
                files={"file": (display_name, f)},
                headers={"Authorization": f"Bearer {token}"},
            )
        data = r.json()
        if data.get("code") == 0:
            doc_id = data["data"]["id"]
            print(f"   ✓ [{kb_defs[kb_idx]['name']}] {display_name} → doc_id={doc_id}")
        else:
            print(f"   ✗ {display_name}: {data.get('msg', data)}")
    except FileNotFoundError:
        print(f"   ⊘ {display_name}: 文件不存在，跳过")
    except Exception as e:
        print(f"   ✗ {display_name}: {e}")

# ============================================================
# 4. Wait for ingestion
# ============================================================
import time
print("=" * 50)
print("4. 等待入库完成（最多 30s）...")
for i in range(30):
    time.sleep(1)
    all_done = True
    for kid in kb_ids:
        r = requests.get(f"{BASE}/api/kb/{kid}/stats", headers=headers)
        if r.status_code == 200 and r.json().get("code") == 0:
            stats = r.json()["data"]
            if stats.get("chunk_count", 0) == 0:
                all_done = False
    if all_done:
        print("   全部入库完成!")
        break
    print(f"   ...{i+1}s")

# ============================================================
# 5. Show stats
# ============================================================
print("=" * 50)
print("5. 知识库统计:")
for kid in kb_ids:
    r = requests.get(f"{BASE}/api/kb/{kid}/stats", headers=headers)
    if r.status_code == 200:
        stats = r.json()["data"]
        kb = next((k for k in kb_defs if kb_ids[kb_defs.index(k)] == kid), None)
        name = kb["name"] if kb else f"kb#{kid}"
        print(f"   {name}: {stats['doc_count']} 文档, {stats['chunk_count']} 块")

# ============================================================
# 6. Test global search
# ============================================================
print("=" * 50)
print("6. 测试全局搜索...")
print()

# 单库（向后兼容）
r = requests.post(f"{BASE}/api/chat", headers=headers, json={
    "kb_id": kb_ids[0],
    "query": "温室如何控制温度",
    "stream": False,
})
ans = r.json()
print(f"[单库] kb_id={kb_ids[0]}: {ans.get('code')} - sources: {len(ans.get('data',{}).get('sources',[]))} 条")

# 多库全局搜索
r = requests.post(f"{BASE}/api/chat", headers=headers, json={
    "kb_ids": kb_ids,
    "query": "介绍一下这方面的内容",
    "stream": False,
})
ans = r.json()
sources = ans.get("data", {}).get("sources", [])
print(f"[多库] kb_ids={kb_ids}: {ans.get('code')} - sources: {len(sources)} 条")
for s in sources:
    print(f"   [{s.get('cite')}] {s.get('filename')} (库: {s.get('kb_name', 'N/A')})")

print()
print("=" * 50)
print("全部完成! 现在可以打开 frontend/index.html 测试多选 UI")
print(f"知识库 IDs: {kb_ids}")
print()

# curl 命令参考
print("手动 curl 测试命令:")
print(f'  curl -X POST {BASE}/api/chat -H "Authorization: Bearer $TOKEN" \\')
print(f'    -H "Content-Type: application/json" \\')
print(f'    -d \'{{"kb_ids": {kb_ids}, "query": "测试全局搜索", "stream": false}}\'')
