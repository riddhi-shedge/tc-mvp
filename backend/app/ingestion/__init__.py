"""Part (a) — Ingestion agent.

Watches the dedicated deal address (Postmark inbound) and the manual-upload
fallback; detects doc type / readability / signatures; extracts fields with
confidence scores; emits a validated Payload. Never writes the SOR directly.
"""
