from io import BytesIO
import pytest
from pypdf import PdfReader
from backend.store import Store
from backend.reports import pdf_report


@pytest.mark.parametrize("lang,title,phone,state", [
    ("kk", "сессия есебі", "Телефон анықталды", "Тексерілмеген"),
    ("ru", "отчёт о сессии", "Обнаружен телефон", "Не проверено"),
    ("en", "session report", "Phone detected", "Pending review"),
])
def test_pdf_language_preserves_data_and_review_separation(tmp_path, lang, title, phone, state):
    store = Store(tmp_path / "report.db")
    session = store.create_session({"student": "Мейірбек Example", "exam": "Exam Қазақша", "platform": "moodle"})
    store.add_event(session["id"], "phone_detected", {"confidence": .9, "duration_seconds": 3})
    store.add_event(session["id"], "navigation_blocked", {"host": "example.org"})
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf_report(store, session["id"], lang))).pages)
    for value in [title, phone, state, "Мейірбек Example", "Exam Қазақша"]:
        assert value in text
    assert "example.org" not in text
    assert store.events(session["id"])[0]["kind"] == "phone_detected"


def test_invalid_pdf_language_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unsupported report language"):
        pdf_report(Store(tmp_path / "report.db"), "irrelevant", "invalid")
