from __future__ import annotations

from datetime import date, timedelta

from app.services.estimate import hours_estimate


def test_health(client) -> None:
    assert client.get("/api/health").json()["ok"] is True


def test_languages_are_seeded_from_config(client) -> None:
    codes = [lang["code"] for lang in client.get("/api/languages").json()]
    assert codes == ["de", "es", "ja"]


def test_settings_roundtrip(client) -> None:
    initial = client.get("/api/settings").json()
    assert initial["active_language"] == "de"
    assert initial["goals"] == {"de": 60, "es": 60, "ja": 60}

    patched = client.patch("/api/settings", json={"active_language": "ja", "goals": {"de": 30}}).json()
    assert patched["active_language"] == "ja"
    assert patched["goals"]["de"] == 30


def test_settings_reject_bad_values(client) -> None:
    assert client.patch("/api/settings", json={"active_language": "fr"}).status_code == 422
    assert client.patch("/api/settings", json={"goals": {"de": 0}}).status_code == 422


def test_manual_log_shows_up_in_today(client) -> None:
    response = client.post("/api/activity/manual", json={"language": "de", "activity": "podcast", "minutes": 25})
    assert response.status_code == 201
    assert len(response.json()["client_uuid"]) == 26

    today = client.get("/api/stats/today", params={"lang": "de"}).json()
    assert today["today_minutes"] == 25
    assert today["last7"][-1]["minutes"] == 25
    assert today["last_session"]["minutes"] == 25


def test_manual_log_on_an_earlier_day(client) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    client.post("/api/activity/manual", json={"language": "es", "activity": "reading", "minutes": 40, "day": yesterday})
    today = client.get("/api/stats/today", params={"lang": "es"}).json()
    assert today["today_minutes"] == 0
    assert today["last7"][-2] == {"date": yesterday, "minutes": 40}


def test_manual_log_validation(client) -> None:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    bad = [
        {"language": "de", "activity": "podcast", "minutes": 0},
        {"language": "de", "activity": "flashcards", "minutes": 10},
        {"language": "xx", "activity": "podcast", "minutes": 10},
        {"language": "de", "activity": "podcast", "minutes": 10, "day": tomorrow},
    ]
    for body in bad:
        assert client.post("/api/activity/manual", json=body).status_code == 422, body


def test_unknown_language_is_404(client) -> None:
    assert client.get("/api/stats/today", params={"lang": "fr"}).status_code == 404


def test_system_status(client) -> None:
    status = client.get("/api/system/status").json()
    assert status["ok"] is True
    assert {c["name"] for c in status["checks"]} >= {"database (main)", "database (dict)", "data folder"}


def test_hours_estimate_matches_your_csv_totals(cfg) -> None:
    de = hours_estimate("de", 142.9, cfg.baselines)
    assert (de["level"], de["adjusted_hours"], de["words_prior"]) == (2, 107.4, 990)
    es = hours_estimate("es", 234.2, cfg.baselines)
    assert (es["level"], es["words_prior"]) == (3, 2340)
    ja = hours_estimate("ja", 500.6, cfg.baselines)
    assert (ja["level"], ja["words_prior"]) == (3, 1670)
    top = hours_estimate("es", 5000, cfg.baselines)
    assert top["level"] == 7 and top["next_level"] is None


def test_an_unexpected_error_answers_json(client) -> None:
    """A crash in one endpoint is shown as an error, not read by the app as "can't reach the server" (issue #6)."""
    from fastapi.testclient import TestClient

    app = client.app

    def _boom() -> None:
        raise RuntimeError("boom")

    app.add_api_route("/api/__boom", _boom)
    app.router.routes.insert(0, app.router.routes.pop())  # ahead of the web app's catch-all

    with TestClient(app, raise_server_exceptions=False) as quiet:
        response = quiet.get("/api/__boom")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json") and "RuntimeError" in response.json()["detail"]
