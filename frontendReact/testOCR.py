import os
import argparse
from dotenv import load_dotenv
from pathlib import Path
import requests
import base64

# Load env variables from .env if present
load_dotenv()

# Pull values from environment
LLAMA_API_KEY = os.getenv("LLAMA_API_KEY")
LLAMA_API_URL = os.getenv("LLAMA_API_URL")
LLAMA_MODEL_NAME = os.getenv("LLAMA_MODEL_NAME", "llama-ocr-model")  # default fallback


def encode_image(image_path: str) -> str:
    """Convert image file to base64 string."""
    with open(image_path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("utf-8")


def run_ocr(image_path: str, model_name: str = LLAMA_MODEL_NAME) -> str:
    """Send image to OCR model and return extracted text."""
    image_url = encode_image(image_path)

    prompt = "You are an OCR system. Perform OCR on the provided image."

    headers = {
        "Authorization": f"Bearer {LLAMA_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "OCR Extraction"
    }

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ],
        "max_tokens": 1500,
        "temperature": 0.1
    }

    response = requests.post(LLAMA_API_URL, headers=headers, json=payload)
    if response.status_code == 200:
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
    else:
        raise RuntimeError(f"OCR failed: {response.status_code} {response.text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test OCR with LLaMA API")
    parser.add_argument("--image", required=True, help="Path to the image file for OCR")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    print(f"Running OCR on {image_path} with model {LLAMA_MODEL_NAME}...")
    try:
        text = run_ocr(str(image_path))
        print("\n=== OCR Result ===")
        print(text)
    except Exception as e:
        print(f"Error: {e}")

