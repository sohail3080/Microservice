# ================================= IMPORTS =================================

import os
from typing import List
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain_community.document_loaders import UnstructuredURLLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from contextlib import asynccontextmanager
from kafka_factory import create_kafka_producer
from kafka_config import KafkaSettings
import asyncio

# ================================= CONFIG =================================

load_dotenv()

EMBEDDING_SERVICE_URL = os.getenv("EMBEDDING_SERVICE_URL")
CHUNK_SIZE = 200
CHUNK_OVERLAP = 0

# ================================= MODELS =================================


class URLRequest(BaseModel):
    urls: List[str]


# ================================= APP =================================

producer = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global producer
    producer = create_kafka_producer()
    await producer.start()

    yield
    # Shutdown
    await producer.stop()


app = FastAPI(title="Ingestion Service", lifespan=lifespan)

# ================================= UTIL =================================


def chunk_documents(urls: List[str]):

    loader = UnstructuredURLLoader(
        urls=urls,
        mode="single",
        show_progress_bar=True,
        headers={"User-Agent": "Mozilla/5.0"},
        strategy="fast",
    )

    documents = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", " ", ".", ""],
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )

    processed_chunks = []

    for i, doc in enumerate(documents):
        chunks = splitter.split_text(doc.page_content)

        for chunk in chunks:
            processed_chunks.append(
                {
                    "text": chunk,
                    "source_url": urls[i],
                    "doc_index": i,
                    "chunk_size": len(chunk),
                }
            )

    return processed_chunks


# ================================= ENDPOINT =================================


@app.post("/v1/api/save-url")
async def save_urls(payload: URLRequest):

    try:
        chunks = chunk_documents(payload.urls)

        # Send chunks to Kafka
        for chunk in chunks:
            await producer.send_and_wait(KafkaSettings.INGEST_TOPIC, chunk)

        return {
            "status": "success",
            "total_chunks": len(chunks),
            "sent_to_topic": KafkaSettings.INGEST_TOPIC,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
