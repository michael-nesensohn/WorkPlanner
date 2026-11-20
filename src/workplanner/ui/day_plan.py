"""Tagesplan: die Einträge eines Tages als Blöcke auf einer Zeitachse (wie ein Kalender), 15-Minuten-Raster.

Block ziehen verschiebt ihn, obere/untere Kante ändert Start bzw. Ende, Doppelklick bearbeitet einen Eintrag, Doppelklick
auf eine Lücke (gestrichelt, hellblau) legt dort einen Eintrag an. Die Ansicht ändert selbst nichts: sie meldet die
neuen Zeiten über Signale, das Hauptfenster speichert sie über den Dienst."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QScrollArea, QSizePolicy, QToolTip, QWidget

from ..service import TimeService
from ..timeline import PAUSE, Entry
from . import theme

SNAP_MIN = 15          # Rasterung in Minuten
PX_PER_MIN = 1.15      # Höhe: 69 Pixel je Stunde
AXIS_W = 58
EDGE = 7               # Pixel an Ober-/Unterkante eines Blocks, die als Griff zum Ändern gelten
DRAG_START = 4         # erst ab so vielen Pixeln Bewegung wird gezogen (ein Klick ändert nichts)


class _Colors:
    """Farben des Plans; folgen dem eingestellten Design (hell/dunkel) bei jedem Zeichnen."""
    @property
    def ink(self): return theme.qcolor("#1f2937")
    @property
    def muted(self): return theme.qcolor("#66708a")
    @property
    def accent(self): return theme.qcolor("#2F5597")
    @property
    def grid(self): return theme.qcolor("#e6ebf3")
    @property
    def grid_hour(self): return theme.qcolor("#c9d3e0")
    @property
    def gap_fill(self): return theme.qcolor("#e8f1fc")
    @property
    def gap_line(self): return theme.qcolor("#9db9e3")
    @property
    def run(self): return theme.qcolor("#1b7f3b")
    @property
    def surface(self): return QColor(theme.PANEL) if theme.is_dark() else QColor("#ffffff")
    @property
    def pause_fill(self): return theme.qcolor("#e4e7ee")
    @property
    def pause_line(self): return theme.qcolor("#c3ccdd")
    @property
    def pause_text(self): return theme.qcolor("#5b647a")
    @property
    def block_base(self): return self.surface   # Projektfarbe wird damit abgeschwächt


COL = _Colors()


def _mix(color: QColor, other: QColor, share: float) -> QColor:
    """`share` Anteil von `other` in `color` (0 = color, 1 = other)."""
    return QColor(round(color.red() + (other.red() - color.red()) * share),
                  round(color.green() + (other.green() - color.green()) * share),
                  round(color.blue() + (other.blue() - color.blue()) * share))


def _fmt(dt: datetime) -> str:
    return f"{dt:%H:%M}"


def _dur(delta: timedelta) -> str:
    minutes = max(0, round(delta.total_seconds() / 60))
    return f"{minutes // 60}:{minutes % 60:02d}"


def _cut(fm: QFontMetrics, line: str, rest: str, width: int) -> str:
    """`line` als letzte sichtbare Zeile, die mit „…“ endet, weil danach noch `rest` folgt."""
    cut = fm.elidedText(f"{line} {rest}".strip(), Qt.ElideRight, width)
    if cut.endswith("…"):
        return cut
    return fm.elidedText(line, Qt.ElideRight, width - fm.horizontalAdvance(" …")) + " …"


def _wrap(text: str, fm: QFontMetrics, width: int, max_lines: int) -> list[str]:
    """Bricht `text` auf Zeilen der Breite `width` um; passt es nicht in `max_lines`, endet die letzte Zeile mit „…“."""
    if max_lines <= 0 or width <= 0:
        return []
    lines: list[str] = []
    paragraphs = [p for p in text.splitlines() if p.strip()]
    for pi, para in enumerate(paragraphs):
        words, current = para.split(), ""
        for wi, word in enumerate(words):
            trial = f"{current} {word}".strip()
            if fm.horizontalAdvance(trial) <= width or not current:
                current = trial
                continue
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                rest = " ".join([word] + words[wi + 1:] + paragraphs[pi + 1:])
                lines[-1] = _cut(fm, lines[-1], rest, width)
                return lines
        lines.append(current)
        if len(lines) == max_lines:
            if pi + 1 < len(paragraphs):   # weitere Absätze gekürzt
                lines[-1] = _cut(fm, lines[-1], " ".join(paragraphs[pi + 1:]), width)
            else:
                lines[-1] = fm.elidedText(lines[-1], Qt.ElideRight, width)
            return lines
    return lines


class _Canvas(QWidget):
    selection_changed = Signal(list)       # [Eintrags-IDs]
    edit_requested = Signal(int)
    gap_requested = Signal(object, object)  # von, bis (datetime)
    retimed = Signal(int, object, object)  # ID, neuer Start, neues Ende (None = läuft weiter)

    def __init__(self, service: TimeService):
        super().__init__()
        self.svc = service
        self.day = date.today()
        self.entries: list[Entry] = []
        self.now = datetime.now()
        self.selected: set[int] = set()
        self.t0 = datetime.combine(self.day, time(8))
        self.t1 = datetime.combine(self.day, time(16))
        self.labels: dict[int, tuple[str, str, str, QColor]] = {}
        self.drag: dict | None = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # --- Daten ---------------------------------------------------------------------------------
    def set_data(self, day: date, entries: list[Entry], now: datetime) -> None:
        self.day, self.entries, self.now, self.drag = day, list(entries), now, None
        midnight = datetime.combine(day, time.min)
        end_of_day = midnight + timedelta(days=1)
        starts = [e.start for e in entries] or [midnight + timedelta(hours=8)]
        ends = [e.end or now for e in entries] or [midnight + timedelta(hours=16)]
        if midnight <= now < end_of_day:
            ends.append(now)
        first, last = min(starts) - timedelta(minutes=30), max(ends) + timedelta(minutes=30)
        t0 = max(midnight, first.replace(minute=0, second=0, microsecond=0))
        t1 = min(end_of_day, (last + timedelta(minutes=59)).replace(minute=0, second=0, microsecond=0))
        while t1 - t0 < timedelta(hours=6):   # nicht zu knapp, damit der Plan nicht winzig wird
            if t1 < end_of_day:
                t1 += timedelta(hours=1)
            elif t0 > midnight:
                t0 -= timedelta(hours=1)
            else:
                break
        self.t0, self.t1 = t0, t1
        self.labels = {}
        for e in entries:
            if e.kind == PAUSE:
                self.labels[e.id] = (self.svc.entry_label(e), "", "", QColor("#c3ccdd"))
            else:
                color = QColor(self.svc.project_color(e.project_id) or "#4f8cff")
                self.labels[e.id] = (self.svc.project_display(e.project_id, e.start.date()) or "–",
                                     self.svc.activity_name(e.activity_id),
                                     e.note.strip(), color)
        self.setFixedHeight(int((self.t1 - self.t0).total_seconds() / 60 * PX_PER_MIN) + 2)
        self.update()

    def set_now(self, now: datetime) -> None:
        self.now = now
        self.update()

    def set_selected(self, ids: set[int]) -> None:
        if ids != self.selected:
            self.selected = set(ids)
            self.update()

    # --- Geometrie -----------------------------------------------------------------------------
    def y_of(self, dt: datetime) -> float:
        return (dt - self.t0).total_seconds() / 60 * PX_PER_MIN

    def time_at(self, y: float) -> datetime:
        return self.t0 + timedelta(minutes=y / PX_PER_MIN)

    def _rect(self, start: datetime, end: datetime, *, min_h: float = 18) -> QRectF:
        top = self.y_of(start)
        return QRectF(AXIS_W + 8, top + 1, max(40, self.width() - AXIS_W - 18), max(min_h, self.y_of(end) - top - 2))

    def _end(self, e: Entry) -> datetime:
        return e.end or self.now

    def gaps(self) -> list[tuple[datetime, datetime]]:
        return self.svc.gaps(self.entries)

    def _hit(self, pos: QPointF):
        """(Eintrag, Zone) unter dem Mauszeiger; Zone: "top", "bot" oder "move". Bei einer Lücke (None, "gap")."""
        for e in self.entries:
            r = self._rect(e.start, self._end(e))
            if r.contains(pos):
                edge = min(EDGE, r.height() / 3)
                if pos.y() - r.top() <= edge:
                    return e, "top"
                if r.bottom() - pos.y() <= edge and not e.running:
                    return e, "bot"
                return e, "move"
        for a, b in self.gaps():
            if self._rect(a, b, min_h=14).contains(pos):
                return (a, b), "gap"
        return None, ""

    def _limits(self, e: Entry) -> tuple[datetime, datetime]:
        """Frühester Start und spätestes Ende: bis zum Nachbarn, zum Tagesende bzw. (heute) bis jetzt."""
        i = self.entries.index(e)
        midnight = datetime.combine(self.day, time.min)
        lo = self._end(self.entries[i - 1]) if i > 0 else midnight
        hi = self.entries[i + 1].start if i + 1 < len(self.entries) else midnight + timedelta(days=1)
        return lo, min(hi, self.now.replace(second=0, microsecond=0))

    def _snap(self, dt: datetime) -> datetime:
        minutes = (dt - datetime.combine(self.day, time.min)).total_seconds() / 60
        return datetime.combine(self.day, time.min) + timedelta(minutes=round(minutes / SNAP_MIN) * SNAP_MIN)

    # --- Zeichnen ------------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), COL.surface)
        font = QFont(self.font())
        font.setPixelSize(12)
        p.setFont(font)
        small = QFont(font)
        small.setPixelSize(11)
        total = int((self.t1 - self.t0).total_seconds() / 60)
        for m in range(0, total + 1, SNAP_MIN):
            y = m * PX_PER_MIN
            at = self.t0 + timedelta(minutes=m)
            hour = at.minute == 0
            p.setPen(QPen(COL.grid_hour if hour else COL.grid, 1, Qt.SolidLine if hour or at.minute == 30 else Qt.DotLine))
            p.drawLine(QPointF(AXIS_W, y), QPointF(self.width(), y))
            if hour:
                p.setPen(COL.muted)
                p.setFont(small)
                p.drawText(QRectF(0, y - 8, AXIS_W - 8, 16), Qt.AlignRight | Qt.AlignVCenter, f"{at:%H:%M}")
        p.setPen(QPen(COL.grid_hour, 1))
        p.drawLine(QPointF(AXIS_W, 0), QPointF(AXIS_W, self.height()))
        p.setFont(font)

        for a, b in self.gaps():                                                      # Lücken (zuerst, liegen darunter)
            r = self._rect(a, b, min_h=14)
            p.setBrush(COL.gap_fill)
            p.setPen(QPen(COL.gap_line, 1.5, Qt.DashLine))
            p.drawRoundedRect(r, 8, 8)
            if r.height() >= 18:
                p.setPen(COL.accent)
                p.drawText(r, Qt.AlignCenter, f"Lücke  {_fmt(a)}–{_fmt(b)}  ·  {_dur(b - a)}")

        for e in self.entries:
            title, activity, note, color = self.labels[e.id]
            end = self._end(e)
            r = self._rect(e.start, end)
            pause = e.kind == PAUSE
            fill = COL.pause_fill if pause else _mix(color, COL.block_base, 0.80)
            border = COL.pause_line if pause else color
            if e.running:
                border = COL.run
            p.setBrush(fill)
            p.setPen(QPen(border, 2 if e.running else 1.2))
            p.drawRoundedRect(r, 8, 8)
            if e.id in self.selected:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(COL.accent, 2.2))
                p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 10, 10)
            text = COL.pause_text if pause else COL.ink
            times = f"{_fmt(e.start)}–{'läuft' if e.running else _fmt(end)}  ·  {_dur(end - e.start)}"
            inner = r.adjusted(10, 3, -8, -2)
            fm = QFontMetrics(font)
            if r.height() < 38:     # eine Zeile: Titel, Zeit und Notiz (so weit sie passt)
                line = f"{title}   {times}" + (f"   ·   {' '.join(note.split())}" if note else "")
                p.setPen(text)
                p.drawText(inner, Qt.AlignVCenter | Qt.AlignLeft, fm.elidedText(line, Qt.ElideRight, int(inner.width())))
                continue
            bold = QFont(font)
            bold.setBold(True)
            p.setFont(bold)
            p.setPen(text)
            p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 16), Qt.AlignVCenter,
                       QFontMetrics(bold).elidedText(title, Qt.ElideRight, int(inner.width())))
            p.setFont(small)
            p.setPen(COL.run if e.running else COL.muted if not pause else text)
            p.drawText(QRectF(inner.left(), inner.top() + 16, inner.width(), 15), Qt.AlignVCenter, times)
            sfm = QFontMetrics(small)
            room = int((inner.height() - 32) // 15)            # so viele Zeilen passen unter Titel und Zeit
            lines = ([activity] if activity and room > 0 else [])
            lines += _wrap(note, sfm, int(inner.width()), room - len(lines))
            p.setPen(text)
            for i, line in enumerate(lines):
                p.drawText(QRectF(inner.left(), inner.top() + 32 + 15 * i, inner.width(), 15), Qt.AlignVCenter,
                           sfm.elidedText(line, Qt.ElideRight, int(inner.width())))
            p.setFont(font)

        if self.t0 <= self.now <= self.t1 and self.now.date() == self.day:             # „jetzt“
            y = self.y_of(self.now)
            p.setPen(QPen(COL.run, 2))
            p.drawLine(QPointF(AXIS_W - 4, y), QPointF(self.width(), y))
            p.setBrush(COL.run)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(AXIS_W, y), 4, 4)

        if self.drag and self.drag["active"]:                                          # Hinweis beim Ziehen
            d = self.drag
            text = f"{_fmt(d['start'])}–{'läuft' if d['end'] is None else _fmt(d['end'])}"
            if d["end"] is not None:
                text += f"  ·  {_dur(d['end'] - d['start'])}"
            w = QFontMetrics(font).horizontalAdvance(text) + 16
            box = QRectF(min(d["pos"].x() + 14, self.width() - w - 4), d["pos"].y() + 14, w, 22)
            p.setBrush(QColor("#1f2937"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QColor("#ffffff"))
            p.drawText(box, Qt.AlignCenter, text)
        p.end()

    def event(self, ev) -> bool:
        """Hinweis beim Darüberfahren: vollständige Angaben des Eintrags samt ganzer Notiz."""
        if ev.type() == QEvent.ToolTip:
            hit, zone = self._hit(QPointF(ev.pos()))
            if isinstance(hit, Entry):
                title, activity, note, _ = self.labels[hit.id]
                end = self._end(hit)
                head = f"<b>{title}</b><br>{_fmt(hit.start)}–{'läuft' if hit.running else _fmt(end)} · {_dur(end - hit.start)}"
                if activity:
                    head += f"<br>{activity}"
                if note:
                    head += "<br><br>" + note.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
                QToolTip.showText(ev.globalPos(), f"<div style='max-width:420px'>{head}</div>", self)
            else:
                QToolTip.hideText()
            return True
        return super().event(ev)

    # --- Maus ----------------------------------------------------------------------------------
    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton:
            return
        hit, zone = self._hit(ev.position())
        if isinstance(hit, Entry):
            ids = set(self.selected)
            if ev.modifiers() & Qt.ControlModifier:
                ids ^= {hit.id}
            elif hit.id not in ids:
                ids = {hit.id}
            self.selected = ids
            self.selection_changed.emit(sorted(ids))
            self.update()
            if len(ids) == 1 or not (ev.modifiers() & Qt.ControlModifier):
                self.drag = {"e": hit, "mode": zone, "y0": ev.position().y(), "active": False, "pos": ev.position(),
                             "start": hit.start, "end": hit.end, "limits": self._limits(hit)}
        elif not (ev.modifiers() & Qt.ControlModifier):
            self.selected = set()
            self.selection_changed.emit([])
            self.update()

    def mouseMoveEvent(self, ev) -> None:
        d = self.drag
        if d is None:
            hit, zone = self._hit(ev.position())
            self.setCursor(Qt.SizeVerCursor if zone in ("top", "bot") else
                           Qt.OpenHandCursor if zone == "move" and not hit.running else
                           Qt.PointingHandCursor if zone == "gap" else Qt.ArrowCursor)
            return
        if not d["active"] and abs(ev.position().y() - d["y0"]) < DRAG_START:
            return
        e, mode = d["e"], d["mode"]
        if mode == "move" and e.running:
            return    # die laufende Aufgabe lässt sich nicht verschieben (nur ihr Start ändern)
        d["active"], d["pos"] = True, ev.position()
        lo, hi = d["limits"]
        shift = timedelta(minutes=(ev.position().y() - d["y0"]) / PX_PER_MIN)
        end0 = e.end
        if mode == "move":
            length = end0 - e.start
            start = max(lo, min(self._snap(e.start + shift), hi - length))
            d["start"], d["end"] = start, start + length
        elif mode == "top":
            limit = (end0 or self.now.replace(second=0, microsecond=0)) - timedelta(minutes=SNAP_MIN)
            d["start"], d["end"] = max(lo, min(self._snap(e.start + shift), limit)), end0
        else:
            d["start"] = e.start
            d["end"] = max(e.start + timedelta(minutes=SNAP_MIN), min(self._snap(end0 + shift), hi))
        self.setCursor(Qt.ClosedHandCursor if mode == "move" else Qt.SizeVerCursor)
        # Vorschau: der Block steht schon an der neuen Stelle
        for i, x in enumerate(self.entries):
            if x.id == e.id:
                self.entries[i] = replace(x, start=d["start"], end=d["end"])
        self.update()

    def mouseReleaseEvent(self, ev) -> None:
        d, self.drag = self.drag, None
        self.setCursor(Qt.ArrowCursor)
        if d is None or not d["active"]:
            return
        e = d["e"]
        if (d["start"], d["end"]) != (e.start, e.end):
            self.retimed.emit(e.id, d["start"], d["end"])
        else:
            self.update()

    def mouseDoubleClickEvent(self, ev) -> None:
        self.drag = None
        hit, zone = self._hit(ev.position())
        if isinstance(hit, Entry):
            self.edit_requested.emit(hit.id)
        elif zone == "gap":
            self.gap_requested.emit(*hit)


class DayPlan(QScrollArea):
    """Rollbare Tagesansicht; reicht die Signale der Zeichenfläche durch."""
    selection_changed = Signal(list)
    edit_requested = Signal(int)
    gap_requested = Signal(object, object)
    retimed = Signal(int, object, object)

    def __init__(self, service: TimeService):
        super().__init__()
        self.canvas = _Canvas(service)
        self.setWidget(self.canvas)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setStyleSheet("QScrollArea{background:#ffffff;border:1px solid #dde3ee;border-radius:10px}")
        self.setToolTip("Block ziehen: verschieben · Kante ziehen: Start/Ende ändern (15-Minuten-Raster) · "
                        "Doppelklick: bearbeiten, auf eine Lücke: Eintrag anlegen")
        for name in ("selection_changed", "edit_requested", "gap_requested", "retimed"):
            getattr(self.canvas, name).connect(getattr(self, name))
        self._shown_day: date | None = None

    def set_data(self, day: date, entries: list[Entry], now: datetime) -> None:
        bar = self.verticalScrollBar()
        keep = bar.value()
        self.canvas.set_data(day, entries, now)
        if day != self._shown_day:       # anderer Tag: oben beginnen, sonst bleibt die Lage
            self._shown_day = day
            bar.setValue(0)
        else:
            bar.setValue(keep)

    def set_now(self, now: datetime) -> None:
        self.canvas.set_now(now)

    def set_selected(self, ids: set[int]) -> None:
        self.canvas.set_selected(ids)
