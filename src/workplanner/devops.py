"""Lesender Zugriff auf Azure DevOps Services (dev.azure.com) über die REST-API."""
from __future__ import annotations

import base64
import html
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote, unquote, urlparse

API = "api-version=7.1"
FIELDS = ["System.Id", "System.Title", "System.WorkItemType", "System.State",
          "System.AssignedTo", "System.Parent", "Microsoft.VSTS.Scheduling.StartDate"]
START_DATE = "Microsoft.VSTS.Scheduling.StartDate"


COMPLETED = "Microsoft.VSTS.Scheduling.CompletedWork"
TASK_TITLE = "WorkPlanner Zeiterfassung"
PATCH = "application/json-patch+json"


class DevOpsError(Exception):
    """Fehler beim Zugriff auf Azure DevOps (mit lesbarer Meldung)."""


@dataclass(frozen=True)
class WorkItem:
    id: int
    title: str
    type: str
    state: str
    assigned_to: str
    parent_id: int | None
    parent_title: str
    url: str
    grandparent_id: int | None = None
    grandparent_title: str = ""
    start_date: date | None = None       # Startdatum des Eintrags (Features/Epics, falls gepflegt)
    parent_start: date | None = None     # Startdatum des Elternteils (Feature bzw. Epic)
    grandparent_start: date | None = None

    @property
    def label(self) -> str:
        return f"#{self.id} {self.title}"

    @property
    def is_feature(self) -> bool:
        return self.type == "Feature"

    @property
    def feature(self) -> str:
        """Übergeordnetes Feature (bei Stories)."""
        return "" if self.is_feature or not self.parent_id else f"#{self.parent_id} {self.parent_title}"

    @property
    def epic(self) -> str:
        """Epic: Elternteil eines Features bzw. Großelternteil einer Story."""
        pid, ptitle = ((self.parent_id, self.parent_title) if self.is_feature
                       else (self.grandparent_id, self.grandparent_title))
        return f"#{pid} {ptitle}" if pid else ""


