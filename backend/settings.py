"""
记忆与鉴权相关配置。
原有的 config.py（ONE_API_BASE_URL / ONE_API_KEY / N8N 等）保持不变，这里只放新增项。
"""
import os

# ==========================================
# 用户（硬编码，只存 bcrypt 哈希）
# ==========================================
# 生成哈希：python manage_users.py hash
# 用户名只能用小写字母、数字、下划线、连字符，3~32 位（会被用作 Chroma collection 名的一部分）
USERS: dict[str, str] = {
    # "marina": "$2b$12$..........................................................",
}

# ==========================================
# JWT
# ==========================================
# 生成密钥：python manage_users.py secret ，然后写入环境变量（systemd 的 Environment= 或 .env）
JWT_SECRET = os.environ.get("MUSIC_AGENT_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24 * 7

# ==========================================
# 登录与 WebSocket 鉴权
# ==========================================
LOGIN_MAX_ATTEMPTS = 5          # 同一 IP 在窗口期内最多失败次数
LOGIN_WINDOW_SECONDS = 300
WS_AUTH_TIMEOUT_SECONDS = 5     # 连接后多少秒内必须发来 auth 消息

# 允许的前端来源，逗号分隔，例如 "https://music.example.com"
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("MUSIC_AGENT_ALLOWED_ORIGINS", "").split(",") if o.strip()
]

# ==========================================
# Embedding（Ollama 上的 bge-m3）与向量库
# ==========================================
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
EMBED_MODEL = "bge-m3"
CHROMA_PATH = os.environ.get("CHROMA_PATH", "/home/storage/agent_memory/chroma")

# ==========================================
# 记忆策略
# ==========================================
SHORT_TERM_TURNS = 3            # 原样保留的最近轮数（按用户消息切分）

EPISODE_TOP_K = 3               # 每轮最多注入几条情景记忆
EPISODE_CANDIDATES = 10         # 先取多少候选，再按相似度 + 时间重排
EPISODE_MIN_SIMILARITY = 0.55   # 余弦相似度阈值，低于此值不注入（需要用真实数据调）
RECENCY_HALF_LIFE_DAYS = 30     # 时间衰减半衰期
RECENCY_WEIGHT = 0.15           # 时间因素在排序中的权重（0 = 只看相似度）

EPISODE_MAX_AGE_DAYS = 90       # 情景记忆最长保留天数
EPISODE_MAX_COUNT = 1000        # 每个用户情景记忆上限，超出删最旧的
# 偏好记忆：永久保留，直到用户删除或被新偏好覆盖

# 防止异常输入撑爆存储
MAX_SUMMARY_CHARS = 300
MAX_USER_TEXT_CHARS = 1000
