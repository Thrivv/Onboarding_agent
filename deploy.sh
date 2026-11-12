#!/bin/bash

if docker compose version &>/dev/null; then
    DC="docker compose"
else
    DC="docker-compose"
fi

echo "========================================"
echo "  Thrivv Onboarding - AWS Deploy"
echo "========================================"
echo ""
echo "This will deploy the entire application on AWS"
echo ""
read -p "Press Enter to continue..."

echo ""
echo "[1/6] Stopping existing containers..."
$DC down 2>/dev/null || true
echo "      ✅ Stopped"

echo ""
echo "[2/6] Checking configuration..."
if [ ! -f .env.docker ]; then
    echo "      ❌ .env.docker not found in $(pwd)"
    echo "      Create/copy your environment file to .env.docker before deploying."
    exit 1
fi
echo "      ✅ .env.docker found"

echo ""
echo "[3/6] Creating directories..."
mkdir -p logs/backend logs/nginx logs/supervisor logs/reply-loop
mkdir -p backend/documents/sme backend/summary
mkdir -p ssl
chmod -R 755 logs
chmod -R 777 backend/documents backend/summary
echo "      ✅ Directories created"

# Guard: a stale `docker run -v .../backend/main.py:...` style bind mount makes
# the daemon create the missing host path as an EMPTY DIRECTORY — which is how
# backend/main.py, backend/config.py, backend/forensics and backend/extractors
# appeared as folders. rmdir only removes them when empty, so this can never
# touch real code. Silent if they don't exist (the normal case).
rmdir backend/main.py backend/config.py backend/forensics backend/extractors 2>/dev/null || true

echo ""
echo "[4/6] Building the image (no cache)..."
$DC build --no-cache
if [ $? -ne 0 ]; then
    echo "      ❌ Failed to build image"
    exit 1
fi
echo "      ✅ Image built"

echo ""
echo "[5/6] Starting all containers..."
$DC up -d
if [ $? -ne 0 ]; then
    echo "      ❌ Failed to start containers"
    exit 1
fi
echo "      ✅ All containers started"

echo ""
echo "[6/6] Waiting for services to initialize..."
sleep 30

echo ""
echo "Running health checks..."
APP_OK=false
BACKEND_OK=false
REPLY_OK=false

if curl -s http://localhost:9000/health > /dev/null 2>&1; then
    echo "✅ App (nginx+backend): HEALTHY"
    APP_OK=true
else
    echo "❌ App (nginx+backend): FAILED"
fi

if curl -s http://localhost:7000/health > /dev/null 2>&1; then
    echo "✅ Backend (direct):    HEALTHY"
    BACKEND_OK=true
else
    echo "⚠️  Backend (direct):    STARTING (check in 1 minute)"
fi

if docker ps | grep OnboardLG-reply-loop | grep -q "Up"; then
    echo "✅ Reply-Loop:          RUNNING"
    REPLY_OK=true
else
    echo "⚠️  Reply-Loop:          STARTING"
fi

PUBLIC_IP=$(curl -s --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null)
if [ -z "$PUBLIC_IP" ]; then PUBLIC_IP=$(curl -s --max-time 5 https://checkip.amazonaws.com 2>/dev/null | tr -d '[:space:]'); fi
if [ -z "$PUBLIC_IP" ]; then PUBLIC_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null); fi
if [ -z "$PUBLIC_IP" ]; then PUBLIC_IP="<YOUR_SERVER_IP>"; fi
PRIVATE_IP=$(curl -s --max-time 3 http://169.254.169.254/latest/meta-data/local-ipv4 2>/dev/null)
INSTANCE_ID=$(curl -s --max-time 3 http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null)

echo ""
echo "========================================"
echo "  Container Status"
echo "========================================"
$DC ps

echo ""
echo "========================================"
echo "  🎉 Deployment Complete!"
echo "========================================"
echo ""
echo "📍 Server Information:"
if [ ! -z "$INSTANCE_ID" ]; then
    echo "  Instance ID:  $INSTANCE_ID"
    echo "  Private IP:   $PRIVATE_IP"
fi
echo "  Public IP:    $PUBLIC_IP"
echo ""
echo "🌐 Access URLs:"
echo ""
echo "  App (frontend, share this):  http://$PUBLIC_IP:9000/onboarding/ai/"
echo "  API (via nginx):              http://$PUBLIC_IP:9000/onboarding/ai/api/"
echo "  API (direct):                 http://$PUBLIC_IP:7000"
echo "  API Docs (Swagger, direct):   http://$PUBLIC_IP:7000/docs"
echo ""
echo "📤 Share with team:"
echo "  http://$PUBLIC_IP:9000/onboarding/ai/"
echo ""
echo "========================================"
echo "  Useful Commands"
echo "========================================"
echo ""
echo "View logs:           ./logs.sh"
echo "View app logs:       ./logs.sh app"
echo "View reply logs:     ./logs.sh reply"
echo "Check status:        ./status.sh"
echo "Stop all:            ./stop.sh"
echo "Restart all:         $DC restart"
echo "Rebuild:             ./rebuild.sh"
echo ""
echo "========================================"
echo "  ⚠️  Security Reminder"
echo "========================================"
echo ""
echo "Ensure AWS Security Group allows:"
echo "  - Port 9000 (App: frontend + API via nginx) from 0.0.0.0/0"
echo "  - Port 7000 (Backend direct, optional)      from trusted IPs only"
echo "  - Port 22   (SSH)                            from your IP only"
echo ""
if [ "$APP_OK" = true ]; then
    echo "✅ Your application is ready!"
    echo "   Test now: http://$PUBLIC_IP:9000/onboarding/ai/"
else
    echo "⚠️  Services are starting..."
    echo "   Wait 2 minutes and run: ./status.sh"
fi
echo ""
echo "========================================"

cat > deployment-info.txt << EOF
Thrivv Onboarding - AWS Deployment
Deployed: $(date)

Instance Information:
$([ ! -z "$INSTANCE_ID" ] && echo "- Instance ID: $INSTANCE_ID")
$([ ! -z "$PRIVATE_IP" ] && echo "- Private IP:  $PRIVATE_IP")
- Public IP:   $PUBLIC_IP

Access URLs:
- App (frontend):             http://$PUBLIC_IP:9000/onboarding/ai/
- API (via nginx):             http://$PUBLIC_IP:9000/onboarding/ai/api/
- API (direct):                http://$PUBLIC_IP:7000
- API Docs (Swagger, direct):  http://$PUBLIC_IP:7000/docs

Service Health:
- App (nginx+backend): $([ "$APP_OK" = true ] && echo "✅ Healthy" || echo "⚠️  Starting")
- Backend (direct):    $([ "$BACKEND_OK" = true ] && echo "✅ Healthy" || echo "⚠️  Starting")
- Reply-Loop:          $([ "$REPLY_OK" = true ] && echo "✅ Running" || echo "⚠️  Starting")

Container Status:
$($DC ps)
EOF

echo "📄 Deployment info saved to: deployment-info.txt"
echo ""
