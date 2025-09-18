# backend/ingestion/faq_retriever.py

from chromadb import PersistentClient
from sentence_transformers import SentenceTransformer

CHROMA_DIR = "chroma_store"
COLLECTION_NAME = "faq"

# Load persistent ChromaDB client
client = PersistentClient(path=CHROMA_DIR)

# Get collection
collection = client.get_or_create_collection(name=COLLECTION_NAME)

# Load embedding model
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

def retrieve_similar_chunks(query: str, top_k: int = 3) -> list[str]:
    query_embedding = embedding_model.encode(query).tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )

    return results["documents"][0] if results and results.get("documents") else []

# # backend/ingestion/faq_retriever.py

# from chromadb import PersistentClient
# from sentence_transformers import SentenceTransformer
# import os

# # Absolute path to ensure consistency
# PROJECT_ROOT = r"D:\Thrivv.ai\onboarding-agent-101\backend"
# CHROMA_DIR = os.path.join(PROJECT_ROOT, "chroma_store")
# COLLECTION_NAME = "faq"

# def get_chromadb_client():
#     return PersistentClient(path=CHROMA_DIR)

# def retrieve_similar_chunks(query: str, top_k: int = 3) -> list[str]:
#     try:
#         print(f"[DEBUG] ChromaDB path: {CHROMA_DIR}")
#         print(f"[DEBUG] Query: {query}")
        
#         client = get_chromadb_client()
#         collection = client.get_or_create_collection(name=COLLECTION_NAME)
        
#         # Load embedding model
#         embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
#         query_embedding = embedding_model.encode(query).tolist()

#         results = collection.query(
#             query_embeddings=[query_embedding],
#             n_results=top_k
#         )
        
#         documents = results["documents"][0] if results and results.get("documents") else []
#         print(f"[DEBUG] Retrieved {len(documents)} documents")
        
#         return documents
        
#     except Exception as e:
#         print(f"[ERROR] Retrieval failed: {e}")
#         return []