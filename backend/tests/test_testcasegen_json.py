from services.testcasegen_service import clean_json_text, extract_json_object


def test_clean_json_text_strips_markdown_fence_with_lang():
    raw = "```json\n{\"a\": 1}\n```"
    assert clean_json_text(raw) == '{"a": 1}'


def test_clean_json_text_strips_plain_fence():
    raw = "```\n{\"a\": 1}\n```"
    assert clean_json_text(raw) == '{"a": 1}'


def test_clean_json_text_passthrough_when_no_fence():
    raw = '{"a": 1}'
    assert clean_json_text(raw) == '{"a": 1}'


def test_extract_json_object_parses_clean_json():
    result = extract_json_object('{"screen_titles": [{"screen_index": 0}]}')
    assert result == {"screen_titles": [{"screen_index": 0}]}


def test_extract_json_object_parses_fenced_json_with_surrounding_text():
    raw = 'Iste sonuc:\n```json\n{"screen_titles": []}\n```\nTesekkurler.'
    result = extract_json_object(raw)
    assert result == {"screen_titles": []}


def test_extract_json_object_returns_none_on_invalid_json():
    assert extract_json_object("bu bir JSON degil") is None


def test_extract_json_object_returns_none_on_empty_string():
    assert extract_json_object("") is None
