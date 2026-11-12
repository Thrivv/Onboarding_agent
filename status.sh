#!/bin/bash

if docker compose version &>/dev/null; then
    DC="docker compose"
else
    DC="docker-compose"
fi

echo "========================================"
echo " Thrivv Onboarding System - Status"
echo "========================================"
echo

echo "Container Status:"
echo "-----------------"
$DC ps

echo
echo "Health Checks:"
echo "--------------"

echo "Checking App / Nginx (port 9000)..."
if curl -s http://localhost:9000/health &> /dev/null; then
    echo "✅ App is healthy"
else
    echo "❌ App is not responding on port 9000"
fi

echo "Checking Backend (via nginx at /onboarding/ai/api/health)..."
if curl -s http://localhost:9000/onboarding/ai/api/health &> /dev/null; then
    echo "✅ Backend is healthy (via nginx)"
else
    echo "❌ Backend not reachable via nginx"
fi

echo "Checking Backend (direct port 7000)..."
if curl -s http://localhost:7000/health &> /dev/null; then
    echo "✅ Backend is healthy (direct port 7000)"
else
    echo "❌ Backend not reachable on port 7000"
fi

echo "Checking Frontend (served by nginx under /onboarding/ai/)..."
if curl -s http://localhost:9000/onboarding/ai/ &> /dev/null; then
    echo "✅ Frontend is healthy"
else
    echo "❌ Frontend not responding"
fi

echo "Checking Reply-Loop..."
if docker ps | grep OnboardLG-reply-loop | grep -q "Up"; then
    echo "✅ Reply-Loop is running"
else
    echo "❌ Reply-Loop is not running"
fi

PUBLIC_IP=$(curl -s --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null)
if [ -z "$PUBLIC_IP" ]; then PUBLIC_IP=$(curl -s --max-time 5 https://checkip.amazonaws.com 2>/dev/null | tr -d '[:space:]'); fi
if [ -z "$PUBLIC_IP" ]; then PUBLIC_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null); fi
if [ -z "$PUBLIC_IP" ]; then PUBLIC_IP="<YOUR_SERVER_IP>"; fi

echo
echo "Access URLs:"
echo "------------"
echo "🌐 App:          http://$PUBLIC_IP:9000/onboarding/ai/"
echo "🔌 API (nginx):  http://$PUBLIC_IP:9000/onboarding/ai/api/"
echo "🔌 API (direct): http://$PUBLIC_IP:7000"
echo "📖 API Docs:     http://$PUBLIC_IP:7000/docs"
echo
echo "Local:"
echo "  App:    http://localhost:9000/onboarding/ai/"
echo "  API:    http://localhost:9000/onboarding/ai/api/"
echo "  Docs:   http://localhost:7000/docs"
echo

read -p "Press Enter to continue..."
