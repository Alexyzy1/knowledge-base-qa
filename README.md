# 知识库问答系统 (Knowledge Base Q&A System)

基于 RAG（检索增强生成）的企业级知识库问答系统。上传文档 → 自动切片入库 → 智能检索 → LLM 回答，支持多知识库、多轮对话、权限管理、分享链接等功能。

> 技术栈：FastAPI + Milvus + MySQL + DeepSeek/Qwen/OpenAI 兼容 API

## 功能特性

- 📄 **多格式文档解析** — PDF、Word、Excel、PPT、Markdown、TXT、CSV、图片（OCR）、音视频（ASR）
- 🔍 **智能检索** — 混合检索 + HyDE + 查询改写 + Rerank + 多样性控制
- 💬 **多轮对话** — 带记忆的问答，支持思考模式（DeepSeek/Qwen reasoning）
- 👥 **RBAC 权限** — 超级管理员 / 知识库 Owner / 成员，完整的角色控制
- 🔗 **分享与导入** — 生成只读分享链接 + 从链接一键导入知识库
- 📊 **仪表盘** — 统计概览、审计日志、使用趋势
- 🤖 **Agentic RAG** — 基于 LangGraph 的智能体检索（可选）
- 🌐 **IP 白名单** — 访问控制 + 双层限流（IP 级 + 用户级）

## 快速开始

### 方式一：Docker Compose（推荐）

一条命令，自动启动应用 + MySQL + Milvus，**全平台适用（Linux / macOS / Windows）**。

**前置条件：安装 Docker**

