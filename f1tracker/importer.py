"""Read F1 game results screenshots with Claude and turn them into race-entry positions.

The Race Master pastes an Anthropic API key in Accounts > Settings. Nothing is sent anywhere until
someone clicks "Import from screenshot" on a race weekend. The positions are filled into the form for
review; nothing is saved until the normal autosave runs after they check it.
"""

import base64
import json
import os

from . import auth
from . import constants as C

KINDS = {"qualifying": "qualifying classification", "sprint": "sprint race classification",
         "race": "Grand Prix race classification"}
MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class ScreenshotError(ValueError):
    pass


def api_key():
    return auth.get_setting("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY") or ""


def configured():
    return bool(api_key())


def _schema(names):
    return {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "driver": {"type": "string", "enum": names},
                        "position": {"type": "integer"},
                        "status": {"type": "string", "enum": ["Finished", "DNF", "DNS", "DSQ"]},
                    },
                    "required": ["driver", "position", "status"],
                    "additionalProperties": False,
                },
            },
            "fastest_lap_driver": {"type": "string", "enum": names + [""]},
            "notes": {"type": "string"},
        },
        "required": ["rows", "fastest_lap_driver", "notes"],
        "additionalProperties": False,
    }


def _prompt(kind, entrants):
    lines = "\n".join(f"- {e['name']} ({e['team']})" for e in entrants)
    return f"""These screenshots are from the F1 video game and show a {KINDS[kind]}. They may be several
pages of the same table (for example P1-P11 and P12-P22).

Read every classified row and match each one to exactly one of these entrants. The game may show
surnames only, three-letter abbreviations, or team names next to drivers; use those to match. Two
entrants are human players whose in-game names may differ from the names below, so match them by
team and seat if the name doesn't fit.

Entrants:
{lines}

For each row give the finishing position shown on screen and a status: Finished for a classified
finish (including lapped cars), DNF for retired, DNS for did not start, DSQ for disqualified. Use
position numbers exactly as displayed; for DNF/DNS/DSQ rows give the position they are listed in.
Only include drivers you can actually see. If a fastest lap marker is visible, name that driver in
fastest_lap_driver, otherwise use an empty string. Put anything uncertain in notes."""


def read_screenshots(images, kind, entrants):
    """images: list of (bytes, media_type). entrants: list of {id, name, team}. Returns matched rows."""
    if kind not in KINDS:
        raise ScreenshotError("Choose qualifying, sprint or race")
    if not images:
        raise ScreenshotError("Add at least one screenshot")
    if len(images) > MAX_IMAGES:
        raise ScreenshotError(f"Up to {MAX_IMAGES} screenshots at a time")
    key = api_key()
    if not key:
        raise ScreenshotError("Screenshot import isn't set up yet. The Race Master can add an Anthropic API key in Accounts > Settings.")
    try:
        import anthropic
    except ModuleNotFoundError:
        raise ScreenshotError("The 'anthropic' package isn't installed. Restart with run.bat so it installs.")

    content = []
    for data, media_type in images:
        if media_type not in MEDIA_TYPES:
            raise ScreenshotError("Screenshots must be PNG, JPEG, WEBP or GIF")
        if len(data) > MAX_IMAGE_BYTES:
            raise ScreenshotError("Each screenshot must be under 8 MB")
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                    "data": base64.standard_b64encode(data).decode("ascii")}})
    names = [e["name"] for e in entrants]
    content.append({"type": "text", "text": _prompt(kind, entrants)})

    client = anthropic.Anthropic(api_key=key, timeout=180.0)
    try:
        response = client.beta.messages.create(
            model=C.IMPORT_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"format": {"type": "json_schema", "schema": _schema(names)}},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError:
        raise ScreenshotError("The Anthropic API key was rejected. Check it in Accounts > Settings.")
    except anthropic.PermissionDeniedError:
        raise ScreenshotError("That API key isn't allowed to use this model.")
    except anthropic.RateLimitError:
        raise ScreenshotError("The screenshot reader is busy (rate limited). Try again in a minute.")
    except anthropic.BadRequestError as exc:
        raise ScreenshotError(f"The screenshot couldn't be read: {exc.message}")
    except anthropic.APIStatusError as exc:
        raise ScreenshotError(f"The screenshot service returned an error ({exc.status_code}). Try again shortly.")
    except anthropic.APIConnectionError:
        raise ScreenshotError("Couldn't reach the screenshot service. Check the internet connection.")

    if response.stop_reason == "refusal":
        raise ScreenshotError("The screenshot reader declined this image. Enter these results by hand.")
    if response.stop_reason == "max_tokens":
        raise ScreenshotError("The screenshot was too long to read in one go. Try fewer pages at a time.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ScreenshotError("The screenshot reader returned something unexpected. Try again.")
    return match(data, entrants)


def match(data, entrants):
    """Turn the model's rows into driver ids, dropping duplicates and out-of-range positions."""
    by_name = {e["name"]: e["id"] for e in entrants}
    limit = max(C.MAX_POSITION, len(entrants))
    rows, seen_drivers, seen_positions, skipped = [], set(), set(), []
    for row in data.get("rows", []):
        did = by_name.get(row.get("driver"))
        pos = row.get("position")
        if did is None or not isinstance(pos, int) or not 1 <= pos <= limit:
            skipped.append(row)
            continue
        if did in seen_drivers or pos in seen_positions:
            skipped.append(row)
            continue
        seen_drivers.add(did)
        seen_positions.add(pos)
        rows.append({"driver_id": did, "position": pos, "status": row.get("status", "Finished")})
    fl = by_name.get(data.get("fastest_lap_driver") or "")
    return {"rows": sorted(rows, key=lambda r: r["position"]), "fastest_lap_driver_id": fl,
            "skipped": len(skipped), "notes": (data.get("notes") or "")[:500]}
