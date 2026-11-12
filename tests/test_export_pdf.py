from datetime import date, datetime, timedelta

from workplanner.export_pdf import DETAIL, build_html, day_projects, export_pdf, join_notes

D = date(2026, 11, 9)


def row(h1, h2, project, activity, note, number="1", kind="work", billable=True):
    s, e = datetime(2026, 11, 9, h1), datetime(2026, 11, 9, h2)
    return {"date": D, "start": s, "end": e, "running": False, "kind": kind, "project": project,
            "project_number": number, "activity": activity, "note": note, "billable": billable,
            "devops_id": None, "duration": e - s, "lunch": timedelta()}


def test_join_notes_without_duplicates_and_blanks():
    assert join_notes(["a", " ", "b\nc", "a", None]) == "a; b c"


def test_project_once_per_day_with_activities_and_joined_notes():
    rows = [row(8, 9, "Zeta", "X", "n1"), row(9, 11, "alpha", "X", "n2"), row(11, 12, "Zeta", "X", "n3"),
            row(12, 13, "Zeta", "Y", ""), row(13, 14, "", "", "", kind="pause")]
    g = day_projects(rows)
    assert [p["project"] for p in g] == ["alpha", "Zeta"]
    zeta = g[1]
    assert zeta["duration"] == timedelta(hours=3)
    assert [(a["activity"], a["notes"], a["duration"]) for a in zeta["activities"]] == [
        ("X", "n1; n3", timedelta(hours=2)), ("Y", "", timedelta(hours=1))]
    html = build_html(rows, timedelta(hours=8), D, D)
    assert html.count("Zeta") == 2     # einmal in der Übersicht, einmal als Block des Tages (nicht je Tätigkeit)


def test_only_checked_columns_appear():
    rows = [row(8, 9, "A", "Tätig", "Notizx", number="42")]
    html = build_html(rows, timedelta(hours=8), D, D, mode=DETAIL, columns=["project", "duration"])
    assert "Tätig" not in html and "Notizx" not in html and "42" not in html and ">Dauer<" in html
    full = build_html(rows, timedelta(hours=8), D, D, mode=DETAIL, columns=["project", "activity", "note", "start"])
    assert "Tätig" in full and "Notizx" in full and "08:00–09:00" in full
    summary = build_html(rows, timedelta(hours=8), D, D, columns=["project", "duration"])
    assert "Notizx" not in summary


def test_html_escaping_and_modes():
    rows = [row(8, 9, "A & B", "T", "<b>x</b>")]
    summary = build_html(rows, timedelta(hours=8), D, D)
    detail = build_html(rows, timedelta(hours=8), D, D, mode=DETAIL)
    assert "A &amp; B" in summary and "&lt;b&gt;x&lt;/b&gt;" in summary and "&lt;b&gt;x&lt;/b&gt;" in detail


def test_export_pdf_writes_file(tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    out = tmp_path / "b.pdf"
    export_pdf(out, [row(8, 9, "A", "T", "n")], timedelta(hours=8), D, D, mode=DETAIL)
    assert out.read_bytes().startswith(b"%PDF")


def test_header_data_appears_and_is_escaped():
    rows = [row(8, 9, "A", "T", "n")]
    html = build_html(rows, timedelta(hours=8), D, D, header={"title": "Stunden <Juli>", "name": "Erika Muster",
                                                              "company": "", "extra": "PN 4711"})
    assert "Stunden &lt;Juli&gt;" in html and "Erika Muster" in html and "PN 4711" in html
    assert "Firma" not in html and "Zeitbericht" not in html
    assert "Zeitbericht" in build_html(rows, timedelta(hours=8), D, D)


def test_font_sizes_come_from_layout():
    rows = [row(8, 9, "A", "T", "n")]
    html = build_html(rows, timedelta(hours=8), D, D, layout={"heading": 14, "text": 9})
    assert "font-size:14pt" in html and "font-size:18pt" in html and "font-size:9pt" in html
    default = build_html(rows, timedelta(hours=8), D, D)
    assert "font-size:12pt" in default and "font-size:8pt" in default


def test_pdf_layout_setting_defaults_and_limits():
    from workplanner.db import Database
    from workplanner.service import TimeService
    svc = TimeService(Database())
    assert svc.pdf_layout == {"heading": 12, "text": 8, "landscape": True}
    svc.set_pdf_layout(40, 1, False)
    assert svc.pdf_layout == {"heading": 24, "text": 5, "landscape": False}


def test_pdf_header_setting_roundtrip(tmp_path):
    from workplanner.db import Database
    from workplanner.service import TimeService
    svc = TimeService(Database())
    assert svc.pdf_header == {"title": "", "name": "", "company": "", "extra": ""}
    svc.set_pdf_header({"title": " Bericht ", "name": "X", "unknown": "y"})
    assert svc.pdf_header["title"] == "Bericht" and svc.pdf_header["name"] == "X"
