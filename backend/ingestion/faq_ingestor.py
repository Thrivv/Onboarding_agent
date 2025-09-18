# backend/ingestion/faq_ingestor.py

import os
from chromadb import PersistentClient
from sentence_transformers import SentenceTransformer

# Path to your local FAQ file
FAQ_FILE_PATH = r"D:\Thrivv.ai\onboarding-agent-101\backend\new_faq.txt"

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


# # backend/ingestion/faq_ingestor.py

# import os
# from chromadb import PersistentClient
# from sentence_transformers import SentenceTransformer

# # Absolute paths
# PROJECT_ROOT = r"D:\Thrivv.ai\onboarding-agent-101\backend"
# FAQ_FILE_PATH = os.path.join(PROJECT_ROOT, "new_faq.txt")
# CHROMA_DIR = os.path.join(PROJECT_ROOT, "chroma_store")
# COLLECTION_NAME = "faq"

# def load_faq_chunks(file_path: str, chunk_size=500) -> list[str]:
#     print(f"[INFO] Reading FAQ from: {file_path}")
#     with open(file_path, "r", encoding="utf-8") as f:
#         content = f.read()
    
#     # Split by questions (each starts with a number)
#     import re
#     questions = re.split(r'\n(?=\d+\.)', content.strip())
#     return [chunk.strip() for chunk in questions if chunk.strip()]

# def embed_and_store_faq():
#     try:
#         client = PersistentClient(path=CHROMA_DIR)
        
#         # Delete existing collection if it exists
#         try:
#             client.delete_collection(name=COLLECTION_NAME)
#             print(f"[INFO] Deleted existing collection: {COLLECTION_NAME}")
#         except:
#             pass
            
#         collection = client.create_collection(name=COLLECTION_NAME)
        
#         chunks = load_faq_chunks(FAQ_FILE_PATH)
#         print(f"[INFO] Loaded {len(chunks)} FAQ chunks")
        
#         # Show first chunk for verification
#         if chunks:
#             print(f"[INFO] First chunk preview: {chunks[0][:100]}...")
        
#         embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        
#         for i, chunk in enumerate(chunks):
#             embedding = embedding_model.encode(chunk).tolist()
#             collection.add(
#                 documents=[chunk],
#                 embeddings=[embedding],
#                 ids=[f"faq_chunk_{i}"]
#             )
#             print(f"[INFO] Added chunk {i+1}/{len(chunks)}")

#         print(f"[INFO] Successfully stored {len(chunks)} chunks in ChromaDB at: {CHROMA_DIR}")
        
#     except Exception as e:
#         print(f"[ERROR] Failed to ingest FAQ: {e}")

# if __name__ == "__main__":
#     embed_and_store_faq()