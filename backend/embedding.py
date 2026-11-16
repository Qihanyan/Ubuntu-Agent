import httpx

import settings


class EmbeddingClient:
    """调用 Ollama 的 /api/embed 接口生成 bge-m3 向量。bge-m3 不需要加查询前缀。"""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=30)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.post(
            "/api/embed", json={"model": settings.EMBED_MODEL, "input": texts}
        )
        resp.raise_for_status()
        embeddings = resp.json().get("embeddings") or []
        if len(embeddings) != len(texts):
            raise RuntimeError(f"embedding 数量不匹配：输入 {len(texts)} 条，返回 {len(embeddings)} 条")
        return embeddings

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]

    async def aclose(self) -> None:
        await self._client.aclose()
