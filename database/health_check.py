# database/health_check.py

import requests
import sys
import time


def check_database_health():
    """Check if database service is healthy"""
    try:
        # Check main database service
        response = requests.get("http://localhost:8002/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "healthy":
                print("[INFO] Database service is healthy")
                return True

        print(f"[ERROR] Database service unhealthy: {response.status_code}")
        return False

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Database health check failed: {e}")
        return False


if __name__ == "__main__":
    # Give service time to start
    time.sleep(2)

    if check_database_health():
        sys.exit(0)
    else:
        sys.exit(1)
