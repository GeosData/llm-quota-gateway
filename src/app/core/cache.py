from __future__ import annotations

import asyncio
import hashlib
import os

import asyncpg
import structlog
from fastembed import TextEmbedding

logger = structlog.get_logger(__name__)

_EMBEDDING_MODEL = os.environ.get(
    "CACHE_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
_EMBEDDING_DIM = 384

_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        cache_dir = os.environ.get("FASTEMBED_CACHE")
        _model = (
            TextEmbedding(_EMBEDDING_MODEL, cache_dir=cache_dir)
            if cache_dir
            else TextEmbedding(_EMBEDDING_MODEL)
        )
    return _model


def _embed_sync(text: str) -> list[float]:
    return next(iter(_get_model().embed([text]))).tolist()


_DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS semantic_cache (
    id          BIGSERIAL PRIMARY KEY,
    prompt_hash TEXT NOT NULL,
    embedding   vector({_EMBEDDING_DIM}) NOT NULL,
    response    TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS semantic_cache_tenant_idx ON semantic_cache (tenant_id);

CREATE INDEX IF NOT EXISTS semantic_cache_embedding_idx
    ON semantic_cache
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
"""


class SemanticCache:
    def __init__(self, pool: asyncpg.Pool, threshold: float = 0.95) -> None:
        self._pool = pool
        self._threshold = threshold

    async def init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(_DDL)
        logger.info("semantic_cache_schema_ready")

    async def _embed(self, text: str) -> list[float]:
        return await asyncio.to_thread(_embed_sync, text)

    async def get(self, prompt: str, tenant_id: str) -> str | None:
        embedding = await self._embed(prompt)
        vector_literal = "[" + ",".join(str(v) for v in embedding) + "]"

        query = """
            SELECT response
            FROM semantic_cache
            WHERE tenant_id = $3
              AND 1 - (embedding <=> $1::vector) >= $2
            ORDER BY embedding <=> $1::vector
            LIMIT 1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, vector_literal, self._threshold, tenant_id)

        if row:
            logger.info("cache_hit", threshold=self._threshold)
            return row["response"]

        logger.info("cache_miss")
        return None

    async def set(self, prompt: str, response: str, tenant_id: str) -> None:
        embedding = await self._embed(prompt)
        vector_literal = "[" + ",".join(str(v) for v in embedding) + "]"
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

        insert_sql = """
            INSERT INTO semantic_cache (prompt_hash, embedding, response, tenant_id)
            VALUES ($1, $2::vector, $3, $4)
        """
        async with self._pool.acquire() as conn:
            await conn.execute(insert_sql, prompt_hash, vector_literal, response, tenant_id)

        logger.info("cache_stored", prompt_hash=prompt_hash)
