"""A learner's starting point in a language: chosen level, hours before Lingo OS, and an imported history CSV."""

from __future__ import annotations

from sqlalchemy import text

SIMPLE_CSV = (
    "date,title,minutes,url,channel,category\n"
    "2026-03-01,Street interviews,18,https://www.youtube.com/watch?v=abcdefghijk,Easy German,video\n"
    "2026-03-02,Podcast episode 12,35,,,podcast\n"
    "02.03.2026,A chapter of a book,1h 10m,,,reading\n"
    "not a date,Broken row,10,,,video\n"
)


def _vocab(client) -> int:
    return client.get("/api/level/de/overview").json()["profile"]["vocab_size"]


def test_choosing_a_level_sets_the_starting_estimate(client) -> None:
    before = _vocab(client)
    state = client.put("/api/languages/de/level", json={"level": "B2"}).json()
    assert state["self_level"] == "B2" and state["has_start"]
    assert _vocab(client) > before and _vocab(client) >= 4000  # B2 ≈ 4,700 words, blended with what you watched
    assert client.put("/api/languages/de/level", json={"level": "Z9"}).status_code == 422
    assert client.put("/api/languages/de/level", json={"level": None}).json()["self_level"] is None
    with client.app.state.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM jobs WHERE kind = 'rescore'")).scalar() >= 1


def test_hours_before_lingo_os_add_to_imported_ones(client) -> None:
    client.post("/api/imports/tracker", json={})  # the fixture tracker has a 10 h baseline for German
    start = client.get("/api/languages/de/start").json()
    imported = start["imported_baseline_hours"]
    assert imported == 10.0
    after = client.put("/api/languages/de/baseline", json={"hours": 25}).json()
    assert after["baseline_hours"] == 25.0 and after["imported_baseline_hours"] == 10.0
    # setting it again replaces the manual part, never doubles it
    assert client.put("/api/languages/de/baseline", json={"hours": 30}).json()["baseline_hours"] == 30.0
    # less than what was imported: the imported hours stay
    assert client.put("/api/languages/de/baseline", json={"hours": 5}).json()["baseline_hours"] == 10.0


def test_importing_a_simple_csv_reports_what_it_read(client) -> None:
    files = {"file": ("my-history.csv", SIMPLE_CSV.encode(), "text/csv")}
    report = client.post("/api/languages/es/history", files=files).json()
    assert report["format"] == "simple" and report["rows"] == 4
    assert report["imported"] == 3 and report["videos"] == 1 and report["time_only_rows"] == 2
    assert len(report["errors"]) == 1 and "row 5" in report["errors"][0]
    assert report["analysis_job"]
    again = client.post("/api/languages/es/history", files=files).json()
    assert again["status"] == "unchanged"  # the same file twice: nothing counted twice
    history = client.get("/api/languages/es/history").json()
    assert history["imports"][0]["file"] == "my-history.csv" and history["imports"][0]["imported"] == 3
    assert history["videos"]["watched"] >= 1
    with client.app.state.engine.connect() as conn:
        minutes = conn.execute(
            text("SELECT SUM(active_seconds) / 60 FROM activity_sessions WHERE language_code = 'es' AND tracking = 'import'")
        ).scalar()
    assert minutes == 18 + 35 + 70


def test_a_csv_without_the_needed_columns_is_refused_with_a_reason(client) -> None:
    files = {"file": ("x.csv", b"name,score\nfoo,3\n", "text/csv")}
    response = client.post("/api/languages/es/history", files=files)
    assert response.status_code == 422 and "date column" in response.json()["detail"]


def test_template_and_unknown_language(client) -> None:
    template = client.get("/api/languages/history-template.csv")
    assert template.status_code == 200 and template.text.startswith("date,title,minutes")
    assert client.get("/api/languages/xx/start").status_code == 404


def test_the_daily_refresh_runs_once_a_day_per_language(client) -> None:
    first = client.post("/api/discover/daily", json={"lang": "de"}).json()
    assert first["ran"] and first["jobs"]
    assert not client.post("/api/discover/daily", json={"lang": "de"}).json()["ran"]  # same day: nothing again
    assert client.post("/api/discover/daily", json={"lang": "es"}).json()["ran"]  # another language: its own day
    with client.app.state.engine.connect() as conn:
        kinds = {r[0] for r in conn.execute(text("SELECT kind FROM jobs")).all()}
    assert "rescore" in kinds


def test_a_chosen_level_moves_the_roadmap_estimate(client) -> None:
    """Choosing B1 in a new language should not show "level 1, starting from zero" (issue #1)."""
    before = client.get("/api/level/es/overview").json()["hours_estimate"]
    assert before["basis"] == "hours only"
    client.put("/api/languages/es/level", json={"level": "B1"})
    est = client.get("/api/level/es/overview").json()["hours_estimate"]
    assert est["basis"] == "chosen level" and est["start_label"] == "B1"
    assert est["level"] > before["level"] and est["words_prior"] == 2700
    overview = next(e for e in client.get("/api/stats/overview").json()["languages"] if e["language"] == "es")
    assert overview["estimate"]["basis"] == "chosen level"
    client.put("/api/languages/es/level", json={"level": None})
    assert client.get("/api/level/es/overview").json()["hours_estimate"]["basis"] == "hours only"
