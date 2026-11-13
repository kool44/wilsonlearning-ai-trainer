"""FastAPI entry point. Serves the API and the static single-page UI."""
import logging

from fastapi import FastAPI, HTTPException
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, content, db, engine

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Counselor Salesperson AI Trainer", version="0.1.0")
STATIC = config.ROOT / "static"


@app.on_event("startup")
def _startup() -> None:
    db.init()
    mods = content.load_all()
    logging.getLogger("trainer").info("loaded modules: %s", list(mods))


class StartBody(BaseModel):
    module_id: str
    learner_name: str | None = None


class MessageBody(BaseModel):
    text: str


class CommandBody(BaseModel):
    cmd: str  # skip | repeat | restart | hint | end_call | continue


@app.get("/api/health")
def health():
    return {"ok": True, "provider": config.LLM_PROVIDER, "model": config.MODEL}


@app.get("/api/modules")
def modules():
    return content.list_modules()


@app.post("/api/session")
def create_session(body: StartBody):
    try:
        return engine.start(body.module_id, body.learner_name)
    except KeyError:
        raise HTTPException(404, "unknown module")


@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    s = engine.get(session_id)
    if not s:
        raise HTTPException(404, "unknown session")
    return s


@app.post("/api/session/{session_id}/message")
def post_message(session_id: str, body: MessageBody):
    s = engine.message(session_id, body.text)
    if not s:
        raise HTTPException(404, "unknown session")
    return s


@app.post("/api/session/{session_id}/command")
def post_command(session_id: str, body: CommandBody):
    s = engine.command(session_id, body.cmd)
    if not s:
        raise HTTPException(404, "unknown session")
    return s


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """Static files are tiny; never let the browser serve a stale app.js after a deploy."""
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
