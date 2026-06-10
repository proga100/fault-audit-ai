"""Query-time embedding via Vertex AI (gemini-embedding-001, RETRIEVAL_QUERY).

Mirrors the document-side embedding in embed_and_load.py but with the QUERY task type,
which is the correct asymmetric setup for retrieval. Lazily builds the Vertex client so
importing this module never hits the network (tests pass a fake embedder instead).
"""

from __future__ import annotations

from functools import lru_cache

from faultaudit.config import get_settings


@lru_cache
def _client():
    from google import genai  # imported lazily so import-time is network-free

    settings = get_settings()
    return genai.Client(vertexai=True, project=settings.gcp_project, location=settings.gcp_region)


def embed_query(text: str) -> list[float]:
    """Embed a search query with gemini-embedding-001 (RETRIEVAL_QUERY, 768 dims)."""
    from google.genai.types import EmbedContentConfig

    settings = get_settings()
    resp = _client().models.embed_content(
        model=settings.embedding_model,
        contents=text,
        config=EmbedContentConfig(task_type="RETRIEVAL_QUERY", output_dimensionality=settings.embedding_dims),
    )
    return resp.embeddings[0].values
