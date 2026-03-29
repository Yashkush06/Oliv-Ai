"""
Oliv AI — FastAPI backend entry point.
All REST endpoints + WebSocket streaming.
"""
import asyncio
import json
import logging
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Startup ────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup."""
    from utils.logger import setup_logging
    setup_logging()
    logger.info("Oliv AI backend starting...")

    # Uvicorn on Windows hardcodes WindowsSelectorEventLoopPolicy which breaks Playwright subprocesses.
    # We must explicitly revert the global policy to ProactorEventLoop so that when Playwright
    # creates its background thread and loop, it gets a Proactor loop.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        logger.info("Set WindowsProactorEventLoopPolicy for Playwright compatibility.")

    # Import tools to trigger decorator registration
    import tools  # noqa: F401

    # Init LLM router if config exists
    from config.manager import load_config
    from llm.router import init_router
    config = load_config()
    if config.get("setup_complete"):
        try:
            init_router(config)
            logger.info("LLM router initialized.")
        except Exception as e:
            logger.warning(f"LLM router init failed (expected on first run): {e}")

    yield
    logger.info("Oliv AI backend shutting down.")


app = FastAPI(title="Oliv AI", version="1.0.0", lifespan=lifespan)
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── WebSocket manager ──────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
        self._confirm_queues: dict[str, asyncio.Queue] = {}
        self._answer_queues: dict[str, asyncio.Queue] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, event: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(json.dumps(event))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

    def get_confirm_queue(self, task_id: str) -> asyncio.Queue:
        if task_id not in self._confirm_queues:
            self._confirm_queues[task_id] = asyncio.Queue()
        return self._confirm_queues[task_id]

    def get_answer_queue(self, task_id: str) -> asyncio.Queue:
        if task_id not in self._answer_queues:
            self._answer_queues[task_id] = asyncio.Queue()
        return self._answer_queues[task_id]


manager = ConnectionManager()

# ── Request/Response models ────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str

class ConfirmRequest(BaseModel):
    task_id: str
    confirmed: bool

class AnswerRequest(BaseModel):
    task_id: str
    answer: str

class FeedbackRequest(BaseModel):
    task_id: str
    feedback: str

class ConfigUpdateRequest(BaseModel):
    config: dict

class SetupCompleteRequest(BaseModel):
    model_config_data: dict
    user_preferences: dict

class TestConnectionRequest(BaseModel):
    provider: str
    model: str
    base_url: Optional[str] = None
    api_provider: Optional[str] = None
    api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    from agent.loop import get_status
    return {"status": "ok", "agent": get_status()}


@app.get("/api/config")
async def get_config():
    from config.manager import load_config
    config = load_config()
    # Mask API key in response
    if config.get("model_config", {}).get("api_key"):
        config["model_config"]["api_key"] = "***"
    return config


@app.put("/api/config")
async def put_config(body: ConfigUpdateRequest):
    from config.manager import update_config
    from llm.router import init_router, get_router
    updated = update_config(body.config)
    # Hot-reload router
    try:
        router = get_router()
        router.reload(updated)
    except RuntimeError:
        init_router(updated)
    return {"success": True, "config": updated}


@app.get("/api/config/setup-status")
async def setup_status():
    from config.manager import get_value
    return {"setup_complete": bool(get_value("setup_complete", False))}


@app.post("/api/config/complete-setup")
async def complete_setup(body: SetupCompleteRequest):
    from config.manager import update_config
    from llm.router import init_router
    updated = update_config({
        "model_config": body.model_config_data,
        "user_preferences": body.user_preferences,
        "setup_complete": True,
    })
    init_router(updated)
    return {"success": True}


@app.post("/api/config/test-connection")
async def test_connection(body: TestConnectionRequest):
    try:
        if body.provider == "ollama":
            from llm.ollama_client import OllamaClient
            client = OllamaClient(
                model=body.model,
                base_url=body.base_url or "http://localhost:11434",
            )
        elif body.provider == "gemini":
            from llm.gemini_client import GeminiClient
            client = GeminiClient(
                api_key=body.gemini_api_key or body.api_key or "",
                model=body.model or "gemini-2.0-flash",
            )
        else:
            from llm.api_client import APIClient
            client = APIClient(
                api_provider=body.api_provider or "openai",
                api_key=body.api_key or "",
                model=body.model,
                base_url=body.base_url,
            )
        ok = client.test_connection()
        return {"success": ok, "message": "Connected!" if ok else "Connection failed."}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.get("/api/ollama/models")
async def list_ollama_models():
    from llm.ollama_client import OllamaClient
    from config.manager import get_value
    base_url = get_value("model_config.base_url", "http://localhost:11434")
    models = OllamaClient.list_models(base_url)
    
    extra_models = [
        "gpt-oss:120b-cloud",
        "gpt-oss:20b-cloud",
        "deepseek-v3.1:671b-cloud",
        "qwen3-coder:480b-cloud",
        "qwen3-vl:235b-cloud",
        "minimax-m2:cloud",
        "alm-4.6:cloud"
    ]
    for m in extra_models:
        if m not in models:
            models.append(m)
            
    return {"models": models}


@app.get("/api/logs")
async def get_logs(last_n: int = 200):
    from utils.logger import read_logs
    return {"logs": read_logs(last_n)}


@app.get("/api/memory")
async def get_memory():
    from memory.store import get_recent
    return {"memories": get_recent(50)}


@app.post("/api/chat")
async def chat(body: ChatRequest):
    """Kick off an agent task. Events streamed via WebSocket /ws/stream."""
    from agent.loop import get_status, run_task, acquire_lock

    task_id = str(uuid.uuid4())[:8]
    if not acquire_lock(task_id):
        raise HTTPException(status_code=409, detail="Agent is already running a task.")

    # Learn from corrections first
    from memory.preference_learner import learn_from_message
    changes = learn_from_message(body.message)
    if changes:
        await manager.broadcast({
            "type": "preference_updated",
            "data": changes,
            "message": f"Preference updated: {changes}",
        })

    task_id_holder = {}

    def emit(event: dict):
        task_id_holder["id"] = event.get("task_id", "")
        asyncio.create_task(manager.broadcast(event))
        from utils.logger import write_log
        write_log(event.get("status", "info"), event.get("message", ""), event)

    confirm_queue = None

    async def run():
        nonlocal confirm_queue
        confirm_queue = manager.get_confirm_queue(task_id)
        answer_queue = manager.get_answer_queue(task_id)
        result = await run_task(body.message, emit, confirm_queue, answer_queue=answer_queue, task_id=task_id)
        return result

    asyncio.create_task(run())
    return {"success": True, "message": "Task started. Watch /ws/stream for updates."}


@app.post("/api/stop")
async def stop():
    from agent.loop import stop_task
    stop_task()
    return {"success": True, "message": "Stop signal sent."}


@app.post("/api/reset-lock")
async def reset_lock():
    from agent.loop import reset_lock
    reset_lock()
    return {"success": True, "message": "Task lock reset."}


@app.post("/api/confirm")
async def confirm_action(body: ConfirmRequest):
    q = manager.get_confirm_queue(body.task_id)
    await q.put(body.confirmed)
    return {"success": True}


@app.post("/api/answer")
async def answer_prompt(body: AnswerRequest):
    q = manager.get_answer_queue(body.task_id)
    await q.put(body.answer)
    return {"success": True}


@app.post("/api/memory/feedback")
async def send_feedback(body: FeedbackRequest):
    from memory.store import update_memory_feedback
    updated = update_memory_feedback(body.task_id, body.feedback)
    return {"success": updated}


@app.get("/api/tools")
async def get_tools():
    from tools.registry import list_tools
    return {"tools": list_tools()}


# ── WebSocket ──────────────────────────────────────────────────────────────────

@app.websocket("/ws/stream")
async def websocket_stream(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive; client sends "ping" messages
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(ws)
