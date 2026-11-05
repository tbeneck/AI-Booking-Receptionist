from __future__ import annotations

import json
from typing import Any

from app.appointments import book_appointment, check_availability, list_appointments
from app.config import settings

SYSTEM_INSTRUCTIONS = f"""You are a warm, professional phone receptionist for {settings.business_name}.

Your job is to greet callers, understand what they need, and book appointments.

Business details:
- Open Monday through Friday, 9:00 AM to 5:00 PM
- Appointment slots are 30 minutes
- Services: cleanings, checkups, consultations, and general dental care

Conversation style:
- Sound natural and human — use brief acknowledgments, friendly tone, and smooth transitions
- Ask one question at a time
- Confirm name, phone number, preferred date, and time before booking
- Read back the full appointment details before finalizing
- If a slot is unavailable, offer nearby alternatives from check_availability
- Keep responses concise — this is a phone call, not an essay

When the caller wants to book:
1. Ask for their full name
2. Ask for a callback phone number
3. Ask what date they prefer (accept natural language; convert to YYYY-MM-DD for tools)
4. Use check_availability before suggesting times
5. Ask what the visit is for
6. Use book_appointment once details are confirmed

If they ask about existing appointments, use list_appointments with their phone number.
"""

REALTIME_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "check_availability",
        "description": "Check open appointment slots for a given date (YYYY-MM-DD).",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                }
            },
            "required": ["date"],
        },
    },
    {
        "type": "function",
        "name": "book_appointment",
        "description": "Book an appointment after confirming all details with the caller.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Caller's full name."},
                "phone": {"type": "string", "description": "Caller's phone number."},
                "appointment_date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                },
                "appointment_time": {
                    "type": "string",
                    "description": "Time in HH:MM 24-hour format.",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for the visit.",
                },
            },
            "required": ["name", "phone", "appointment_date", "appointment_time"],
        },
    },
    {
        "type": "function",
        "name": "list_appointments",
        "description": "Look up existing appointments by phone number.",
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Phone number to search."}
            },
            "required": ["phone"],
        },
    },
]


def build_session_config(audio_format: str) -> dict[str, Any]:
    return {
        "modalities": ["text", "audio"],
        "instructions": SYSTEM_INSTRUCTIONS,
        "voice": settings.realtime_voice,
        "input_audio_format": audio_format,
        "output_audio_format": audio_format,
        "input_audio_transcription": {"model": "whisper-1"},
        "turn_detection": {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 500,
        },
        "tools": REALTIME_TOOLS,
        "tool_choice": "auto",
    }


def execute_tool(name: str, arguments: str) -> dict[str, Any]:
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return {"success": False, "message": "Invalid tool arguments."}

    if name == "check_availability":
        return check_availability(args.get("date", ""))
    if name == "book_appointment":
        return book_appointment(
            name=args.get("name", ""),
            phone=args.get("phone", ""),
            appointment_date=args.get("appointment_date", ""),
            appointment_time=args.get("appointment_time", ""),
            reason=args.get("reason", "General visit"),
        )
    if name == "list_appointments":
        return list_appointments(args.get("phone", ""))

    return {"success": False, "message": f"Unknown tool: {name}"}
