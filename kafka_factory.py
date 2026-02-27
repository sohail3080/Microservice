import json
import ssl
from aiokafka import AIOKafkaProducer
from kafka_config import KafkaSettings


def _get_ssl_context() -> ssl.SSLContext | None:
    """Create SSL context for Kafka when certs are configured."""
    if not KafkaSettings.SSL_CAFILE or not KafkaSettings.SSL_CERTFILE or not KafkaSettings.SSL_KEYFILE:
        return None
    ssl_context = ssl.create_default_context(
        purpose=ssl.Purpose.SERVER_AUTH,
        cafile=KafkaSettings.SSL_CAFILE,
    )
    ssl_context.load_cert_chain(
        certfile=KafkaSettings.SSL_CERTFILE,
        keyfile=KafkaSettings.SSL_KEYFILE,
    )
    return ssl_context


def create_kafka_producer() -> AIOKafkaProducer:
    """Create a Kafka producer (SSL if certs set, else PLAINTEXT)."""
    ssl_context = _get_ssl_context()
    if ssl_context is not None:
        return AIOKafkaProducer(
            bootstrap_servers=KafkaSettings.BOOTSTRAP_SERVERS,
            security_protocol="SSL",
            ssl_context=ssl_context,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    return AIOKafkaProducer(
        bootstrap_servers=KafkaSettings.BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
