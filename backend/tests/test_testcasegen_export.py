from services.testcasegen_service import build_export_workbook


def _sample_testcases():
    titles_by_id = {"t1": {"text": "Ödeme onaylanır"}}
    testcases = [{
        "id": "tc1",
        "title_id": "t1",
        "steps": [
            {"step_action": '"Devam" butonuna tıklanır', "step_expected": "Onay ekranı açılır"},
            {"step_action": '"Onayla" butonuna tıklanır', "step_expected": "İşlem tamamlanır"},
        ],
    }]
    return testcases, titles_by_id


def test_export_header_row():
    testcases, titles_by_id = _sample_testcases()
    wb = build_export_workbook(testcases, titles_by_id)
    ws = wb.active
    header = [cell.value for cell in ws[1]]
    assert header == [
        "ID", "Work Item Type", "Title", "Test Step",
        "Step Action", "Step Expected", "Area Path", "Assigned To", "State",
    ]
    assert ws[1][0].font.bold is True


def test_export_title_row_has_title_and_type_only():
    testcases, titles_by_id = _sample_testcases()
    wb = build_export_workbook(testcases, titles_by_id)
    ws = wb.active
    title_row = [cell.value for cell in ws[2]]
    assert title_row[1] == "Test Case"
    assert title_row[2] == "Ödeme onaylanır"
    assert title_row[3] is None  # Test Step boş
    assert title_row[4] is None  # Step Action boş


def test_export_step_rows_have_step_fields_only():
    testcases, titles_by_id = _sample_testcases()
    wb = build_export_workbook(testcases, titles_by_id)
    ws = wb.active
    step1_row = [cell.value for cell in ws[3]]
    assert step1_row[2] is None  # Title boş
    assert step1_row[3] == 1     # Test Step sıra no
    assert step1_row[4] == '"Devam" butonuna tıklanır'
    assert step1_row[5] == "Onay ekranı açılır"

    step2_row = [cell.value for cell in ws[4]]
    assert step2_row[3] == 2


def test_export_uses_arial_font():
    testcases, titles_by_id = _sample_testcases()
    wb = build_export_workbook(testcases, titles_by_id)
    ws = wb.active
    assert ws[3][4].font.name == "Arial"


def test_export_multiple_testcases_appended_sequentially():
    titles_by_id = {"t1": {"text": "Başlık 1"}, "t2": {"text": "Başlık 2"}}
    testcases = [
        {"id": "tc1", "title_id": "t1", "steps": [{"step_action": "A", "step_expected": "B"}]},
        {"id": "tc2", "title_id": "t2", "steps": [{"step_action": "C", "step_expected": "D"}]},
    ]
    wb = build_export_workbook(testcases, titles_by_id)
    ws = wb.active
    # satir1=header, satir2=tc1 baslik, satir3=tc1 step, satir4=tc2 baslik, satir5=tc2 step
    assert ws[4][2].value == "Başlık 2"
    assert ws[5][4].value == "C"
