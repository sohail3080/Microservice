# ========================================= IMPORTS =========================================
import os
from typing import Literal
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

# ========================================= CONFIG =========================================
load_dotenv()

COLLECTION_NAME = "News"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_SIZE = 384
QUERY_LIMIT = 20
MAX_CONTEXT_CHARS = 4000
MAX_TOKENS = 300


# ========================================= REQUEST MODEL =========================================
class QueryRequest(BaseModel):
    query: str
    backend: Literal["custom"]
    model: str
    custom_url: str


# ========================================= SERVICES =========================================

# Qdrant connection (read-only service)
qdrant = QdrantClient(
    url=os.environ.get("QDRANT_URL"),
    api_key=os.environ.get("QDRANT_API_KEY"),
)

# Embedding model (local)
embedder = TextEmbedding(EMBEDDING_MODEL)


def build_context(results) -> str:
    texts = []

    for point in results.points:
        payload = point.payload
        if payload and "text" in payload:
            texts.append(payload["text"].strip())

    context = "\n\n".join(texts)
    return context[:MAX_CONTEXT_CHARS]


async def call_custom_llm(
    query: str,
    context: str,
    model: str,
    custom_url: str,
    api_key: str | None = None,
):
    system_prompt = f"""
You are a helpful assistant.
Answer the question using ONLY the provided context.
If partial information exists, mention it clearly.
If answer is incomplete, say so.
If no relevant information exists, say: "I don't know."

CONTEXT:
{context}
"""

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                custom_url,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": query},
                    ],
                    "max_tokens": MAX_TOKENS,
                },
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            )

            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail="LLM provider error",
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=500,
            detail="Failed to connect to LLM service",
        )


# ========================================= FASTAPI APP =========================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure collection exists (safe check)
    collections = qdrant.get_collections().collections
    if COLLECTION_NAME not in [c.name for c in collections]:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=EMBEDDING_SIZE,
                distance=Distance.COSINE,
            ),
        )
    yield


app = FastAPI(lifespan=lifespan)

BASE_URL = "/v1/query-service"


# ========================================= QUERY ENDPOINT =========================================


@app.post(f"{BASE_URL}/query")
async def query_news(payload: QueryRequest, api_key: str | None = Header(default=None)):
    if not payload.query:
        raise HTTPException(status_code=400, detail="Query is required")

    # 1️⃣ Embed query
    query_vector = next(iter(embedder.embed(payload.query)))

    # 2️⃣ Search Qdrant
    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        with_payload=True,
        limit=QUERY_LIMIT,
    )

    if not results.points:
        return {
            "answer": "I don't know.",
            "chunks_found": 0,
        }

    # 3️⃣ Build context
    context = build_context(results)

    # 4️⃣ Call LLM
    answer = await call_custom_llm(
        query=payload.query,
        context=context,
        model=payload.model,
        custom_url=payload.custom_url,
        api_key=api_key,
    )

    return {
        "query": payload.query,
        "answer": answer,
        "chunks_found": len(results.points),
    }
