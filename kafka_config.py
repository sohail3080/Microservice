# ========================================= Kafka Configuration =========================================

import os
from dotenv import load_dotenv

load_dotenv()

class KafkaSettings:
    BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS")

    # SSL config
    SECURITY_PROTOCOL: str = os.getenv("KAFKA_SECURITY_PROTOCOL", "SSL")

    SSL_CAFILE: str | None = os.getenv("KAFKA_SSL_CAFILE")
    SSL_CERTFILE: str | None = os.getenv("KAFKA_SSL_CERTFILE")
    SSL_KEYFILE: str | None = os.getenv("KAFKA_SSL_KEYFILE")

    # Topics
    INGEST_TOPIC: str = os.getenv("KAFKA_INGEST_TOPIC", "ingest-topic")
    EMBED_TOPIC: str = os.getenv("KAFKA_EMBED_TOPIC", "embed-topic")

    GROUP_ID: str = os.getenv("KAFKA_GROUP_ID", "rag-group")