import asyncio
import threading

import aiohttp
import uvicorn
from fastapi import FastAPI
from pyrogram import idle
from pyrogram.types import BotCommand

from Aditya.core import config
from Aditya.core.clients import bot, assistant, call_py, LOGGER
from Aditya.core.helpers import smallcaps_title

# Handlers register karne ke liye import karna zaroori hai
from Aditya import play  # noqa: F401

BOT_COMMANDS = [
    ("start", "start the bot"),
    ("help", "help and command menu"),
    ("play", "play a song"),
    ("pause", "pause playback"),
    ("resume", "resume playback"),
    ("skip", "skip the track"),
    ("stop", "stop and leave"),
    ("id", "show ids"),
    ("ping", "check bot speed"),
]

web = FastAPI()


@web.get("/")
async def root():
    return {"status": "running"}


def run_web():
    uvicorn.run(web, host="0.0.0.0", port=config.PORT, log_level="warning")


async def keep_alive():
    """Render free web service ~15 min inactivity ke baad sula deta hai — bot khud apne URL ko ping karta hai."""
    if not config.RENDER_EXTERNAL_URL:
        LOGGER.info("RENDER_EXTERNAL_URL set nahi hai — keep-alive ping skip ho raha hai.")
        return

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(config.RENDER_EXTERNAL_URL, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    LOGGER.info(f"Keep-alive ping: {resp.status}")
            except Exception as e:
                LOGGER.warning(f"Keep-alive ping fail: {e}")
            await asyncio.sleep(config.PING_INTERVAL)


async def register_bot_commands():
    """'/' likhne par dikhne wala menu."""
    try:
        await bot.set_bot_commands([BotCommand(name, smallcaps_title(desc)) for name, desc in BOT_COMMANDS])
    except Exception as e:
        LOGGER.warning(f"Bot commands set nahi ho paye: {e}")


async def _run_once():
    await bot.start()
    LOGGER.info("✅ Bot started")

    await assistant.start()
    LOGGER.info("✅ Assistant started")

    # Assistant ke dialogs ek baar fetch karo taaki peers cache ho jaayein
    # (warna baad mein "Peer id invalid" aa sakta hai)
    try:
        async for _ in assistant.get_dialogs():
            pass
        LOGGER.info("✅ Assistant peers cached")
    except Exception as e:
        LOGGER.warning(f"Dialogs cache karne mein error: {e}")

    await call_py.start()
    LOGGER.info("✅ PyTgCalls started — ab bot music bajane ke liye taiyar hai")

    await register_bot_commands()

    if config.LOG_GROUP_ID:
        try:
            await bot.send_message(config.LOG_GROUP_ID, "✅ Bot restart ho gaya hai aur ab online hai.")
        except Exception as e:
            LOGGER.warning(f"Log group mein message nahi bhej paya: {e}")

    keep_alive_task = asyncio.create_task(keep_alive())

    try:
        await idle()
    finally:
        keep_alive_task.cancel()
        try:
            await bot.stop()
        except Exception:
            pass
        try:
            await assistant.stop()
        except Exception:
            pass
        LOGGER.info("🛑 Bot stopped")


async def main():
    """Koi unexpected crash ho to 10 second baad khud restart."""
    while True:
        try:
            await _run_once()
            break  # idle() sirf tabhi return karta hai jab process normally stop ho
        except Exception as e:
            LOGGER.error(f"Bot crash ho gaya, 10 second mein restart kar raha hoon: {e}")
            await asyncio.sleep(10)


if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main())
