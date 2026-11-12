#!/bin/bash

# docker compose v2 (plugin) vs v1 (standalone) compatibility
if docker compose version &>/dev/null; then
    DC="docker compose"
else
    DC="docker-compose"
fi

echo "========================================"
echo " Thrivv Onboarding System - Starting"
echo "========================================"
echo

if ! command -v docker &> /dev/null; then
    echo "[ERROR] Docker is not installed"
    echo "Install it first: https://docs.docker.com/engine/install/"
    exit 1
fi

echo "[1/5] Checking Docker status..."
if ! docker info &> /dev/null; then
    echo "[ERROR] Docker daemon is not running or you lack permission"
    echo "Try: sudo systemctl start docker   (or: sudo usermod -aG docker \$USER && re-login)"
    exit 1
fi
echo "      Docker is running (using: $DC)"

echo
echo "[2/5] Checking configuration..."
if [ ! -f .env.docker ]; then
    echo "[ERROR] .env.docker not found in $(pwd)"
    echo "Create/copy your environment file to .env.docker before starting."
    exit 1
fi
echo "      .env.docker found"

echo
echo "[3/5] Creating directories..."
mkdir -p logs/backend logs/nginx logs/supervisor logs/reply-loop
mkdir -p backend/documents/sme backend/summary
mkdir -p ssl
chmod -R 755 logs
chmod -R 777 backend/documents backend/summary
echo "      Directories created"

# Guard: a stale `docker run -v .../backend/main.py:...` style bind mount makes
# the daemon create the missing host path as an EMPTY DIRECTORY — which is how
# backend/main.py, backend/config.py, backend/forensics and backend/extractors
# appeared as folders. rmdir only removes them when empty, so this can never
# touch real code. Silent if they don't exist (the normal case).
rmdir backend/main.py backend/config.py backend/forensics backend/extractors 2>/dev/null || true

echo
echo "[4/5] Building the image (app + reply-loop share one Dockerfile)..."
$DC build
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to build image"
    exit 1
fi
echo "      Build complete"

echo
echo "[5/5] Starting containers..."
$DC up -d
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to start containers"
    exit 1
fi

echo
echo "========================================"
echo " Thrivv Onboarding System - Started"
echo "========================================"
echo
echo "Services are starting up (this may take 30-60 seconds)..."
echo

PUBLIC_IP=$(curl -s --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null)
if [ -z "$PUBLIC_IP" ]; then PUBLIC_IP=$(curl -s --max-time 5 https://checkip.amazonaws.com 2>/dev/null | tr -d '[:space:]'); fi
if [ -z "$PUBLIC_IP" ]; then PUBLIC_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null); fi
if [ -z "$PUBLIC_IP" ]; then PUBLIC_IP="<YOUR_SERVER_IP>"; fi

echo "=========================================="
echo "🔗 ACCESS LINKS"
echo "=========================================="
echo
echo "🌐 App (frontend, share this):       http://$PUBLIC_IP:9000/onboarding/ai/"
echo "🔌 Backend API (via nginx):          http://$PUBLIC_IP:9000/onboarding/ai/api/"
echo "🔌 Backend Direct:                   http://$PUBLIC_IP:7000"
echo "📖 API Docs (Swagger, direct only):  http://$PUBLIC_IP:7000/docs"
echo "❤️  Health check:                     http://$PUBLIC_IP:9000/health"
echo
echo "Local (from this server):"
echo "  App:    http://localhost:9000/onboarding/ai/"
echo "  API:    http://localhost:9000/onboarding/ai/api/"
echo "  Direct: http://localhost:7000"
echo "  Docs:   http://localhost:7000/docs"
echo
echo "Useful commands:"
echo "  View logs:         ./logs.sh"
echo "  View app logs:     ./logs.sh app"
echo "  View reply logs:   ./logs.sh reply"
echo "  Check status:      ./status.sh"
echo "  Stop system:       ./stop.sh"
echo "  Rebuild:           ./rebuild.sh"
echo

echo "Checking service health..."
sleep 10

HEALTH_CHECKS=0
MAX_CHECKS=12

while [ $HEALTH_CHECKS -lt $MAX_CHECKS ]; do
    if curl -s http://localhost:9000/health &> /dev/null; then
        echo
        echo "[SUCCESS] App is healthy!"
        echo
        echo "🚀 App:      http://$PUBLIC_IP:9000/onboarding/ai/"
        echo "🔌 API:      http://$PUBLIC_IP:9000/onboarding/ai/api/"
        echo "🔌 Direct:   http://$PUBLIC_IP:7000"
        break
    fi
    HEALTH_CHECKS=$((HEALTH_CHECKS + 1))
    echo "Still starting... (attempt $HEALTH_CHECKS/$MAX_CHECKS)"
    sleep 10
done

if [ $HEALTH_CHECKS -eq $MAX_CHECKS ]; then
    echo
    echo "[WARNING] Services are taking longer than expected"
    echo "Run './status.sh' to check individual service status"
    echo "Run './logs.sh' to view logs"
fi

echo
