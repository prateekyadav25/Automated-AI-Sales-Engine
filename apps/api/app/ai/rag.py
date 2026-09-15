import json
import math
import re
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ai.providers import get_embedding_provider
from app.core.config import get_settings
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


def _write_vector(db: Session, chunk_id, embedding: list[float]) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    settings = get_settings()
    if len(embedding) != settings.embedding_dimensions:
        return
    literal = "[" + ",".join(str(float(x)) for x in embedding) + "]"
    db.execute(
        text("UPDATE knowledge_chunks SET embedding = CAST(:vec AS vector) WHERE id = :id"),
        {"vec": literal, "id": str(chunk_id)},
    )


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
        chunk = KnowledgeChunk(
            tenant_id=tenant_id,
            created_by=actor_id,
            source_id=source.id,
            ordinal=idx,
            text=part,
            embedding_json=json.dumps(embedding),
            metadata_json=json.dumps({"title": title}),
        )
        db.add(chunk)
        db.flush()
        _write_vector(db, chunk.id, embedding)
    return source


def _retrieve_pgvector(db: Session, *, tenant_id: UUID, query_vec: list[float], limit: int) -> list[dict]:
    settings = get_settings()
    if len(query_vec) != settings.embedding_dimensions:
        return []
    literal = "[" + ",".join(str(float(x)) for x in query_vec) + "]"
    try:
        rows = db.execute(
            text(
                """
                SELECT id::text, source_id::text, text,
                       1 - (embedding <=> CAST(:vec AS vector)) AS score
                FROM knowledge_chunks
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND deleted_at IS NULL
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :lim
                """
            ),
            {"vec": literal, "tid": str(tenant_id), "lim": limit},
        ).all()
    except Exception:  # noqa: BLE001
        return []
    hits = []
    for chunk_id, source_id, body, score in rows:
        source = db.get(KnowledgeSource, UUID(str(source_id)))
        if source is None or source.tenant_id != tenant_id:
            continue
        if score is None or float(score) <= 0:
            continue
        hits.append(
            {
                "chunk_id": chunk_id,
                "source_id": source_id,
                "title": source.title,
                "text": body,
                "score": round(float(score), 4),
            }
        )
    return hits


def retrieve(db: Session, *, tenant_id: UUID, query: str, limit: int = 5) -> list[dict]:
    provider = get_embedding_provider()
    query_vec = provider.embed([query])[0]
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        hits = _retrieve_pgvector(db, tenant_id=tenant_id, query_vec=query_vec, limit=limit)
        if hits:
            return hits
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
