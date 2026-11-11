"""
Now Playing card ke progress-bar button (00:35 ●────── 04:38) ko gaane ke saath
aage badhata rehta hai. Button ka COLOR fixed rehta hai — sirf bar/time badalta hai.

Updater tab tak chalta hai jab tak gaana khatam, skip, stop ya replay na ho.
Pause ke dauraan bar wahin ruka rehta hai (us time koi edit nahi hota).
"""

import asyncio
import time

from pyrogram.errors import FloodWait

from Aditya.core.clients import LOGGER

UPDATE_INTERVAL = 10          # seconds — progress bar itne gap par update hota hai
BAR_LENGTH = 8                # button text chhota rakha hai taaki line se bahar na nikle
MAX_EDIT_FAILURES = 3         # itni baar edit fail hone par updater khud band ho jaata hai

# chat_id -> {"start": monotonic ts, "paused_at": ts|None, "paused_total": float, "video_id": str}
_progress: dict = {}

# chat_id -> background asyncio.Task
_tasks: dict = {}


def _now() -> float:
    return time.monotonic()


def start(chat_id: int, video_id: str):
    """Naya track shuru hone par elapsed-time tracking (0 se) reset karta hai."""
    _progress[chat_id] = {"start": _now(), "paused_at": None, "paused_total": 0.0, "video_id": video_id}


def pause(chat_id: int):
    p = _progress.get(chat_id)
    if p and p["paused_at"] is None:
        p["paused_at"] = _now()


def resume(chat_id: int):
    p = _progress.get(chat_id)
    if p and p["paused_at"] is not None:
        p["paused_total"] += _now() - p["paused_at"]
        p["paused_at"] = None


def replay(chat_id: int):
    """Bar ko 00:00 se dobara shuru karta hai."""
    p = _progress.get(chat_id)
    if p:
        p["start"] = _now()
        p["paused_at"] = None
        p["paused_total"] = 0.0


def seek_to(chat_id: int, new_elapsed: float):
    """Bar ko kisi position par le jaata hai (15s+ button ke liye) — playing aur paused dono mein."""
    p = _progress.get(chat_id)
    if not p:
        return
    new_elapsed = max(0.0, new_elapsed)
    if p["paused_at"] is not None:
        p["start"] = p["paused_at"] - new_elapsed
    else:
        p["start"] = _now() - new_elapsed
    p["paused_total"] = 0.0


def is_paused(chat_id: int) -> bool:
    p = _progress.get(chat_id)
    return bool(p and p["paused_at"] is not None)


def elapsed(chat_id: int) -> float:
    """Ab tak kitna waqt beet gaya (seconds), pause ka time ginte hue nahi."""
    p = _progress.get(chat_id)
    if not p:
        return 0.0
    ref = p["paused_at"] if p["paused_at"] is not None else _now()
    return max(0.0, ref - p["start"] - p["paused_total"])


def cancel_task(chat_id: int):
    task = _tasks.pop(chat_id, None)
    if task and not task.done():
        task.cancel()


def clear(chat_id: int):
    """Track/session poori tarah khatam — tracking + updater dono band."""
    _progress.pop(chat_id, None)
    cancel_task(chat_id)


def _mmss(sec) -> str:
    sec = max(int(sec), 0)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def render_button_bar(elapsed_sec: float, total_sec: int) -> str:
    """00:08 ●─────── 03:06"""
    total_sec = max(total_sec, 1)
    ratio = min(max(elapsed_sec / total_sec, 0.0), 1.0)
    pos = int(round(ratio * (BAR_LENGTH - 1)))
    bar = "─" * pos + "●" + "─" * (BAR_LENGTH - 1 - pos)
    return f"{_mmss(elapsed_sec)} {bar} {_mmss(total_sec)}"


def start_updater(chat_id: int, message, markup_fn, video_id: str, total_sec: int):
    """
    Background task: har UPDATE_INTERVAL seconds par sirf buttons (progress bar) refresh karta hai.
    `markup_fn(elapsed, total)` -> InlineKeyboardMarkup (colors fixed).
    """
    cancel_task(chat_id)
    if total_sec <= 0:
        return  # duration pata nahi to bar dikhane ka fayda nahi

    async def _runner():
        failures = 0
        try:
            while True:
                await asyncio.sleep(UPDATE_INTERVAL)

                p = _progress.get(chat_id)
                if not p or p.get("video_id") != video_id:
                    return  # track badal gaya / skip / stop / replay

                if p["paused_at"] is not None:
                    continue  # pause mein bar nahi badalta

                el = min(elapsed(chat_id), total_sec)
                try:
                    await message.edit_reply_markup(markup_fn(el, total_sec))
                    failures = 0
                except FloodWait as e:
                    await asyncio.sleep(int(getattr(e, "value", 10)) + 1)
                except Exception as e:
                    if "MESSAGE_NOT_MODIFIED" not in str(e):
                        failures += 1
                        LOGGER.warning(f"Progress update fail ({failures}): {e}")
                        if failures >= MAX_EDIT_FAILURES:
                            return

                if el >= total_sec:
                    return
        except asyncio.CancelledError:
            pass

    _tasks[chat_id] = asyncio.create_task(_runner())
