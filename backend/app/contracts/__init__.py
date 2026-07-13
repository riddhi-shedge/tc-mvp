"""Shared boundary contracts.

The ONLY thing parts (a) ingestion, (b) master, and (c) compliance are allowed
to share. Parts exchange validated Payloads defined here; they never import each
other's internal modules or touch each other's database. See rules/architecture.md.
"""
