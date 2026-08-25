import io

import openpyxl
import pytest
from docx import Document as DocxDocument
from docx.shared import Inches
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage

from services import testcasegen_service as svc


def _png_bytes(color="red", size=(20, 10)):
    buf = io.BytesIO()
    PILImage.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


def _make_docx_bytes(paragraphs, table_rows=None):
    doc = DocxDocument()
    for p in paragraphs:
        doc.add_paragraph(p)
    if table_rows:
        table = doc.add_table(rows=0, cols=len(table_rows[0]))
        for row in table_rows:
            cells = table.add_row().cells
            for i, val in enumerate(row):
                cells[i].text = val
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_xlsx_bytes(sheet_name, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_text_from_docx_reads_paragraphs_and_tables():
    data = _make_docx_bytes(
        ["Giris ekrani kullanici adi ve sifre alir.", "Onayla butonuna basilinca giris yapilir."],
        table_rows=[["Alan", "Zorunlu"], ["Kullanici Adi", "Evet"]],
    )
    text, truncated = svc.extract_text_from_docx(data)
    assert "Giris ekrani kullanici adi ve sifre alir." in text
    assert "Kullanici Adi | Evet" in text
    assert truncated is False


def test_extract_text_from_docx_truncates_long_text():
    data = _make_docx_bytes(["a" * (svc.DOC_TEXT_CHAR_LIMIT + 20000)])
    text, truncated = svc.extract_text_from_docx(data)
    assert len(text) == svc.DOC_TEXT_CHAR_LIMIT
    assert truncated is True


def test_extract_text_from_xlsx_keeps_every_sheet_when_one_sheet_is_huge():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws1 = wb.create_sheet("BuyukSayfa")
    for i in range(400):
        ws1.append([f"satir{i}", "x" * 200])
    ws2 = wb.create_sheet("KucukSayfa")
    ws2.append(["Login", "Kullanici giris yapar"])
    buf = io.BytesIO()
    wb.save(buf)

    text, truncated = svc.extract_text_from_xlsx(buf.getvalue())
    assert "Sayfa: BuyukSayfa" in text
    assert "Sayfa: KucukSayfa" in text
    assert "Login | Kullanici giris yapar" in text
    assert truncated is True


def test_extract_text_from_docx_invalid_bytes_raises_value_error():
    with pytest.raises(ValueError):
        svc.extract_text_from_docx(b"not a docx file")


def test_extract_text_from_xlsx_reads_sheet_rows():
    data = _make_xlsx_bytes("Analiz", [["Ekran", "Aksiyon"], ["Login", "Kullanici giris yapar"]])
    text, truncated = svc.extract_text_from_xlsx(data)
    assert "Sayfa: Analiz" in text
    assert "Login | Kullanici giris yapar" in text
    assert truncated is False


def test_extract_text_from_xlsx_invalid_bytes_raises_value_error():
    with pytest.raises(ValueError):
        svc.extract_text_from_xlsx(b"not an xlsx file")


def test_extract_images_from_xlsx_finds_images_across_sheets():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws1 = wb.create_sheet("Sayfa1")
    img1 = XLImage(io.BytesIO(_png_bytes("red")))
    img1.anchor = "A1"
    ws1.add_image(img1)
    ws2 = wb.create_sheet("Sayfa2")
    img2 = XLImage(io.BytesIO(_png_bytes("blue")))
    img2.anchor = "B2"
    ws2.add_image(img2)
    buf = io.BytesIO()
    wb.save(buf)

    images = svc.extract_images_from_xlsx(buf.getvalue())
    assert len(images) == 2
    for data, ext in images:
        assert ext == ".png"
        assert data.startswith(b"\x89PNG")


def test_extract_images_from_xlsx_no_images_returns_empty_list():
    data = _make_xlsx_bytes("Analiz", [["Ekran", "Aksiyon"]])
    assert svc.extract_images_from_xlsx(data) == []


def test_extract_images_from_xlsx_invalid_bytes_returns_empty_list():
    assert svc.extract_images_from_xlsx(b"not an xlsx file") == []


def test_extract_images_from_docx_finds_embedded_image():
    doc = DocxDocument()
    doc.add_paragraph("Ekran goruntusu asagida")
    doc.add_picture(io.BytesIO(_png_bytes("green")), width=Inches(1))
    buf = io.BytesIO()
    doc.save(buf)

    images = svc.extract_images_from_docx(buf.getvalue())
    assert len(images) == 1
    data, ext = images[0]
    assert ext == ".png"
    assert data.startswith(b"\x89PNG")


def test_extract_images_from_docx_no_images_returns_empty_list():
    data = _make_docx_bytes(["Sadece metin, gorsel yok."])
    assert svc.extract_images_from_docx(data) == []


def test_extract_images_from_docx_invalid_bytes_returns_empty_list():
    assert svc.extract_images_from_docx(b"not a docx file") == []
