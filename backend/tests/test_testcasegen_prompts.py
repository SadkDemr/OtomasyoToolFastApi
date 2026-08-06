from services.testcasegen_service import (
    build_title_extraction_prompt,
    build_rationale_prompt,
    build_testcase_prompt,
)


def test_title_extraction_prompt_requires_json_only():
    prompt = build_title_extraction_prompt("", "", "")
    assert "JSON" in prompt
    assert "screen_titles" in prompt
    assert "candidate_titles" in prompt
    assert "screen_summary" in prompt


def test_title_extraction_prompt_includes_previous_screen_context():
    prompt = build_title_extraction_prompt("bu ekran onay ekranı", "önceki not", "önceki özet")
    assert "önceki not" in prompt
    assert "önceki özet" in prompt
    assert "bu ekran onay ekranı" in prompt


def test_rationale_prompt_asks_for_explanation_not_decision():
    prompt = build_rationale_prompt("Ödeme onaylanır", "high", 4.5)
    assert "gerekçe" in prompt.lower()
    assert "Ödeme onaylanır" in prompt
    assert "high" in prompt


def test_testcase_prompt_includes_all_four_rules():
    screens = [{"index": 0, "summary": "Ekranda tutar ve onay butonu var", "note": "not yok"}]
    prompt = build_testcase_prompt("Ödeme onaylanır", screens)
    assert "pasif" in prompt.lower()
    assert "@Param" in prompt or "@" in prompt
    assert "Step Expected" in prompt
    assert "Ödeme onaylanır" in prompt


def test_testcase_prompt_requires_json_steps_schema():
    screens = [{"index": 0, "summary": "ozet", "note": "not"}]
    prompt = build_testcase_prompt("Baslik", screens)
    assert "steps" in prompt
    assert "step_action" in prompt
    assert "step_expected" in prompt


def test_testcase_prompt_multi_screen_includes_all_screens_in_order():
    screens = [
        {"index": 0, "summary": "Login ekranı", "note": ""},
        {"index": 1, "summary": "Diğer İşlemler menüsü", "note": ""},
        {"index": 2, "summary": "Kar Payı Hesapla ekranı", "note": ""},
    ]
    prompt = build_testcase_prompt("Kar Payı Hesaplama Akışı", screens)
    assert "Login ekranı" in prompt
    assert "Diğer İşlemler menüsü" in prompt
    assert "Kar Payı Hesapla ekranı" in prompt
    assert prompt.index("Login ekranı") < prompt.index("Diğer İşlemler menüsü") < prompt.index("Kar Payı Hesapla ekranı")


def test_testcase_prompt_single_screen_has_no_flow_instruction():
    screens = [{"index": 0, "summary": "tek ekran", "note": ""}]
    prompt = build_testcase_prompt("Baslik", screens)
    assert "SIRAYLA" not in prompt


def test_testcase_prompt_forbids_echoing_screen_context_and_gives_example():
    screens = [{"index": 0, "summary": "", "note": "Hesaplama Araçları"}]
    prompt = build_testcase_prompt("Baslik", screens)
    assert "KOPYALAMA" in prompt
    assert "ÖRNEK" in prompt
