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


def test_search_ranks_by_cosine_similarity(db, monkeypatch):
    embeddings = {
        "sorgu": [1.0, 0.0],
        "alakali": [0.9, 0.1],
        "alakasiz": [0.0, 1.0],
    }

    async def fake_embed(text):
        return embeddings[text]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    asyncio.run(ks.add_entry(db, "document", "t1", "alakali"))
    asyncio.run(ks.add_entry(db, "document", "t2", "alakasiz"))

    result = asyncio.run(ks.search(db, "sorgu", top_k=5))
    assert result == ["alakali", "alakasiz"]


def test_search_respects_top_k(db, monkeypatch):
    async def fake_embed(text):
        return [1.0, 0.0]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    for i in range(3):
        asyncio.run(ks.add_entry(db, "document", f"t{i}", f"icerik {i}"))

    result = asyncio.run(ks.search(db, "sorgu", top_k=2))
    assert len(result) == 2


def test_search_filters_by_entry_types(db, monkeypatch):
    async def fake_embed(text):
        return [1.0, 0.0]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    asyncio.run(ks.add_entry(db, "document", "t1", "dokuman icerik"))
    asyncio.run(ks.add_entry(db, "rule", "t2", "kural icerik"))

    result = asyncio.run(ks.search(db, "sorgu", entry_types=["rule"]))
    assert result == ["kural icerik"]


def test_search_returns_empty_list_when_embedding_unavailable(db, monkeypatch):
    async def failing_embed(text):
        return None

    monkeypatch.setattr(ai_service, "ollama_embed", failing_embed)
    result = asyncio.run(ks.search(db, "sorgu"))
    assert result == []


def test_search_returns_empty_list_when_no_entries(db, monkeypatch):
    async def fake_embed(text):
        return [1.0, 0.0]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    result = asyncio.run(ks.search(db, "sorgu"))
    assert result == []


def test_format_context_block_empty_returns_empty_string():
    assert ks.format_context_block([]) == ""


def test_format_context_block_formats_bullet_list():
    block = ks.format_context_block(["birinci", "ikinci"])
    assert "İlgili geçmiş bilgi" in block
    assert "- birinci" in block
    assert "- ikinci" in block


def test_knowledge_document_version_model_defaults(db):
    from models.db_models import KnowledgeDocumentVersion

    row = KnowledgeDocumentVersion(entry_type="rule", title="T", full_content="C")
    db.add(row)
    db.commit()
    db.refresh(row)

    assert row.is_current is True
    assert row.diff_summary is None
    assert row.created_at is not None
