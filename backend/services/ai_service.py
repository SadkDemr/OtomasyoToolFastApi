"""
AI Service - Gemini entegrasyonu
---------------------------------
- Görüntü analizi (vision fallback)
- BDD senaryo üretimi
- API key yönetimi (ai_config.json)
"""

import json
import base64
import os
from pathlib import Path
from typing import Optional, List
import httpx

CONFIG_PATH = Path(__file__).parent.parent / "ai_config.json"


def get_ai_config() -> dict:
    """ai_config.json oku (yoksa boş dict)"""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_ai_config(data: dict) -> None:
    """ai_config.json'a kaydet"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_gemini_key() -> Optional[str]:
    """Aktif Gemini API key (config > env)"""
    cfg = get_ai_config()
    return cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY") or None


def get_ollama_config() -> dict:
    """Ollama URL ve model (config > varsayılan)"""
    cfg = get_ai_config()
    return {
        "url":   cfg.get("ollama_url",   "http://localhost:11434/api/generate"),
        "model": cfg.get("ollama_model", "gemma3:4b"),
    }


# ──────────────────────────────────────────────────────
# Gemini yardımcıları
# ──────────────────────────────────────────────────────

def _gemini_text(prompt: str, api_key: str) -> str:
    """Gemini flash'a metin isteği gönder, yanıt metnini döndür."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(prompt)
        return resp.text.strip()
    except ImportError:
        raise RuntimeError("google-generativeai kütüphanesi kurulu değil. `pip install google-generativeai` çalıştırın.")
    except Exception as e:
        raise RuntimeError(f"Gemini API hatası: {e}")


def _gemini_vision(image_b64: str, prompt: str, api_key: str) -> str:
    """Gemini flash'a görüntü + metin isteği gönder."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        image_data = {"mime_type": "image/png", "data": image_b64}
        resp = model.generate_content([prompt, image_data])
        return resp.text.strip()
    except ImportError:
        raise RuntimeError("google-generativeai kütüphanesi kurulu değil.")
    except Exception as e:
        raise RuntimeError(f"Gemini Vision API hatası: {e}")


# ──────────────────────────────────────────────────────
# Vision Fallback
# ──────────────────────────────────────────────────────

def analyze_screenshot_for_step(image_b64: str, failed_step_text: str, api_key: str) -> dict:
    """
    Hatalı adım için ekran görüntüsünü analiz et.

    Returns:
        {
            "suggestion": "UI'da ne göründüğü",
            "action": "tap | type | scroll | skip",
            "target": "önerilen hedef metin/xpath",
            "confidence": "high | medium | low"
        }
    """
    prompt = f"""Sen bir mobil test otomasyon asistanısın.
Bir test adımı başarısız oldu: "{failed_step_text}"

Ekran görüntüsünü analiz et ve:
1. Ekranda ne görüyorsun? (kısa özet)
2. Bu adımı nasıl gerçekleştirebiliriz? (action: tap/type/scroll/skip)
3. Hedef element veya metin nedir?
4. Güven düzeyin: high/medium/low

JSON formatında yanıt ver:
{{"suggestion": "...", "action": "tap|type|scroll|skip", "target": "...", "confidence": "high|medium|low"}}"""

    try:
        text = _gemini_vision(image_b64, prompt, api_key)
        # JSON parse et
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {"suggestion": text, "action": "skip", "target": "", "confidence": "low"}
    except Exception as e:
        return {"suggestion": f"Analiz hatası: {e}", "action": "skip", "target": "", "confidence": "low"}


# ──────────────────────────────────────────────────────
# Senaryo Üretici
# ──────────────────────────────────────────────────────

def generate_scenario_variants(bdd_text: str, api_key: str, count: int = 3) -> List[dict]:
    """
    Mevcut BDD senaryosundan N adet varyant üret.

    Returns:
        [{"title": "...", "bdd_text": "...", "description": "..."}, ...]
    """
    prompt = f"""Sen bir mobil test otomasyon uzmanısın. Aşağıdaki BDD senaryosundan {count} farklı varyant üret.

Mevcut senaryo:
```
{bdd_text}
```

Kurallar:
- Türkçe BDD formatı kullan: Özellik, Senaryo, Verilen, Ve, Sonra, Doğrula
- Her varyant gerçekçi ve test edilebilir olsun
- Varyantlar şunları kapsayabilir: hata senaryoları, sınır değerleri, alternatif akışlar, negatif testler
- Her varyant için kısa bir açıklama ekle

JSON dizisi olarak döndür:
[
  {{
    "title": "Varyant başlığı",
    "description": "Bu senaryonun amacı",
    "bdd_text": "Özellik: ...\\n\\nSenaryo: ...\\n\\n  Verilen ...\\n  Ve ..."
  }}
]

Sadece JSON döndür, başka metin ekleme."""

    try:
        text = _gemini_text(prompt, api_key)
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            variants = json.loads(text[start:end])
            return variants[:count]
        return []
    except json.JSONDecodeError:
        # JSON parse hatası — ham metni döndür
        return [{"title": "Oluşturulan Senaryo", "description": "LLM yanıtı", "bdd_text": text}]
    except Exception as e:
        raise RuntimeError(f"Senaryo üretme hatası: {e}")


# ──────────────────────────────────────────────────────
# Ollama yardımcıları (paylaşılan — TestCaseGen ve benzeri modüller için)
# ──────────────────────────────────────────────────────

async def _ollama_post(payload: dict, timeout: float) -> str:
    cfg = get_ollama_config()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(cfg["url"], json={**payload, "model": payload.get("model") or cfg["model"]})
        resp.raise_for_status()
        return (resp.json().get("response") or "").strip()


async def ollama_generate_text(prompt: str, model: Optional[str] = None, timeout: float = 300.0) -> str:
    """Ollama'ya salt metin isteği gönderir, 'response' alanını döndürür."""
    return await _ollama_post({"model": model, "prompt": prompt, "stream": False}, timeout)


async def ollama_generate_vision(prompt: str, images_b64: List[str], model: Optional[str] = None, timeout: float = 300.0) -> str:
    """Ollama'ya görüntü(ler) + metin isteği gönderir (vision-capable model gerekir)."""
    return await _ollama_post({"model": model, "prompt": prompt, "images": images_b64, "stream": False}, timeout)


def get_embedding_config() -> dict:
    """Embedding modeli URL ve model adı (config > varsayılan)"""
    cfg = get_ai_config()
    return {
        "url": cfg.get("ollama_embed_url", "http://localhost:11434/api/embeddings"),
        "model": cfg.get("ollama_embed_model", "nomic-embed-text"),
    }


async def ollama_embed(text: str) -> Optional[List[float]]:
    """Embedding modeline istek atar; model kurulu değilse veya Ollama'ya ulaşılamazsa None döner
    (çağıran taraf bunu 'bilgi tabanını atla' olarak yorumlar, asla hata fırlatmaz)."""
    cfg = get_embedding_config()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(cfg["url"], json={"model": cfg["model"], "prompt": text})
            resp.raise_for_status()
            return resp.json().get("embedding")
    except Exception:
        return None
