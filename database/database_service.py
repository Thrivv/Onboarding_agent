# database/database_service.py

import os
import json
import time
import threading
from datetime import datetime
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import shutil


# Data models
class Document(BaseModel):
    id: str
    text: str
    metadata: Dict[str, Any] = {}


class QueryRequest(BaseModel):
    query: str
    collection_name: str = "default"
    top_k: int = 5


class QueryResponse(BaseModel):
    results: List[Dict[str, Any]]
    took_ms: int


# Initialize embedding model
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")


class VectorDatabaseService:
    def __init__(self):
        self.chroma_client = None
        self.backup_dir = "/data/backups"
        self.documents_dir = "/data/documents"
        self.chroma_dir = "/data/chroma"

        # Ensure directories exist
        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.documents_dir, exist_ok=True)
        os.makedirs(self.chroma_dir, exist_ok=True)

        # Initialize ChromaDB
        self._init_chromadb()

        # Start backup scheduler
        self._start_backup_scheduler()

    def _init_chromadb(self):
        """Initialize ChromaDB with persistent storage"""
        try:
            self.chroma_client = chromadb.PersistentClient(
                path=self.chroma_dir, settings=Settings(allow_reset=True)
            )
            print(f"[INFO] ChromaDB initialized at {self.chroma_dir}")
        except Exception as e:
            print(f"[ERROR] Failed to initialize ChromaDB: {e}")
            raise

    def create_collection(self, collection_name: str) -> bool:
        """Create a new collection"""
        try:
            collection = self.chroma_client.get_or_create_collection(
                name=collection_name
            )
            print(f"[INFO] Collection '{collection_name}' created/retrieved")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to create collection {collection_name}: {e}")
            return False

    def add_documents(self, collection_name: str, documents: List[Document]) -> bool:
        """Add documents to collection with backup"""
        try:
            collection = self.chroma_client.get_or_create_collection(
                name=collection_name
            )

            # Prepare data for ChromaDB
            ids = [doc.id for doc in documents]
            texts = [doc.text for doc in documents]
            metadatas = [doc.metadata for doc in documents]

            # Generate embeddings
            embeddings = embedding_model.encode(texts).tolist()

            # Add to ChromaDB
            collection.add(
                documents=texts, embeddings=embeddings, metadatas=metadatas, ids=ids
            )

            # Create local backup
            self._backup_documents(collection_name, documents)

            print(f"[INFO] Added {len(documents)} documents to {collection_name}")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to add documents to {collection_name}: {e}")
            return False

    def query_documents(
        self, collection_name: str, query: str, top_k: int = 5
    ) -> List[Dict]:
        """Query documents from collection"""
        try:
            collection = self.chroma_client.get_collection(name=collection_name)

            # Generate query embedding
            query_embedding = embedding_model.encode(query).tolist()

            # Query ChromaDB
            results = collection.query(
                query_embeddings=[query_embedding], n_results=top_k
            )

            # Format results
            formatted_results = []
            if results and results.get("documents"):
                documents = results["documents"][0]
                metadatas = results.get("metadatas", [[{}] * len(documents)])[0]
                distances = results.get("distances", [[0] * len(documents)])[0]
                ids = results.get("ids", [[""] * len(documents)])[0]

                for i, doc in enumerate(documents):
                    formatted_results.append(
                        {
                            "id": ids[i],
                            "text": doc,
                            "metadata": metadatas[i],
                            "score": 1 - distances[i],  # Convert distance to similarity
                        }
                    )

            return formatted_results

        except Exception as e:
            print(f"[ERROR] Failed to query {collection_name}: {e}")
            return []

    def _backup_documents(self, collection_name: str, documents: List[Document]):
        """Create local file backup of documents"""
        try:
            backup_file = os.path.join(
                self.backup_dir,
                f"{collection_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            )

            backup_data = {
                "collection": collection_name,
                "timestamp": datetime.now().isoformat(),
                "documents": [doc.dict() for doc in documents],
            }

            with open(backup_file, "w", encoding="utf-8") as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)

            # Also save individual document files
            for doc in documents:
                doc_file = os.path.join(
                    self.documents_dir, f"{collection_name}_{doc.id}.txt"
                )
                with open(doc_file, "w", encoding="utf-8") as f:
                    f.write(f"ID: {doc.id}\n")
                    f.write(f"Metadata: {json.dumps(doc.metadata)}\n")
                    f.write(f"Text: {doc.text}\n")

            print(f"[INFO] Backup created: {backup_file}")

        except Exception as e:
            print(f"[ERROR] Backup failed: {e}")

    def _start_backup_scheduler(self):
        """Start periodic backup of all collections"""

        def backup_all():
            while True:
                try:
                    time.sleep(3600)  # Backup every hour
                    self._create_full_backup()
                except Exception as e:
                    print(f"[ERROR] Scheduled backup failed: {e}")

        backup_thread = threading.Thread(target=backup_all, daemon=True)
        backup_thread.start()
        print("[INFO] Backup scheduler started")

    def _create_full_backup(self):
        """Create full backup of ChromaDB"""
        try:
            backup_path = os.path.join(
                self.backup_dir,
                f"full_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            )

            # Copy entire ChromaDB directory
            shutil.copytree(self.chroma_dir, backup_path)
            print(f"[INFO] Full backup created: {backup_path}")

        except Exception as e:
            print(f"[ERROR] Full backup failed: {e}")

    def get_collections(self) -> List[str]:
        """Get list of all collections"""
        try:
            collections = self.chroma_client.list_collections()
            return [col.name for col in collections]
        except Exception as e:
            print(f"[ERROR] Failed to list collections: {e}")
            return []

    def get_collection_stats(self, collection_name: str) -> Dict:
        """Get statistics for a collection"""
        try:
            collection = self.chroma_client.get_collection(name=collection_name)
            count = collection.count()
            return {
                "name": collection_name,
                "document_count": count,
                "status": "healthy",
            }
        except Exception as e:
            print(f"[ERROR] Failed to get stats for {collection_name}: {e}")
            return {
                "name": collection_name,
                "document_count": 0,
                "status": "error",
                "error": str(e),
            }


# Initialize service
db_service = VectorDatabaseService()

# FastAPI app
app = FastAPI(title="Vector Database Service", version="1.0.0")


@app.get("/health")
def health_check():
    """Health check endpoint"""
    collections = db_service.get_collections()
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "collections": len(collections),
        "chroma_status": "connected",
    }


