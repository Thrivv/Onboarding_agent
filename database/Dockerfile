# # Use Python 3.11 slim as base
# FROM python:3.11-slim

# # Set working directory
# WORKDIR /app

# # Install system dependencies
# RUN apt-get update && apt-get install -y \
#     gcc \
#     curl \
#     && rm -rf /var/lib/apt/lists/*

# # Install Python dependencies for database services
# RUN pip install --no-cache-dir \
#     chromadb \
#     sentence-transformers \
#     qdrant-client \
#     fastapi \
#     uvicorn

# # Copy database scripts
# COPY database_service.py .
# COPY health_check.py .

# # Create directories for vector storage
# RUN mkdir -p /data/chroma /data/documents /data/backups

# # Expose ports
# EXPOSE 8002 8003

# # Health check
# HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
#     CMD python health_check.py

# # Start database services
# CMD ["python", "database_service.py"]

# Use the pre-built base image with all dependencies
FROM thrivv-base:latest

WORKDIR /app

# Copy database service files only
COPY database_service.py .
COPY health_check.py .

# Create directories for vector storage
RUN mkdir -p /data/chroma /data/documents /data/backups

# Expose ports
EXPOSE 8002 8003

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python health_check.py

# Start database services
CMD ["python", "database_service.py"]