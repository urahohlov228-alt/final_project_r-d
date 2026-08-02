"""Ingest the knowledge base: chunk data/docs/*.md and build the Chroma index.

Usage: python scripts/ingest.py
Run once locally (or during `docker build`) before starting the server.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hr_assistant.config import get_settings
from hr_assistant.logging_setup import setup_logging
from hr_assistant.rag.chunking import chunk_directory
from hr_assistant.rag.store import VectorStore


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    chunks = chunk_directory(settings.docs_dir)
    if not chunks:
        raise SystemExit(f"No markdown documents found in {settings.docs_dir}")

    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    store = VectorStore(str(settings.chroma_dir), settings.rag_collection)
    n = store.rebuild(chunks)

    print(f"Ingested {n} chunks from {len({c.source for c in chunks})} documents")
    print("\nSmoke-test query: 'How much paid time off can I take?'")
    for hit in store.search("How much paid time off can I take?", top_k=3):
        print(f"  score={hit['score']:.3f}  {hit['source']}  [{hit['section'][:60]}]")


if __name__ == "__main__":
    main()
