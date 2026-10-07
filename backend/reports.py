from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import os, json, hashlib
from .event_policy import annotate
from .report_i18n import MESSAGES

LABELS = {
    "sound_activity": "Ұзақ дауыс белсенділігі — тексеру қажет",
    "sustained_noise": "Ұзақ қатты шу — дыбыс үзіндісін тексеріңіз",
    "identity_mismatch": "Фотоға тіркелген бетпен сәйкеспейді",
    "presentation_attack": "Фото немесе экрандағы бейне күдігі",
    "application_closed": "Бөгде бағдарлама жабылды",
    "application_close_failed": "Бағдарламаны жабу расталмады",
    "foreground_changed": "Экрандағы белсенді бағдарлама өзгерді",
    "remote_control_blocked": "Қашықтан басқару бұғатталды",
    "screen_capture_error": "Экран жазбасы тоқтады",
    "session_started": "Емтихан басталды",
    "phone_detected": "Телефон анықталды",
    "phone_raised": "Телефон экран алдына көтерілді",
    "face_absent": "Бет кадрда көрінбейді",
    "multiple_faces": "Екінші бет анықталды",
    "gaze_down": "Төмен қарай ұзақ қарау",
    "gaze_side": "Экраннан басқа жаққа қарау",
    "camera_obscured": "Камера бейнесі жарамсыз",
    "camera_disconnected": "Камера ажыратылды",
    "usb_connected": "Сыртқы құрылғы қосылды",
    "usb_removed": "Сыртқы құрылғы ажыратылды",
    "shortcut_blocked": "Перне әрекеті бұғатталды",
    "focus_lost": "Емтихан терезесі фокусты жоғалтты",
    "display_changed": "Монитор конфигурациясы өзгерді",
    "forbidden_process": "Рұқсатсыз қолданба",
    "guard_lost": "Қорғаныс қызметі тоқтады",
    "session_interrupted": "Сессия үзілді",
    "navigation_blocked": "Рұқсатсыз бет бұғатталды",
    "window_blocked": "Жаңа терезе бұғатталды",
    "download_blocked": "Файл жүктеу бұғатталды",
    "camera_pipeline_error": "Камера өңдеу қатесі",
}


def payload(store, sid):
    session = store.session(sid)
    return {
        "schema": "sergek-report/1",
        "session": session,
        "events": [annotate(event) for event in store.events(sid)],
        "integrity_ok": store.integrity(sid),
        "answers": store.answers(sid),
        "meaning": "Observations for human review; not an automatic cheating verdict.",
    }


def pdf_report(store, sid, lang="kk"):
    if lang not in {"kk", "ru", "en"}:
        raise ValueError("Unsupported report language")

    def text(value):
        return value if lang == "kk" else MESSAGES.get(value, {}).get(lang, value)

    states = {"preflight": "Дайындық", "active": "Белсенді", "completed": "Аяқталды", "interrupted": "Үзілді", "pending": "Тексерілмеген", "confirmed": "Расталды", "dismissed": "Негізсіз"}
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib import colors

    font = "Helvetica"
    for path in [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]:
        if path.exists():
            if "Sergek" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("Sergek", str(path)))
            font = "Sergek"
            break
    data = payload(store, sid)
    session = data["session"]
    styles = getSampleStyleSheet()
    for name in ["Normal", "Title", "Heading2"]:
        styles[name].fontName = font
    normal = styles["Normal"]
    normal.fontSize = 9
    normal.leading = 13
    stream = BytesIO()
    document = SimpleDocTemplate(
        stream,
        title="Sergek Proctor report",
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    def p(value):
        return Paragraph(escape(text(str(value))), normal)

    flow = [Paragraph(text("Sergек Proctor — сессия есебі"), styles["Title"]), Spacer(1, 16)]
    fields = [
        ("Студент", session["data"]["student"]),
        ("Емтихан", session["data"]["exam"]),
        ("Платформа", session["data"]["platform"]),
        ("Күй", text(states.get(session["status"], session["status"]))),
        ("Дайындалды (UTC)", session["created"]),
        ("Басталды (UTC)", session.get('started') or '—'),
        ("Аяқталды (UTC)", session["ended"] or "—"),
        ("Журнал тұтастығы", "OK" if data["integrity_ok"] else "FAILED"),
    ]
    for key, value in fields:
        flow.append(p(f"{text(key)}: {value}"))
    flow += [
        Spacer(1, 16),
        p(
            "Оқиғалар — мұғалім тексеруіне арналған бақылау нәтижелері. Автоматты айыптау немесе бағаны өзгерту жүргізілмейді."
        ),
        Spacer(1, 16),
    ]
    rows = [[p("Уақыт (UTC)"), p("Оқиға"), p("Шешім және пікір")]]
    for event in data["events"]:
        if not event["requires_review"]:
            continue
        rows.append(
            [
                p(event["created"][11:19]),
                p(LABELS.get(event["kind"], event["kind"])),
                p(text(states.get(event["verdict"], event["verdict"])) + " " + event["note"]),
            ]
        )
    if len(rows) == 1:
        rows.append([p("—"), p("Тексерілетін оқиға жоқ"), p("—")])
    table = Table(rows, colWidths=[65, 220, 220], repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eff9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d8dfeb")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    flow.append(table)
    flow.append(Spacer(1, 14))
    flow.append(p(f"{text('Техникалық жазбалар')}: {sum(not event['requires_review'] for event in data['events'])}. {text('Толық журнал JSON есебінде және мұғалім панелінде сақталған.')}"))
    flow.append(
        p(
            text("Қорғаныс тексерісі") + ": "
            + json.dumps(session["data"].get("preflight", {}), ensure_ascii=False)
        )
    )
    document.build(flow)
    return stream.getvalue()
