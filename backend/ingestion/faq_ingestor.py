# backend/ingestion/faq_ingestor.py

import os
from chromadb import PersistentClient
from sentence_transformers import SentenceTransformer

# Path to your local FAQ file
FAQ_FILE_PATH = "/Users/satvik/Desktop/Onboarding 12 August/onboarding-agent-101/backend/faq.txt"

# ChromaDB setup
CHROMA_DIR = "chroma_store"
COLLECTION_NAME = "faq"

client = PersistentClient(path=CHROMA_DIR)
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

def load_faq_chunks(file_path: str, chunk_size=500) -> list[str]:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    return [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]

def embed_and_store_faq():
    chunks = load_faq_chunks(FAQ_FILE_PATH)

    print(f"[INFO] Loaded {len(chunks)} chunks.")

    collection = client.get_or_create_collection(name=COLLECTION_NAME)

    for i, chunk in enumerate(chunks):
        embedding = embedding_model.encode(chunk).tolist()
        collection.add(
            documents=[chunk],
            embeddings=[embedding],
            ids=[f"chunk_{i}"]
        )

    # Removed: client.persist()
    print("[INFO] FAQ embedding complete and saved.")

if __name__ == "__main__":
    embed_and_store_faq()
