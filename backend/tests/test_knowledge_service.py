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


def test_build_diff_summary_prompt_includes_title_and_diff_lines():
    from services import testcasegen_service

    prompt = testcasegen_service.build_diff_summary_prompt(
        "Sifre Kurali", "-eski minimum 8 karakter\n+yeni minimum 10 karakter"
    )

    assert "Sifre Kurali" in prompt
    assert "eski minimum 8 karakter" in prompt
    assert "yeni minimum 10 karakter" in prompt


def test_save_versioned_entry_first_time_creates_version_and_search_rows(db, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    result = asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "icerik", user_id=1))

    assert result == {"is_update": False, "diff_summary": None, "chunks": 1}
    from models.db_models import KnowledgeDocumentVersion
    versions = db.query(KnowledgeDocumentVersion).all()
    assert len(versions) == 1
    assert versions[0].is_current is True
    assert versions[0].diff_summary is None
    assert db.query(KnowledgeEntry).count() == 1


def test_save_versioned_entry_same_content_is_noop(db, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "icerik", user_id=1))
    result = asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "icerik", user_id=1))

    assert result == {"is_update": False, "diff_summary": None, "chunks": 0}
    from models.db_models import KnowledgeDocumentVersion
    assert db.query(KnowledgeDocumentVersion).count() == 1
    assert db.query(KnowledgeEntry).count() == 1


def test_save_versioned_entry_update_replaces_search_rows_and_summarizes_diff(db, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    async def fake_generate_text(prompt, model=None, timeout=300.0, num_ctx=None):
        return "Icerik degisti."

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_generate_text)

    asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "eski icerik", user_id=1))
    result = asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "yeni icerik", user_id=1))

    assert result["is_update"] is True
    assert result["diff_summary"] == "Icerik degisti."

    from models.db_models import KnowledgeDocumentVersion
    versions = db.query(KnowledgeDocumentVersion).order_by(KnowledgeDocumentVersion.id).all()
    assert len(versions) == 2
    assert versions[0].is_current is False
    assert versions[1].is_current is True
    assert versions[1].full_content == "yeni icerik"

    entries = db.query(KnowledgeEntry).all()
    assert len(entries) == 1
    assert entries[0].content == "yeni icerik"


def test_save_versioned_entry_llm_failure_falls_back_to_fixed_message(db, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    async def failing_generate_text(prompt, model=None, timeout=300.0, num_ctx=None):
        raise RuntimeError("baglanti hatasi")

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    monkeypatch.setattr(ai_service, "ollama_generate_text", failing_generate_text)

    asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "eski icerik", user_id=1))
    result = asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "yeni icerik", user_id=1))

    assert "otomatik özet çıkarılamadı" in result["diff_summary"]


def test_save_versioned_entry_rule_embedding_unavailable_raises_and_changes_nothing(db, monkeypatch):
    async def failing_embed(text):
        return None

    monkeypatch.setattr(ai_service, "ollama_embed", failing_embed)

    with pytest.raises(ks.KnowledgeEmbeddingUnavailable):
        asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "icerik", user_id=1))

    from models.db_models import KnowledgeDocumentVersion
    assert db.query(KnowledgeDocumentVersion).count() == 0
    assert db.query(KnowledgeEntry).count() == 0


def test_save_versioned_entry_update_embedding_failure_keeps_old_content(db, monkeypatch):
    async def ok_embed(text):
        return [0.1, 0.2]

    monkeypatch.setattr(ai_service, "ollama_embed", ok_embed)
    asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "eski icerik", user_id=1))

    async def failing_embed(text):
        return None

    monkeypatch.setattr(ai_service, "ollama_embed", failing_embed)
    with pytest.raises(ks.KnowledgeEmbeddingUnavailable):
        asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "yeni icerik", user_id=1))

    from models.db_models import KnowledgeDocumentVersion
    versions = db.query(KnowledgeDocumentVersion).all()
    assert len(versions) == 1
    assert versions[0].full_content == "eski icerik"
    assert versions[0].is_current is True
    entries = db.query(KnowledgeEntry).all()
    assert len(entries) == 1
    assert entries[0].content == "eski icerik"


def test_save_versioned_entry_example_no_embedding_needed(db, monkeypatch):
    result = asyncio.run(ks.save_versioned_entry(db, "example", "Ornek", "adimlar", user_id=1))

    assert result == {"is_update": False, "diff_summary": None, "chunks": 1}
    assert db.query(KnowledgeEntry).filter(KnowledgeEntry.entry_type == "example").count() == 1
