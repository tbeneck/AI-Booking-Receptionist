from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from app.agent import build_session_config, execute_tool
from app.config import settings

logger = logging.getLogger(__name__)

OPENAI_REALTIME_URL = (
    f"wss://api.openai.com/v1/realtime?model={settings.realtime_model}"
)


async def _send_openai(openai_ws: websockets.WebSocketClientProtocol, payload: dict[str, Any]) -> None:
    await openai_ws.send(json.dumps(payload))


async def _handle_openai_events(
    openai_ws: websockets.WebSocketClientProtocol,
    send_audio: Any,
    send_mark: Any | None = None,
) -> None:
    """Forward OpenAI audio to client and handle tool calls."""
    async for raw in openai_ws:
        event = json.loads(raw)
        event_type = event.get("type", "")

        if event_type == "response.audio.delta":
            delta = event.get("delta")
            if delta:
                await send_audio(delta)

        elif event_type == "response.function_call_arguments.done":
            call_id = event.get("call_id")
            name = event.get("name")
            arguments = event.get("arguments", "{}")
            result = execute_tool(name, arguments)
            logger.info("Tool %s -> %s", name, result.get("message", result))

            await _send_openai(
                openai_ws,
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result),
                    },
                },
            )
            await _send_openai(openai_ws, {"type": "response.create"})

        elif event_type == "response.audio.done" and send_mark:
            await send_mark()

        elif event_type == "error":
            logger.error("OpenAI Realtime error: %s", event)


async def bridge_twilio_stream(twilio_ws: WebSocket) -> None:
    """Bridge Twilio Media Stream (g711_ulaw) to OpenAI Realtime."""
    await twilio_ws.accept()
    stream_sid: str | None = None
    mark_queue: asyncio.Queue[str] = asyncio.Queue()

    headers = {"Authorization": f"Bearer {settings.openai_api_key}", "OpenAI-Beta": "realtime=v1"}

    try:
        async with websockets.connect(OPENAI_REALTIME_URL, additional_headers=headers) as openai_ws:
            await _send_openai(
                openai_ws,
                {
                    "type": "session.update",
                    "session": build_session_config("g711_ulaw"),
                },
            )

            async def send_audio_to_twilio(delta_b64: str) -> None:
                if not stream_sid:
                    return
                await twilio_ws.send_json(
                    {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": delta_b64},
                    }
                )

            async def send_mark_to_twilio() -> None:
                if not stream_sid:
                    return
                label = f"mark-{asyncio.get_event_loop().time()}"
                mark_queue.put_nowait(label)
                await twilio_ws.send_json(
                    {
                        "event": "mark",
                        "streamSid": stream_sid,
                        "mark": {"name": label},
                    }
                )

            openai_task = asyncio.create_task(
                _handle_openai_events(openai_ws, send_audio_to_twilio, send_mark_to_twilio)
            )

            try:
                while True:
                    message = await twilio_ws.receive_text()
                    data = json.loads(message)
                    event = data.get("event")

                    if event == "start":
                        stream_sid = data["start"]["streamSid"]
                        logger.info("Twilio stream started: %s", stream_sid)

                    elif event == "media":
                        payload = data["media"]["payload"]
                        await _send_openai(
                            openai_ws,
                            {"type": "input_audio_buffer.append", "audio": payload},
                        )

                    elif event == "mark":
                        try:
                            mark_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass

                    elif event == "stop":
                        logger.info("Twilio stream stopped")
                        break

            except WebSocketDisconnect:
                logger.info("Twilio WebSocket disconnected")
            finally:
                openai_task.cancel()
                try:
                    await openai_task
                except asyncio.CancelledError:
                    pass

    except websockets.exceptions.InvalidStatusCode as exc:
        logger.error("Failed to connect to OpenAI Realtime: %s", exc)
        await twilio_ws.close(code=1011)


async def bridge_browser_stream(browser_ws: WebSocket) -> None:
    """Bridge browser WebSocket (pcm16) to OpenAI Realtime."""
    await browser_ws.accept()

    headers = {"Authorization": f"Bearer {settings.openai_api_key}", "OpenAI-Beta": "realtime=v1"}

    try:
        async with websockets.connect(OPENAI_REALTIME_URL, additional_headers=headers) as openai_ws:
            await _send_openai(
                openai_ws,
                {
                    "type": "session.update",
                    "session": build_session_config("pcm16"),
                },
            )

            async def send_audio_to_browser(delta_b64: str) -> None:
                await browser_ws.send_json({"type": "audio", "data": delta_b64})

            async def forward_openai() -> None:
                async for raw in openai_ws:
                    event = json.loads(raw)
                    event_type = event.get("type", "")

                    if event_type == "response.audio.delta":
                        delta = event.get("delta")
                        if delta:
                            await send_audio_to_browser(delta)

                    elif event_type == "response.function_call_arguments.done":
                        call_id = event.get("call_id")
                        name = event.get("name")
                        arguments = event.get("arguments", "{}")
                        result = execute_tool(name, arguments)
                        logger.info("Tool %s -> %s", name, result.get("message", result))

                        await browser_ws.send_json(
                            {"type": "tool_call", "name": name, "result": result}
                        )

                        await _send_openai(
                            openai_ws,
                            {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": json.dumps(result),
                                },
                            },
                        )
                        await _send_openai(openai_ws, {"type": "response.create"})

                    elif event_type in ("session.created", "session.updated", "response.done"):
                        await browser_ws.send_json({"type": event_type, "event": event})

                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        transcript = event.get("transcript", "")
                        if transcript:
                            await browser_ws.send_json(
                                {"type": "transcript", "role": "user", "text": transcript}
                            )

                    elif event_type == "response.audio_transcript.done":
                        transcript = event.get("transcript", "")
                        if transcript:
                            await browser_ws.send_json(
                                {"type": "transcript", "role": "assistant", "text": transcript}
                            )

                    elif event_type == "error":
                        logger.error("OpenAI Realtime error: %s", event)
                        await browser_ws.send_json({"type": "error", "event": event})

            openai_task = asyncio.create_task(forward_openai())

            try:
                while True:
                    message = await browser_ws.receive_text()
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "audio":
                        await _send_openai(
                            openai_ws,
                            {
                                "type": "input_audio_buffer.append",
                                "audio": data["data"],
                            },
                        )

                    elif msg_type == "commit":
                        await _send_openai(openai_ws, {"type": "input_audio_buffer.commit"})
                        await _send_openai(openai_ws, {"type": "response.create"})

                    elif msg_type == "clear":
                        await _send_openai(openai_ws, {"type": "input_audio_buffer.clear"})

            except WebSocketDisconnect:
                logger.info("Browser WebSocket disconnected")
            finally:
                openai_task.cancel()
                try:
                    await openai_task
                except asyncio.CancelledError:
                    pass

    except websockets.exceptions.InvalidStatusCode as exc:
        logger.error("Failed to connect to OpenAI Realtime: %s", exc)
        await browser_ws.send_json({"type": "error", "message": str(exc)})
        await browser_ws.close(code=1011)
