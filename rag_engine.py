

from __future__ import annotations
from typing import List, Dict, Any
import uuid

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from config import (
    VECTORSTORE_DIR,
    EMBEDDING_MODEL_NAME,
    POLICY_COLLECTION,
    DOCUMENT_COLLECTION,
    TOP_K_POLICY_CHUNKS,
)


class RAGEngine:
    """Thin wrapper providing add / query over two Chroma collections:
    one for policy / ISO / SOP reference material, one for the company
    process documents being checked for compliance.
    """

    def __init__(self) -> None:
        self._client = chromadb.PersistentClient(
            path=str(VECTORSTORE_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        self._embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)

        self.policy_collection = self._client.get_or_create_collection(
            POLICY_COLLECTION, metadata={"hnsw:space": "cosine"}
        )
        self.document_collection = self._client.get_or_create_collection(
            DOCUMENT_COLLECTION, metadata={"hnsw:space": "cosine"}
        )

    # ------------------------------------------------------------------
    # Embedding helper
    # ------------------------------------------------------------------
    def _embed(self, texts: List[str]) -> List[List[float]]:
        vectors = self._embedder.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return vectors.tolist()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    def add_policy_chunks(self, file_id: str, filename: str, chunks: List[str]) -> int:
        return self._add(self.policy_collection, file_id, filename, chunks)

    def add_document_chunks(self, file_id: str, filename: str, chunks: List[str]) -> int:
        return self._add(self.document_collection, file_id, filename, chunks)

    def _add(self, collection, file_id: str, filename: str, chunks: List[str]) -> int:
        if not chunks:
            return 0
        ids = [f"{file_id}-{i}-{uuid.uuid4().hex[:6]}" for i in range(len(chunks))]
        embeddings = self._embed(chunks)
        metadatas = [{"file_id": file_id, "filename": filename, "chunk_index": i} for i in range(len(chunks))]
        collection.add(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
        return len(chunks)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def query_policies(self, query_text: str, top_k: int = TOP_K_POLICY_CHUNKS) -> List[Dict[str, Any]]:
        return self._query(self.policy_collection, query_text, top_k)

    def query_documents(self, query_text: str, file_id: str | None = None, top_k: int = 20) -> List[Dict[str, Any]]:
        where = {"file_id": file_id} if file_id else None
        return self._query(self.document_collection, query_text, top_k, where=where)

    def get_all_document_chunks(self, file_id: str) -> List[Dict[str, Any]]:
        result = self.document_collection.get(where={"file_id": file_id})
        return [
            {"text": doc, "metadata": meta}
            for doc, meta in zip(result.get("documents", []), result.get("metadatas", []))
        ]

    def _query(self, collection, query_text: str, top_k: int, where: dict | None = None) -> List[Dict[str, Any]]:
        if collection.count() == 0:
            return []
        query_embedding = self._embed([query_text])[0]
        kwargs = dict(query_embeddings=[query_embedding], n_results=min(top_k, collection.count()))
        if where:
            kwargs["where"] = where
        results = collection.query(**kwargs)

        out = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]
        for doc, meta, dist in zip(docs, metas, dists):
            out.append({"text": doc, "metadata": meta, "distance": dist})
        return out

    # ------------------------------------------------------------------
    # File removal (used if a user deletes an upload)
    # ------------------------------------------------------------------
    def delete_file(self, kind: str, file_id: str) -> None:
        collection = self.policy_collection if kind == "policy" else self.document_collection
        collection.delete(where={"file_id": file_id})


# Singleton instance shared across the FastAPI app
rag_engine = RAGEngine()
