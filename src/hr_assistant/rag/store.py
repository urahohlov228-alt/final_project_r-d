"""ChromaDB-backed vector store.

Uses Chroma's built-in ONNX embedding model (all-MiniLM-L6-v2): no external
embedding API and no GPU/torch dependency, which keeps the Docker image small
and lets the whole RAG stack run for free.
"""

import logging

import chromadb

from .chunking import Chunk

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, persist_dir: str, collection_name: str):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection_name = collection_name

    @property
    def collection(self) -> chromadb.Collection:
        return self._client.get_or_create_collection(
            self._collection_name, metadata={"hnsw:space": "cosine"}
        )

    def count(self) -> int:
        return self.collection.count()

    def rebuild(self, chunks: list[Chunk], batch_size: int = 64) -> int:
        """Drop and re-create the collection from the given chunks."""
        try:
            self._client.delete_collection(self._collection_name)
        except Exception:  # noqa: BLE001 - collection may not exist yet
            pass
        collection = self.collection
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            collection.add(
                ids=[c.id for c in batch],
                documents=[c.text for c in batch],
                metadatas=[
                    {"source": c.source, "title": c.title, "section": c.section} for c in batch
                ],
            )
        logger.info("Indexed %d chunks into '%s'", len(chunks), self._collection_name)
        return len(chunks)

    def search(self, query: str, top_k: int = 4) -> list[dict]:
        """Return the top_k most similar chunks with metadata and a 0..1 score."""
        result = self.collection.query(query_texts=[query], n_results=top_k)
        hits = []
        for text, meta, distance in zip(
            result["documents"][0], result["metadatas"][0], result["distances"][0], strict=True
        ):
            hits.append(
                {
                    "text": text,
                    "source": meta["source"],
                    "title": meta["title"],
                    "section": meta["section"],
                    "score": round(1.0 - distance, 4),  # cosine distance -> similarity
                }
            )
        return hits
