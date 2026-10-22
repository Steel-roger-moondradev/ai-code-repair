"""Bounded, provenance-preserving Python repository retrieval."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import Settings, get_settings
from app.services.repository import RepositoryService


class EmbeddingProvider(Protocol):
    """Optional provider used only when semantic retrieval is configured."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


@dataclass(frozen=True)
class RetrievalChunk:
    """A source chunk with complete repository provenance."""

    repository_id: str
    commit_hash: str
    path: str
    start_line: int
    end_line: int
    content_hash: str
    text: str
    embedding: tuple[float, ...] | None = None

    def as_dict(self) -> dict:
        """Return the stable structure passed to later workflow stages."""

        return {
            "repository_id": self.repository_id,
            "commit_hash": self.commit_hash,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content_hash": self.content_hash,
            "content": self.text,
        }


@dataclass
class RetrievalIndex:
    """An in-memory repository-scoped retrieval index."""

    repository_id: str
    commit_hash: str
    chunks: list[RetrievalChunk]
    mode: str = "exact"


def chunk_source(
    text: str,
    *,
    repository_id: str,
    commit_hash: str,
    path: str,
    chunk_lines: int = 80,
    overlap_lines: int = 10,
) -> list[RetrievalChunk]:
    """Chunk source only at line boundaries with bounded overlap."""

    if chunk_lines <= 0:
        raise ValueError("chunk_lines must be positive")
    if overlap_lines < 0 or overlap_lines >= chunk_lines:
        raise ValueError("overlap_lines must be non-negative and smaller than chunk_lines")

    lines = text.splitlines()
    chunks: list[RetrievalChunk] = []
    start = 0
    while start < len(lines):
        end = min(start + chunk_lines, len(lines))
        content = "\n".join(lines[start:end])
        chunks.append(
            RetrievalChunk(
                repository_id=repository_id,
                commit_hash=commit_hash,
                path=path,
                start_line=start + 1,
                end_line=end,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                text=content,
            )
        )
        if end == len(lines):
            break
        start = end - overlap_lines
    return chunks


def build_index(
    repository_path: Path,
    *,
    repository_id: str,
    commit_hash: str | None = None,
    settings: Settings | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    chunk_lines: int = 80,
    overlap_lines: int = 10,
) -> RetrievalIndex:
    """Build a bounded index from eligible Python source files."""

    settings = settings or get_settings()
    service = RepositoryService(settings)
    root = repository_path.resolve()
    resolved_commit = commit_hash or repository_commit(root)
    chunks: list[RetrievalChunk] = []

    for path in service.get_repository_tree(root):
        file_path = root.joinpath(*path.split("/"))
        if file_path.stat().st_size > settings.max_file_bytes:
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        file_chunks = chunk_source(
            text,
            repository_id=repository_id,
            commit_hash=resolved_commit,
            path=path,
            chunk_lines=chunk_lines,
            overlap_lines=overlap_lines,
        )
        chunks.extend(file_chunks)
        if len(chunks) >= settings.max_repository_files:
            chunks = chunks[: settings.max_repository_files]
            break

    mode = "exact"
    if embedding_provider is not None and chunks:
        try:
            vectors = embedding_provider.embed([chunk.text for chunk in chunks])
            if len(vectors) != len(chunks):
                raise ValueError("embedding count does not match chunk count")
            chunks = [
                RetrievalChunk(**{**chunk.__dict__, "embedding": tuple(vector)})
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            mode = "semantic"
        except Exception:
            mode = "exact_fallback"

    return RetrievalIndex(
        repository_id=repository_id,
        commit_hash=resolved_commit,
        chunks=chunks,
        mode=mode,
    )


def retrieve_semantic(
    index: RetrievalIndex,
    query: str,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    limit: int = 5,
    max_context_chars: int = 30000,
) -> list[dict]:
    """Retrieve semantically when configured, otherwise use exact fallback."""

    if not query.strip():
        raise ValueError("query must be non-empty")
    if limit <= 0 or max_context_chars <= 0:
        raise ValueError("retrieval limits must be positive")
    if embedding_provider is None or not any(chunk.embedding for chunk in index.chunks):
        return _exact_results(index, query, limit, max_context_chars)

    try:
        query_vector = embedding_provider.embed_query(query)
        ranked = sorted(
            index.chunks,
            key=lambda chunk: _cosine_similarity(query_vector, chunk.embedding or ()),
            reverse=True,
        )
    except Exception:
        return _exact_results(index, query, limit, max_context_chars)
    return _bounded_unique_results(ranked, limit, max_context_chars)


def retrieve_hybrid(
    index: RetrievalIndex,
    query: str,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    limit: int = 5,
    max_context_chars: int = 30000,
) -> list[dict]:
    """Combine exact matches with optional semantic ranking."""

    exact = _exact_results(index, query, limit, max_context_chars)
    exact_keys = {(item["path"], item["start_line"], item["end_line"]) for item in exact}
    semantic = retrieve_semantic(
        index,
        query,
        embedding_provider=embedding_provider,
        limit=limit,
        max_context_chars=max_context_chars,
    )
    merged = exact + [
        item
        for item in semantic
        if (item["path"], item["start_line"], item["end_line"]) not in exact_keys
    ]
    return _bounded_unique_dict_results(merged, limit, max_context_chars)


def repository_commit(repository_path: Path) -> str:
    """Read the pinned commit without executing repository code."""

    try:
        result = subprocess.run(
            ["git", "-C", str(repository_path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("repository commit could not be determined") from exc
    commit = result.stdout.strip()
    if not commit:
        raise ValueError("repository commit could not be determined")
    return commit


def _exact_results(
    index: RetrievalIndex,
    query: str,
    limit: int,
    max_context_chars: int,
) -> list[dict]:
    query_lower = query.casefold()
    ranked = sorted(
        (
            chunk
            for chunk in index.chunks
            if query_lower in chunk.text.casefold()
        ),
        key=lambda chunk: (chunk.path, chunk.start_line),
    )
    return _bounded_unique_results(ranked, limit, max_context_chars)


def _bounded_unique_results(
    chunks: list[RetrievalChunk],
    limit: int,
    max_context_chars: int,
) -> list[dict]:
    return _bounded_unique_dict_results(
        [chunk.as_dict() for chunk in chunks],
        limit,
        max_context_chars,
    )


def _bounded_unique_dict_results(
    items: list[dict],
    limit: int,
    max_context_chars: int,
) -> list[dict]:
    results: list[dict] = []
    seen: set[tuple[str, int, int, str]] = set()
    total_chars = 0
    for item in items:
        key = (
            item["path"],
            item["start_line"],
            item["end_line"],
            item["content_hash"],
        )
        if key in seen:
            continue
        content_size = len(item["content"])
        if total_chars + content_size > max_context_chars:
            continue
        seen.add(key)
        results.append(item)
        total_chars += content_size
        if len(results) >= limit:
            break
    return results


def _cosine_similarity(left: list[float], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
