"""Address-based property enrichment for the buyer/agent/appraiser property card.

Zillow/MLS have no usable public API and can't be scraped, so we use ToS-clean
channels: RentCast (structured facts by address) + Google Street View Static (an
exterior photo) + plain deep links (Zillow/Maps/Realtor). Everything is OPTIONAL
and degrades gracefully — no key or no data simply yields an address-only card.
Public-record + street imagery only; no document content, no Rule-5 data.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Any

import httpx

_log = logging.getLogger(__name__)
_TIMEOUT = 10.0


def _http_json(url: str, headers: dict[str, str] | None = None) -> Any | None:
    # httpx (bundles certifi) — urllib fails SSL cert verification on macOS.
    try:
        r = httpx.get(url, headers=headers or {}, timeout=_TIMEOUT, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # network/HTTP/parse — enrichment is best-effort
        _log.info("enrichment: json fetch failed (%s)", type(exc).__name__)
        return None


def _http_bytes(url: str) -> bytes | None:
    try:
        r = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
        r.raise_for_status()
        return r.content
    except Exception as exc:
        _log.info("enrichment: image fetch failed (%s)", type(exc).__name__)
        return None


def deep_links(address: str) -> dict[str, str]:
    """Public deep links a party can click through to (no API key, no scraping)."""
    q = urllib.parse.quote(address)
    return {
        "maps": f"https://www.google.com/maps/search/?api=1&query={q}",
        "zillow": f"https://www.zillow.com/homes/{q}_rb/",
        "realtor": f"https://www.realtor.com/realestateandhomes-search/{q}",
    }


def embed_links(address: str | None) -> dict[str, str]:
    """Interactive Maps Embed API iframes (street-view panorama + satellite map)
    for the buyer's 'look around your home' moment. Computed fresh per request —
    never cached — so a key rotation takes effect immediately. The key appears in
    the iframe URL by design (that is how the Embed API works client-side);
    restrict it to your app's referrers in the Google Cloud console. Empty dict
    when no address or no key — the UI hides the feature."""
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not address or not key:
        return {}
    q = urllib.parse.quote(address)
    return {
        "street": f"https://www.google.com/maps/embed/v1/streetview?key={key}&location={q}",
        "map": f"https://www.google.com/maps/embed/v1/place?key={key}&q={q}&maptype=satellite&zoom=18",
    }


def fetch_facts(address: str) -> dict[str, Any] | None:
    """Structured property facts from RentCast (needs RENTCAST_API_KEY). None on
    no key / no data / error."""
    key = os.environ.get("RENTCAST_API_KEY")
    if not key or not address:
        return None
    url = "https://api.rentcast.io/v1/properties?" + urllib.parse.urlencode({"address": address})
    data = _http_json(url, {"X-Api-Key": key, "Accept": "application/json"})
    rec = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
    if not rec:
        return None
    facts = {
        "beds": rec.get("bedrooms"),
        "baths": rec.get("bathrooms"),
        "sqft": rec.get("squareFootage"),
        "year_built": rec.get("yearBuilt"),
        "lot_size": rec.get("lotSize"),
        "property_type": rec.get("propertyType"),
        "last_sale_price": rec.get("lastSalePrice"),
    }
    return {k: v for k, v in facts.items() if v not in (None, "")} or None


def street_view_image(address: str) -> bytes | None:
    """An exterior Street View JPEG for the address (needs GOOGLE_MAPS_API_KEY).
    Checks the metadata endpoint first so we never store a 'no imagery' placeholder."""
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key or not address:
        return None
    loc = urllib.parse.urlencode({"location": address, "key": key})
    meta = _http_json(f"https://maps.googleapis.com/maps/api/streetview/metadata?{loc}")
    if not meta or meta.get("status") != "OK":
        return None
    params = urllib.parse.urlencode({"size": "640x360", "location": address, "fov": "80", "key": key})
    return _http_bytes(f"https://maps.googleapis.com/maps/api/streetview?{params}")