def parse_date(value) -> date | None:
    """DevOps liefert UTC-Zeitstempel („2026-11-03T00:00:00Z“); angezeigt wird das lokale Datum."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().date()
    except ValueError:
        return None


def parse_backlog_url(url: str) -> dict[str, str]:
    """Zerlegt https://dev.azure.com/<Org>/<Projekt>/_backlogs/backlog/<Team>/Stories?… in
    Organisation, Projekt und Team."""
    parts = [unquote(p) for p in urlparse(url.strip()).path.split("/") if p]
    if "dev.azure.com" not in url or len(parts) < 2:
        raise DevOpsError("Bitte eine Adresse der Form https://dev.azure.com/<Organisation>/<Projekt>/… einfügen.")
    team = ""
    if "_backlogs" in parts:
        i = parts.index("_backlogs")
        if len(parts) > i + 2 and parts[i + 1] == "backlog":
            team = parts[i + 2]
    return {"org": parts[0], "project": parts[1], "team": team}


def backlog_url(org: str, project: str, team: str) -> str:
    if not (org and project):
        return ""
    url = f"https://dev.azure.com/{quote(org)}/{quote(project)}"
    return f"{url}/_backlogs/backlog/{quote(team)}/Stories" if team else url


def _default_transport(method: str, url: str, headers: dict, body: bytes | None):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read().decode("utf-8", "replace")
    except urllib.error.URLError as ex:
        raise DevOpsError(f"Keine Verbindung zu Azure DevOps: {ex.reason}") from ex


class DevOpsClient:
    def __init__(self, org: str, project: str, team: str, pat: str, transport=_default_transport):
        self.org, self.project, self.team = org, project, team
        self._transport = transport
        token = base64.b64encode(f":{pat}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json",
                         "Accept": "application/json"}

    @property
    def base(self) -> str:
        return f"https://dev.azure.com/{quote(self.org)}"

    def web_url(self, item_id: int) -> str:
        return f"{self.base}/{quote(self.project)}/_workitems/edit/{item_id}"

    def _call(self, method: str, url: str, payload: dict | list | None = None,
              content_type: str = "application/json") -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        status, text = self._transport(method, url, {**self._headers, "Content-Type": content_type}, body)
        if status in (401, 403, 203):
            raise DevOpsError("Anmeldung oder Berechtigung fehlgeschlagen – bitte Token (PAT) prüfen "
                              "(„Work Items: Read“, zum Anlegen und Übertragen „Read & write“).")
        if status == 404:
            raise DevOpsError("Organisation, Projekt oder Team wurde nicht gefunden.")
        if status >= 400:
            try:
                msg = json.loads(text).get("message", text)
            except ValueError:
                msg = text[:200]
            raise DevOpsError(f"Azure DevOps meldet Fehler {status}: {msg}")
        try:
            return json.loads(text)
        except ValueError as ex:  # z. B. HTML-Anmeldeseite statt JSON
            raise DevOpsError("Unerwartete Antwort – ist das Token gültig?") from ex

    def test_connection(self) -> str:
        data = self._call("GET", f"{self.base}/_apis/projects/{quote(self.project)}?{API}")
        return data.get("name", self.project)

    def _area_paths(self) -> list[str]:
        if not self.team:
            return []
        try:
            data = self._call("GET", f"{self.base}/{quote(self.project)}/{quote(self.team)}"
                                     f"/_apis/work/teamsettings/teamfieldvalues?{API}")
        except DevOpsError:
            return []
        return [v["value"] for v in data.get("values", []) if v.get("value")]

    def fetch_stories(self, only_mine: bool = True, limit: int = 200) -> list[WorkItem]:
        """Offene Stories (Requirement-Kategorie) des Teams, auf Wunsch nur die mir zugewiesenen."""
        return self._fetch("Microsoft.RequirementCategory", only_mine, limit)

    def fetch_features(self, only_mine: bool = False, limit: int = 200) -> list[WorkItem]:
        """Offene Features (Feature-Kategorie) des Teams, mit ihrem Epic."""
        return self._fetch("Microsoft.FeatureCategory", only_mine, limit)

    def _fetch(self, category: str, only_mine: bool, limit: int) -> list[WorkItem]:
        conds = ["[System.TeamProject] = @project",
                 f"[System.WorkItemType] IN GROUP '{category}'",
                 "[System.State] NOT IN ('Closed', 'Done', 'Removed')"]
        areas = self._area_paths()
        if areas:
            conds.append("(" + " OR ".join(
                "[System.AreaPath] UNDER '" + a.replace("'", "''") + "'" for a in areas) + ")")
        if only_mine:
            conds.append("[System.AssignedTo] = @Me")
        wiql = {"query": "SELECT [System.Id] FROM WorkItems WHERE " + " AND ".join(conds)
                         + " ORDER BY [Microsoft.VSTS.Common.BacklogPriority], [System.Id]"}
        result = self._call("POST", f"{self.base}/{quote(self.project)}/_apis/wit/wiql?{API}", wiql)
        ids = [w["id"] for w in result.get("workItems", [])][:limit]
        if not ids:
            return []
        items = self._batch(ids)
        parent_ids = sorted({items[i]["System.Parent"] for i in ids if items.get(i, {}).get("System.Parent")})
        parents = self._batch(parent_ids) if parent_ids else {}
        gp_ids = sorted({parents[p]["System.Parent"] for p in parent_ids if parents.get(p, {}).get("System.Parent")})
        grandparents = self._batch(gp_ids) if gp_ids else {}
        out = []
        for i in ids:
            f = items.get(i)
            if not f:
                continue
            pid = f.get("System.Parent")
            gpid = parents.get(pid, {}).get("System.Parent") if pid else None
            assigned = f.get("System.AssignedTo")
            out.append(WorkItem(
                id=i, title=f.get("System.Title", ""), type=f.get("System.WorkItemType", ""),
                state=f.get("System.State", ""),
                assigned_to=assigned.get("displayName", "") if isinstance(assigned, dict) else (assigned or ""),
                parent_id=pid, parent_title=parents.get(pid, {}).get("System.Title", "") if pid else "",
                url=self.web_url(i),
                grandparent_id=gpid,
                grandparent_title=grandparents.get(gpid, {}).get("System.Title", "") if gpid else "",
                start_date=parse_date(f.get(START_DATE)),
                parent_start=parse_date(parents.get(pid, {}).get(START_DATE)) if pid else None,
                grandparent_start=parse_date(grandparents.get(gpid, {}).get(START_DATE)) if gpid else None))
        return out

    def _batch(self, ids: list[int], fields: list[str] | None = None) -> dict[int, dict]:
        found: dict[int, dict] = {}
        for k in range(0, len(ids), 200):
            data = self._call("POST", f"{self.base}/{quote(self.project)}/_apis/wit/workitemsbatch?{API}",
                              {"ids": ids[k:k + 200], "fields": fields or FIELDS})
            for v in data.get("value", []):
                found[v["id"]] = v.get("fields", {})
        return found

    # --- Schreiben: Stories anlegen, Zeit übertragen ------------------------------------
    def story_type(self) -> str:
        """Standard-Typ der Story-Ebene im Prozess („User Story“, „Product Backlog Item“ …)."""
        data = self._call("GET", f"{self.base}/{quote(self.project)}/_apis/wit/workitemtypecategories/"
                                 f"Microsoft.RequirementCategory?{API}")
        name = data.get("defaultWorkItemType", {}).get("name")
        if not name:
            raise DevOpsError("Der Story-Typ des Prozesses konnte nicht ermittelt werden.")
        return name

    def requirement_types(self) -> set[str]:
        data = self._call("GET", f"{self.base}/{quote(self.project)}/_apis/wit/workitemtypecategories/"
                                 f"Microsoft.RequirementCategory?{API}")
        return {t["name"] for t in data.get("workItemTypes", [])}

    def _identity(self) -> str:
        try:
            u = self._call("GET", f"{self.base}/_apis/connectionData?connectOptions=none"
                                  "&api-version=7.1-preview.1").get("authenticatedUser", {})
        except DevOpsError:
            return ""
        return u.get("properties", {}).get("Account", {}).get("$value") or u.get("providerDisplayName", "")

    def _defaults(self, parent_id: int | None) -> tuple[str, str]:
        """Area Path (vom Feature, sonst Team-Vorgabe) und Iteration (Team-Vorgabe, sonst Feature)."""
        area = iteration = ""
        if parent_id:
            f = self._batch([parent_id], ["System.AreaPath", "System.IterationPath"]).get(parent_id, {})
            area, iteration = f.get("System.AreaPath", ""), f.get("System.IterationPath", "")
        if self.team:
            try:
                settings = self._call("GET", f"{self.base}/{quote(self.project)}/{quote(self.team)}"
                                             f"/_apis/work/teamsettings?{API}")
                iteration = settings.get("defaultIteration", {}).get("path") or iteration
            except DevOpsError:
                pass
            if not area:
                try:
                    fv = self._call("GET", f"{self.base}/{quote(self.project)}/{quote(self.team)}"
                                           f"/_apis/work/teamsettings/teamfieldvalues?{API}")
                    area = fv.get("defaultValue", "")
                except DevOpsError:
                    pass
        return area, iteration

    def _create(self, type_name: str, title: str, description: str, parent_id: int | None,
                assign: str, extra_ops: list[dict] | None = None) -> WorkItem:
        area, iteration = self._defaults(parent_id)
        ops = [{"op": "add", "path": "/fields/System.Title", "value": title}]
        if description.strip():
            ops.append({"op": "add", "path": "/fields/System.Description",
                        "value": html.escape(description.strip()).replace("\n", "<br>")})
        if area:
            ops.append({"op": "add", "path": "/fields/System.AreaPath", "value": area})
        if iteration:
            ops.append({"op": "add", "path": "/fields/System.IterationPath", "value": iteration})
        if assign:
            ops.append({"op": "add", "path": "/fields/System.AssignedTo", "value": assign})
        if parent_id:
            ops.append({"op": "add", "path": "/relations/-", "value": {
                "rel": "System.LinkTypes.Hierarchy-Reverse",
                "url": f"{self.base}/_apis/wit/workItems/{parent_id}"}})
        ops += extra_ops or []
        data = self._call("POST", f"{self.base}/{quote(self.project)}/_apis/wit/workitems/"
                                  f"${quote(type_name)}?{API}", ops, PATCH)
        f = data.get("fields", {})
        return WorkItem(id=data["id"], title=f.get("System.Title", title), type=type_name,
                        state=f.get("System.State", ""), assigned_to=assign, parent_id=parent_id,
                        parent_title="", url=self.web_url(data["id"]))

    def create_story(self, title: str, description: str = "", parent_id: int | None = None,
                     assign_to_me: bool = True) -> WorkItem:
        """Legt eine Story an (auf Wunsch unter einem Feature und mir zugewiesen)."""
        if not title.strip():
            raise DevOpsError("Eine Story braucht einen Titel.")
        return self._create(self.story_type(), title.strip(), description, parent_id,
                            self._identity() if assign_to_me else "")

    def create_task(self, parent_id: int, title: str, description: str = "", assign_to_me: bool = True) -> WorkItem:
        """Legt einen Task unter einer Story an (z. B. aus der Notiz eines Zeiteintrags)."""
        if not title.strip():
            raise DevOpsError("Ein Task braucht einen Titel.")
        return self._create("Task", title.strip(), description, parent_id, self._identity() if assign_to_me else "")

    def completed_info(self, ids: list[int]) -> dict[int, dict]:
        return self._batch(ids, ["System.Title", "System.WorkItemType", COMPLETED])

    def type_has_completed_work(self, type_name: str) -> bool:
        data = self._call("GET", f"{self.base}/{quote(self.project)}/_apis/wit/workitemtypes/"
                                 f"{quote(type_name)}/fields?{API}")
        return any(f.get("referenceName") == COMPLETED for f in data.get("value", []))

    def find_time_task(self, story_id: int) -> tuple[int | None, float]:
        """Task „WorkPlanner Zeiterfassung“ unter der Story (ID, bisher gebuchte Stunden)."""
        data = self._call("GET", f"{self.base}/{quote(self.project)}/_apis/wit/workitems/{story_id}"
                                 f"?$expand=relations&{API}")
        child_ids = [int(r["url"].rsplit("/", 1)[1]) for r in data.get("relations", [])
                     if r.get("rel") == "System.LinkTypes.Hierarchy-Forward"]
        if child_ids:
            for cid, f in self._batch(child_ids, ["System.Title", "System.WorkItemType", COMPLETED]).items():
                if f.get("System.WorkItemType") == "Task" and f.get("System.Title") == TASK_TITLE:
                    return cid, float(f.get(COMPLETED) or 0)
        return None, 0.0

    def set_completed_work(self, item_id: int, hours: float) -> None:
        self._call("PATCH", f"{self.base}/{quote(self.project)}/_apis/wit/workitems/{item_id}?{API}",
                   [{"op": "add", "path": f"/fields/{COMPLETED}", "value": round(hours, 2)}], PATCH)

    def create_time_task(self, story_id: int, hours: float) -> WorkItem:
        return self._create("Task", TASK_TITLE, "Von WorkPlanner übertragene Arbeitszeit.", story_id,
                            self._identity(), [{"op": "add", "path": f"/fields/{COMPLETED}",
                                                "value": round(hours, 2)}])
