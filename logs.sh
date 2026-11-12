#!/bin/bash

if docker compose version &>/dev/null; then
    DC="docker compose"
else
    DC="docker-compose"
fi

echo "========================================"
echo " Thrivv Onboarding System - Logs"
echo "========================================"
echo

case "$1" in
    "")
        echo "Viewing all logs (app + reply-loop)..."
        echo "Press Ctrl+C to stop"
        echo
        $DC logs -f
        ;;
    app|backend|nginx)
        echo "Viewing app container logs (backend + nginx run together via supervisord)..."
        echo
        $DC logs -f app
        ;;
    reply|reply-loop)
        echo "Viewing reply-loop logs..."
        echo
        $DC logs -f reply-loop
        ;;
    *)
        echo "Unknown option: $1"
        echo
        echo "Usage: ./logs.sh [service]"
        echo
        echo "Available services:"
        echo "  app / backend / nginx  - Combined backend + nginx container"
        echo "                           (they run in one container via supervisord)"
        echo "  reply                  - Reply-loop email automation logs"
        echo "  (no arg)               - All logs"
        echo
        ;;
esac