@app.post("/collections/{collection_name}")
def create_collection(collection_name: str):
    """Create a new collection"""
    success = db_service.create_collection(collection_name)
    if success:
        return {"message": f"Collection {collection_name} created successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to create collection")


@app.post("/collections/{collection_name}/documents")
def add_documents(collection_name: str, documents: List[Document]):
    """Add documents to collection"""
    success = db_service.add_documents(collection_name, documents)
    if success:
        return {"message": f"Added {len(documents)} documents to {collection_name}"}
    else:
        raise HTTPException(status_code=500, detail="Failed to add documents")


@app.post("/collections/{collection_name}/query")
def query_collection(collection_name: str, query_request: QueryRequest):
    """Query documents in collection"""
    start_time = time.time()

    results = db_service.query_documents(
        collection_name, query_request.query, query_request.top_k
    )

    took_ms = int((time.time() - start_time) * 1000)

    return QueryResponse(results=results, took_ms=took_ms)


@app.get("/collections")
def list_collections():
    """List all collections"""
    collections = db_service.get_collections()
    stats = [db_service.get_collection_stats(col) for col in collections]
    return {"collections": stats}


@app.get("/collections/{collection_name}/stats")
def get_collection_stats(collection_name: str):
    """Get collection statistics"""
    return db_service.get_collection_stats(collection_name)


if __name__ == "__main__":
    print("[INFO] Starting Vector Database Service...")
    uvicorn.run(app, host="0.0.0.0", port=8002)
