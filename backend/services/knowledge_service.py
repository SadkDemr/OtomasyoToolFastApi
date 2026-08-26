"""
Knowledge Service - TestCaseGen paylaşımlı bilgi tabanı (RAG)
---------------------------------------------------------------
- Yüklenen analiz dökümanları, onaylı senaryolar, kullanıcı düzeltmeleri
  ve admin .md kuralları KnowledgeEntry olarak saklanır.
- Ollama embedding modeli (varsayılan: nomic-embed-text) ile vektörleştirilir.
- search(): cosine similarity ile en alakalı içerikleri döner.
"""

import logging

import numpy as np
from sqlalchemy.orm import Session

from models.db_models import KnowledgeEntry
from services import ai_service

logger = logging.getLogger(__name__)

CHUNK_CHAR_LIMIT = 1000


def _chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= CHUNK_CHAR_LIMIT:
            chunks.append(remaining.strip())
            break
        cut = remaining.rfind(" ", 0, CHUNK_CHAR_LIMIT)
        if cut <= 0:
            cut = CHUNK_CHAR_LIMIT
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    return [c for c in chunks if c]


async def add_entry(
    db: Session,
    entry_type: str,
    title: str,
    content: str,
    user_id: "int | None" = None,
    source_ref: "str | None" = None,
) -> int:
    """content'i CHUNK_CHAR_LIMIT parçalara böler, her parça için embedding alır.
    Embedding alınamayan parçalar atlanır. Eklenen parça sayısını döner."""
    added = 0
    for chunk in _chunk_text(content):
        embedding = await ai_service.ollama_embed(chunk)
        if embedding is None:
            logger.warning(f"Embedding alınamadı, chunk atlanıyor: entry_type={entry_type!r} title={title!r}")
            continue
        vec = np.asarray(embedding, dtype=np.float32)
        db.add(KnowledgeEntry(
            entry_type=entry_type,
            title=title,
            content=chunk,
            embedding=vec.tobytes(),
            embedding_dim=int(vec.shape[0]),
            source_ref=source_ref,
            created_by_user_id=user_id,
        ))
        added += 1
    if added:
        db.commit()
    return added


def add_example(db: Session, title: str, content: str, user_id: "int | None" = None) -> None:
    """Format örneği ekler (entry_type="example"). Embedding YOK, chunking YOK — bunlar similarity
    search ile aranmaz, generate-testcases her seferinde TÜMÜNÜ (en yeni birkaçını) prompt'a
    few-shot olarak ekler, bu yüzden embedding modeli çevrimdışıyken de eklenebilmeli ve bir
    örneğin adımları parçalara bölünmemeli."""
    db.add(KnowledgeEntry(
        entry_type="example",
        title=title,
        content=content,
        embedding=None,
        embedding_dim=None,
        created_by_user_id=user_id,
    ))
    db.commit()


async def search(
    db: Session,
    query_text: str,
    top_k: int = 5,
    entry_types: "list[str] | None" = None,
) -> list[str]:
    """query_text'i embed eder, kayıtlı KnowledgeEntry'ler arasından cosine similarity'ye göre
    en alakalı top_k içeriği döner. Embedding alınamazsa veya hiç kayıt yoksa boş liste döner."""
    query_embedding = await ai_service.ollama_embed(query_text)
    if query_embedding is None:
        return []
    query_vec = np.asarray(query_embedding, dtype=np.float32)

    q = db.query(KnowledgeEntry)
    if entry_types:
        q = q.filter(KnowledgeEntry.entry_type.in_(entry_types))
    rows = q.all()
    if not rows:
        return []

    scored = []
    for row in rows:
        vec = np.frombuffer(row.embedding, dtype=np.float32)
        if vec.shape[0] != query_vec.shape[0]:
            continue
        denom = float(np.linalg.norm(query_vec) * np.linalg.norm(vec))
        score = float(np.dot(query_vec, vec) / denom) if denom else 0.0
        scored.append((score, row.content))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [content for _, content in scored[:top_k]]


def format_context_block(snippets: list[str]) -> str:
    if not snippets:
        return ""
    bullet_list = "\n".join(f"- {s}" for s in snippets)
    return f"İlgili geçmiş bilgi / kurallar:\n{bullet_list}\n\n"
