"""PDF-Bericht über Qt (`QTextDocument` → `QPdfWriter`), also ohne zusätzliche Bibliothek.

Zwei Arten:
- **zusammengefasst**: je Tag und Projekt ein Block – Projektzeile mit der Gesamtdauer, darunter je Tätigkeit die
  verbundenen Notizen (das Projekt steht also nur einmal);
- **einzeln**: je Tag alle Einträge als Tabelle.
Es erscheinen nur die Spalten, die in den Berichten angehakt sind."""
from __future__ import annotations

from datetime import date, timedelta
from html import escape
from pathlib import Path

ACCENT = "#2F5597"
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
SUMMARY, DETAIL = "summary", "detail"
DEFAULT_COLUMNS = ["date", "duration", "billable", "project_number", "project", "activity", "note", "devops"]


def fmt_hm(d: timedelta) -> str:
    minutes = round(d.total_seconds() / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def join_notes(notes) -> str:
    """Notizen einer Gruppe hintereinander, ohne Wiederholungen und leere Einträge."""
    seen: list[str] = []
    for n in notes:
        text = " ".join((n or "").split())
        if text and text not in seen:
            seen.append(text)
    return "; ".join(seen)


def day_projects(rows: list[dict]) -> list[dict]:
    """Arbeitseinträge eines Tages: je Projekt (A–Z) die Gesamtdauer und darunter je Tätigkeit Dauer und Notizen."""
    projects: dict[str, dict] = {}
    for r in sorted((r for r in rows if r["kind"] == "work"), key=lambda r: r["start"]):
        p = projects.setdefault(r["project"], {"project": r["project"], "number": r["project_number"] or "",
                                               "duration": timedelta(), "billable": timedelta(), "activities": {}})
        a = p["activities"].setdefault(r["activity"] or "", {"activity": r["activity"] or "",
                                                              "duration": timedelta(), "notes": []})
        p["duration"] += r["duration"]
        a["duration"] += r["duration"]
        if r["billable"]:
            p["billable"] += r["duration"]
        a["notes"].append(r["note"])
    out = []
    for p in sorted(projects.values(), key=lambda p: (p["project"] or "").casefold()):
        acts = sorted(p["activities"].values(), key=lambda a: a["activity"].casefold())
        out.append({**p, "activities": [{**a, "notes": join_notes(a["notes"])} for a in acts]})
    return out


def _th(text: str, align: str = "left", width: str = "") -> str:
    w = f' width="{width}"' if width else ""
    return f'<th align="{align}"{w} bgcolor="{ACCENT}" style="color:#ffffff;padding:3px">{escape(text)}</th>'


def _td(text: str, align: str = "left", style: str = "", extra: str = "") -> str:
    return f'<td align="{align}" valign="top"{extra} style="color:#222222;padding:3px;{style}">{escape(text)}</td>'


def _table(inner: str, size: str = "") -> str:
    return (f'<table width="100%" cellspacing="0" cellpadding="0" border="1" '
            f'style="border-color:#c8d0e0;{size}">{inner}</table>')


def _day_totals(day_rows: list[dict]) -> tuple[timedelta, timedelta]:
    work = sum((r["duration"] for r in day_rows if r["kind"] == "work"), timedelta())
    pause = sum((r["duration"] for r in day_rows if r["kind"] == "pause"), timedelta()) \
        + sum((r["lunch"] for r in day_rows), timedelta())
    return work, pause


def _summary_table(day_rows: list[dict], cols: set[str]) -> str:
    """Je Projekt eine Kopfzeile (Nummer, Name, Gesamtdauer), darunter je Tätigkeit die Notizen."""
    show_dur = "duration" in cols
    show_act, show_note = "activity" in cols, "note" in cols
    head = _th("Tätigkeit", width="22%") if show_act else ""
    head += _th("Notizen", width="66%" if show_dur else "78%") if show_note else ""
    head += _th("Dauer", "right", "12%") if show_dur else ""
    span = max(head.count("<th"), 1)
    rows = [f"<tr>{head}</tr>"] if head else []
    for p in day_projects(day_rows):
        title = " · ".join(x for x in (p["number"] if "project_number" in cols else "",
                                       p["project"] if "project" in cols else "") if x) or "(Projekt)"
        if "billable" in cols and p["billable"]:
            title += f"  –  davon verrechenbar {fmt_hm(p['billable'])}"
        both = show_dur and span > 1
        cells = _td(title, style="font-weight:700;", extra=f' bgcolor="#e6ecf7" colspan="{span - 1 if both else span}"')
        if both:
            cells += _td(fmt_hm(p["duration"]), "right", "font-weight:700;", ' bgcolor="#e6ecf7"')
        rows.append(f"<tr>{cells}</tr>")
        if head:
            for a in p["activities"]:
                c = (_td(a["activity"]) if show_act else "") + (_td(a["notes"]) if show_note else "")
                c += _td(fmt_hm(a["duration"]), "right") if show_dur else ""
                rows.append(f"<tr>{c}</tr>")
    return _table("".join(rows))


def _detail_table(day_rows: list[dict], cols: set[str], show_pauses: bool) -> str:
    shown = sorted((r for r in day_rows if show_pauses or r["kind"] == "work"), key=lambda r: r["start"])
    spec = []   # (Titel, Ausrichtung, Breite, Wert)
    if cols & {"start", "end"}:
        spec.append(("Zeit", "left", 14,
                     lambda r: f"{r['start']:%H:%M}–{r['end']:%H:%M}" + (" (läuft)" if r["running"] else "")))
    if "project_number" in cols:
        spec.append(("Projektnr.", "left", 12, lambda r: r["project_number"] or ""))
    if "project" in cols:
        spec.append(("Projekt", "left", 20, lambda r: r["project"]))
    if "activity" in cols:
        spec.append(("Tätigkeit", "left", 15, lambda r: r["activity"] or ""))
    if "billable" in cols:
        spec.append(("Verr.", "center", 7, lambda r: "Ja" if r["billable"] else "Nein" if r["kind"] == "work" else ""))
    if "duration" in cols:
        spec.append(("Dauer", "right", 8, lambda r: fmt_hm(r["duration"])))
    if "devops" in cols:
        spec.append(("DevOps", "left", 8, lambda r: str(r["devops_id"] or "")))
    if "note" in cols:
        spec.append(("Notiz", "left", 0, lambda r: " ".join((r["note"] or "").split())))
    if not spec or not shown:
        return ""
    fixed = sum(w for _, _, w, _ in spec)
    rows = ["<tr>" + "".join(_th(t, a, f"{w or max(100 - fixed, 20)}%") for t, a, w, _ in spec) + "</tr>"]
    for r in shown:
        style = "color:#777777;" if r["kind"] == "pause" else ""
        rows.append("<tr>" + "".join(_td(f(r), a, style) for _, a, _, f in spec) + "</tr>")
    return _table("".join(rows), "font-size:8pt;")


def build_html(rows: list[dict], daily_target: timedelta, first: date, last: date, project_name: str = "",
               mode: str = SUMMARY, columns: list[str] | None = None, show_pauses: bool = False,
               header: dict[str, str] | None = None) -> str:
    """HTML des Berichts. `header`: Kopfdaten aus den Einstellungen (title, name, company, extra). `rows` wie von `TimeService.report_rows` (inklusive Pausen); `columns` sind die angehakten
    Schlüssel aus `export.COLUMNS`."""
    cols = set(DEFAULT_COLUMNS if columns is None else columns)
    work_rows = [r for r in rows if r["kind"] == "work"]
    total = sum((r["duration"] for r in work_rows), timedelta())
    billable = sum((r["duration"] for r in work_rows if r["billable"]), timedelta())
    _, pause_total = _day_totals(rows)
    head = {k: (v or "").strip() for k, v in (header or {}).items()}
    lines = [f"{label}: <b>{escape(head[key])}</b>" for key, label in
             (("name", "Name"), ("company", "Firma / Abteilung")) if head.get(key)]
    if head.get("extra"):
        lines.append(escape(head["extra"]))
    out = [f'<h1 style="color:{ACCENT}">{escape(head.get("title") or "Zeitbericht")}</h1>']
    if lines:
        out.append(f'<p style="color:#222222">{"<br>".join(lines)}</p>')
    project = f" · Projekt: <b>{escape(project_name)}</b>" if project_name else ""
    billable_text = f" · davon verrechenbar: <b>{fmt_hm(billable)} h</b>" if "billable" in cols else ""
    out.append(f'<p style="color:#222222">Zeitraum: <b>{first:%d.%m.%Y} – {last:%d.%m.%Y}</b>{project}<br>'
               f'Arbeitszeit (ohne Pausen): <b>{fmt_hm(total)} h</b>{billable_text}'
               f' · Pausen: {fmt_hm(pause_total)} h</p>')

    totals: dict[str, dict] = {}   # Summe je Projekt über den ganzen Zeitraum
    for r in work_rows:
        t = totals.setdefault(r["project"], {"number": r["project_number"] or "", "d": timedelta(), "b": timedelta()})
        t["d"] += r["duration"]
        if r["billable"]:
            t["b"] += r["duration"]
    if totals:
        spec = ([("Projektnr.", "left")] if "project_number" in cols else []) + [("Projekt", "left")] \
            + ([("Dauer", "right")] if "duration" in cols else []) \
            + ([("davon verrechenbar", "right")] if "billable" in cols else [])
        out.append(f'<h2 style="color:{ACCENT}">Summe je Projekt</h2>')
        body = ["<tr>" + "".join(_th(t, a) for t, a in spec) + "</tr>"]

        def line(number, name, d, b, style=""):
            cells = (_td(number, style=style) if "project_number" in cols else "")
            cells += _td(name, style=style or "font-weight:600")
            cells += _td(fmt_hm(d), "right", style) if "duration" in cols else ""
            cells += _td(fmt_hm(b), "right", style) if "billable" in cols else ""
            return f"<tr>{cells}</tr>"
        for name in sorted(totals, key=str.casefold):
            body.append(line(totals[name]["number"], name, totals[name]["d"], totals[name]["b"]))
        body.append(line("", "Gesamt", total, billable, "font-weight:700;"))
        out.append(_table("".join(body)))

    for d in sorted({r["date"] for r in rows}):
        day_rows = [r for r in rows if r["date"] == d]
        work, pause = _day_totals(day_rows)
        out.append(f'<h3 style="color:{ACCENT}">{WEEKDAYS[d.weekday()]}, {d:%d.%m.%Y}'
                   f' &nbsp;–&nbsp; Arbeitszeit {fmt_hm(work)} h{f" · Pausen {fmt_hm(pause)} h" if pause else ""}</h3>')
        out.append(_summary_table(day_rows, cols) if mode == SUMMARY else _detail_table(day_rows, cols, show_pauses))
    if not rows:
        out.append('<p style="color:#555555">Im gewählten Zeitraum gibt es keine Einträge.</p>')
    return ('<html><body style="font-family:Segoe UI,Arial;font-size:9pt;color:#222222">'
            + "\n".join(out) + "</body></html>")


def export_pdf(path: str | Path, rows: list[dict], daily_target: timedelta, first: date, last: date,
               project_name: str = "", mode: str = SUMMARY, columns: list[str] | None = None,
               show_pauses: bool = False, header: dict[str, str] | None = None) -> None:
    """Schreibt den Bericht als A4-PDF. Braucht eine QGuiApplication (die Oberfläche läuft ohnehin)."""
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
    writer.setResolution(120)
    writer.setTitle((header or {}).get("title") or "Zeitbericht")
    doc = QTextDocument()
    doc.setHtml(build_html(rows, daily_target, first, last, project_name, mode, columns, show_pauses, header))
    doc.print_(writer)
