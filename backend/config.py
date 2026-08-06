# backend/config.py
import os

# ── 模型服务(OpenAI 兼容,LLM 与 Embedding 共用同一 endpoint + key)──
MODEL_API_BASE = os.getenv("MODEL_API_BASE", "https://api.deepseek.com/v1")
MODEL_API_KEY  = os.getenv("MODEL_API_KEY",  "")                         # 必须通过环境变量设置，不可硬编码

LLM_MODEL       = os.getenv("LLM_MODEL",       "DeepSeek-V4-Flash-H800")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "Qwen3-Embedding-4B")
EMBEDDING_DIM   = 2560   # Qwen3-Embedding-4B 维度,建 Milvus collection 时对齐

MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530")

# ── 生成/打分 token 上限（防跑飞、省算力）──
LLM_ANSWER_MAX_TOKENS   = int(os.getenv("LLM_ANSWER_MAX_TOKENS",   "1024"))  # 问答回答上限

QUERY_REWRITE_MAX_TOKENS = int(os.getenv("QUERY_REWRITE_MAX_TOKENS", "256"))  # 检索改写上限
RERANK_MAX_TOKENS_CAP   = int(os.getenv("RERANK_MAX_TOKENS_CAP",   "2048"))  # rerank 打分硬上限（需覆盖 recall_k=50 的候选数）

# ── rerank 重试 ──
RERANK_MAX_RETRIES = int(os.getenv("RERANK_MAX_RETRIES", "2"))  # 失败后额外重试次数

# ── 安全过滤 ──
SAFETY_LLM_CHECK = os.getenv("SAFETY_LLM_CHECK", "false").lower() == "true"  # 词库未命中时是否再过一遍 LLM 审查；默认关以降低延迟
SAFETY_BLOCK_REPLY = "抱歉，我无法回应包含不当内容的请求。请换一个与知识库相关的问题。"

# MySQL（pymysql 同步驱动；charset=utf8mb4 支持中文）
MYSQL_URL = os.getenv("MYSQL_URL", "mysql+pymysql://user:CHANGE_ME@127.0.0.1:3306/knowledge_base?charset=utf8mb4")

# ── JWT 鉴权配置 ──
def _load_jwt_secret() -> str:
    import os, secrets
    from pathlib import Path
    env = os.getenv("JWT_SECRET")
    p = Path(__file__).resolve().parent / ".jwt_secret"
    # 1) 环境变量优先，读到后同时写入文件（容器重建后文件丢失时，只要 env 还在就能恢复）
    if env:
        _write_secret_file(p, env)
        return env
    # 2) 从文件读取（持久化恢复）
    if p.exists():
        return p.read_text().strip()
    # 3) 都不存在：自动生成（首次部署 / 文件丢失且未设置 env）
    import warnings
    warnings.warn(
        "JWT Secret 未配置，已自动生成。建议在生产环境设置 JWT_SECRET 环境变量，"
        "否则容器重建后所有用户 Token 将失效。",
        RuntimeWarning,
    )
    s = secrets.token_urlsafe(48)
    _write_secret_file(p, s)
    return s


def _write_secret_file(path, secret: str) -> None:
    """写入 secret 文件，仅当内容不同时更新（避免覆盖已有正确值）。"""
    from pathlib import Path as _Path
    p = _Path(path)
    existing = p.read_text().strip() if p.exists() else ""
    if existing == secret:
        return
    p.write_text(secret)
    try:
        p.chmod(0o600)
    except OSError:
        pass


JWT_SECRET = _load_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

# ── 查询增强 Feature Flags（默认开启，可通过环境变量关闭）──
ENHANCE_ENABLED           = os.getenv("ENHANCE_ENABLED",           "true").lower() == "true"
HYDE_ENABLED              = os.getenv("HYDE_ENABLED",              "true").lower() == "true"
MULTI_QUERY_ENABLED       = os.getenv("MULTI_QUERY_ENABLED",       "true").lower() == "true"
ENHANCE_CLASSIFIER_ENABLED = os.getenv("ENHANCE_CLASSIFIER_ENABLED", "true").lower() == "true"

# ── ASR 引擎选择 ──
ASR_ENGINE = os.getenv("ASR_ENGINE", "legacy")  # "legacy" 或 "qwen"
QWEN_ASR_BASE_URL = os.getenv("QWEN_ASR_BASE_URL", MODEL_API_BASE.rstrip("/v1"))
QWEN_ASR_API_KEY  = os.getenv("QWEN_ASR_API_KEY",  MODEL_API_KEY)
QWEN_ASR_MODEL    = os.getenv("QWEN_ASR_MODEL",    "Qwen3-ASR-1.7B")
QWEN_ASR_TIMEOUT  = int(os.getenv("QWEN_ASR_TIMEOUT", "120"))

# Qwen ASR 长音频切分配置
QWEN_ASR_FFMPEG_PATH      = os.getenv("QWEN_ASR_FFMPEG_PATH",      "ffmpeg")
QWEN_ASR_FFPROBE_PATH     = os.getenv("QWEN_ASR_FFPROBE_PATH",     "ffprobe")
QWEN_ASR_SPLIT_THRESHOLD  = int(os.getenv("QWEN_ASR_SPLIT_THRESHOLD",  "60"))
QWEN_ASR_MIN_SEGMENT      = int(os.getenv("QWEN_ASR_MIN_SEGMENT",      "15"))
QWEN_ASR_MAX_SEGMENT      = int(os.getenv("QWEN_ASR_MAX_SEGMENT",      "60"))
QWEN_ASR_SILENCE_DB       = os.getenv("QWEN_ASR_SILENCE_DB",          "-40")
QWEN_ASR_SILENCE_DURATION = float(os.getenv("QWEN_ASR_SILENCE_DURATION", "0.5"))
QWEN_ASR_MAX_CONCURRENT   = int(os.getenv("QWEN_ASR_MAX_CONCURRENT",   "3"))
