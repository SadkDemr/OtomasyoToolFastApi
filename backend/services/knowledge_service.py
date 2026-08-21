"""
Knowledge Service - TestCaseGen paylaşımlı bilgi tabanı (RAG)
---------------------------------------------------------------
- Yüklenen analiz dökümanları, onaylı senaryolar, kullanıcı düzeltmeleri
  ve admin .md kuralları KnowledgeEntry olarak saklanır.
- Ollama embedding modeli (varsayılan: nomic-embed-text) ile vektörleştirilir.
- search(): cosine similarity ile en alakalı içerikleri döner.
"""

import numpy as np
from sqlalchemy.orm import Session

from models.db_models import KnowledgeEntry
from services import ai_service

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
