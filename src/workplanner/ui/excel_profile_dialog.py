"""Assistent: Aufbau der eigenen Excel-Vorlage zuordnen (Beschriftungen per Klick in die Tabelle übernehmen),
testen, als Profil speichern sowie Profile exportieren und importieren."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLayout, QScrollArea,
                               QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..excel_timesheet import (DEFAULT_PROFILE, GRID_COLS, GRID_ROWS, IDENTIFY_MODES, ExcelError, ExcelProfile,
                               ProfileError, SheetView, _text, col_letter, describe_layout, detect_layout, display_text,
                               file_sheet_names, load_profile, month_of_sheet, read_sheet_view, save_profile)
from ..service import TimeService

ACCENT = "#2F5597"
STYLE = f"""
QDialog {{ background:#f6f8fc; color:#1f2a44; }}
QLabel {{ color:#1f2a44; }}
QScrollArea#side, QScrollArea#side > QWidget, #sideBody {{ background:transparent; border:none; }}
QLineEdit, QComboBox {{ border:1px solid #c9d3e6; border-radius:8px; padding:5px 8px; background:white; color:#1f2a44; }}
QLineEdit:focus, QComboBox:focus {{ border-color:{ACCENT}; }}
QPushButton {{ border:1px solid #c9d3e6; border-radius:8px; padding:6px 14px; background:white; color:#1f2a44; }}
QPushButton:hover {{ border-color:{ACCENT}; }}
QPushButton#primary {{ background:{ACCENT}; color:white; border:none; font-weight:600; padding:7px 20px; }}
QPushButton#primary:hover {{ background:#264a82; }}
QPushButton#pick {{ padding:4px 10px; color:{ACCENT}; }}
QPushButton#pick:checked {{ background:{ACCENT}; color:white; }}
QPushButton#show {{ padding:4px 10px; color:{ACCENT}; }}
QPushButton#show:checked {{ background:#ffc866; border:1px solid #e0a030; color:#3a2a00; font-weight:600; }}
QTableWidget {{ border:1px solid #c9d3e6; border-radius:8px; gridline-color:#e3e8f2; background:white; color:#000; }}
"""

# Beschriftungs-Felder: (Profilfeld, Titel, Hinweis)
LABEL_FIELDS = [
    ("header_number", "Spalte „Projektnummer“", "Überschrift der Spalte mit den Projektnummern"),
    ("header_name", "Spalte „Projektname“", "Überschrift der Spalte mit den Projektnamen"),
    ("section_start", "Hier beginnen die Projekte", "Beschriftung der Zeile direkt über den Projekten. Ab der "
                                                    "Zeile darunter entstehen neue Projektzeilen."),
    ("section_next", "Hier dürfen keine neuen Projekte mehr angelegt werden",
     "Beschriftung des nächsten Abschnitts. Darüber ist Schluss für neue Zeilen. Leer = bis zur Summenzeile."),
    ("section_total", "Summenzeile (optional, Ende der Suche)",
     "Beschriftung der Zeile unter allen Projekten; sie wird nie beschrieben. Nur nötig, wenn oben keine Grenze "
     "angegeben ist: Ist „Hier dürfen keine neuen Projekte mehr …“ gesetzt, kann die Summenzeile leer bleiben "
     "(oder fehlen)."),
    ("weekday_label", "Erster Wochentag", "Beschriftung „Mo“ über dem ersten Tag jedes Wochenblocks"),
]
SECTION_KEYS = ("section_start", "section_next", "section_total")   # wahlweise nach Text oder feste Zeile
MARK = QColor("#ffc866")   # „Zeigen“: was ein Feld in der Tabelle meint
SIDE_WIDTH = 440
TINT_NR, TINT_NAME, TINT_DAYS = QColor("#cfe0fb"), QColor("#e6dcf7"), QColor("#dcf2e1")


class _Rows(QVBoxLayout):
    """Beschriftung über dem Feld, beides in voller Breite (ein QFormLayout schneidet umbrochene Beschriftungen ab)."""

    def addRow(self, label: QWidget, field) -> None:
        self.addWidget(label)
        (self.addLayout if isinstance(field, QLayout) else self.addWidget)(field)
        self.addSpacing(6)


class ExcelProfileDialog(QDialog):
    def __init__(self, service: TimeService, parent=None, grid_loader=read_sheet_view, sheet_lister=file_sheet_names):
        super().__init__(parent)
        self.svc, self._load_grid, self._list_sheets = service, grid_loader, sheet_lister
        self._grid: list[list] = []
        self._view = SheetView([])
        self._layout = None                               # Ergebnis von „Testen“ (farbige Überlagerung)
        self._marks: dict[tuple[int, int], QColor] = {}   # „Zeigen“ (Zeile, Spalte) -> Farbe
        self._marked_key: str | None = None
        self._pick: QLineEdit | None = None
        self.profile: ExcelProfile = service.excel_profile
        self.setWindowTitle("Excel-Vorlage zuordnen")
        # Maximieren erlaubt (große Tabelle), Minimieren nicht (es ist ein Dialog)
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowCloseButtonHint
                            | Qt.WindowMaximizeButtonHint)
        self.resize(1300, 720)
        self.setStyleSheet(STYLE)

        intro = QLabel("<b>So geht’s:</b> Beispieldatei laden, bei jedem Feld rechts auf <b>◎</b> klicken und dann in der "
                       "Tabelle die passende Beschriftung anklicken. Mit <b>Testen</b> siehst du, wie die Vorlage erkannt "
                       "wird. Dann <b>Speichern</b>.")
        intro.setWordWrap(True)

        self.path = QLineEdit(service.excel_path)
        self.path.setPlaceholderText("Excel-Datei mit deiner Vorlage")
        browse = QPushButton("Datei …")
        browse.clicked.connect(self._browse)
        self.sheets = QComboBox()
        self.sheets.setMinimumWidth(160)
        self.sheets.activated.connect(lambda _: self._load())
        load = QPushButton("Laden")
        load.clicked.connect(self._load)
        top = QHBoxLayout()
        for w in (QLabel("Datei"), self.path, browse, QLabel("Blatt"), self.sheets, load):
            top.addWidget(w, 1 if w is self.path else 0)

        self.table = QTableWidget(GRID_ROWS, GRID_COLS)
        self.table.setHorizontalHeaderLabels([col_letter(c) for c in range(1, GRID_COLS + 1)])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setDefaultSectionSize(78)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.cellClicked.connect(self._cell_clicked)

        # --- Formular rechts
        self.name = QLineEdit()
        self.identify = QComboBox()
        for key, text in IDENTIFY_MODES.items():
            self.identify.addItem(text, key)
        self.pattern = QLineEdit()
        self.pattern.setToolTip("{monat} = Januar, {MM} = 01, {M} = 1, {jahr} = 2026")
        self.days = QComboBox()
        self.days.addItem("Automatisch erkennen (Mo–Sa oder Mo–So)", 0)
        self.days.addItem("6 Tage: Montag bis Samstag", 6)
        self.days.addItem("7 Tage: Montag bis Sonntag", 7)
        for box in (self.identify, self.days):   # lange Einträge dürfen die feste Seitenbreite nicht sprengen
            box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(12)
        form = _Rows()
        form.setSpacing(2)

        def label(text: str) -> QLabel:
            lab = QLabel(text)
            lab.setWordWrap(True)
            lab.setStyleSheet("color:#445")
            return lab

        form.addRow(label("Name dieses Profils"), self.name)
        form.addRow(label("Projekte tragen ein"), self.identify)
        form.addRow(label("Blattname je Monat"), self.pattern)
        form.addRow(label("Tage in Spalten"), self.days)
        self.edits: dict[str, QLineEdit] = {}
        self.field_labels: dict[str, QLabel] = {}
        self.picks: dict[str, QPushButton] = {}
        self.shows: dict[str, QPushButton] = {}
        self.modes: dict[str, QComboBox] = {}
        for key, title, hint in LABEL_FIELDS:
            edit, btn = QLineEdit(), QPushButton("◎")
            edit.setToolTip(hint)
            btn.setObjectName("pick")
            btn.setCheckable(True)
            btn.setFixedWidth(36)
            btn.setToolTip(f"{hint}\nKlicken, dann die Zelle in der Tabelle anklicken")
            btn.clicked.connect(lambda checked, k=key: self._start_pick(k, checked))
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            if key in SECTION_KEYS:   # „nach Text suchen“ oder „feste Zeile“
                mode = QComboBox()
                mode.addItem("Text", "text")
                mode.addItem("Zeile", "row")
                mode.setFixedWidth(84)
                mode.setToolTip("Text: die Zeile wird in jedem Blatt über diese Beschriftung gefunden.\n"
                                "Zeile: immer genau diese Zeilennummer, in allen Blättern.")
                mode.currentIndexChanged.connect(lambda _, k=key: self._mode_changed(k))
                self.modes[key] = mode
                row.addWidget(mode)
            show = QPushButton("Zeigen")
            show.setObjectName("show")
            show.setCheckable(True)   # orange, solange die Markierung dieses Feldes in der Tabelle aktiv ist
            self.shows[key] = show
            show.setToolTip("Markiert in der Tabelle, was dieses Feld meint (nochmal klicken: Markierung weg)")
            show.clicked.connect(lambda _, k=key: self._show_field(k))
            row.addWidget(show)
            row.addWidget(btn)
            lab = label(title)
            form.addRow(lab, row)
            self.edits[key], self.picks[key], self.field_labels[key] = edit, btn, lab
            edit.textChanged.connect(self._update_hints)
            edit.textChanged.connect(lambda _, k=key: self._clear_marks(k))
        self.identify.currentIndexChanged.connect(self._identify_changed)
        for w in (self.pattern,):
            w.textChanged.connect(self._clear_test)
        for w in (self.identify, self.days, *self.modes.values()):
            w.currentIndexChanged.connect(self._clear_test)
        for w in self.edits.values():
            w.textChanged.connect(self._clear_test)

        hint = QLabel("Beispiel: Steht in deiner Vorlage „Projekt verrechenbar“ über den Projekten und „Projekte nicht "
                      "verrechenbar“ darunter, dann ist das der erste Wert bei „Hier beginnen“ und der zweite bei "
                      "„Hier dürfen keine neuen Projekte mehr angelegt werden“. Vorhandene Projekte (mit Nummer) werden "
                      "bis zur Summenzeile automatisch gefunden.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#667")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.result = QLabel()
        self.result.setWordWrap(True)
        test = self.test_btn = QPushButton("Testen")
        test.setObjectName("pick")
        test.setCheckable(True)   # blau, solange die erkannte Struktur in der Tabelle eingefärbt ist
        test.setToolTip("Zeigt, wie die Vorlage erkannt wird (nochmal klicken: Farben wieder weg)")
        test.clicked.connect(self._test_clicked)
        reset = QPushButton("Standard")
        reset.setToolTip("Zurück auf das mitgelieferte Standardprofil")
        reset.clicked.connect(lambda: self._fill(DEFAULT_PROFILE))
        imp, exp = QPushButton("Importieren …"), QPushButton("Exportieren …")
        imp.clicked.connect(self._import)
        exp.clicked.connect(self._export)
        tools = QGridLayout()   # zwei Reihen, damit die Seite nicht breiter als ihr fester Platz wird
        for i, w in enumerate((test, reset, imp, exp)):
            tools.addWidget(w, i // 2, i % 2)

        side = QWidget()
        side.setObjectName("sideBody")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(8, 0, 0, 0)
        sl.addLayout(form)
        sl.addWidget(hint)
        sl.addLayout(tools)
        sl.addWidget(self.status)
        sl.addWidget(self.result)
        sl.addStretch(1)

        body = QHBoxLayout()
        body.addWidget(self.table, 1)
        scroll = QScrollArea()
        scroll.setObjectName("side")   # bei niedrigem Fenster lässt sich die rechte Seite scrollen
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(SIDE_WIDTH)   # die rechte Seite bleibt gleich breit, nur die Tabelle wächst mit
        self.side = scroll
        body.addWidget(scroll)

        self.save_btn = QPushButton("Speichern")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self._save)
        cancel = QPushButton("Abbrechen")
        cancel.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(cancel)
        bottom.addWidget(self.save_btn)

        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addLayout(top)
        lay.addLayout(body, 1)
        lay.addLayout(bottom)

        self._fill(self.profile)
        if service.excel_path:
            self._load(quiet=True)

    # --- Profil <-> Formular ------------------------------------------------------------------
    def _fill(self, profile: ExcelProfile) -> None:
        self.name.setText(profile.name)
        self.identify.setCurrentIndex(max(0, self.identify.findData(profile.identify)))
        self.pattern.setText(profile.sheet_pattern)
        self.days.setCurrentIndex(max(0, self.days.findData(profile.days_per_block)))
        for key, edit in self.edits.items():
            fixed = getattr(profile, key + "_row", 0) if key in SECTION_KEYS else 0
            if key in SECTION_KEYS:
                self.modes[key].blockSignals(True)
                self.modes[key].setCurrentIndex(1 if fixed else 0)
                self.modes[key].blockSignals(False)
            edit.setText(str(fixed) if fixed else getattr(profile, key))
        self._identify_changed()
        self._update_hints()

    def _row_mode(self, key: str) -> bool:
        return key in self.modes and self.modes[key].currentData() == "row"

    def _first_text_in_row(self, r: int) -> str:
        if not 1 <= r <= len(self._grid):
            return ""
        return next((_text(v) for v in self._grid[r - 1][:12] if _text(v)), "")

    def _find_row(self, label: str) -> int | None:
        text = label.strip().casefold()
        if not text:
            return None
        return next((r for r in range(1, len(self._grid) + 1)
                     if any(_text(v).casefold().startswith(text) for v in self._grid[r - 1][:12])), None)

    def _mode_changed(self, key: str) -> None:
        """Beim Umschalten den Wert mitnehmen: Text → Zeilennummer, in der der Text steht, und umgekehrt."""
        edit = self.edits[key]
        if self._row_mode(key):
            r = self._find_row(edit.text())
            edit.setText(str(r) if r else "")
        else:
            raw = edit.text().strip()
            edit.setText(self._first_text_in_row(int(raw)) if raw.isdigit() else "")
        self._update_hints()

    def _find_cell(self, key: str) -> tuple[int, int] | None:
        """(Zeile, Spalte) der Beschriftung des Feldes im geladenen Blatt (1-basiert) oder None."""
        text = self.edits[key].text().strip().casefold()
        if not text or not self._grid:
            return None
        if self._row_mode(key):
            return (int(text), 1) if text.isdigit() and 1 <= int(text) <= len(self._grid) else None
        exact = key == "weekday_label"
        rows = range(2, 9) if exact else range(1, len(self._grid) + 1)
        for r in rows:
            for c in range(1, min(12 if not exact else GRID_COLS, len(self._grid[r - 1])) + 1):
                cell = _text(self._grid[r - 1][c - 1]).casefold()
                if cell == text if exact else cell.startswith(text):
                    return r, c
        return None

    # --- „Zeigen“ -----------------------------------------------------------------------------
    def _sync_show_buttons(self) -> None:
        for k, b in self.shows.items():
            b.setChecked(k == self._marked_key)

    def _clear_marks(self, key: str | None = None) -> None:
        if self._marks and (key is None or key == self._marked_key):
            self._marks, self._marked_key = {}, None
            self._show_grid()
        self._sync_show_buttons()

    def marks_for(self, key: str) -> dict[tuple[int, int], QColor]:
        """Zellen, die das Feld meint: Grenzen = ganze Zeile, Spaltenüberschriften = ganze Spalte bis zum Ende der
        Projektzeilen, erster Wochentag = alle Wochenblöcke samt Kalenderwoche darüber."""
        cell = self._find_cell(key)
        if cell is None:
            return {}
        r, c = cell
        if key in SECTION_KEYS:
            return {(r, cc): MARK for cc in range(1, GRID_COLS + 1)}
        if key == "weekday_label":
            label = self.edits[key].text().strip()
            cols = [cc for cc in range(1, GRID_COLS + 1) if _text(self._grid[r - 1][cc - 1]) == label]
            return {(rr, cc): MARK for cc in cols for rr in (r - 1, r) if rr >= 1}
        end = r + 25                                    # Spaltenüberschrift: bis zum Ende der Projektzeilen
        try:
            sheet, year = self.sheets.currentText(), self.svc.now().year
            month = month_of_sheet(self.collect(), sheet, year) or self.svc.now().month
            end = detect_layout(self._grid, month, year, self.collect()).row_scan_end
        except ExcelError:
            pass
        return {(rr, c): MARK for rr in range(r, min(end, len(self._grid)) + 1)}

    def _show_field(self, key: str) -> None:
        title = next(t for k, t, _ in LABEL_FIELDS if k == key)
        if self._marked_key == key:                     # zweiter Klick: Markierung wieder weg
            self._clear_marks(key)
            self.status.setText("")
            return
        if not self._grid:
            self._load()
            if not self._grid:
                self._sync_show_buttons()
                return
        marks = self.marks_for(key)
        if not marks:
            self._clear_marks()
            self._error(f"„{title}“: In der Tabelle nicht gefunden – nichts zu markieren.")
            return
        self._marks, self._marked_key = marks, key
        self._sync_show_buttons()
        self._show_grid()
        r, c = min(marks)
        self.table.scrollTo(self.table.model().index(r - 1, c - 1))
        self.status.setText(f"Orange markiert: „{title}“ – {self.locate(key)}.")

    def locate(self, key: str) -> str | None:
        """Wo steht die Beschriftung des Feldes im geladenen Blatt? „Zeile 7“ bzw. „Spalte E (Zeile 6)“."""
        text = self.edits[key].text().strip()
        if not text or not self._grid:
            return None
        cell = self._find_cell(key)
        if cell is None:
            return "keine gültige Zeile" if self._row_mode(key) else "nicht gefunden"
        r, c = cell
        if self._row_mode(key):
            first = self._first_text_in_row(r)
            return f"Zeile {r}: „{first}“" if first else f"Zeile {r} (leer)"
        return f"Spalte {col_letter(c)} (Zeile {r})" if key.startswith(("header", "weekday")) else f"Zeile {r}"

    def _update_hints(self) -> None:
        for key, lab in self.field_labels.items():
            title = next(t for k, t, _ in LABEL_FIELDS if k == key)
            where = self.locate(key) if self.edits[key].isEnabled() else None
            if where is None:
                lab.setText(title)
            else:
                color = "#c0392b" if where in ("nicht gefunden", "keine gültige Zeile") else "#1e7e34"
                lab.setText(f"{title} <span style='color:{color};font-weight:600'>· {where}</span>")

    def _identify_changed(self) -> None:
        uses_number = self.identify.currentData() != "name"
        self.edits["header_number"].setEnabled(uses_number)
        self.picks["header_number"].setEnabled(uses_number)
        if hasattr(self, "field_labels"):
            self._update_hints()

    def collect(self) -> ExcelProfile:
        """Formular → Profil (wirft ProfileError, wenn etwas fehlt)."""
        values = {k: e.text().strip() for k, e in self.edits.items()}
        for key in SECTION_KEYS:   # feste Zeile: Zahl speichern, den Text des Profils unverändert lassen
            title = next(t for k, t, _ in LABEL_FIELDS if k == key)
            if self._row_mode(key):
                if not values[key].isdigit():
                    raise ProfileError(f"„{title}“: Bitte eine Zeilennummer eingeben.")
                values[key + "_row"], values[key] = int(values[key]), getattr(self.profile, key)
            else:
                values[key + "_row"] = 0
        if self.identify.currentData() == "name":
            values["header_number"] = self.profile.header_number or DEFAULT_PROFILE.header_number
        return replace(self.profile, name=self.name.text().strip(), identify=self.identify.currentData(),
                       sheet_pattern=self.pattern.text().strip(), days_per_block=self.days.currentData(),
                       **values).validate()

    # --- Datei und Tabelle --------------------------------------------------------------------
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Beispieldatei wählen", self.path.text(), "Excel (*.xlsx *.xlsm)")
        if path:
            self.path.setText(path)
            self._load(reload_sheets=True)

    def _error(self, text: str) -> None:
        self.status.setText(f"<span style='color:#c0392b'>⚠ {text}</span>")

    def _load(self, *, quiet: bool = False, reload_sheets: bool = False) -> None:
        path = self.path.text().strip()
        if not path:
            if not quiet:
                self._error("Bitte zuerst eine Excel-Datei wählen.")
            return
        try:
            if reload_sheets or not self.sheets.count():
                names = self._list_sheets(path)
                self.sheets.clear()
                self.sheets.addItems(names)
                year = self.svc.now().year
                month = self.svc.now().month
                guess = next((n for n in names if month_of_sheet(self._current_or_default(), n, year) == month), None)
                if guess:
                    self.sheets.setCurrentText(guess)
            loaded = self._load_grid(path, self.sheets.currentText())   # SheetView (oder nur ein Raster ohne Format)
            self._view = loaded if isinstance(loaded, SheetView) else SheetView(loaded)
            self._grid = self._view.grid
        except Exception as ex:  # noqa: BLE001 – Datei fehlt, gesperrt, keine Excel-Datei …
            self._grid, self._view = [], SheetView([])
            if not quiet:
                self._error(f"Datei nicht lesbar: {ex}")
            return
        self._layout, self._marks, self._marked_key = None, {}, None
        self._sync_show_buttons()
        self._sync_test_button()
        self._show_grid()
        self._update_hints()
        self.status.setText(f"Blatt „{self.sheets.currentText()}“ geladen.")

    def _current_or_default(self) -> ExcelProfile:
        try:
            return self.collect()
        except ExcelError:
            return self.profile

    def _show_grid(self) -> None:
        """Zeigt das Blatt wie in Excel (Farben, Schrift, Breiten, verbundene Zellen); nach „Testen“ liegt die
        erkannte Struktur als farbige Überlagerung darüber."""
        view, t = self._view, self.table
        t.clearSpans()
        t.clearContents()
        for c in range(1, GRID_COLS + 1):
            t.setColumnWidth(c - 1, view.col_px.get(c, 78) or 0)
        for r in range(1, GRID_ROWS + 1):
            t.setRowHeight(r - 1, view.row_px.get(r, 22))
        tints: dict[tuple[int, int], QColor] = {}
        layout = self._layout
        if layout is not None:
            for r in range(layout.row_first, layout.row_scan_end + 1):
                for cols, tint in (([layout.col_nr], TINT_NR), ([layout.col_name], TINT_NAME),
                                   (layout.day_cols, TINT_DAYS)):
                    for c in cols:
                        if c:
                            tints[r, c] = tint
        tints.update(self._marks)   # „Zeigen“ liegt über der Erkennungsfarbe
        for r, row in enumerate(self._grid, 1):
            for c, value in enumerate(row, 1):
                style, tint = view.styles.get((r, c)), tints.get((r, c))
                text = display_text(value)
                if not (text or style or tint):
                    continue
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                bg = QColor(style.bg) if style and style.bg else None
                if tint is not None:   # Überlagerung: eigene Füllung bleibt zur Hälfte sichtbar
                    base = bg or QColor("white")
                    bg = QColor((base.red() + tint.red()) // 2, (base.green() + tint.green()) // 2,
                                (base.blue() + tint.blue()) // 2)
                if (r, c) in self._marks:   # „Zeigen“ deckt die Zelle ganz ab, damit man es sofort sieht
                    bg = self._marks[r, c]
                if bg is not None:
                    item.setBackground(QBrush(bg))
                if style:
                    if style.fg:
                        item.setForeground(QBrush(QColor(style.fg)))
                    if style.bold or style.italic:
                        font = QFont(t.font())
                        font.setBold(style.bold)
                        font.setItalic(style.italic)
                        item.setFont(font)
                    if style.align in ("left", "center", "right"):
                        item.setTextAlignment({"left": Qt.AlignLeft, "center": Qt.AlignHCenter,
                                               "right": Qt.AlignRight}[style.align] | Qt.AlignVCenter)
                t.setItem(r - 1, c - 1, item)
        for r1, c1, r2, c2 in view.merges:
            t.setSpan(r1 - 1, c1 - 1, r2 - r1 + 1, c2 - c1 + 1)

    # --- Klick-Zuordnung ----------------------------------------------------------------------
    def _start_pick(self, key: str, on: bool) -> None:
        for k, b in self.picks.items():
            b.setChecked(on and k == key)
        self._pick = self.edits[key] if on else None
        title = next(t for k, t, _ in LABEL_FIELDS if k == key)
        self.status.setText(f"Klicke jetzt in der Tabelle auf die Zelle für „{title}“ …" if on else "")

    def _cell_clicked(self, row: int, col: int) -> None:
        if self._pick is None:
            return
        key = next(k for k, e in self.edits.items() if e is self._pick)
        if self._row_mode(key):   # feste Zeile: egal, in welcher Spalte geklickt wird
            self._pick.setText(str(row + 1))
            for b in self.picks.values():
                b.setChecked(False)
            self._pick = None
            self.status.setText(f"✓ Zeile {row + 1} übernommen.")
            return
        text = _text(self._grid[row][col]) if row < len(self._grid) and col < len(self._grid[row]) else ""
        if not text:
            self._error("Diese Zelle ist leer – bitte eine Zelle mit Beschriftung anklicken.")
            return
        self._pick.setText(text)
        for b in self.picks.values():
            b.setChecked(False)
        self._pick = None
        self.status.setText(f"✓ „{text}“ übernommen ({col_letter(col + 1)}{row + 1}).")

    # --- Testen / Speichern / Export / Import -------------------------------------------------
    def _sync_test_button(self) -> None:
        self.test_btn.setChecked(self._layout is not None)

    def _clear_test(self, *_) -> None:
        """Die Einfärbung der erkannten Struktur gehört zum Stand beim Testen: wird etwas geändert, ist sie veraltet."""
        if self._layout is not None:
            self._layout = None
            self.result.setText("")
            self._show_grid()
        self._sync_test_button()

    def _test_clicked(self) -> None:
        if self._layout is not None:    # Knopf war aktiv: Farben wieder weg
            self._clear_test()
            return
        self._test()
        self._sync_test_button()

    def _test(self) -> None:
        try:
            profile = self.collect()
        except ExcelError as ex:
            self._error(str(ex))
            return
        if not self._grid:
            self._load()
            if not self._grid:
                return
        sheet, year = self.sheets.currentText(), self.svc.now().year
        month = month_of_sheet(profile, sheet, year)
        note = ""
        if month is None:
            month = self.svc.now().month
            note = (f"<br><span style='color:#8a5a00'>Der Blattname „{sheet}“ passt nicht zum Blattnamen-Muster – "
                    f"getestet wie für {month:02d}/{year}.</span>")
        try:
            layout = detect_layout(self._grid, month, year, profile)
        except ExcelError as ex:
            self._layout = None
            self._show_grid()
            self.result.setText(f"<span style='color:#c0392b'>✗ Nicht erkannt: {ex}</span>" + note)
            return
        self._layout = layout
        self._sync_test_button()
        self._show_grid()
        self.result.setText("<span style='color:#1e7e34'>✓ Vorlage erkannt.</span> " + describe_layout(layout)
                            + "<br><span style='color:#667'>Blau: Nummer · Violett: Name · Grün: Tage</span>" + note)

    def _save(self) -> None:
        try:
            self.profile = self.collect()
        except ExcelError as ex:
            self._error(str(ex))
            return
        self.svc.set_excel_profile(self.profile)
        self.accept()

    def export_to(self, path: str) -> None:
        save_profile(self.collect(), path)

    def import_from(self, path: str) -> None:
        self.profile = load_profile(path)
        self._fill(self.profile)

    def _export(self) -> None:
        try:
            profile = self.collect()
        except ExcelError as ex:
            self._error(str(ex))
            return
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in profile.name).strip() or "Profil"
        path, _ = QFileDialog.getSaveFileName(self, "Profil exportieren", f"{safe}.wpprofile.json",
                                              "WorkPlanner-Profil (*.wpprofile.json *.json)")
        if path:
            try:
                self.export_to(path)
                self.status.setText(f"✓ Profil exportiert: {path}")
            except OSError as ex:
                self._error(f"Konnte nicht speichern: {ex}")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Profil importieren", "",
                                              "WorkPlanner-Profil (*.wpprofile.json *.json)")
        if not path:
            return
        try:
            self.import_from(path)
        except ExcelError as ex:
            self._error(str(ex))
            return
        self.status.setText("✓ Profil importiert – mit „Testen“ prüfen, dann „Speichern“.")
