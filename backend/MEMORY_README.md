# Music Agent：登录 + 向量记忆

## 文件说明

| 文件 | 作用 | 状态 |
|---|---|---|
| `main.py` | 替换原 main.py：登录、WebSocket 鉴权、短期上下文、记忆注入、记忆接口 | 改写 |
| `settings.py` | 用户、JWT、Ollama、Chroma、记忆策略参数 | 新增 |
| `auth.py` | 密码校验、JWT、登录限流 | 新增 |
| `embedding.py` | 调用 Ollama 的 bge-m3 | 新增 |
| `memory_store.py` | Chroma 存储，每用户一个 collection | 新增 |
| `memory_extractor.py` | 每轮结束后用 LLM 提取记忆 | 新增 |
| `manage_users.py` | 生成密码哈希、JWT 密钥 | 新增 |
| `deploy/` | Ollama 的 docker-compose、Nginx 配置片段 | 新增 |

`config.py` 和 `tools/` 不需要改动。

## 部署步骤

1. 安装依赖：`pip install -r requirements-memory.txt`
2. 启动 Ollama 并拉取模型：
   ```bash
   docker compose -f deploy/docker-compose.ollama.yml up -d
   docker exec ollama ollama pull bge-m3
   ```
3. 测一下 embedding 速度：
   ```bash
   time curl -s http://127.0.0.1:11434/api/embed -d '{"model":"bge-m3","input":["最近在准备考试，压力有点大"]}' | head -c 100
   ```
   第二次调用的耗时才是常态（第一次包含模型加载）。
4. 生成 JWT 密钥，写入环境变量 `MUSIC_AGENT_JWT_SECRET`（systemd 的 `Environment=` 或 `EnvironmentFile=`）：
   ```bash
   python manage_users.py secret
   ```
5. 为每个用户生成密码哈希，粘贴到 `settings.py` 的 `USERS`：
   ```bash
   python manage_users.py hash
   ```
6. 设置 `MUSIC_AGENT_ALLOWED_ORIGINS`（前端域名，逗号分隔）。
7. 把 `deploy/nginx-music-agent.conf` 加进 Nginx 的 443 server 块，配好证书。
8. 确认公网只能访问 Nginx：n8n（5678）、one-api（7086）、Ollama（11434）、uvicorn（8000）都不能从外网访问。可以在外网机器上用 `nc -zv <公网IP> 5678` 逐个检查。

注意：main.py 现在只监听 `127.0.0.1`。如果 Nginx 跑在 Docker 容器里，需要相应调整监听地址和 `forwarded_allow_ips`。
同时只能运行一个 uvicorn worker（Chroma 嵌入式模式 + 内存版限流的限制）。

## 前端需要改的地方

> 第 1–3 条已在 `frontend/src/App.jsx` 中实现（登录页、WS 首条 auth 消息、4401 跳回登录、`error` 消息）。第 4 条记忆页面尚未做。

1. **登录**：`POST /api/login`，body `{"username": "...", "password": "..."}`，返回 `{"token": "...", "username": "..."}`。
2. **WebSocket**：连接 `wss://<域名>/ws/chat` 后，**第一条消息**发送：
   ```json
   {"type": "auth", "token": "<token>"}
   ```
   收到 `{"type": "auth_ok"}` 后才能发聊天消息（聊天消息仍然是纯文本）。
   鉴权失败时服务端以关闭码 `4401` 断开，前端应跳转回登录页。
3. **新的消息类型**：除原有的 `status`、`message` 外，新增 `error`（本轮处理失败）。
4. **记忆页面**（请求头 `Authorization: Bearer <token>`）：
   - `GET /api/memories` → `{"preferences": [...], "episodes": [...]}`，每条含 `id`、`summary`、`user_text`、`created_at`、`updated_at`
   - `DELETE /api/memories/{id}` → 删除单条
   - `DELETE /api/memories` → 删除全部

## 需求对照

| # | 需求 | 实现位置 |
|---|---|---|
| 1 | 硬编码用户、bcrypt 哈希、JWT 密钥在环境变量 | `settings.USERS`、`auth.py`；启动时 `validate_config` 检查 |
| 2 | HTTP 登录换 JWT | `POST /api/login` |
| 3 | WebSocket 第一条消息鉴权，5 秒超时 | `authenticate_ws` |
| 4–5 | HTTPS/WSS，只暴露一个入口 | `deploy/nginx-music-agent.conf`；uvicorn 只监听本机 |
| 6 | CORS 收紧、登录限流 | `CORSMiddleware`、`LoginRateLimiter` |
| 7 | 每用户一个 collection，user_id 只来自 token | `MemoryStore._collection` |
| 8 | 音乐库不变 | `tools/` 未改动 |
| 9–10 | 功能性操作、寒暄、AI 回复不存；存偏好和有语义的情景 | `EXTRACTOR_PROMPT` |
| 11 | 摘要做 embedding，原话存 metadata | `MemoryStore._add` |
| 12 | 判断时看全轮，功能性请求中的偏好也提取 | `_render_turn`、`EXTRACTOR_PROMPT` |
| 13 | 回复发出后同步写入 | `websocket_chat` 中 `extractor.process_turn` |
| 14–16 | 偏好常驻、情景 top-3 + 阈值、注入时说明非指令 | `load_memory_block`、`build_memory_block` |
| 17–20 | 最近 3 轮按用户消息切分、各端独立、重启丢失 | `turns` deque |
| 21–23 | bge-m3、不用 Chroma 默认 embedding | `embedding.py`、`embedding_function=None` |
| 24 | 查看、删除自己的记忆 | `/api/memories` 系列接口 |
| 25–26 | 偏好永久；情景 90 天 / 1000 条，检索加时间衰减 | `_prune_episodes`、`search_episodes` |

## 需要用真实数据调的参数

- `EPISODE_MIN_SIMILARITY = 0.55`：这是起始值。积累一些记忆后，看日志里实际检索到的相似度分布再调整。
- 偏好提取的措辞强度（`EXTRACTOR_PROMPT` 中"只下载过一次 → 对X感兴趣"这一段）：如果觉得偏好太容易被提取，或者太保守，改这里。

## 其他改动

- 修了一个原有的潜在 bug：如果模型在总结回复时又请求调用工具，原代码会把没有对应 `ToolMessage` 的 `tool_calls` 留在历史里，导致下一轮 API 报错。现在会丢弃这次请求并给出兜底回复。
- 单轮处理出错时连接不再中断，残缺的一轮也不会进入历史。
- 记忆服务（Ollama 或 Chroma）出错时自动降级为无记忆聊天，不影响正常使用。
