import json

import pytest

from test_service import DAY, Clock
from workplanner.db import Database
from workplanner.devops import COMPLETED, TASK_TITLE, DevOpsClient, DevOpsError
from workplanner.devops_sync import PlanItem, apply_plan, build_plan, hours_by_item, item_id_from_note
from workplanner.service import TimeService


class Router:
    """Antwortet je (Methode, URL-Teil); der erste Treffer gewinnt, sonst 404."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, url, headers, body):
        data = json.loads(body) if body else None
        self.calls.append({"method": method, "url": url, "ct": headers["Content-Type"], "body": data})
        for m, part, status, payload in self.routes:
            if m == method and part in url:
                return status, json.dumps(payload)
        return 404, "{}"

    def find(self, method, part):
        return [c for c in self.calls if c["method"] == method and part in c["url"]]


def make(routes):
    r = Router(routes)
    return DevOpsClient("example-org", "Demo", "Example Team", "T", r), r


STORY_ROUTES = [
    ("GET", "workitemtypecategories/Microsoft.RequirementCategory",
     200, {"defaultWorkItemType": {"name": "User Story"}, "workItemTypes": [{"name": "User Story"}]}),
    ("GET", "connectionData", 200, {"authenticatedUser": {"properties": {"Account": {"$value": "me@x.de"}}}}),
    ("POST", "workitemsbatch", 200, {"value": [{"id": 21, "fields": {
        "System.AreaPath": "Demo\\Team A", "System.IterationPath": "Demo\\Feature-Iter"}}]}),
    ("GET", "teamsettings?", 200, {"defaultIteration": {"path": "Demo\\Sprint 5"}}),
    ("POST", "workitems/$User%20Story", 200, {"id": 99, "fields": {"System.Title": "Neue Story",
                                                                  "System.State": "New"}}),
]


def test_create_story_under_feature():
    c, r = make(STORY_ROUTES)
    item = c.create_story("Neue Story", "Zeile 1\nZeile <2>", parent_id=21)
    assert (item.id, item.type, item.title) == (99, "User Story", "Neue Story")
    (post,) = r.find("POST", "workitems/$User%20Story")
    assert post["ct"] == "application/json-patch+json"
    ops = {o["path"]: o["value"] for o in post["body"]}
    assert ops["/fields/System.Title"] == "Neue Story"
    assert ops["/fields/System.Description"] == "Zeile 1<br>Zeile &lt;2&gt;"
    assert ops["/fields/System.AreaPath"] == "Demo\\Team A"          # vom Feature
    assert ops["/fields/System.IterationPath"] == "Demo\\Sprint 5"   # Team-Vorgabe
    assert ops["/fields/System.AssignedTo"] == "me@x.de"
    assert ops["/relations/-"] == {"rel": "System.LinkTypes.Hierarchy-Reverse",
                                   "url": "https://dev.azure.com/example-org/_apis/wit/workItems/21"}


def test_create_story_without_feature_and_unassigned():
    c, r = make(STORY_ROUTES)
    c.create_story("Lose Story", parent_id=None, assign_to_me=False)
    ops = {o["path"] for o in r.find("POST", "workitems/$User%20Story")[0]["body"]}
    assert "/relations/-" not in ops and "/fields/System.AssignedTo" not in ops
    assert not r.find("GET", "connectionData")


def test_create_story_needs_title_and_reports_permission_error():
    c, _ = make(STORY_ROUTES)
    with pytest.raises(DevOpsError, match="Titel"):
        c.create_story("   ")
    c, _ = make([r for r in STORY_ROUTES if "workitems/$" not in r[1]] +
                [("POST", "workitems/$User%20Story", 403, {})])
    with pytest.raises(DevOpsError, match="Berechtigung"):
        c.create_story("X")


# --- Stunden -----------------------------------------------------------------------

def test_item_id_from_note():
    assert item_id_from_note("#4411 Waage") == 4411
    assert item_id_from_note("  #7") == 7
    assert item_id_from_note("siehe #4411") is None and item_id_from_note("") is None


def test_hours_by_item_sums_work_entries_only():
    from datetime import datetime
    from workplanner.timeline import PAUSE, Entry
    t = lambda h, m=0: datetime(2026, 11, 2, h, m)  # noqa: E731
    entries = [Entry(t(8), t(9, 30), note="#11 Waage"), Entry(t(9, 30), t(10), note="#11 Waage"),
               Entry(t(10), t(11), note="ohne"), Entry(t(11), t(12), kind=PAUSE, note="#11"),
               Entry(t(12, 30), None, note="#12 läuft")]
    assert hours_by_item(entries, t(13, 30)) == {11: 2.0, 12: 1.0}


def test_service_collects_hours_from_notes_and_tracks_synced():
    db = Database()
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    p = db.add_project("A")
    svc.start_task(p, None, "#11 Waage")
    clock.set(9, 30)
    svc.start_task(p, None, "#12 Export")
    clock.set(10, 0)
    svc.stop()
    assert svc.devops_hours() == {11: 1.5, 12: 0.5}
    svc.devops_mark_synced(11, 1.0)
    assert svc.devops_synced() == {11: 1.0}


PLAN_ROUTES = [
    ("GET", "workitemtypecategories/Microsoft.RequirementCategory", 200,
     {"defaultWorkItemType": {"name": "User Story"}, "workItemTypes": [{"name": "User Story"}]}),
    ("POST", "workitemsbatch", 200, {"value": [
        {"id": 11, "fields": {"System.Title": "Waage", "System.WorkItemType": "User Story"}},
        {"id": 12, "fields": {"System.Title": "Export", "System.WorkItemType": "Task", COMPLETED: 4.0}},
        {"id": 13, "fields": {"System.Title": "Großes Ziel", "System.WorkItemType": "Epic"}}]}),
    ("GET", "workitemtypes/User%20Story/fields", 200, {"value": []}),
    ("GET", "workitemtypes/Task/fields", 200, {"value": [{"referenceName": COMPLETED}]}),
    ("GET", "workitemtypes/Epic/fields", 200, {"value": []}),
    ("GET", "workitems/11?$expand=relations", 200, {"relations": []}),
    ("GET", "connectionData", 200, {"authenticatedUser": {"providerDisplayName": "Michael"}}),
    ("PATCH", "workitems/12", 200, {"id": 12}),
    ("POST", "workitems/$Task", 200, {"id": 500, "fields": {"System.Title": TASK_TITLE}}),
]


def test_plan_picks_field_or_task_and_skips_unsupported():
    c, _ = make(PLAN_ROUTES)
    plan = {p.item_id: p for p in build_plan(
        c, {11: 3.5, 12: 2.0, 13: 1.0, 14: 1.0, 15: 1.0}, {12: 0.5, 15: 1.0})}
    assert 15 not in plan                                   # nichts Neues
    assert (plan[12].mode, plan[12].current_h, plan[12].delta_h, plan[12].new_h) == ("story", 4.0, 1.5, 5.5)
    assert (plan[11].mode, plan[11].task_id, plan[11].new_h) == ("task", None, 3.5)
    assert "wird angelegt" in plan[11].target
    assert "kann keine Zeit" in plan[13].skip_reason
    assert "nicht gefunden" in plan[14].skip_reason


def test_nothing_to_do_makes_no_requests():
    c, r = make(PLAN_ROUTES)
    assert build_plan(c, {11: 1.0}, {11: 1.0}) == []
    assert r.calls == []


def test_apply_writes_difference_only_and_creates_task():
    c, r = make(PLAN_ROUTES)
    plan = build_plan(c, {11: 3.5, 12: 2.0, 13: 1.0}, {12: 0.5})
    results = apply_plan(c, plan)
    assert [(p.item_id, err) for p, err in results] == [(11, None), (12, None)]  # 13 übersprungen
    (patch,) = r.find("PATCH", "workitems/12")
    assert patch["body"] == [{"op": "add", "path": f"/fields/{COMPLETED}", "value": 5.5}]
    assert patch["ct"] == "application/json-patch+json"
    (task,) = r.find("POST", "workitems/$Task")
    ops = {o["path"]: o["value"] for o in task["body"]}
    assert ops["/fields/System.Title"] == TASK_TITLE and ops[f"/fields/{COMPLETED}"] == 3.5
    assert ops["/relations/-"]["url"].endswith("/workItems/11")


def test_apply_continues_after_error():
    routes = [r for r in PLAN_ROUTES if r[0] != "PATCH"] + [("PATCH", "workitems/12", 403, {})]
    c, _ = make(routes)
    plan = build_plan(c, {11: 1.0, 12: 2.0}, {})
    results = {p.item_id: err for p, err in apply_plan(c, plan)}
    assert results[11] is None and "Berechtigung" in results[12]


def test_existing_time_task_is_updated_not_duplicated():
    routes = [r for r in PLAN_ROUTES if "expand=relations" not in r[1]] + [
        ("GET", "workitems/11?$expand=relations", 200, {"relations": [
            {"rel": "System.LinkTypes.Hierarchy-Forward", "url": "https://dev.azure.com/o/_apis/wit/workItems/77"}]}),
    ]
    # Batch liefert für 77 den Zeit-Task, daher zusätzlich in die Batch-Antwort aufnehmen
    routes = [(m, part, st, ({"value": payload["value"] + [
        {"id": 77, "fields": {"System.Title": TASK_TITLE, "System.WorkItemType": "Task", COMPLETED: 2.0}}]}
        if part == "workitemsbatch" else payload)) for m, part, st, payload in routes]
    routes.append(("PATCH", "workitems/77", 200, {"id": 77}))
    c, r = make(routes)
    (p,) = build_plan(c, {11: 3.0}, {11: 1.0})
    assert (p.mode, p.task_id, p.current_h, p.delta_h, p.new_h) == ("task", 77, 2.0, 2.0, 4.0)
    apply_plan(c, [p])
    assert r.find("PATCH", "workitems/77")[0]["body"][0]["value"] == 4.0
    assert not r.find("POST", "workitems/$Task")


def test_create_task_under_story_with_note_as_description():
    routes = [r for r in STORY_ROUTES if "workitems/$User" not in r[1]] + [
        ("POST", "workitems/$Task", 200, {"id": 700, "fields": {"System.Title": "Schnittstelle gebaut"}})]
    c, r = make(routes)
    item = c.create_task(211, "Schnittstelle gebaut", "Schnittstelle gebaut\nTests <laufen>")
    assert (item.id, item.type, item.parent_id) == (700, "Task", 211)
    (post,) = r.find("POST", "workitems/$Task")
    ops = {o["path"]: o["value"] for o in post["body"]}
    assert ops["/fields/System.Title"] == "Schnittstelle gebaut"
    assert ops["/fields/System.Description"] == "Schnittstelle gebaut<br>Tests &lt;laufen&gt;"
    assert ops["/relations/-"]["url"].endswith("/workItems/211")
    assert ops["/fields/System.AssignedTo"] == "me@x.de"
    with pytest.raises(DevOpsError, match="Titel"):
        c.create_task(211, "  ")
