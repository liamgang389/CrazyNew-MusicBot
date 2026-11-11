import logging
import time
from pyrogram import Client
from pytgcalls import PyTgCalls

from Aditya.core import config

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] - [%(levelname)s] - %(name)s - %(message)s",
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("pytgcalls").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Compatibility shim: py-tgcalls==0.9.7 UpdateGroupCall par `.chat_id` maangta hai,
# naye kurigram mein sirf `.peer` hota hai. Yeh patch `.chat_id` ko `.peer` se nikaal deta hai.
# ---------------------------------------------------------------------------
try:
    from pyrogram.raw.types import UpdateGroupCall, PeerChat, PeerChannel

    if "chat_id" not in UpdateGroupCall.__dict__:
        def _shim_chat_id(self):
            peer = getattr(self, "peer", None)
            if isinstance(peer, PeerChat):
                return peer.chat_id
            if isinstance(peer, PeerChannel):
                return peer.channel_id
            raise AttributeError("chat_id")

        UpdateGroupCall.chat_id = property(_shim_chat_id)
        logging.getLogger("MusicBot").info("✅ UpdateGroupCall.chat_id compatibility shim applied")
except Exception as _shim_err:
    logging.getLogger("MusicBot").warning(f"⚠️ UpdateGroupCall compatibility shim skip ho gaya: {_shim_err}")

LOGGER = logging.getLogger("MusicBot")

# Process shuru hone ka time — /ping mein uptime dikhane ke liye
START_TIME = time.monotonic()

bot = Client(
    name="MusicBot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    in_memory=True,
)

assistant = Client(
    name="Assistant",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.STRING_SESSION,
    in_memory=True,
)

call_py = PyTgCalls(assistant)
