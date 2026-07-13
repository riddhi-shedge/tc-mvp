"""FastAPI entry point for the tc-mvp backend.

Thin composition root. Real routes (Postmark inbound webhook, HITL confirmation,
extraction review, approval/send) are added in later Stage C phases.
"""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError

from app.ingestion.routes import router as ingestion_router
from app.master.routes import router as master_router

logger = logging.getLogger("tc_mvp")

app = FastAPI(title="tc-mvp")
app.include_router(master_router)
app.include_router(ingestion_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(APIError)
async def postgrest_error_handler(request: Request, exc: APIError) -> JSONResponse:
    # Log only the error class and code — never row content, field values, or
    # anything that could carry NPI (rules/security.md logging discipline).
    logger.error(
        "Database operation failed on %s %s: %s (code=%s)",
        request.method,
        request.url.path,
        type(exc).__name__,
        getattr(exc, "code", None),
    )
    return JSONResponse(status_code=502, content={"detail": "Database operation failed"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
