from services.testcasegen_service import score_title


def test_transaction_screen_scores_high():
    score, level = score_title("Tutar girilip onaylanır", "", screen_index=0)
    assert level == "high"


def test_info_only_screen_scores_low():
    score, level = score_title("Hakkımızda sayfası görüntülenir", "", screen_index=0)
    assert level == "low"


def test_negative_potential_raises_score_to_at_least_medium():
    score, level = score_title("Zorunlu alan doğrulaması yapılır", "", screen_index=0)
    assert level in ("medium", "high")


def test_depth_penalty_lowers_score_for_later_screens():
    score_early, _ = score_title("Tutar girilip onaylanır", "", screen_index=0)
    score_late, _ = score_title("Tutar girilip onaylanır", "", screen_index=10)
    assert score_late < score_early


def test_screen_note_contributes_to_scoring():
    score_with_note, _ = score_title("Ekran açılır", "tutar onaylanır", screen_index=0)
    score_without_note, _ = score_title("Ekran açılır", "", screen_index=0)
    assert score_with_note > score_without_note


def test_score_is_rounded_to_two_decimals():
    score, _ = score_title("Herhangi bir ekran", "", screen_index=0)
    assert score == round(score, 2)
