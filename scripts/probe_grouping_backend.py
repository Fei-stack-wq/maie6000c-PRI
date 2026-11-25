"""Fail if the AI process is not using sentence_transformers for grouping."""

from __future__ import annotations

from services.ai.app.grouping import reset_embedder_cache, resolve_embedder
from services.common.config import get_settings


def main() -> None:
    reset_embedder_cache()
    get_settings.cache_clear()
    settings = get_settings()
    print(f"backend={settings.grouping_embedding_backend}")
    print(f"threshold={settings.grouping_similarity_threshold}")
    print(f"model={settings.grouping_embedding_model}")
    if settings.grouping_embedding_backend != "sentence_transformers":
        raise SystemExit(
            f"expected sentence_transformers, got {settings.grouping_embedding_backend}"
        )
    embedder = resolve_embedder(settings)
    name = getattr(embedder, "__name__", type(embedder).__name__)
    print(f"embedder={name}")
    if "hashing" in name.lower():
        raise SystemExit(f"hashing embedder is not deliverable: {name}")


if __name__ == "__main__":
    main()
