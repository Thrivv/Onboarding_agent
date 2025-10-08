# Base image with all dependencies pre-installed
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install ALL dependencies once
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install database service dependencies
RUN pip install --no-cache-dir \
    chromadb \
    sentence-transformers \
    qdrant-client \
    fastapi \
    uvicorn

# Install frontend dependencies if any
RUN pip install streamlit pandas plotly

# This base image is now ready with all dependencies