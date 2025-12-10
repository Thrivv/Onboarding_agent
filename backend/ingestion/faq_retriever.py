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

    results = collection.query(query_embeddings=[query_embedding], n_results=top_k)

    return results["documents"][0] if results and results.get("documents") else []
