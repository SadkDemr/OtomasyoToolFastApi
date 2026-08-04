from services.testcasegen_service import validate_steps


def test_valid_step_has_no_violations():
    steps = [{"step_action": '"Devam" butonuna tıklanır', "step_expected": "Onay ekranı açılır"}]
    result = validate_steps(steps)
    assert result[0]["violations"] == []


def test_imperative_mood_is_flagged():
    steps = [{"step_action": '"Devam" butonuna tıkla', "step_expected": "Onay ekranı açılır"}]
    result = validate_steps(steps)
    rules = [v["rule"] for v in result[0]["violations"]]
    assert "imperative_mood" in rules


def test_passive_mood_synonyms_are_not_flagged():
    for action in ['"Kaydet" tıklanır', "Form doldurulur", "Sayfa açılır", "Metin yazılır"]:
        result = validate_steps([{"step_action": action, "step_expected": "Sonuç görülür"}])
        rules = [v["rule"] for v in result[0]["violations"]]
        assert "imperative_mood" not in rules, f"'{action}' yanlış işaretlendi"


def test_missing_at_notation_for_variable_is_flagged():
    steps = [{"step_action": "Güncel kur alanı kontrol edilir", "step_expected": "Kur görüntülenir"}]
    result = validate_steps(steps)
    rules = [v["rule"] for v in result[0]["violations"]]
    assert "missing_variable_notation" in rules


def test_at_notation_present_is_not_flagged():
    steps = [{"step_action": "@güncel_kur alanı kontrol edilir", "step_expected": "Kur görüntülenir"}]
    result = validate_steps(steps)
    rules = [v["rule"] for v in result[0]["violations"]]
    assert "missing_variable_notation" not in rules


def test_multiple_actions_in_one_step_is_flagged():
    steps = [{"step_action": '"Ad" alanına yazılır ve "Devam" tıklanır', "step_expected": "Sonraki ekran açılır"}]
    result = validate_steps(steps)
    rules = [v["rule"] for v in result[0]["violations"]]
    assert "multiple_actions" in rules


def test_empty_step_expected_is_flagged():
    steps = [{"step_action": '"Devam" butonuna tıklanır', "step_expected": ""}]
    result = validate_steps(steps)
    rules = [v["rule"] for v in result[0]["violations"]]
    assert "empty_expected" in rules


def test_whitespace_only_step_expected_is_flagged():
    steps = [{"step_action": '"Devam" butonuna tıklanır', "step_expected": "   "}]
    result = validate_steps(steps)
    rules = [v["rule"] for v in result[0]["violations"]]
    assert "empty_expected" in rules


def test_validate_steps_preserves_original_fields():
    steps = [{"step_action": "X", "step_expected": "Y"}]
    result = validate_steps(steps)
    assert result[0]["step_action"] == "X"
    assert result[0]["step_expected"] == "Y"
