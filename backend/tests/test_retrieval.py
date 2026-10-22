"""Offline tests for bounded repository retrieval."""

from pathlib import Path

import pytest

from app.agents.retrieval import (
    build_index,
    chunk_source,
    retrieve_hybrid,
    retrieve_semantic,
)
from app.config import Settings


def settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "repository_root": str(tmp_path / "repositories"),
        "max_file_bytes": 10000,
        "max_repository_files": 100,
    }
    values.update(overrides)
    return Settings(**values)


def make_repo(tmp_path: Path, owner: str = "octo", repo: str = "repo") -> tuple[Settings, Path]:
    config = settings(tmp_path)
    root = Path(config.repository_root) / owner / repo
    root.mkdir(parents=True)
    return config, root


def test_empty_repository_builds_empty_index(tmp_path: Path) -> None:
    config, root = make_repo(tmp_path)

    index = build_index(root, repository_id="octo/repo", commit_hash="commit", settings=config)

    assert index.chunks == []
    assert index.mode == "exact"


def test_chunk_boundaries_overlap_and_provenance() -> None:
    chunks = chunk_source(
        "\n".join(f"line-{number}" for number in range(1, 7)),
        repository_id="octo/repo",
        commit_hash="abc",
        path="src/main.py",
        chunk_lines=3,
        overlap_lines=1,
    )

    assert [(chunk.start_line, chunk.end_line) for chunk in chunks] == [(1, 3), (3, 5), (5, 6)]
    assert chunks[0].repository_id == "octo/repo"
    assert chunks[1].content_hash


def test_exact_retrieval_is_stable_and_source_grounded(tmp_path: Path) -> None:
    config, root = make_repo(tmp_path)
    (root / "b.py").write_text("target\n", encoding="utf-8")
    (root / "a.py").write_text("target\n", encoding="utf-8")
    index = build_index(root, repository_id="octo/repo", commit_hash="commit", settings=config)

    results = retrieve_semantic(index, "target", limit=5, max_context_chars=100)

    assert [result["path"] for result in results] == ["a.py", "b.py"]
    assert all(result["repository_id"] == "octo/repo" for result in results)
    assert all(result["commit_hash"] == "commit" for result in results)


def test_context_budget_and_duplicate_results_are_bounded(tmp_path: Path) -> None:
    config, root = make_repo(tmp_path)
    (root / "main.py").write_text("needle\n" * 5, encoding="utf-8")
    index = build_index(
        root,
        repository_id="octo/repo",
        commit_hash="commit",
        settings=config,
        chunk_lines=2,
        overlap_lines=1,
    )
    duplicate = index.chunks[0]
    index.chunks.append(duplicate)

    results = retrieve_hybrid(index, "needle", limit=10, max_context_chars=15)

    assert len(results) == 1
    assert len(results[0]["content"]) <= 15


def test_repositories_are_isolated(tmp_path: Path) -> None:
    config, first = make_repo(tmp_path, "one", "repo")
    second = Path(config.repository_root) / "two" / "repo"
    second.mkdir(parents=True)
    (first / "main.py").write_text("first-only\n", encoding="utf-8")
    (second / "main.py").write_text("second-only\n", encoding="utf-8")
    first_index = build_index(first, repository_id="one/repo", commit_hash="one", settings=config)
    second_index = build_index(second, repository_id="two/repo", commit_hash="two", settings=config)

    assert retrieve_semantic(first_index, "second-only", limit=5, max_context_chars=100) == []
    assert retrieve_semantic(second_index, "second-only", limit=5, max_context_chars=100)[0]["repository_id"] == "two/repo"


def test_embedding_failure_falls_back_to_exact_search(tmp_path: Path) -> None:
    config, root = make_repo(tmp_path)
    (root / "main.py").write_text("fallback-term\n", encoding="utf-8")

    class BrokenProvider:
        def embed(self, texts):
            raise RuntimeError("embedding unavailable")

        def embed_query(self, text):
            raise RuntimeError("embedding unavailable")

    index = build_index(
        root,
        repository_id="octo/repo",
        commit_hash="commit",
        settings=config,
        embedding_provider=BrokenProvider(),
    )

    assert index.mode == "exact_fallback"
    assert retrieve_semantic(
        index,
        "fallback-term",
        embedding_provider=BrokenProvider(),
        max_context_chars=100,
    )[0]["path"] == "main.py"


def test_semantic_results_are_ranked_and_hybrid_deduplicates(tmp_path: Path) -> None:
    config, root = make_repo(tmp_path)
    (root / "main.py").write_text("exact-term semantic\n", encoding="utf-8")
    (root / "other.py").write_text("semantic-only\n", encoding="utf-8")

    class Provider:
        def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def embed_query(self, text):
            return [1.0, 0.0]

    index = build_index(
        root,
        repository_id="octo/repo",
        commit_hash="commit",
        settings=config,
        embedding_provider=Provider(),
    )
    results = retrieve_hybrid(
        index,
        "exact-term",
        embedding_provider=Provider(),
        limit=5,
        max_context_chars=100,
    )

    assert index.mode == "semantic"
    assert [item["path"] for item in results] == ["main.py", "other.py"]


def test_oversized_files_are_not_indexed(tmp_path: Path) -> None:
    config = settings(tmp_path, max_file_bytes=5)
    root = Path(config.repository_root) / "octo" / "repo"
    root.mkdir(parents=True)
    (root / "large.py").write_text("too-large", encoding="utf-8")

    index = build_index(root, repository_id="octo/repo", commit_hash="commit", settings=config)

    assert index.chunks == []
