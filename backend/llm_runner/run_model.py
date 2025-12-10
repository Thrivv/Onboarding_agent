# backend/llm_runner/run_model.py
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)


def call_local_llm(prompt: str) -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error generating response: {str(e)}"


"""
import requests
OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "meta-llama-3.1-8b-instruct-q6_k"
def call_local_llm(prompt: str) -> str:
    try:
        response = requests.post(
            OLLAMA_API_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False
            }
        )
        response.raise_for_status()
        return response.json()["response"].strip()
    except Exception as e:
        return f"Error generating response: {str(e)}"
"""
