import json
from datetime import date

import pytest

from workplanner import secret
from workplanner.devops import DevOpsClient, DevOpsError, backlog_url, parse_backlog_url

URL = ("https://dev.azure.com/example-org/Demo/_backlogs/backlog/"
       "Example%20Team/Stories?showParents=true")


def test_parse_backlog_url():
    assert parse_backlog_url(URL) == {"org": "example-org", "project": "Demo",
                                      "team": "Example Team"}
    assert parse_backlog_url("https://dev.azure.com/o/p") == {"org": "o", "project": "p", "team": ""}
    with pytest.raises(DevOpsError):
        parse_backlog_url("https://example.com/foo")


def test_backlog_url_roundtrip():
    assert parse_backlog_url(backlog_url("example-org", "Demo", "Example Team")) == {
        "org": "example-org", "project": "Demo", "team": "Example Team"}


def test_secret_roundtrip_and_not_plaintext():
    token = secret.protect("pat-äöü-123")
    assert token and "pat-" not in token
    assert secret.unprotect(token) == "pat-äöü-123"
    assert secret.protect("") == "" and secret.unprotect("") == ""
    assert secret.unprotect("kein-gültiger-wert") == ""


class FakeTransport:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, json.loads(body) if body else None))
        for key, (status, payload) in self.routes.items():
            if key in url:
                return status, payload if isinstance(payload, str) else json.dumps(payload)
        return 404, "{}"


def client(routes):
    t = FakeTransport(routes)
    return DevOpsClient("example-org", "Demo", "Example Team", "TOKEN", t), t


def test_fetch_stories_builds_query_and_resolves_parents():
    c, t = client({
        "teamfieldvalues": (200, {"values": [{"value": "Demo\\Team A", "includeChildren": True}]}),
        "wiql": (200, {"workItems": [{"id": 11}, {"id": 12}]}),
        "workitemsbatch": (200, {"value": [
            {"id": 11, "fields": {"System.Title": "Waage", "System.WorkItemType": "User Story",
                                  "System.State": "Active", "System.Parent": 5,
                                  "System.AssignedTo": {"displayName": "Michael"}}},
            {"id": 12, "fields": {"System.Title": "Export", "System.WorkItemType": "User Story",
                                  "System.State": "New"}},
            {"id": 5, "fields": {"System.Title": "Feature X"}}]}),
    })
    items = c.fetch_stories(only_mine=True)
    assert [(i.id, i.title, i.parent_title, i.assigned_to) for i in items] == [
        (11, "Waage", "Feature X", "Michael"), (12, "Export", "", "")]
    assert items[0].label == "#11 Waage"
    assert items[0].url == "https://dev.azure.com/example-org/Demo/_workitems/edit/11"
    wiql = next(call for call in t.calls if "wiql" in call[1])[3]["query"]
    assert "IN GROUP 'Microsoft.RequirementCategory'" in wiql
    assert "[System.AssignedTo] = @Me" in wiql
    assert "[System.AreaPath] UNDER 'Demo\\Team A'" in wiql
    assert all(call[2]["Authorization"].startswith("Basic ") for call in t.calls)


def test_fetch_all_not_only_mine_and_empty_result():
    c, t = client({"teamfieldvalues": (200, {"values": []}), "wiql": (200, {"workItems": []})})
    assert c.fetch_stories(only_mine=False) == []
    wiql = next(call for call in t.calls if "wiql" in call[1])[3]["query"]
    assert "@Me" not in wiql and "AreaPath" not in wiql


@pytest.mark.parametrize("status,text,msg", [
    (401, "", "Anmeldung oder Berechtigung"), (203, "<html>", "Anmeldung oder Berechtigung"),
    (404, "{}", "nicht gefunden"), (500, '{"message": "kaputt"}', "kaputt"),
    (200, "<html>Sign in</html>", "Token")])
def test_errors_are_readable(status, text, msg):
    c, _ = client({"_apis/projects": (status, text)})
    with pytest.raises(DevOpsError, match=msg):
        c.test_connection()


def test_connection_ok():
    c, _ = client({"_apis/projects": (200, {"name": "Demo"})})
    assert c.test_connection() == "Demo"


def hierarchy_client():
    return client({
        "teamfieldvalues": (200, {"values": []}),
        "wiql": (200, {"workItems": [{"id": 21}]}),
        "workitemsbatch": (200, {"value": [
            {"id": 21, "fields": {"System.Title": "Waagen-Anbindung", "System.WorkItemType": "Feature",
                                  "System.State": "Active", "System.Parent": 3,
                                  "Microsoft.VSTS.Scheduling.StartDate": "2026-11-03T12:00:00Z"}},
            {"id": 3, "fields": {"System.Title": "Demo-Plattform", "System.WorkItemType": "Epic",
                                 "System.Parent": 1,
                                 "Microsoft.VSTS.Scheduling.StartDate": "2026-10-01T12:00:00Z"}},
            {"id": 1, "fields": {"System.Title": "Portfolio"}}]}),
    })


def test_fetch_features_with_epic():
    c, t = hierarchy_client()
    (f,) = c.fetch_features()
    assert f.is_feature and f.id == 21 and f.title == "Waagen-Anbindung"
    assert f.epic == "#3 Demo-Plattform" and f.feature == ""
    assert f.start_date == date(2026, 11, 3) and f.parent_start == date(2026, 10, 1)
    wiql = next(call for call in t.calls if "wiql" in call[1])[3]["query"]
    assert "IN GROUP 'Microsoft.FeatureCategory'" in wiql and "@Me" not in wiql


def test_story_shows_feature_and_epic():
    c, _ = client({
        "teamfieldvalues": (200, {"values": []}),
        "wiql": (200, {"workItems": [{"id": 11}]}),
        "workitemsbatch": (200, {"value": [
            {"id": 11, "fields": {"System.Title": "Waage lesen", "System.WorkItemType": "User Story",
                                  "System.Parent": 21}},
            {"id": 21, "fields": {"System.Title": "Waagen-Anbindung", "System.WorkItemType": "Feature",
                                  "System.Parent": 3}},
            {"id": 3, "fields": {"System.Title": "Demo-Plattform"}}]}),
    })
    (s,) = c.fetch_stories()
    assert s.feature == "#21 Waagen-Anbindung" and s.epic == "#3 Demo-Plattform"


def test_parse_date_handles_missing_and_broken_values():
    from workplanner.devops import parse_date
    assert parse_date(None) is None and parse_date("") is None and parse_date("kein Datum") is None
    assert parse_date("2026-11-03T12:00:00Z") == date(2026, 11, 3)
    assert parse_date("2026-11-03T12:00:00.123Z") == date(2026, 11, 3)
