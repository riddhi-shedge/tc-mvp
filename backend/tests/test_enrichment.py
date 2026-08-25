"""Address property enrichment (party workspaces). No real HTTP in CI — the
network helpers are monkeypatched; the no-key paths make no call at all. Confirms
the RentCast/Street View mapping AND that everything degrades gracefully."""

from __future__ import annotations

import app.enrichment.property_data as pd


def test_deep_links_are_pure_and_encoded():
    links = pd.deep_links("21989 McClellan Rd, Cupertino, CA")
    assert "google.com/maps" in links["maps"]
    assert "zillow.com" in links["zillow"]
    assert "realtor.com" in links["realtor"]
    assert "McClellan" in links["maps"]  # address is URL-encoded but preserved


def test_fetch_facts_no_key_makes_no_call(monkeypatch):
    monkeypatch.delenv("RENTCAST_API_KEY", raising=False)
    monkeypatch.setattr(pd, "_http_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert pd.fetch_facts("21989 McClellan Rd") is None


def test_fetch_facts_maps_rentcast_record(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY", "k")
    monkeypatch.setattr(pd, "_http_json", lambda url, headers=None: [
        {"bedrooms": 4, "bathrooms": 3, "squareFootage": 2100, "yearBuilt": 1998,
         "lotSize": 6000, "propertyType": "Single Family", "lastSalePrice": 1_800_000},
    ])
    facts = pd.fetch_facts("21989 McClellan Rd")
    assert facts == {
        "beds": 4, "baths": 3, "sqft": 2100, "year_built": 1998,
        "lot_size": 6000, "property_type": "Single Family", "last_sale_price": 1_800_000,
    }


def test_fetch_facts_empty_or_error_is_none(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY", "k")
    monkeypatch.setattr(pd, "_http_json", lambda url, headers=None: [])
    assert pd.fetch_facts("nowhere") is None
    monkeypatch.setattr(pd, "_http_json", lambda url, headers=None: None)  # network fail
    assert pd.fetch_facts("nowhere") is None


def test_street_view_no_key_makes_no_call(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setattr(pd, "_http_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert pd.street_view_image("21989 McClellan Rd") is None


def test_street_view_ok_returns_bytes(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k")
    monkeypatch.setattr(pd, "_http_json", lambda url, headers=None: {"status": "OK"})
    monkeypatch.setattr(pd, "_http_bytes", lambda url: b"\xff\xd8jpegbytes")
    assert pd.street_view_image("21989 McClellan Rd") == b"\xff\xd8jpegbytes"


def test_street_view_zero_results_returns_none(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k")
    monkeypatch.setattr(pd, "_http_json", lambda url, headers=None: {"status": "ZERO_RESULTS"})
    # metadata says no imagery → we never fetch/store a placeholder
    monkeypatch.setattr(pd, "_http_bytes", lambda url: (_ for _ in ()).throw(AssertionError("called")))
    assert pd.street_view_image("123 Stub St") is None
