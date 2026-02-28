# RAG-Powered News Q&A — Microservices (Ingestion, Embedding, Query) 

Backend for saving news URLs and querying them with AI-powered search. Built as **three microservices** communicating via **Kafka** (Aiven free tier) and sharing a **Qdrant** vector store.

---

## Project Context

This project is a distributed, event-driven evolution of my earlier monolithic project linkmind. While [linkmind](https://github.com/sohail3080/linkmind) was a single FastAPI application that handled everything (ingestion, embedding, and query) in one codebase, this version separates those concerns into three independent microservices connected via Kafka.

The transformation from monolith to microservices was a deliberate learning exercise to understand:

- Event-driven architectures
- Message queues (Kafka) as a backbone
- Service decoupling and fault tolerance
- Real-world distributed system patterns

---

## Architecture Overview

```
┌─────────────┐     POST /save-url     ┌──────────────┐     chunks      ┌─────────────┐     consume     ┌──────────────┐
│   Client    │───────────────────────►│  Ingestion   │────────────────►│   Kafka     │◄────────────────│  Embedding   │
└─────────────┘                        │   Service    │   ingest-topic  │  (Aiven)    │   ingest-topic  │   Service    │
       │                               └──────────────┘                 └─────────────┘                 └──────┬───────┘
       │                                                                                         embed & store │
       │                                                                                                       │
       │ POST /query                  ┌──────────────┐     query       ┌─────────────┐                         ▼
       └─────────────────────────────►│    Query     │────────────────►│   Kafka     │────────────────►┌──────────────┐
                                      │   Service    │  query-events   │             │                 │   Qdrant     │
                                      └──────┬───────┘                 └─────────────┘                 │  (vectors)   │
                                             │ search & LLM                                            │              │
                                             └────────────────────────────────────────────────────────►└──────────────┘
```

- **Ingestion**: Scrapes URLs, chunks text, publishes chunks to Kafka `ingest-topic`.
- **Embedding**: Consumes from `ingest-topic`, generates embeddings, stores in Qdrant.
- **Query**: Embeds the user query, searches Qdrant, calls your custom LLM with context, returns the answer; optionally publishes query events to Kafka `query-events`.

---

## General Setup Flow

### 1. Get Kafka (Aiven — Free Tier)

This project uses **Aiven for Kafka** because it offers a free tier.

1. Sign up at [Aiven](https://aiven.io/).
2. Create a **Kafka** service (choose a cloud/region; free plan available).
3. In the Aiven console, download:
   - **CA certificate** → save as `ca.pem`
   - **Access key** and **Access certificate** → save as `service.key` and `service.cert`
4. Note the **Service URI** (e.g. `your-service.kafka.region.aivencloud.com:12345`) — this is your `KAFKA_BOOTSTRAP_SERVERS`.
5. Create two topics (or use defaults):
   - `ingest-topic` — for chunks from Ingestion → Embedding
   - `query-events` — optional, for query analytics from Query service

Place `ca.pem`, `service.cert`, and `service.key` in each service folder that uses Kafka (Ingestion, Embedding, Query), or set `KAFKA_SSL_CAFILE`, `KAFKA_SSL_CERTFILE`, `KAFKA_SSL_KEYFILE` to their paths.

### 2. Get Qdrant

- Use [Qdrant Cloud](https://qdrant.tech/documentation/cloud-quickstart/) or self-hosted Qdrant.
- Note **URL** and **API key** → `QdrantClientURL`, `QdrantClientAPIKey`.

### 3. Environment Variables (Per Service)

Each service has its own `.env`. Copy from `.env.example` in each folder and fill in values.

| Service    | Key env vars |
|-----------|---------------|
| **Ingestion** | `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_SSL_CAFILE`, `KAFKA_SSL_CERTFILE`, `KAFKA_SSL_KEYFILE`, `KAFKA_INGEST_TOPIC` |
| **Embedding** | `QdrantClientURL`, `QdrantClientAPIKey`, same Kafka vars, `KAFKA_INGEST_TOPIC`, `KAFKA_GROUP_ID_EMBEDDING` |
| **Query**     | `QdrantClientURL`, `QdrantClientAPIKey`, optional Kafka vars for query-events, `KAFKA_QUERY_EVENTS_TOPIC` |

### 4. Run the Three Services

Use three terminals. Recommended order: **Embedding** (consumer) → **Ingestion** (producer) → **Query**.


```bash
# In the three terminals:
# create a venv
# install the required packages listed in requirements.txt
# python -m pip install -r requirements.txt
# Copy the file named .env.example and rename the copy to .env
# Open the .env file and fill in the required values
# Start the services on different ports

# Terminal 1 — Embedding (consumes from Kafka, writes to Qdrant)
cd embedding
uvicorn main:app --reload --port 8001

# Terminal 2 — Ingestion (produces chunks to Kafka)
cd ingestion
uvicorn main:app --reload --port 8000

# Terminal 3 — Query (reads Qdrant, calls LLM)
cd query
uvicorn main:app --reload --port 8002
```

Adjust ports if needed. Ensure Embedding is running so it can consume chunks as soon as Ingestion publishes.

---

## Routes Summary

| Service    | Route                 | Method | Use |
|-----------|------------------------|--------|-----|
| Ingestion | `/v1/api/save-url`     | POST   | Ingest news URLs; content is scraped, chunked, and sent to Kafka. Embedding service consumes and stores in Qdrant. |
| Embedding | `/v1/api/health`       | GET    | Health check. |
| Embedding | `/v1/api/embed-store`  | POST   | Direct embed-and-store chunks (bypasses Kafka). |
| Embedding | `/v1/api/collection-info` | GET | Collection name and point count. |
| Query     | `/v1/api/query`        | POST   | Search stored news and (with `backend: "custom"`) get an AI answer from your LLM. |

---

## Payloads

### POST `/v1/api/save-url` (Ingestion)

```json
{
  "urls": [
    "https://example.com/article1",
    "https://example.com/article2"
  ]
}
```

### POST `/v1/api/query` (Query)

**Headers**

```
api_key: YOUR_API_KEY
```

**Body**

```json
{
  "query": "Your question",
  "backend": "custom",
  "model": "your-model-id",
  "custom_url": "https://your-llm-api/completions"
}
```

---

## Custom LLM / OpenRouter

The Query service supports only **custom** LLM endpoints. Your LLM must accept:

**Request (sent by Query service):**

```json
{
  "model": "your-model-id",
  "messages": [
    { "role": "system", "content": "System instructions with retrieved context" },
    { "role": "user", "content": "User query" }
  ],
  "max_tokens": 300
}
```

**Headers:** `Authorization: Bearer YOUR_API_KEY`, `Content-Type: application/json`.

The response is forwarded as-is (no strict schema). For a **free test endpoint**, use [OpenRouter](https://openrouter.ai): create an API key, use `https://openrouter.ai/api/v1/chat/completions` as `custom_url`, and pass your OpenRouter key in the `api_key` header.

---

## Environment Variables (Summary)

- **Qdrant:** `QdrantClientURL`, `QdrantClientAPIKey` (Embedding, Query).
- **Kafka (Aiven):** `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_SECURITY_PROTOCOL=SSL`, `KAFKA_SSL_CAFILE`, `KAFKA_SSL_CERTFILE`, `KAFKA_SSL_KEYFILE`.
- **Topics:** `KAFKA_INGEST_TOPIC` (default `ingest-topic`), `KAFKA_QUERY_EVENTS_TOPIC` (default `query-events`), `KAFKA_GROUP_ID_EMBEDDING` (Embedding consumer group).

See each service’s `.env.example` for the full list.

---

## Architectural Notes

1. **RAG (Retrieval-Augmented Generation)** with vector search in Qdrant.
2. **Async pipeline:** URL → scrape → chunk → Kafka → embed → Qdrant; query → embed → search → LLM.
3. **Kafka** decouples Ingestion from Embedding; Aiven free tier is used for Kafka hosting.
4. **Stateless FastAPI** services; Qdrant and Kafka are the shared state/transport.

---

## Limitations

- **LLM:** Only `backend: "custom"` is supported; no built-in OpenAI/Claude.
- **Chunking:** Small chunk size (e.g. 200 chars), no overlap in Ingestion by default; retrieval limit and context length are fixed in Query.
- **Duplicates:** Re-ingesting the same URLs can create duplicate vectors; no deduplication.
- **Kafka optional for Query:** If Kafka is not configured in Query, it still works but does not publish query events.

---

## Sources

- [Aiven for Kafka](https://aiven.io/kafka)
- [Qdrant Cloud Quickstart](https://qdrant.tech/documentation/cloud-quickstart/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [OpenRouter](https://openrouter.ai) (free LLM endpoint for testing)

---

# Personal Learning & Key Takeaway:

While building a distributed version of my [linkmind](https://github.com/sohail3080/linkmind) project, I had a moment that perfectly illustrated the power of event-driven architecture.

I had just finished splitting the original monolithic application into three microservices:
- **Ingestion Service:** Receives articles and publishes them to Kafka.
- **Embedding Service:** Consumes articles from Kafka, generates embeddings, and stores them in Qdrant.
- **Query Service:** Reads from Qdrant to answer user questions.

### The Experiment (That Accidentally Went Wrong)

During local testing, I mistakenly started only the Ingestion and Query services. The Embedding service remained offline.

I ingested several news articles through the Ingestion service. No errors were thrown, and the process appeared successful. However, when I queried the system for information related to those articles, I received no results.

Initially, I was confused. Was my system broken?

Then I noticed the Embedding service was still stopped.

### The "Oh" Moment

I restarted the Embedding service. Almost immediately, it began processing messages. The chunks that were stuck in the queue were now being embedded and inserted into the vector database.

After a few moments, I queried the system again. This time, it worked perfectly. It was answering questions about the articles I had ingested *before* the Embedding service was even running.

**And the best part? I did not have to re-ingest a single article.**

### The Key Takeaways

It was a simple setup, but it clearly demonstrated why event-driven systems are resilient to partial failures

- **Fault Tolerance & Resilience:** A failure in one service (Embedding) did not bring down the entire system. The Ingestion and Query services remained operational.
- **Loose Coupling:** Services communicated through Kafka, not direct API calls. This decoupling meant the Ingestion service didn't need to know anything about the status or location of the Embedding service.
- **Data Durability & Asynchronous Processing:** Kafka acted as a shock absorber and a persistent buffer. It held onto the messages safely until the Embedding service was ready to consume them. No data was lost.
- **No Manual Recovery:** The system automatically recovered from a partial failure. Once the Embedding service was back online, it caught up on its backlog without any manual intervention or data replay.

In a monolithic system, if the embedding logic failed, the entire ingestion and query flow would have likely come to a halt. This small experiment clearly demonstrated the real advantage of event-driven microservices and message queues. Even though this is just a learning project and not production-ready, it gave me practical insight into how distributed systems handle partial failures and recover gracefully.

---

**Note:** This is a learning project to understand Kafka and microservices. Not intended for production as-is. This project actually is based on a another learning project I did, [linkmind](https://github.com/sohail3080/linkmind). Feedback and issues are welcome.
