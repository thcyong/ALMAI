"""FastAPI backend for the chat demo.

Serves the minimal chat UI at "/" and exposes ``POST /api/chat`` which delegates
to :func:`llm.run_agent`. All PostgreSQL reads happen inside ``financial_query``
and remain unchanged; the LLM only supplies query parameters.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root (containing ontology/ and financial_query/) is importable.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

try:
    from .llm import run_agent
except ImportError:  # also allow running as a script via "python chat/app.py"
    from chat.llm import run_agent

app = FastAPI(title="ALMAI Chat Demo")

_INDEX = Path(__file__).resolve().parent / "static" / "index.html"


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None


@app.get("/")
async def index():
    return FileResponse(_INDEX)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    return run_agent(req.message, req.history)


if __name__ == "__main__":
    import uvicorn

    # Launch directly (e.g. via VS Code F5) on the same port as the
    # documented "uvicorn chat.app:app --reload --port 8000" command.
    # reload=False keeps breakpoints working under the debugger.
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
