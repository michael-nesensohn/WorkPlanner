import hashlib
import io
import json
import time
import urllib.error

import pytest
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from workplanner import updater
from workplanner._version import __version__
from workplanner.updater import Release, UpdateError


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


INSTALLER = b"MZ-fake-installer" * 1000
SHA = hashlib.sha256(INSTALLER).hexdigest()
URL = f"{updater.DOWNLOAD_PREFIX}v9.9.9/WorkPlanner-Setup-9.9.9.exe"


class Response(io.BytesIO):
    def __init__(self, payload: bytes):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def release_json(**over):
    data = {"tag_name": "v9.9.9", "body": "## Neu\n- etwas", "html_url": updater.PAGE + "/releases/tag/v9.9.9",
            "assets": [{"name": "WorkPlanner-Handbuch.pdf", "browser_download_url": updater.DOWNLOAD_PREFIX + "x.pdf"},
                       {"name": "WorkPlanner-Setup-9.9.9.exe", "browser_download_url": URL,
                        "digest": "sha256:" + SHA}]}
    data.update(over)
    return data


def opener_for(payload=None, error=None):
    def opener(request, timeout=None):
        if error:
            raise error
        return Response(payload)
    return opener


def test_version_parsing_and_comparison():
    assert updater.parse_version("v0.1.10") == (0, 1, 10)
    assert updater.is_newer("0.1.10", "0.1.9") and not updater.is_newer("v0.1.6", "0.1.6")
    assert updater.is_newer("0.2.0", "0.1.99") and not updater.is_newer("0.1.5", "0.1.6")
    with pytest.raises(UpdateError):
        updater.parse_version("latest")


def test_fetch_latest_reads_installer_and_checksum():
    rel = updater.fetch_latest(opener_for(json.dumps(release_json()).encode()))
    assert (rel.version, rel.asset, rel.url, rel.sha256) == ("9.9.9", "WorkPlanner-Setup-9.9.9.exe", URL, SHA)
    assert "Neu" in rel.notes


@pytest.mark.parametrize("change, message", [
    ({"assets": []}, "keinen Installer"),
    ({"assets": [{"name": "WorkPlanner-Setup-9.9.9.exe", "browser_download_url": "https://evil.example/x.exe",
                  "digest": "sha256:" + SHA}]}, "nicht im Repository"),
    ({"assets": [{"name": "WorkPlanner-Setup-9.9.9.exe", "browser_download_url": URL}]}, "keine Prüfsumme"),
    ({"tag_name": "nightly"}, "Versionsangabe"),
])
def test_fetch_latest_rejects_unsafe_or_unusable_releases(change, message):
    with pytest.raises(UpdateError, match=message):
        updater.fetch_latest(opener_for(json.dumps(release_json(**change)).encode()))


def test_fetch_latest_reports_network_and_http_errors():
    with pytest.raises(UpdateError, match="nicht erreichbar"):
        updater.fetch_latest(opener_for(error=urllib.error.URLError("kein Netz")))
    with pytest.raises(UpdateError, match="noch kein Release"):
        updater.fetch_latest(opener_for(error=urllib.error.HTTPError(updater.API, 404, "nf", {}, None)))


def make_release():
    return Release("v9.9.9", "9.9.9", "Notizen", updater.PAGE, "WorkPlanner-Setup-9.9.9.exe", URL, SHA)


def test_download_verifies_the_checksum(tmp_path):
    progress = []
    path = updater.download(make_release(), lambda d, t: progress.append((d, t)), opener_for(INSTALLER), tmp_path)
    assert path.read_bytes() == INSTALLER and progress[-1] == (len(INSTALLER), len(INSTALLER))
    bad = Release("v9.9.9", "9.9.9", "", updater.PAGE, "WorkPlanner-Setup-9.9.9.exe", URL, "0" * 64)
    with pytest.raises(UpdateError, match="Prüfsumme"):
        updater.download(bad, None, opener_for(INSTALLER), tmp_path)
    assert not (tmp_path / "WorkPlanner-Setup-9.9.9.exe").exists()      # falsche Datei wird gelöscht


def wait(qapp, condition, seconds=3):
    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_about_dialog_checks_only_on_click_and_installs_only_on_click(qapp, tmp_path):
    from workplanner.ui.about_dialog import AboutDialog
    calls, installed = [], []
    rel = make_release()

    def fetch():
        calls.append("fetch")
        return rel

    def download(release, progress=None):
        calls.append("download")
        return tmp_path / release.asset
    d = AboutDialog(None, fetch=fetch, download=download, install=installed.append)
    d.show()
    qapp.processEvents()
    assert calls == [] and "Michael Nesensohn" in d.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)[1].text()
    d.check_btn.click()                                              # erst auf Klick wird gesucht
    assert wait(qapp, lambda: d.update_btn.isVisibleTo(d))
    assert calls == ["fetch"] and not installed                       # gefunden, aber noch nichts geladen
    assert "9.9.9" in d.update_btn.text() and d.notes.isVisibleTo(d)
    d.update_btn.click()                                             # erst auf Klick wird aktualisiert
    assert wait(qapp, lambda: installed)
    assert calls == ["fetch", "download"] and installed == [tmp_path / rel.asset]


def test_about_dialog_up_to_date_and_errors(qapp):
    from workplanner.ui.about_dialog import AboutDialog
    same = Release(f"v{__version__}", __version__, "", updater.PAGE, "WorkPlanner-Setup-1.exe", URL, SHA)
    d = AboutDialog(None, fetch=lambda: same)
    d.check_btn.click()
    assert wait(qapp, lambda: "aktuell" in d.status.text()) and not d.update_btn.isVisibleTo(d)

    def fail():
        raise UpdateError("GitHub ist nicht erreichbar (kein Netz).")
    d2 = AboutDialog(None, fetch=fail)
    d2.check_btn.click()
    assert wait(qapp, lambda: "nicht erreichbar" in d2.status.text()) and d2.check_btn.isEnabled()
    older = Release("v0.0.1", "0.0.1", "", updater.PAGE, "WorkPlanner-Setup-0.0.1.exe", URL, SHA)
    d3 = AboutDialog(None, fetch=lambda: older)                      # neuere Version installiert: kein Update anbieten
    d3.check_btn.click()
    assert wait(qapp, lambda: "aktuell" in d3.status.text()) and not d3.update_btn.isVisibleTo(d3)


def test_without_installer_callback_nothing_is_started(qapp, tmp_path):
    from workplanner.ui.about_dialog import AboutDialog
    d = AboutDialog(None, fetch=lambda: make_release(), download=lambda r, progress=None: tmp_path / r.asset,
                    install=None)                                    # Testlauf: kein Installer-Start
    d.check_btn.click()
    assert wait(qapp, lambda: d.update_btn.isVisibleTo(d))
    d.update_btn.click()
    assert wait(qapp, lambda: "nicht gestartet" in d.status.text())
