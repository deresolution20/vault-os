"""M2.2 — vault RAG: obsidian-notes-rag (sqlite-vec) + LOCAL embeddings.

Constraint (PRD §3.4): embeddings run locally — provider is the local ollama
daemon (nomic-embed-text); vault content never leaves the box. The sqlite-vec
store itself is a single local file with no telemetry.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from obsidian_rag.indexer import LMStudioEmbedder, VaultIndexer
from obsidian_rag.store import VectorStore

from .config import settings


class RagService:
    def __init__(
        self,
        vault_path: Path,
        data_dir: Path,
        embed_url: str,
        embed_model: str,
    ) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        # OpenAI-compatible /v1/embeddings — served by vault-embed
        # (llama.cpp); same nomic weights + task prefixes as before, so the
        # existing sqlite-vec index remains valid
        self.embedder = LMStudioEmbedder(base_url=embed_url, model=embed_model)
        self.store = VectorStore(data_path=str(data_dir))
        self.indexer = VaultIndexer(vault_path=str(vault_path), embedder=self.embedder)

    def index_all(self) -> dict:
        """(Re)index every markdown file; returns counts for logging/UI."""
        files = chunks = 0
        for file_path in self.indexer.iter_markdown_files():
            files += 1
            chunks += self.index_file(file_path)
        return {"files": files, "chunks": chunks, **self.stats()}

    def index_file(self, file_path: str | Path) -> int:
        """Index one file (used by the M2.3 watcher for incremental updates)."""
        pairs = list(self.indexer.index_file(file_path))
        if pairs:
            self.store.upsert_batch(
                [c for c, _ in pairs], [e for _, e in pairs]
            )
        return len(pairs)

    def remove_file(self, rel_path: str) -> None:
        self.store.delete_by_file(rel_path)

    def query(self, text: str, limit: int = 8) -> list[dict]:
        emb = self.embedder.embed(text, task_type="search_query")
        return self.store.search(emb, limit=limit)

    def stats(self) -> dict:
        return self.store.get_stats()


@lru_cache(maxsize=1)
def rag() -> RagService:
    return RagService(
        vault_path=settings.vault_path,
        data_dir=settings.rag_data_dir,
        embed_url=settings.embed_url,
        embed_model=settings.embed_model,
    )
