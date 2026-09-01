from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

app = FastAPI(
    title="AI Audit Assistant",
    description=(
        "AI-assisted financial document auditing: deterministic rules and "
        "statistical anomaly detection produce findings; an LLM only "
        "explains those findings — it never decides risk on its own."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # fine for a local hackathon demo; tighten for prod
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root():
    return {
        "service": "ai-audit-assistant",
        "docs": "/docs",
        "endpoints": ["/audit/upload", "/audit/sample/{name}", "/audit/samples"],
    }
