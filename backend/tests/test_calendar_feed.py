"""P4 — the .ics deadline feed: token-gated, read-only, stable UIDs so a
recomputed date updates its event rather than duplicating it."""


def _deal_with_deadline(client, tc_headers) -> str:
    txn = client.post(
        "/transactions", json={"property_address": "4 Feed Way, Fresno"}, headers=tc_headers
    ).json()["id"]
    client.post(f"/transactions/{txn}/timeline/stub", headers=tc_headers)
    return txn


def test_feed_requires_the_token(client, tc_headers, monkeypatch):
    monkeypatch.setenv("CALENDAR_FEED_TOKEN", "synthetic-feed-token")
    assert client.get("/calendar.ics").status_code == 401
    assert client.get("/calendar.ics?key=wrong").status_code == 401


def test_feed_serves_deadlines_as_ics(client, tc_headers, monkeypatch):
    monkeypatch.setenv("CALENDAR_FEED_TOKEN", "synthetic-feed-token")
    _deal_with_deadline(client, tc_headers)
    r = client.get("/calendar.ics?key=synthetic-feed-token")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    body = r.text
    assert body.startswith("BEGIN:VCALENDAR")
    assert "BEGIN:VEVENT" in body and "DTSTART;VALUE=DATE:" in body
    assert "4 Feed Way" in body  # address rides in the summary

    # stable UIDs: same book, same UIDs on a second fetch (update, not duplicate)
    r2 = client.get("/calendar.ics?key=synthetic-feed-token")
    uids = lambda t: sorted(line for line in t.splitlines() if line.startswith("UID:"))  # noqa: E731
    assert uids(r.text) == uids(r2.text)


def test_feed_url_needs_tc_and_carries_token(client, tc_headers, monkeypatch):
    monkeypatch.setenv("CALENDAR_FEED_TOKEN", "synthetic-feed-token")
    assert client.get("/transactions/calendar/feed-url").status_code in (401, 403)
    r = client.get("/transactions/calendar/feed-url", headers=tc_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True and body["url"].endswith("/calendar.ics?key=synthetic-feed-token")
