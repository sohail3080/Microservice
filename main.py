# ================================= IMPORTS =================================

import asyncio
import os
import uuid
from typing import List, Dict, Any
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from dotenv import load_dotenv

from kafka_factory import create_kafka_consumer
from kafka_config import KafkaSettings


# ================================= CONFIG =================================

load_dotenv()

# Constants
COLLECTION_NAME = "News"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_SIZE = 384

# Qdrant Configuration
QDRANT_URL = os.getenv("QdrantClientURL")
QDRANT_API_KEY = os.getenv("QdrantClientAPIKey")


# ================================= MODELS =================================

class ChunkData(BaseModel):
    text: str
    source_url: str
    doc_index: int
    chunk_size: int


class EmbedStoreRequest(BaseModel):
    chunks: List[ChunkData]


# ================================= SERVICES =================================

# Initialize Qdrant client
qdrant_client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
)

# Initialize embedding model
embedding_model = TextEmbedding(EMBEDDING_MODEL)


# ================================= UTILITIES =================================

async def ensure_collection_exists():
    """Create collection if it doesn't exist"""
    collections = qdrant_client.get_collections().collections
    collection_names = {c.name for c in collections}

    if COLLECTION_NAME not in collection_names:
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=EMBEDDING_SIZE,
                distance=Distance.COSINE,
            ),
        )
        print(f"Collection '{COLLECTION_NAME}' created successfully")
    else:
        print(f"Collection '{COLLECTION_NAME}' already exists")


def generate_embeddings(texts: List[str]):
    """Generate embeddings for a list of texts"""
    embeddings = embedding_model.embed(texts)
    return [emb.tolist() for emb in embeddings]


def create_points(chunks: List[ChunkData], embeddings: List[List[float]]):
    """Create Qdrant points from chunks and embeddings"""
    points = []
    
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "text": chunk.text,
                    "source_url": chunk.source_url,
                    "doc_index": chunk.doc_index,
                    "chunk_size": chunk.chunk_size,
                },
            )
        )
    
    return points


def process_chunk_from_kafka(chunk_payload: dict) -> None:
    """Embed and store a single chunk (from Kafka message) into Qdrant."""
    chunk = ChunkData(
        text=chunk_payload["text"],
        source_url=chunk_payload["source_url"],
        doc_index=chunk_payload["doc_index"],
        chunk_size=chunk_payload["chunk_size"],
    )
    texts = [chunk.text]
    embeddings = generate_embeddings(texts)
    points = create_points([chunk], embeddings)
    qdrant_client.upsert(
        collection_name=COLLECTION_NAME,
        points=points,
    )


async def run_kafka_consumer():
    """Consume chunks from Kafka ingest topic and embed/store in Qdrant."""
    if not KafkaSettings.BOOTSTRAP_SERVERS:
        print("Kafka not configured (KAFKA_BOOTSTRAP_SERVERS unset); skipping consumer.")
        return
    consumer = create_kafka_consumer(KafkaSettings.INGEST_TOPIC)
    await consumer.start()
    try:
        async for msg in consumer:
            try:
                process_chunk_from_kafka(msg.value)
                print(f"Embedded and stored chunk from {msg.value.get('source_url', '?')}")
            except Exception as e:
                print(f"Kafka chunk processing error: {e}")
    finally:
        await consumer.stop()


# ================================= LIFESPAN =================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure collection exists
    await ensure_collection_exists()
    print("Embedding Service started successfully")

    consumer_task = None
    if KafkaSettings.BOOTSTRAP_SERVERS:
        consumer_task = asyncio.create_task(run_kafka_consumer())
        print(f"Kafka consumer subscribed to {KafkaSettings.INGEST_TOPIC}")

    yield

    if consumer_task and not consumer_task.done():
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
    print("Embedding Service shutting down")


# ================================= APP =================================

app = FastAPI(
    title="Embedding Service",
    description="Microservice for generating embeddings and storing them in Qdrant",
    version="1.0.0",
    lifespan=lifespan,
)


# ================================= ENDPOINTS =================================

@app.get("/v1/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "embedding-service",
        "collection": COLLECTION_NAME,
        "embedding_model": EMBEDDING_MODEL,
    }


@app.post("/v1/api/embed-store")
async def embed_and_store(request: EmbedStoreRequest):
    """
    Generate embeddings for chunks and store them in Qdrant
    """
    try:
        # Extract text from chunks
        chunks = request.chunks
        texts = [chunk.text for chunk in chunks]
        
        if not texts:
            return {
                "status": "warning",
                "message": "No chunks to process",
                "chunks_processed": 0,
            }
        
        # Generate embeddings
        print(f"Generating embeddings for {len(texts)} chunks...")
        embeddings = generate_embeddings(texts)
        
        # Create Qdrant points
        points = create_points(chunks, embeddings)
        
        # Store in Qdrant
        print(f"Storing {len(points)} points in Qdrant...")
        operation_result = qdrant_client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
        )
        
        return {
            "status": "success",
            "message": "Successfully embedded and stored chunks",
            "chunks_processed": len(chunks),
            "points_stored": len(points),
            "qdrant_response": str(operation_result),
        }
        
    except Exception as e:
        print(f"Error in embed-store: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to embed and store chunks: {str(e)}"
        )


@app.get("/v1/api/collection-info")
async def get_collection_info():
    """Get information about the Qdrant collection"""
    try:
        collection_info = qdrant_client.get_collection(collection_name=COLLECTION_NAME)
        points_count = qdrant_client.count(collection_name=COLLECTION_NAME)
        
        return {
            "collection_name": COLLECTION_NAME,
            "status": "exists",
            "points_count": points_count.count,
            "vector_size": collection_info.config.params.vectors.size,
            "distance": str(collection_info.config.params.distance),
        }
    except Exception as e:
        return {
            "collection_name": COLLECTION_NAME,
            "status": "error",
            "error": str(e),
        }

