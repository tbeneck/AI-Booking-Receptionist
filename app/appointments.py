from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.database import get_connection

BUSINESS_HOURS = {
    0: (9, 17),  # Monday
    1: (9, 17),
    2: (9, 17),
    3: (9, 17),
    4: (9, 17),
}

SLOT_MINUTES = 30


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _format_slot(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _booked_slots(target_date: str) -> set[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT appointment_time FROM appointments WHERE appointment_date = ?",
            (target_date,),
        ).fetchall()
    return {row["appointment_time"] for row in rows}


def check_availability(target_date: str) -> dict[str, Any]:
    try:
        parsed = _parse_date(target_date)
    except ValueError:
        return {"success": False, "message": "Please use date format YYYY-MM-DD."}

    weekday = parsed.weekday()
    if weekday > 4:
        return {
            "success": True,
            "date": target_date,
            "available_slots": [],
            "message": "We are closed on weekends.",
        }

    start_hour, end_hour = BUSINESS_HOURS[weekday]
    booked = _booked_slots(target_date)
    slots: list[str] = []

    current = datetime.combine(parsed, datetime.min.time()).replace(hour=start_hour)
    end = datetime.combine(parsed, datetime.min.time()).replace(hour=end_hour)
    while current + timedelta(minutes=SLOT_MINUTES) <= end:
        slot = _format_slot(current.hour, current.minute)
        if slot not in booked:
            slots.append(slot)
        current += timedelta(minutes=SLOT_MINUTES)

    return {
        "success": True,
        "date": target_date,
        "available_slots": slots,
        "message": f"Found {len(slots)} open slots on {target_date}.",
    }


def book_appointment(
    name: str,
    phone: str,
    appointment_date: str,
    appointment_time: str,
    reason: str = "General visit",
) -> dict[str, Any]:
    availability = check_availability(appointment_date)
    if not availability.get("success"):
        return availability

    if appointment_time not in availability["available_slots"]:
        return {
            "success": False,
            "message": (
                f"Sorry, {appointment_time} on {appointment_date} is not available. "
                f"Open slots: {', '.join(availability['available_slots'][:5])}"
            ),
        }

    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO appointments (name, phone, appointment_date, appointment_time, reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name.strip(), phone.strip(), appointment_date, appointment_time, reason.strip()),
            )
            conn.commit()
    except Exception:
        return {
            "success": False,
            "message": "That time slot was just taken. Please choose another time.",
        }

    return {
        "success": True,
        "message": (
            f"Appointment confirmed for {name} on {appointment_date} at {appointment_time}. "
            f"We'll see you for {reason}."
        ),
        "appointment": {
            "name": name,
            "phone": phone,
            "date": appointment_date,
            "time": appointment_time,
            "reason": reason,
        },
    }


def list_appointments(phone: str) -> dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT name, phone, appointment_date, appointment_time, reason
            FROM appointments
            WHERE phone = ?
            ORDER BY appointment_date, appointment_time
            """,
            (phone.strip(),),
        ).fetchall()

    appointments = [dict(row) for row in rows]
    return {
        "success": True,
        "appointments": appointments,
        "message": f"Found {len(appointments)} appointment(s) for {phone}.",
    }


def list_all_appointments() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, phone, appointment_date, appointment_time, reason, created_at
            FROM appointments
            ORDER BY appointment_date, appointment_time
            """
        ).fetchall()
    return [dict(row) for row in rows]
