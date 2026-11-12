#!/bin/bash

if docker compose version &>/dev/null; then
    DC="docker compose"
else
    DC="docker-compose"
fi

echo "========================================"
echo " Thrivv Onboarding System - Rebuild"
echo "========================================"
echo
echo "This will stop all containers and rebuild the image from scratch"
echo
read -p "Press Enter to continue..."

echo
echo "[1/3] Stopping all containers..."
$DC down

# Guard: a stale `docker run -v .../backend/main.py:...` style bind mount makes
# the daemon create the missing host path as an EMPTY DIRECTORY — which is how
# backend/main.py, backend/config.py, backend/forensics and backend/extractors
# appeared as folders. rmdir only removes them when empty, so this can never
# touch real code. Silent if they don't exist (the normal case).
rmdir backend/main.py backend/config.py backend/forensics backend/extractors 2>/dev/null || true

echo
echo "[2/3] Rebuilding image (no cache)..."
$DC build --no-cache
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to rebuild image"
    read -p "Press Enter to exit..."
    exit 1
fi

echo
echo "[3/3] Starting services..."
$DC up -d
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to start services"
    read -p "Press Enter to exit..."
    exit 1
fi

echo
echo "========================================"
echo " Rebuild Complete!"
echo "========================================"
echo
PUBLIC_IP=$(curl -s --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null)
if [ -z "$PUBLIC_IP" ]; then PUBLIC_IP=$(curl -s --max-time 5 https://checkip.amazonaws.com 2>/dev/null | tr -d '[:space:]'); fi
if [ -z "$PUBLIC_IP" ]; then PUBLIC_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null); fi
if [ -z "$PUBLIC_IP" ]; then PUBLIC_IP="<YOUR_SERVER_IP>"; fi

echo "Services are starting up..."
echo
echo "🌐 App:          http://$PUBLIC_IP:9000/onboarding/ai/"
echo "🔌 API (nginx):  http://$PUBLIC_IP:9000/onboarding/ai/api/"
echo "🔌 API (direct): http://$PUBLIC_IP:7000"
echo "📖 API Docs:     http://$PUBLIC_IP:7000/docs"
echo
echo "Run './status.sh' to check health"
echo
read -p "Press Enter to continue..."
