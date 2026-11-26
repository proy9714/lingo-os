"""Unchanged API answers are revalidated with an ETag instead of being sent again."""

from __future__ import annotations


def test_json_answers_carry_an_etag_and_unchanged_ones_are_not_sent_again(client) -> None:
    first = client.get("/api/settings")
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert etag.startswith('W/"') and first.headers["cache-control"] == "private, no-cache"
    again = client.get("/api/settings", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    other = client.get("/api/settings", headers={"If-None-Match": 'W/"something-else"'})
    assert other.status_code == 200 and other.json() == first.json()


def test_writes_errors_and_non_api_paths_are_left_alone(client) -> None:
    assert "etag" not in client.patch("/api/settings", json={}).headers
    missing = client.get("/api/tutor/reference/xx/weak-spots")
    assert missing.status_code >= 400 and "etag" not in missing.headers
    assert "etag" not in client.get("/api/languages/history-template.csv").headers
