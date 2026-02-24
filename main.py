# ================================= IMPORTS =================================

import os
from typing import List
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain_community.document_loaders import UnstructuredURLLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter


# ================================= CONFIG =================================

load_dotenv()

EMBEDDING_SERVICE_URL = os.getenv("EMBEDDING_SERVICE_URL")
CHUNK_SIZE = 200
CHUNK_OVERLAP = 0


# ================================= MODELS =================================

class URLRequest(BaseModel):
    urls: List[str]


# ================================= APP =================================

app = FastAPI(title="Ingestion Service")


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
            processed_chunks.append({
                "text": chunk,
                "source_url": urls[i],
                "doc_index": i,
                "chunk_size": len(chunk),
            })

    return processed_chunks


# ================================= ENDPOINT =================================

@app.post("/v1/api/ingest")
async def ingest_urls(payload: URLRequest):

    try:
        chunks = chunk_documents(payload.urls)

        # Send chunks to Embedding Service
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{EMBEDDING_SERVICE_URL}/v1/api/embed-store",
                json={"chunks": chunks},
                timeout=60.0,
            )

        response.raise_for_status()

        return {
            "status": "success",
            "total_chunks": len(chunks),
            "embedding_service_response": response.json()
        }

    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail="Embedding service failed")

    except Exception:
        raise HTTPException(status_code=400, detail="Failed to ingest URLs")