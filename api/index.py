import os
import re
import json
import requests

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI()


BASE_URL = "https://better-campus.vercel.app"

SERVICE_ID = 1370

SPORTS = {
    "gym": 8,
    "thai": 15,
}

NEXT_ACTION = "702932d38981fc7306e6a3cb45516f4f5e7e10d6bb"

COOKIE = os.environ["BETTER_CAMPUS_COOKIE"]


# --------------------------------------------------
# Request model
# --------------------------------------------------

class BookingRequest(BaseModel):
    sport: str
    date: str
    time: str


# --------------------------------------------------
# Get slots
# --------------------------------------------------

def get_slots(date: str, allowance_id: int):

    url = f"{BASE_URL}/services/{SERVICE_ID}/{allowance_id}"

    response = requests.get(
        url,
        params={"date": date},
        headers={
            "Cookie": f"t={COOKIE}",
            "User-Agent": "Mozilla/5.0",
        },
        timeout=15,
    )

    response.raise_for_status()

    text = response.text.replace('\\"', '"')

    slots = []

    for match in re.finditer(
        r'"slot":(\{.*?\})',
        text,
    ):
        try:
            slot = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue

        if all(
            key in slot
            for key in ("id", "start", "end")
        ):
            slots.append(slot)

    return slots


# --------------------------------------------------
# Reserve
# --------------------------------------------------

def reserve(
    date: str,
    slot_id: int,
    allowance_id: int,
):

    url = f"{BASE_URL}/services/{SERVICE_ID}/{allowance_id}"

    headers = {
        "Accept": "text/x-component",
        "Content-Type": "text/plain;charset=UTF-8",
        "Origin": BASE_URL,
        "Referer": (
            f"{BASE_URL}/services/"
            f"{SERVICE_ID}/{allowance_id}"
            f"?date={date}"
        ),
        "next-action": NEXT_ACTION,
        "Cookie": f"t={COOKIE}",
        "User-Agent": "Mozilla/5.0",
    }

    payload = json.dumps(
        [allowance_id, date, slot_id],
        separators=(",", ":"),
    )

    response = requests.post(
        url,
        params={"date": date},
        headers=headers,
        data=payload,
        timeout=15,
    )

    response.raise_for_status()

    return response.text


# --------------------------------------------------
# Parse booking result
# --------------------------------------------------

def parse_reservation_response(response: str):

    match = re.search(
        r'\{"success":(true|false),"message":"([^"]*)"\}',
        response,
    )

    if not match:
        return None

    success = match.group(1) == "true"
    message = match.group(2)

    return success, message


# --------------------------------------------------
# API endpoint
# --------------------------------------------------

@app.post("/api/check")
def check_booking(request: BookingRequest):

    # Validate sport
    if request.sport not in SPORTS:
        return {
            "status": "error",
            "message": "Invalid sport.",
        }

    allowance_id = SPORTS[request.sport]

    try:

        # ------------------------------------------
        # Get slots
        # ------------------------------------------

        slots = get_slots(
            request.date,
            allowance_id,
        )

        if not slots:
            return {
                "status": "error",
                "message": "No slots found.",
            }

        # ------------------------------------------
        # Find requested time
        # ------------------------------------------

        target = next(
            (
                slot
                for slot in slots
                if slot.get("start") == request.time
            ),
            None,
        )

        if target is None:
            return {
                "status": "not_found",
                "message": (
                    f"No slot starts at "
                    f"{request.time}."
                ),
            }

        capacity = target.get("capacity")
        reserved_count = target.get("reserved")

        available = None

        if (
            isinstance(capacity, int)
            and isinstance(reserved_count, int)
        ):
            available = capacity - reserved_count

        # ------------------------------------------
        # Not bookable
        # ------------------------------------------

        if not target.get("canBook"):

            return {
                "status": "waiting",
                "message": "Slot is not currently available.",
                "sport": request.sport,
                "date": request.date,
                "time": request.time,
                "slot_id": target["id"],
                "available": available,
                "capacity": capacity,
                "reserved": reserved_count,
                "waiting_list": target.get("waitingList"),
            }

        # ------------------------------------------
        # Available -> reserve
        # ------------------------------------------

        response = reserve(
            date=request.date,
            slot_id=target["id"],
            allowance_id=allowance_id,
        )

        result = parse_reservation_response(
            response
        )

        if result is None:

            return {
                "status": "error",
                "message": "Could not parse reservation response.",
                "raw": response,
            }

        success, message = result

        if success:

            return {
                "status": "booked",
                "message": message,
                "sport": request.sport,
                "date": request.date,
                "time": request.time,
                "slot_id": target["id"],
            }

        # Someone may have taken it between GET and POST
        return {
            "status": "waiting",
            "message": message,
            "sport": request.sport,
            "date": request.date,
            "time": request.time,
            "slot_id": target["id"],
        }

    except requests.RequestException as error:

        return {
            "status": "error",
            "message": str(error),
        }

    except Exception as error:

        return {
            "status": "error",
            "message": str(error),
        }
