from __future__ import annotations

import json
import os

import asyncpg
import structlog
from openai import AsyncOpenAI

logger = structlog.get_logger(__name__)

_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIM = 1536

_DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS semantic_cache (
    id          BIGSERIAL PRIMARY KEY,
    prompt_hash TEXT NOT NULL,
    embedding   vector({_EMBEDDING_DIM}) NOT NULL,
    response    TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS semantic_cache_embedding_idx
    ON semantic_cache
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
"""


class SemanticCache:
    def __init__(self, pool: asyncpg.Pool, threshold: float = 0.95) -> None:
        self._pool = pool
        self._threshold = threshold
        self._openai = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    async def init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(_DDL)
        logger.info("semantic_cache_schema_ready")

    async def _embed(self, text: str) -> list[float]:
        response = await self._openai.embeddings.create(
            model=_EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding

    async def get(self, prompt: str) -> str | None:
        embedding = await self._embed(prompt)
        vector_literal = "[" + ",".join(str(v) for v in embedding) + "]"

        query = """
            SELECT response
            FROM semantic_cache
            WHERE 1 - (embedding <=> $1::vector) >= $2
            ORDER BY embedding <=> $1::vector
            LIMIT 1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, vector_literal, self._threshold)

        if row:
            logger.info("cache_hit", threshold=self._threshold)
            return row["response"]

        logger.info("cache_miss")
        return None

    async def set(self, prompt: str, response: str) -> None:
        embedding = await self._embed(prompt)
        vector_literal = "[" + ",".join(str(v) for v in embedding) + "]"

        import hashlib
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

        insert_sql = """
            INSERT INTO semantic_cache (prompt_hash, embedding, response)
            VALUES ($1, $2::vector, $3)
        """
        async with self._pool.acquire() as conn:
            await conn.execute(insert_sql, prompt_hash, vector_literal, response)

        logger.info("cache_stored", prompt_hash=prompt_hash)