| 系统 | 安装方式 |
|------|----------|
| **Linux** | `curl -fsSL https://get.docker.com \| sudo sh` |
| **macOS** | `brew install --cask docker`（然后启动 Docker Desktop） |
| **Windows** | 下载 [Docker Desktop](https://www.docker.com/products/docker-desktop/) 安装并启动 |

**启动步骤（三系统通用）：**

```bash
# 1. 克隆仓库
git clone https://github.com/你的用户名/yuanzy-kb.git
cd yuanzy-kb

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入以下三项：
#   MODEL_API_KEY=sk-your-api-key     # DeepSeek / Qwen / OpenAI API Key
#   JWT_SECRET=一段随机字符串
#   ADMIN_PASSWORD=你的管理员密码

# 3. 启动
docker compose up -d

# 4. 打开浏览器访问
# http://localhost:8000
```

首次启动会自动初始化数据库表、创建管理员账号。默认用户名 `admin`，密码为 `.env` 中设置的 `ADMIN_PASSWORD`。

---

### 方式二：源码安装

适合已有 MySQL + Milvus 实例，或需要本地开发调试。

**前置条件：**

- Python 3.11+
- MySQL 8.0+（已创建 `knowledge_base` 数据库）
- Milvus 2.6+（Standalone 模式）

#### Linux（Ubuntu/Debian）

```bash
# 1. 安装 Python 3.11
sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip git

# 2. 启动 MySQL 和 Milvus（如果没有，可以用 Docker 跑）
docker run -d --name kb-mysql \
  -e MYSQL_ROOT_PASSWORD=your_db_password \
  -e MYSQL_DATABASE=knowledge_base \
  -p 3306:3306 mysql:8.4

docker run -d --name kb-milvus \
  -p 19530:19530 -p 9091:9091 \
  milvusdb/milvus:v2.6.6 standalone

# 3. 克隆仓库
git clone https://github.com/你的用户名/yuanzy-kb.git
cd yuanzy-kb

# 4. 创建虚拟环境并安装依赖
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. 配置环境变量
cp .env.example .env
nano .env    # 填入 MODEL_API_KEY / JWT_SECRET / ADMIN_PASSWORD
             # 以及正确的 MYSQL_URL / MILVUS_HOST

# 6. 初始化数据库
python -c "
import os
os.environ['ADMIN_PW'] = '你的管理员密码'
os.environ['MYSQL_URL'] = 'mysql+pymysql://root:your_db_password@127.0.0.1:3306/knowledge_base?charset=utf8mb4'
exec(open('backend/store/init_auth.py').read())
"

# 7. 启动
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

#### macOS

```bash
# 1. 安装 Python
brew install python@3.11

# 2. 启动 MySQL 和 Milvus（用 Docker Desktop）
docker run -d --name kb-mysql \
  -e MYSQL_ROOT_PASSWORD=your_db_password \
  -e MYSQL_DATABASE=knowledge_base \
  -p 3306:3306 mysql:8.4

docker run -d --name kb-milvus \
  -p 19530:19530 -p 9091:9091 \
  milvusdb/milvus:v2.6.6 standalone

# 3. 克隆仓库
git clone https://github.com/你的用户名/yuanzy-kb.git
cd yuanzy-kb

# 4. 虚拟环境 + 依赖
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. 配置
cp .env.example .env
nano .env   # 填入配置

# 6. 初始化数据库（同上 Linux 步骤 6）

# 7. 启动
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

#### Windows

```powershell
# 1. 安装 Python 3.11
#    从 https://www.python.org/downloads/ 下载安装，勾选 "Add to PATH"

# 2. 启动 MySQL 和 Milvus（用 Docker Desktop）
docker run -d --name kb-mysql `
  -e MYSQL_ROOT_PASSWORD=your_db_password `
  -e MYSQL_DATABASE=knowledge_base `
  -p 3306:3306 mysql:8.4

docker run -d --name kb-milvus `
  -p 19530:19530 -p 9091:9091 `
  milvusdb/milvus:v2.6.6 standalone

# 3. 克隆仓库
git clone https://github.com/你的用户名/yuanzy-kb.git
cd yuanzy-kb

# 4. 虚拟环境 + 依赖
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

# 5. 配置
copy .env.example .env
notepad .env    # 填入配置

# 6. 初始化数据库
python -c "import os; os.environ['ADMIN_PW']='你的密码'; os.environ['MYSQL_URL']='mysql+pymysql://root:your_db_password@127.0.0.1:3306/knowledge_base?charset=utf8mb4'; exec(open('backend/store/init_auth.py').read())"

# 7. 启动
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## 环境变量参考

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `MODEL_API_KEY` | ✅ | — | LLM API Key |
| `JWT_SECRET` | ✅ | — | JWT 签名密钥 |
| `ADMIN_PASSWORD` | ✅ | — | 管理员初始密码 |
| `MODEL_API_BASE` | | `https://api.deepseek.com/v1` | LLM API 地址 |
| `LLM_MODEL` | | `deepseek-chat` | 对话模型名 |
| `EMBEDDING_MODEL` | | `text-embedding-3-small` | Embedding 模型名 |
| `EMBEDDING_BASE_URL` | | `https://api.openai.com/v1` | Embedding API 地址 |
| `EMBEDDING_API_KEY` | | 复用 `MODEL_API_KEY` | Embedding API Key |
| `EMBEDDING_DIM` | | `1536` | 向量维度 |
| `MYSQL_URL` | | Docker 内网地址 | MySQL 连接串 |
| `MILVUS_HOST` | | `milvus-standalone` | Milvus 地址 |
| `MILVUS_PORT` | | `19530` | Milvus 端口 |
| `ASR_ENGINE` | | `legacy` | ASR 引擎（`legacy` 或 `qwen`） |
| `IP_ACCESS_ENABLED` | | `false` | 是否开启 IP 白名单 |

详细环境变量说明见 [docs/环境变量参考.md](docs/环境变量参考.md)

## 修改管理员密码

如果忘记了管理员密码，可以通过 CLI 工具重置：

```bash
# Docker 方式
docker exec -it kb-app bash
export NEW_ADMIN_PW="新密码"
python -m backend.store.change_admin_password

# 源码方式
set NEW_ADMIN_PW=新密码 && python -m backend.store.change_admin_password  # Windows
NEW_ADMIN_PW="新密码" python -m backend.store.change_admin_password       # Linux/macOS
```

## 项目结构

```
├── backend/                # FastAPI 后端
│   ├── api/                # API 路由（15 个模块）
│   ├── core/               # 核心逻辑（LLM/Rerank/ASR/安全/限流）
│   ├── store/              # 数据层（MySQL + Milvus）
│   ├── ingest/             # 文档解析与入库
│   ├── retrieval/          # 检索链路
│   └── agent/              # Agentic RAG（LangGraph）
├── frontend/               # 单页前端（Vanilla JS）
│   ├── js/                 # 38 个 JS 模块
│   └── css/                # 样式
├── scripts/                # 工具脚本
├── tests/                  # 测试套件
├── docker/                 # Docker 启动脚本
├── docker-compose.yml      # 一键部署编排
├── Dockerfile              # 应用镜像
├── .env.example            # 环境变量模板
└── requirements.txt        # Python 依赖
```

## 常用命令

```bash
# Docker 方式
docker compose up -d           # 后台启动
docker compose logs -f app     # 查看应用日志
docker compose down            # 停止并删除容器
docker compose down -v         # 停止并删除容器+数据卷（⚠️ 清空数据）
docker compose up -d --build   # 重新构建并启动

# 源码方式
Ctrl+C                         # 停止
```

## 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI 0.115+ |
| 向量数据库 | Milvus 2.6 |
| 关系数据库 | MySQL 8.4 |
| LLM 客户端 | OpenAI SDK (兼容 DeepSeek/Qwen/OpenAI) |
| 鉴权 | JWT + bcrypt |
| 异步 | Uvicorn + httpx |
| 前端 | Vanilla JS (ES Modules) |

## License

[MIT](LICENSE)
