# ============================================================
# Stage 1: Build React Frontend
# ============================================================
FROM node:18-alpine AS frontend-builder

WORKDIR /app

COPY frontend/package*.json ./
RUN npm install --silent

COPY frontend/ .

# Build-time API URL — nginx proxies /onboarding/ai/api/* to backend on localhost:7000
ARG REACT_APP_API_URL=/onboarding/ai/api
RUN echo "REACT_APP_API_URL=${REACT_APP_API_URL}" > .env
RUN npm run build

# ============================================================
# Stage 2: Combined Runtime Image
# ============================================================
FROM python:3.11-slim

# Install system deps + nginx + supervisor
RUN apt-get update && apt-get install -y \
    gcc g++ curl wget build-essential \
    libpq-dev libgl1 libglib2.0-0 libsm6 \
    libxext6 libxrender1 libgomp1 libfontconfig1 \
    libice6 libxau6 libxdmcp6 \
    nginx supervisor \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ──────────────────────────────────────
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Backend source ───────────────────────────────────────────
COPY backend/app            ./app

# ── Frontend build (static files) ───────────────────────────
COPY --from=frontend-builder /app/build /usr/share/nginx/html/onboarding/ai

# ── Nginx config ─────────────────────────────────────────────
COPY nginx-combined.conf /etc/nginx/nginx.conf

# ── Supervisord config ────────────────────────────────────────
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# ── Directories ──────────────────────────────────────────────
RUN mkdir -p /app/backend/documents/sme \
             /app/backend/summary \
             /app/external_documents \
             /var/log/backend \
             /var/log/nginx \
             /var/log/supervisor \
             /var/log/frontend && \
    chmod -R 777 /app/backend/documents /app/backend/summary /app/external_documents /var/log/frontend

# ── Environment ───────────────────────────────────────────────
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV DOCUMENTS_PATH=/app/backend/documents/sme
# Optional secondary/mirror save location — no-op if unset or unwritable.
ENV EXTERNAL_FILE_PATH=/app/external_documents

# Backend on 7000, Nginx (frontend + proxy) on 9000
EXPOSE 7000 9000

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
