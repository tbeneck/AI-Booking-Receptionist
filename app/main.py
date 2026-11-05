from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.appointments import list_all_appointments
from app.config import settings
from app.database import init_db
from app.realtime_bridge import bridge_browser_stream, bridge_twilio_stream

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Voice Appointment Agent", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def startup() -> None:
    init_db()
    logger.info("Voice agent started for %s", settings.business_name)
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY is not set — voice features will not work")
    if not settings.twilio_configured:
        logger.info("Twilio not configured — use the browser demo at /")


@app.get("/", response_class=HTMLResponse)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "business": settings.business_name}


@app.get("/api/appointments")
async def get_appointments() -> JSONResponse:
    return JSONResponse({"appointments": list_all_appointments()})


@app.post("/voice/incoming")
async def voice_incoming(request: Request) -> HTMLResponse:
    """Twilio webhook — answer call and stream audio to OpenAI Realtime."""
    host = request.headers.get("host", "localhost:8000")
    scheme = "wss" if request.url.scheme == "https" or "ngrok" in host else "ws"
    stream_url = f"{scheme}://{host}/voice/media-stream"

    response = VoiceResponse()
    response.say(
        "Please wait while we connect you.",
        voice="Polly.Joanna-Neural",
    )
    connect = Connect()
    connect.stream(url=stream_url)
    response.append(connect)

    logger.info("Incoming call — streaming to %s", stream_url)
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/voice/media-stream")
async def twilio_media_stream(websocket: WebSocket) -> None:
    await bridge_twilio_stream(websocket)


@app.websocket("/ws/demo")
async def browser_demo_stream(websocket: WebSocket) -> None:
    await bridge_browser_stream(websocket)
