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
    prompt = build_testcase_prompt("Ödeme onaylanır", "Ekranda tutar ve onay butonu var", "not yok")
    assert "pasif" in prompt.lower()
    assert "@Param" in prompt or "@" in prompt
    assert "Step Expected" in prompt
    assert "Ödeme onaylanır" in prompt


def test_testcase_prompt_requires_json_steps_schema():
    prompt = build_testcase_prompt("Baslik", "ozet", "not")
    assert "steps" in prompt
    assert "step_action" in prompt
    assert "step_expected" in prompt
