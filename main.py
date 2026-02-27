# ========================================= IMPORTS =========================================
import os
from typing import Literal
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from fastapi import Request

from kafka_factory import create_kafka_producer
from kafka_config import KafkaSettings


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
    custom_url: str | None = None


# ========================================= SERVICES =========================================

# Kafka producer (optional; used for query events when KAFKA_BOOTSTRAP_SERVERS is set)
kafka_producer = None

# Qdrant connection (read-only service)
qdrant = QdrantClient(
    url=os.environ.get("QdrantClientURL"),
    api_key=os.environ.get("QdrantClientAPIKey"),
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
    global kafka_producer
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
    if KafkaSettings.BOOTSTRAP_SERVERS:
        kafka_producer = create_kafka_producer()
        await kafka_producer.start()
    yield
    if kafka_producer:
        await kafka_producer.stop()
        kafka_producer = None


app = FastAPI(lifespan=lifespan)

# ========================================= QUERY ENDPOINT =========================================


@app.post(f"/v1/api/query")
async def query_news(payload: QueryRequest, request: Request):
    try:
        if payload.query:
            query_text = payload.query
            query_backend = payload.backend
            query_model = payload.model
            query_apikey = request._headers.get("api_key")
            query_custom_url = payload.custom_url

            # 1️⃣ Embed query
            query_vector = next(iter(embedder.embed(query_text)))

            # 2️⃣ Search Qdrant
            results = qdrant.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                with_payload=True,
                limit=QUERY_LIMIT,
            )

            # Handle custom backend only 
            if query_backend == "custom":
                context = build_context(results)

                answer = await call_custom_llm(
                    query=query_text,
                    context=context,
                    model=query_model,
                    custom_url=query_custom_url,
                    api_key=query_apikey,
                )

                if kafka_producer:
                    print("Kafka producer is available")
                else:
                    print("Kafka producer is not available")

                # Publish query event to Kafka when producer is available
                if kafka_producer:
                    try:
                        event = {
                            "query": query_text,
                            "model": query_model,
                            "backend": query_backend,
                            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        }
                        test = await kafka_producer.send_and_wait(
                            KafkaSettings.QUERY_EVENTS_TOPIC,
                            value=event,
                        )
                        print("Kafka publish successful:", test)
                    except Exception:
                        # pass  # Don't fail the request if Kafka publish fails
                        print("Kafka publish failed:", str(e))

                return {
                    "status": "query received",
                    "query": query_text,
                    "result": answer,
                    "chunks": results,
                }

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Failed to fetch data",
        )
