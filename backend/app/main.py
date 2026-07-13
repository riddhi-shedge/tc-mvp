"""FastAPI entry point for the tc-mvp backend.

Thin composition root. Real routes (Postmark inbound webhook, HITL confirmation,
extraction review, approval/send) are added in later Stage C phases.
"""

from fastapi import FastAPI

app = FastAPI(title="tc-mvp")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
