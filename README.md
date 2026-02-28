This project is a distributed, event-driven evolution of my earlier monolithic project linkmind. While [linkmind](https://github.com/sohail3080/linkmind) was a single FastAPI application that handled everything (ingestion, embedding, and query) in one codebase, this version separates those concerns into three independent microservices connected via Kafka.

# Links to different services: 

- [Embedding-microservice]https://github.com/sohail3080/linkmind-embedding-microservice.git
- [Ingestion-microservice] https://github.com/sohail3080/linkmind-ingestion-microservice.git
- [Query-microservice] https://github.com/sohail3080/linkmind-query-microservice.git