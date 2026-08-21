import asyncio

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.db_models import KnowledgeEntry
from services import ai_service, knowledge_service as ks


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_add_entry_stores_embedding_and_returns_count(db, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    added = asyncio.run(ks.add_entry(db, "document", "analiz.docx", "Kisa bir dokuman metni.", user_id=1, source_ref="s1"))

    assert added == 1
    rows = db.query(KnowledgeEntry).all()
    assert len(rows) == 1
    assert rows[0].entry_type == "document"
    assert rows[0].title == "analiz.docx"
    assert rows[0].content == "Kisa bir dokuman metni."
    assert rows[0].source_ref == "s1"
    assert rows[0].created_by_user_id == 1
    vec = np.frombuffer(rows[0].embedding, dtype=np.float32)
    assert list(vec) == pytest.approx([0.1, 0.2, 0.3])
    assert rows[0].embedding_dim == 3


def test_add_entry_chunks_long_content(db, monkeypatch):
    async def fake_embed(text):
        return [0.1]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    long_text = ("kelime " * 400).strip()  # ~2800 karakter, CHUNK_CHAR_LIMIT'i (1000) asar
    added = asyncio.run(ks.add_entry(db, "document", "buyuk.docx", long_text))

    assert added >= 3
    rows = db.query(KnowledgeEntry).all()
    assert len(rows) == added
    assert all(len(r.content) <= ks.CHUNK_CHAR_LIMIT for r in rows)


def test_add_entry_skips_chunk_when_embedding_unavailable(db, monkeypatch):
    async def failing_embed(text):
        return None

    monkeypatch.setattr(ai_service, "ollama_embed", failing_embed)
    added = asyncio.run(ks.add_entry(db, "rule", "Kural", "icerik"))

    assert added == 0
    assert db.query(KnowledgeEntry).count() == 0


def test_add_entry_empty_content_returns_zero(db, monkeypatch):
    async def fake_embed(text):
        return [0.1]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    added = asyncio.run(ks.add_entry(db, "rule", "Bos", "   "))

    assert added == 0
    assert db.query(KnowledgeEntry).count() == 0
