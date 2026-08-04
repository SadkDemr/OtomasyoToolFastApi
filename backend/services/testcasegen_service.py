"""
TestCaseGen Service
--------------------
Ekran görüntülerinden test case başlığı çıkarma, kural tabanlı
önceliklendirme, adım doğrulama ve ADO formatlı Excel export.
Veritabanı YOK — state dosya tabanlı (bkz. session_* fonksiyonları).
"""

import json
import re
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────────────
# JSON temizleme / parse
# ──────────────────────────────────────────────────────

def clean_json_text(text: str) -> str:
    """Markdown code fence'leri (```json ... ``` veya ``` ... ```) temizler."""
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    return cleaned.strip()


def extract_json_object(text: str) -> Optional[dict]:
    """LLM çıktısından ilk JSON nesnesini çıkarır. Parse edilemezse None döner."""
    if not text:
        return None
    cleaned = clean_json_text(text)
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = cleaned[start:end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None
