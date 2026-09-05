import json
import math
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_embedding_provider
from app.models.ai import KnowledgeChunk, KnowledgeSource


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def chunk_text(text: str, size: int = 800) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    return [cleaned[i : i + size] for i in range(0, len(cleaned), size)]


def ingest_text(db: Session, *, tenant_id: UUID, actor_id: UUID, title: str, text: str) -> KnowledgeSource:
    provider = get_embedding_provider()
    parts = chunk_text(text)
    embeddings = provider.embed(parts) if parts else []
    source = KnowledgeSource(
        tenant_id=tenant_id,
        created_by=actor_id,
        title=title,
        source_type="upload",
        mime_type="text/plain",
        status="ready",
    )
    db.add(source)
    db.flush()
    for idx, (part, embedding) in enumerate(zip(parts, embeddings, strict=True)):
        db.add(
            KnowledgeChunk(
                tenant_id=tenant_id,
                created_by=actor_id,
                source_id=source.id,
                ordinal=idx,
                text=part,
                embedding_json=json.dumps(embedding),
                metadata_json=json.dumps({"title": title}),
            )
        )
    return source


def retrieve(db: Session, *, tenant_id: UUID, query: str, limit: int = 5) -> list[dict]:
    provider = get_embedding_provider()
    query_vec = provider.embed([query])[0]
    chunks = db.scalars(
        select(KnowledgeChunk).where(
            KnowledgeChunk.tenant_id == tenant_id, KnowledgeChunk.deleted_at.is_(None)
        )
    ).all()
    scored: list[tuple[float, KnowledgeChunk]] = []
    for chunk in chunks:
        try:
            vec = json.loads(chunk.embedding_json)
        except json.JSONDecodeError:
            vec = []
        lexical = 1.0 if query.lower()[:20] in chunk.text.lower() else 0.0
        score = (0.7 * _cosine(query_vec, vec)) + (0.3 * lexical)
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    hits = []
    for score, chunk in scored[:limit]:
        source = db.get(KnowledgeSource, chunk.source_id)
        if source is None or source.tenant_id != tenant_id:
            continue
        hits.append(
            {
                "chunk_id": str(chunk.id),
                "source_id": str(chunk.source_id),
                "title": source.title,
                "text": chunk.text,
                "score": round(score, 4),
            }
        )
    return hits
