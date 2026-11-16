"""
每个用户一个 Chroma collection：mem_<user_id>
每条记忆：
  document  = 归一化摘要（参与 embedding）
  metadata  = kind / user_text（用户原话，只存有语义的部分，不参与 embedding）/ created_at / updated_at
kind 分两种：preference（偏好）、episode（情景）
"""
import asyncio
import time
import uuid
from dataclasses import asdict, dataclass

import chromadb

import settings
from embedding import EmbeddingClient

KIND_PREFERENCE = "preference"
KIND_EPISODE = "episode"


@dataclass
class MemoryItem:
    id: str
    kind: str
    summary: str
    user_text: str
    created_at: float
    updated_at: float
    similarity: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _clip(text: str, limit: int) -> str:
    return text.strip()[:limit]


class MemoryStore:
    def __init__(self, embedder: EmbeddingClient) -> None:
        self._client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
        self._embedder = embedder
        self._collections: dict[str, chromadb.Collection] = {}

    # ------------------------------------------------------------------
    # collection 管理
    # ------------------------------------------------------------------
    def _collection(self, user_id: str):
        # user_id 必须来自服务端验证过的 token；这里再兜底检查一次
        if user_id not in settings.USERS:
            raise PermissionError(f"未知用户: {user_id}")
        col = self._collections.get(user_id)
        if col is None:
            col = self._client.get_or_create_collection(
                name=f"mem_{user_id}",
                # 不用 Chroma 默认的英文 embedding 模型，所有向量都由 bge-m3 显式传入
                embedding_function=None,
                metadata={"hnsw:space": "cosine"},
            )
            self._collections[user_id] = col
        return col

    @staticmethod
    def _to_items(result: dict, distances: list[float] | None = None) -> list[MemoryItem]:
        items = []
        for i, mid in enumerate(result["ids"]):
            meta = result["metadatas"][i] or {}
            items.append(
                MemoryItem(
                    id=mid,
                    kind=meta.get("kind", ""),
                    summary=result["documents"][i] or "",
                    user_text=meta.get("user_text", ""),
                    created_at=float(meta.get("created_at", 0)),
                    updated_at=float(meta.get("updated_at", 0)),
                    similarity=None if distances is None else 1.0 - distances[i],
                )
            )
        return items

    async def _get_one(self, user_id: str, memory_id: str) -> MemoryItem | None:
        col = self._collection(user_id)
        res = await asyncio.to_thread(col.get, ids=[memory_id], include=["documents", "metadatas"])
        items = self._to_items(res)
        return items[0] if items else None

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    async def list_preferences(self, user_id: str) -> list[MemoryItem]:
        col = self._collection(user_id)
        res = await asyncio.to_thread(
            col.get, where={"kind": KIND_PREFERENCE}, include=["documents", "metadatas"]
        )
        return sorted(self._to_items(res), key=lambda m: m.created_at)

    async def list_all(self, user_id: str) -> dict[str, list[MemoryItem]]:
        col = self._collection(user_id)
        res = await asyncio.to_thread(col.get, include=["documents", "metadatas"])
        items = sorted(self._to_items(res), key=lambda m: m.updated_at, reverse=True)
        return {
            "preferences": [m for m in items if m.kind == KIND_PREFERENCE],
            "episodes": [m for m in items if m.kind == KIND_EPISODE],
        }

    async def search_episodes(self, user_id: str, query: str) -> list[MemoryItem]:
        """相似度过阈值后，按 相似度 × 时间衰减 重排，取 top-k。"""
        col = self._collection(user_id)
        if await asyncio.to_thread(col.count) == 0:
            return []
        emb = await self._embedder.embed_one(query)
        res = await asyncio.to_thread(
            col.query,
            query_embeddings=[emb],
            n_results=settings.EPISODE_CANDIDATES,
            where={"kind": KIND_EPISODE},
            include=["documents", "metadatas", "distances"],
        )
        flat = {k: (res[k][0] if res.get(k) else []) for k in ("ids", "documents", "metadatas")}
        items = self._to_items(flat, distances=res["distances"][0] if res.get("distances") else [])

        now = time.time()
        w = settings.RECENCY_WEIGHT

        def score(m: MemoryItem) -> float:
            age_days = max(0.0, (now - m.created_at) / 86400)
            decay = 0.5 ** (age_days / settings.RECENCY_HALF_LIFE_DAYS)
            return (m.similarity or 0.0) * ((1 - w) + w * decay)

        passed = [m for m in items if (m.similarity or 0.0) >= settings.EPISODE_MIN_SIMILARITY]
        return sorted(passed, key=score, reverse=True)[: settings.EPISODE_TOP_K]

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    async def _add(self, user_id: str, kind: str, summary: str, user_text: str) -> str:
        col = self._collection(user_id)
        summary = _clip(summary, settings.MAX_SUMMARY_CHARS)
        emb = await self._embedder.embed_one(summary)
        now = time.time()
        prefix = "pref" if kind == KIND_PREFERENCE else "ep"
        memory_id = f"{prefix}-{uuid.uuid4().hex}"
        await asyncio.to_thread(
            col.add,
            ids=[memory_id],
            embeddings=[emb],
            documents=[summary],
            metadatas=[{
                "kind": kind,
                "user_text": _clip(user_text, settings.MAX_USER_TEXT_CHARS),
                "created_at": now,
                "updated_at": now,
            }],
        )
        return memory_id

    async def add_episode(self, user_id: str, summary: str, user_text: str) -> str:
        memory_id = await self._add(user_id, KIND_EPISODE, summary, user_text)
        await asyncio.to_thread(self._prune_episodes, user_id)
        return memory_id

    async def add_preference(self, user_id: str, text: str, user_text: str) -> str:
        return await self._add(user_id, KIND_PREFERENCE, text, user_text)

    async def update_preference(self, user_id: str, memory_id: str, text: str, user_text: str) -> bool:
        existing = await self._get_one(user_id, memory_id)
        if existing is None or existing.kind != KIND_PREFERENCE:
            return False
        text = _clip(text, settings.MAX_SUMMARY_CHARS)
        emb = await self._embedder.embed_one(text)
        col = self._collection(user_id)
        await asyncio.to_thread(
            col.update,
            ids=[memory_id],
            embeddings=[emb],
            documents=[text],
            metadatas=[{
                "kind": KIND_PREFERENCE,
                # 新证据没有原话时（例如来自功能性请求），保留旧的原话
                "user_text": _clip(user_text, settings.MAX_USER_TEXT_CHARS) or existing.user_text,
                "created_at": existing.created_at,
                "updated_at": time.time(),
            }],
        )
        return True

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------
    async def delete(self, user_id: str, memory_id: str) -> bool:
        if await self._get_one(user_id, memory_id) is None:
            return False
        col = self._collection(user_id)
        await asyncio.to_thread(col.delete, ids=[memory_id])
        return True

    async def delete_all(self, user_id: str) -> None:
        self._collection(user_id)  # 校验用户
        self._collections.pop(user_id, None)
        await asyncio.to_thread(self._client.delete_collection, name=f"mem_{user_id}")

    def _prune_episodes(self, user_id: str) -> None:
        """删除超过保留天数的情景记忆；超出条数上限时删最旧的。偏好不受影响。"""
        col = self._collection(user_id)
        res = col.get(where={"kind": KIND_EPISODE}, include=["metadatas"])
        entries = [(mid, float((meta or {}).get("created_at", 0))) for mid, meta in zip(res["ids"], res["metadatas"])]
        cutoff = time.time() - settings.EPISODE_MAX_AGE_DAYS * 86400
        expired = [mid for mid, ts in entries if ts < cutoff]
        alive = sorted([(mid, ts) for mid, ts in entries if ts >= cutoff], key=lambda x: x[1])
        overflow = [mid for mid, _ in alive[: max(0, len(alive) - settings.EPISODE_MAX_COUNT)]]
        to_delete = expired + overflow
        if to_delete:
            col.delete(ids=to_delete)
