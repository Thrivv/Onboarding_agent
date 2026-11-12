#!/bin/bash

if docker compose version &>/dev/null; then
    DC="docker compose"
else
    DC="docker-compose"
fi

echo "========================================"
echo " Thrivv Onboarding System - Stopping"
echo "========================================"
echo

echo "Stopping all containers..."
$DC down

if [ $? -eq 0 ]; then
    echo
    echo "========================================"
    echo " Thrivv Onboarding System - Stopped"
    echo "========================================"
    echo
    echo "All services have been stopped successfully."
    echo
    echo "To start again, run: ./start.sh"
else
    echo
    echo "[ERROR] Failed to stop some containers"
    echo "Check with: docker ps -a"
fi

echo
read -p "Press Enter to continue..."
