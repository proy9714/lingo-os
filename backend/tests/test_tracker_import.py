from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.timeutil import local_day
from conftest import FIXTURES


def _file(summary: dict, lang: str) -> dict:
    return next(item for item in summary["files"] if item["language"] == lang)


def test_first_import(client) -> None:
    summary = client.post("/api/imports/tracker").json()
    de = _file(summary, "de")
    assert (de["status"], de["rows"], de["imported"]) == ("imported", 7, 6)
    assert [flag["entry_id"] for flag in de["duplicates"]] == ["a3"]
    assert de["errors"] == []
    assert _file(summary, "es")["status"] == "missing"
    assert _file(summary, "ja")["imported"] == 1
    assert summary["goals_imported"] == {"de": 45, "ja": 30, "es": 60}

    overview = {entry["language"]: entry for entry in client.get("/api/stats/overview").json()["languages"]}
    de_stats = overview["de"]
    assert de_stats["baseline_hours"] == 10.0
    assert de_stats["tracked_hours"] == 1.4  # 600 + 600 + 1200 + 957 + 1800 s
    assert de_stats["sessions"] == 5
    assert de_stats["content_items"] == 2
    assert overview["ja"]["sessions"] == 0 and overview["ja"]["baseline_hours"] == 2.0


def test_reimport_is_idempotent_and_flags_can_be_counted(client) -> None:
    client.post("/api/imports/tracker")
    again = client.post("/api/imports/tracker").json()
    assert _file(again, "de")["status"] == "unchanged"

    flags = client.get("/api/imports/tracker/flags").json()
    assert [flag["entry_id"] for flag in flags] == ["a3"]
    assert client.post("/api/imports/tracker/flags/a3/count").status_code == 200
    assert client.get("/api/imports/tracker/flags").json() == []
    assert client.post("/api/imports/tracker/flags/nope/count").status_code == 404

    de = next(e for e in client.get("/api/stats/overview").json()["languages"] if e["language"] == "de")
    assert de["sessions"] == 6


def test_grown_csv_adds_only_new_rows(client, tmp_path: Path) -> None:
    folder = tmp_path / "tracker"
    shutil.copytree(FIXTURES / "tracker", folder)
    client.post("/api/imports/tracker", json={"path": str(folder)})
    with (folder / "immersion_log_de.csv").open("a", encoding="utf-8") as fh:
        fh.write("a8,session,reading,2026-09-01,,,Book,,900,15m,2026-09-01 20:00:00\n")
    de = _file(client.post("/api/imports/tracker", json={"path": str(folder)}).json(), "de")
    assert (de["imported"], de["already_present"], len(de["duplicates"])) == (1, 6, 1)


def test_session_dates_follow_the_tracker(client) -> None:
    client.post("/api/imports/tracker")
    engine = client.app.state.engine
    with engine.begin() as conn:
        rows = dict(
            conn.execute(text("SELECT external_ref, started_at FROM activity_sessions WHERE tracking = 'import'")).all()
        )
        url_title = conn.execute(
            text("SELECT title, notes FROM activity_sessions WHERE external_ref = 'a5'")
        ).one()
    # Logged 4 minutes after midnight for a 16-minute video: still counts on its own date.
    assert local_day(rows["a6"]) == date(2026, 8, 24)
    # Logged four days later: placed on the session's date, not the logging date.
    assert local_day(rows["a7"]) == date(2026, 8, 26)
    assert url_title[0] == "Listening session" and url_title[1].startswith("https://")


def test_user_edited_goals_are_not_overwritten(client, tmp_path: Path) -> None:
    client.patch("/api/settings", json={"goals": {"de": 90}})
    folder = tmp_path / "tracker"
    shutil.copytree(FIXTURES / "tracker", folder)
    summary = client.post("/api/imports/tracker", json={"path": str(folder)}).json()
    assert summary["goals_imported"] is None
    assert client.get("/api/settings").json()["goals"]["de"] == 90


def test_missing_folder_is_404(client, tmp_path: Path) -> None:
    response = client.post("/api/imports/tracker", json={"path": str(tmp_path / "nowhere")})
    assert response.status_code == 404
