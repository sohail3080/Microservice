import json
import ssl
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from kafka_config import KafkaSettings


def create_ssl_context() -> ssl.SSLContext:
    """Create SSL context for Kafka connection."""
    ssl_context = ssl.create_default_context(
        purpose=ssl.Purpose.SERVER_AUTH,
        cafile=KafkaSettings.SSL_CAFILE
    )
    ssl_context.load_cert_chain(
        certfile=KafkaSettings.SSL_CERTFILE,
        keyfile=KafkaSettings.SSL_KEYFILE
    )
    return ssl_context


def create_kafka_producer() -> AIOKafkaProducer:
    """Create a Kafka producer with SSL configuration."""
    ssl_context = create_ssl_context()
    
    return AIOKafkaProducer(
        bootstrap_servers=KafkaSettings.BOOTSTRAP_SERVERS,
        security_protocol="SSL",
        ssl_context=ssl_context,  # Use ssl_context instead of individual SSL params
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )


def create_kafka_consumer(topic: str) -> AIOKafkaConsumer:
    """Create a Kafka consumer with SSL configuration."""
    ssl_context = create_ssl_context()
    
    return AIOKafkaConsumer(
        topic,
        bootstrap_servers=KafkaSettings.BOOTSTRAP_SERVERS,
        group_id=KafkaSettings.GROUP_ID,
        security_protocol="SSL",
        ssl_context=ssl_context,  # Use ssl_context instead of individual SSL params
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )