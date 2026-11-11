"""
Simple Music Bot — saare commands, buttons aur playback yahin hain.

Commands: /start /help /ping /play /pause /resume /skip /stop /id
"""
import asyncio
import os
import random
import re
import time

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ButtonStyle
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from pytgcalls.types.input_stream import AudioPiped
from pytgcalls.exceptions import NoActiveGroupCall
from pyrogram.raw import functions as raw_functions

from Aditya.core import config
from Aditya.core import music_queue as q
from Aditya.core import progress
from Aditya.core.clients import bot, assistant, call_py, LOGGER, START_TIME
from Aditya.platform.youtube import search_track, get_stream_url
from Aditya.core.helpers import (
    smallcaps,
    smallcaps_title,
    std_smallcaps,
    random_processing_emoji,
    processing_caption,
    duration_to_seconds,
    blockquote,
    expandable_blockquote,
    esc,
    fancy_italic,
    FOOTER_LINE,
)
from Aditya.nowplaying import generate_now_playing_card
from Aditya.platform.assistant_join import ensure_assistant_in_chat

ADMIN_STATUSES = (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
COMMAND_NAMES = ["start", "help", "ping", "play", "pause", "resume", "skip", "stop", "id"]


async def _say(message: Message, text: str, **kwargs):
    """Group mein command ka message baad mein delete hota hai, isliye reply-quote nahi
    karte — seedha chat mein bhejte hain (warna reply 'deleted message' dikhata)."""
    kwargs.setdefault("disable_web_page_preview", True)
    return await bot.send_message(message.chat.id, text, **kwargs)


async def _piped(track: dict, start=0):
    """Track ke liye AudioPiped (start > 0 ho to us second se)."""
    path = track["stream_url"]
    if start and int(start) > 0:
        return AudioPiped(path, additional_ffmpeg_parameters=f"-ss {int(start)}")
    return AudioPiped(path)


# ---------------------------------------------------------------------------
# Peer cache — "Peer id invalid" aane par dialogs refresh karke retry
# ---------------------------------------------------------------------------
async def _refresh_assistant_peers():
    try:
        async for _ in assistant.get_dialogs():
            pass
    except Exception as e:
        LOGGER.warning(f"Peer refresh fail: {e}")


def _is_peer_error(e: Exception) -> bool:
    return isinstance(e, ValueError) and "Peer id invalid" in str(e)


# ---------------------------------------------------------------------------
# VC live na ho to assistant khud shuru kar de (assistant ke paas right ho to)
# ---------------------------------------------------------------------------
async def _auto_start_group_call(chat_id: int) -> bool:
    try:
        peer = await assistant.resolve_peer(chat_id)
        await assistant.invoke(
            raw_functions.phone.CreateGroupCall(peer=peer, random_id=random.randint(1, 2_147_483_647))
        )
        return True
    except Exception as e:
        LOGGER.warning(f"Auto voice-chat start fail (chat {chat_id}): {e}")
        return False


# ---------------------------------------------------------------------------
# Permissions — /pause /resume /skip /stop (aur buttons): requester, group admin ya owner
# ---------------------------------------------------------------------------
async def _is_group_admin(chat_id: int, user_id: int) -> bool:
    if config.OWNER_ID and user_id == config.OWNER_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ADMIN_STATUSES
    except Exception:
        return False


async def _can_control(chat_id: int, user_id: int) -> bool:
    if await _is_group_admin(chat_id, user_id):
        return True
    track = q.get_now_playing(chat_id)
    return bool(track and track.get("requested_by_id") == user_id)


NOT_YOUR_REQUEST_TEXT = (
    f"❌ {smallcaps_title('this is not your request')}!\n"
    f"{smallcaps_title('only the person who requested this track, or a group admin/owner, can control it')}."
)
NOTHING_PLAYING_TEXT = f"❌ {smallcaps_title('nothing is playing right now')}."


def _assistant_not_joined_text(username: str) -> str:
    return (
        f"❌ **{smallcaps_title('my assistant account is not in this group')}!**\n\n"
        f"{smallcaps_title('the assistant account needs to be in the group to play music')}.\n"
        f"👉 @{username or config.ASSISTANT_USERNAME} {smallcaps_title('add it to the group, or get it to join')}.\n\n"
        f"{smallcaps_title('then run')} `/play` {smallcaps_title('again')}."
    )


ASSISTANT_FLOOD_TEXT = f"⏳ {smallcaps_title('telegram has rate-limited us for a bit, try again shortly')}."


# ---------------------------------------------------------------------------
# Buttons (colored — Telegram Bot API 9.4 button style). Colors FIXED hain.
# ---------------------------------------------------------------------------
def _btn(text: str, *, style: str = "primary", **kwargs) -> InlineKeyboardButton:
    style_map = {
        "primary": ButtonStyle.PRIMARY,
        "success": ButtonStyle.SUCCESS,
        "danger": ButtonStyle.DANGER,
    }
    return InlineKeyboardButton(text, style=style_map.get(style, ButtonStyle.PRIMARY), **kwargs)


def _controls_keyboard(elapsed_sec=None, total_sec=None) -> InlineKeyboardMarkup:
    """Now Playing card ke buttons: progress bar → ▶️ ⏸ 🔁 ⏭ ⏹ → 15s- 15s+ → close."""
    rows = []
    if total_sec and total_sec > 0:
        rows.append([_btn(progress.render_button_bar(elapsed_sec or 0, total_sec),
                          callback_data="m_progress", style="primary")])
    rows.append([
        _btn("▶️", callback_data="m_resume", style="success"),
        _btn("⏸️", callback_data="m_pause", style="primary"),
        _btn("🔁", callback_data="m_replay", style="primary"),
        _btn("⏭️", callback_data="m_skip", style="success"),
        _btn("⏹️", callback_data="m_stop", style="danger"),
    ])
    rows.append([
        _btn("15s-", callback_data="m_seek_bwd", style="primary"),
        _btn("15s+", callback_data="m_seek_fwd", style="success"),
    ])
    rows.append([_btn(smallcaps_title("close"), callback_data="m_close", style="danger")])
    return InlineKeyboardMarkup(rows)


def _start_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn(smallcaps("add me to your chat"), url=f"https://t.me/{bot_username}?startgroup=true", style="success")],
        [_btn(smallcaps("help and command"), callback_data="help_menu", style="primary")],
        [
            _btn(smallcaps("updates"), url=config.CHANNEL_URL, style="primary"),
            _btn(smallcaps("support"), url=config.SUPPORT_URL, style="success"),
        ],
        [_btn(smallcaps("owner"), url=config.OWNER_URL, style="success")],
    ])


def _help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn(smallcaps_title("back"), callback_data="back_to_start", style="primary")]])


# ---------------------------------------------------------------------------
# Start / Help text
# ---------------------------------------------------------------------------
def _welcome_text(user_name: str, user_id: int, bot_username: str) -> str:
    user_tag = f'<a href="tg://user?id={user_id}">{esc(smallcaps_title(user_name))}</a>'
    bot_tag = f'<a href="https://t.me/{bot_username}">『𝙈ᴜ𝙨ɪᴄ』</a>'

    greeting = blockquote(f"<b>💐 Gʀєєᴛɪηɢs {user_tag} 🥀</b>")
    details = blockquote(
        f"<b>💮 Yσυ Aʀє Usɪηɢ {bot_tag} : "
        f"{smallcaps_title('a simple and fast music player for your telegram voice chats')}.\n\n"
        f"● {smallcaps_title('play')} : {smallcaps_title('any song from youtube in seconds')}.\n"
        f"● {smallcaps_title('quality')} : {smallcaps_title('clean and smooth audio')}.\n"
        f"● {smallcaps_title('control')} : {smallcaps_title('pause, resume, skip and stop')}.\n\n"
        f"🎋 {smallcaps_title('add me to your group, start a voice chat and send')} /play "
        f"{smallcaps_title('song name')}.\n"
        f"{smallcaps_title('click help to see all commands')}.</b>"
    )
    return f"{greeting}\n\n{details}"


HELP_TEXT = (
    blockquote(f"<b>🔮 {smallcaps_title('music bot commands')}</b>")
    + "\n\n"
    + blockquote(
        f"➻ /play [{std_smallcaps('song name')}] : {std_smallcaps('play a song or add it to the queue')}\n"
        f"➻ /pause : {std_smallcaps('pause the stream')}\n"
        f"➻ /resume : {std_smallcaps('resume the stream')}\n"
        f"➻ /skip : {std_smallcaps('play the next track')}\n"
        f"➻ /stop : {std_smallcaps('stop and leave the voice chat')}\n"
        f"➻ /id : {std_smallcaps('show your id and chat id')}\n"
        f"➻ /ping : {std_smallcaps('check bot speed')}\n"
        f"➻ /help : {std_smallcaps('show this menu')}"
    )
    + "\n\n"
    + blockquote(
        f"<b>• {std_smallcaps('pause, resume, skip and stop can be used by group admins, the owner or the person who requested the song')}.</b>"
    )
)

CAPTION_LIMIT = 1000  # Telegram caption limit 1024 hai, thoda margin


def _plain_len(text: str) -> int:
    return len(re.sub(r"<[^>]+>", "", text))


async def _get_user_dp(user_id: int):
    """User ki profile photo (in-memory) — nahi hai / privacy band hai to None."""
    try:
        async for photo in bot.get_chat_photos(user_id, limit=1):
            data = await bot.download_media(photo.file_id, in_memory=True)
            if data:
                data.name = "dp.jpg"
                return data
    except Exception as e:
        LOGGER.warning(f"DP fetch fail ({user_id}): {e}")
    return None


async def _send_welcome(chat_id: int, text: str, reply_markup, dp=None):
    """START_IMAGE_URL (photo/video/gif) ke saath, warna user ki DP ke saath, warna sirf text."""
    url = (config.START_IMAGE_URL or "").strip()
    try:
        if url:
            low = url.lower().split("?")[0]
            if low.endswith((".mp4", ".webm", ".mov")):
                return await bot.send_video(chat_id, url, caption=text, reply_markup=reply_markup)
            if low.endswith(".gif"):
                return await bot.send_animation(chat_id, url, caption=text, reply_markup=reply_markup)
            return await bot.send_photo(chat_id, url, caption=text, reply_markup=reply_markup)
        if dp is not None:
            return await bot.send_photo(chat_id, dp, caption=text, reply_markup=reply_markup)
    except Exception as e:
        LOGGER.warning(f"Start media send fail, text fallback: {e}")
    return await bot.send_message(chat_id, text, reply_markup=reply_markup, disable_web_page_preview=True)


async def _edit_body(cq_message, text: str, reply_markup):
    """Callback par message edit karta hai — media caption ho ya plain text."""
    has_media = bool(cq_message.photo or cq_message.video or cq_message.animation)
    if has_media and _plain_len(text) > CAPTION_LIMIT:
        try:
            await cq_message.delete()
        except Exception:
            pass
        return await bot.send_message(cq_message.chat.id, text, reply_markup=reply_markup,
                                      disable_web_page_preview=True)
    if has_media:
        return await cq_message.edit_caption(text, reply_markup=reply_markup)
    return await cq_message.edit_text(text, reply_markup=reply_markup)


# ---------------------------------------------------------------------------
# /start /help
# ---------------------------------------------------------------------------
@bot.on_message(filters.command("start"))
async def start_cmd(client, message: Message):
    if not message.from_user:
        return
    me = await bot.get_me()
    text = _welcome_text(message.from_user.first_name, message.from_user.id, me.username)
    dp = None
    if message.chat.type.name == "PRIVATE" and not config.START_IMAGE_URL:
        dp = await _get_user_dp(message.from_user.id)
    await _send_welcome(message.chat.id, text, _start_keyboard(me.username), dp)
    try:
        await message.delete()   # sirf welcome card dikhe
    except Exception as e:
        LOGGER.warning(f"/start msg delete fail: {e}")


@bot.on_message(filters.command("help"))
async def help_cmd(client, message: Message):
    await _say(message, HELP_TEXT, reply_markup=_help_keyboard())


@bot.on_callback_query(filters.regex("^help_menu$"))
async def help_menu_cb(client, cq: CallbackQuery):
    await cq.answer()
    await _edit_body(cq.message, HELP_TEXT, _help_keyboard())


@bot.on_callback_query(filters.regex("^back_to_start$"))
async def back_to_start_cb(client, cq: CallbackQuery):
    await cq.answer()
    me = await bot.get_me()
    text = _welcome_text(cq.from_user.first_name, cq.from_user.id, me.username)
    msg = cq.message
    has_media = bool(msg.photo or msg.video or msg.animation)
    if has_media or msg.chat.type.name != "PRIVATE":
        return await _edit_body(msg, text, _start_keyboard(me.username))
    # Help page text message tha (media nahi) — welcome ko dobara bhejo
    dp = None if config.START_IMAGE_URL else await _get_user_dp(cq.from_user.id)
    try:
        await msg.delete()
    except Exception:
        pass
    await _send_welcome(msg.chat.id, text, _start_keyboard(me.username), dp)


# ---------------------------------------------------------------------------
# Bot ko group mein add kiya jaana
# ---------------------------------------------------------------------------
@bot.on_message(filters.new_chat_members & filters.group)
async def added_to_group(client, message: Message):
    me = await bot.get_me()
    if not any(u.id == me.id for u in message.new_chat_members):
        return
    adder = message.from_user.first_name if message.from_user else "there"
    bot_tag = f"[{fancy_italic(me.first_name)}](https://t.me/{me.username})"
    await bot.send_message(
        message.chat.id,
        f"❖ {smallcaps_title('hey')} {adder}..!! 🥀\n"
        f"» {smallcaps_title('thanks for adding')} {bot_tag}!\n\n"
        f"» {bot_tag} {smallcaps_title('can now play songs in this chat')}.\n\n"
        f"⌾ {smallcaps_title('play music')} : /play\n"
        f"⌾ {smallcaps_title('help & cmds')} : /help\n\n"
        f"{FOOTER_LINE}",
        reply_markup=_start_keyboard(me.username),
        disable_web_page_preview=True,
    )


# ---------------------------------------------------------------------------
# /play
# ---------------------------------------------------------------------------
@bot.on_message(filters.command("play") & filters.private)
async def play_private_command(client, message: Message):
    me = await bot.get_me()
    await message.reply_text(
        f"❌ {smallcaps_title('this is a group command')}!\n\n"
        f"» {smallcaps_title('add me to your group, start the voice chat there, then use')} "
        f"`/play` {smallcaps_title('in the group')}.",
        reply_markup=_start_keyboard(me.username),
        disable_web_page_preview=True,
    )


PLAY_USAGE_TEXT = blockquote(
    f"❌ {smallcaps_title('give me a song name too')}!\n\n"
    f"<b>{std_smallcaps('usage')}</b> : /play [{std_smallcaps('song name/youtube url')}]\n"
    f"Example: <code>/play Shape of You</code>"
)


@bot.on_message(filters.command("play") & filters.group)
async def play_command(client, message: Message):
    if len(message.command) < 2:
        return await _say(message, PLAY_USAGE_TEXT)
    await _do_play(message, message.text.split(None, 1)[1])


async def _do_play(message: Message, query: str):
    chat_id = message.chat.id
    requester = message.from_user.first_name if message.from_user else "Someone"
    requester_id = message.from_user.id if message.from_user else None

    # User ka /play msg turant delete — taaki chat saaf rahe
    try:
        await message.delete()
    except Exception as e:
        LOGGER.warning(f"Play command msg delete fail: {e}")

    joined, reason = await ensure_assistant_in_chat(chat_id, assistant)
    if not joined:
        if reason == "flood_wait":
            return await bot.send_message(chat_id, ASSISTANT_FLOOD_TEXT)
        try:
            uname = (await assistant.get_me()).username
        except Exception:
            uname = None
        return await bot.send_message(chat_id, _assistant_not_joined_text(uname))

    # Pehle sirf ek emoji, turant baad uske niche processing text
    status = await bot.send_message(chat_id, random_processing_emoji())
    try:
        await status.edit_text(processing_caption(status.text))
    except Exception as e:
        LOGGER.warning(f"Processing caption edit fail: {e}")

    track = await search_track(query)
    if not track:
        return await status.edit_text(f"❌ {smallcaps_title('could not find anything, try a different name')}.")

    try:
        stream_url = await get_stream_url(track["id"])
    except Exception as e:
        LOGGER.error(f"Stream URL error: {e}")
        return await status.edit_text(
            f"❌ {smallcaps_title('could not load this track, try again shortly or send another song')}."
        )

    track["stream_url"] = stream_url
    track["requested_by"] = requester
    track["requested_by_id"] = requester_id

    # Pehle se kuch baj raha hai -> queue mein daalo
    if q.is_playing(chat_id):
        position = q.push(chat_id, track)
        await status.delete()
        title_parts = track["title"].split("|")
        main = smallcaps_title(esc(title_parts[0].strip()))
        lines = [f"╰┈➤ {smallcaps_title(esc(x.strip()))}" for x in title_parts[1:] if x.strip()]
        requester_tag = f"[{smallcaps_title(requester)}](tg://user?id={requester_id})"
        header = blockquote(f"❖ {smallcaps_title('queued to play')}..!! ✦")
        body = expandable_blockquote("\n".join([f"» 『 #{position} • {main} 』"] + lines))
        meta = expandable_blockquote(
            f"⌾ {smallcaps_title('duration')} : {esc(track['duration'])}\n"
            f"⌾ {smallcaps_title('requested by')} : {requester_tag}"
        )
        me = await bot.get_me()
        return await bot.send_message(
            chat_id,
            f"{header}\n\n{body}\n\n{meta}",
            reply_markup=InlineKeyboardMarkup([[
                _btn(smallcaps_title("add me to your chat"),
                     url=f"https://t.me/{me.username}?startgroup=true", style="success")
            ]]),
            disable_web_page_preview=True,
        )

    await status.delete()
    await _start_playing(chat_id, track)


async def _start_playing(chat_id: int, track: dict):
    """VC join/change karke track play karta hai aur Now Playing card bhejta hai."""
    try:
        try:
            await call_py.join_group_call(chat_id, await _piped(track))
        except NoActiveGroupCall:
            started = await _auto_start_group_call(chat_id)
            if started:
                await asyncio.sleep(1.5)
                try:
                    await call_py.join_group_call(chat_id, await _piped(track))
                    started = "joined"
                except Exception as e3:
                    LOGGER.warning(f"Auto-start ke baad join fail: {e3}")
                    started = False
            if started != "joined":
                return await bot.send_message(
                    chat_id,
                    f"❌ **{smallcaps_title('voice chat is not active')}!**\n\n"
                    f"{smallcaps_title('start a voice chat in the group first')}:\n"
                    "Group Settings → Voice Chat → Start Voice Chat\n\n"
                    f"{smallcaps_title('then send')} `/play` {smallcaps_title('again')}.",
                )
        except Exception as e:
            LOGGER.warning(f"join_group_call fail: {e!r}", exc_info=True)
            if _is_peer_error(e):
                await _refresh_assistant_peers()
            try:
                await call_py.change_stream(chat_id, await _piped(track))
            except Exception as e2:
                LOGGER.error(f"Play error: {e2!r}", exc_info=True)
                return await bot.send_message(
                    chat_id,
                    f"❌ **{smallcaps_title('could not play it')}**\n\n"
                    f"{smallcaps_title('check whether the voice chat is active, then try again')}.",
                )

        q.set_now_playing(chat_id, track)
        await _send_now_playing(chat_id, track)

    except Exception as e:
        LOGGER.error(f"_start_playing fatal error: {e}")
        await bot.send_message(chat_id, f"❌ {smallcaps_title('something went wrong, try again')}.")


def _now_playing_caption(track: dict) -> str:
    parts = [x.strip() for x in str(track.get("title", "")).split("|") if x.strip()]
    main_title = smallcaps_title(esc(parts[0])) if parts else smallcaps_title("unknown")
    song_lines = [f"» 『 {main_title} 』"]
    for part in parts[1:]:
        song_lines.append(f"╰┈➤ {smallcaps_title(esc(part))}")

    requester = track.get("requested_by", "Unknown")
    requester_id = track.get("requested_by_id")
    if requester_id:
        requester_tag = f"[{smallcaps_title(requester)}](tg://user?id={requester_id})"
    else:
        requester_tag = smallcaps_title(requester)

    header = blockquote(f"❖ {smallcaps_title('now playing')}..!! ✦")
    body = expandable_blockquote("\n".join(song_lines))
    meta = expandable_blockquote(
        f"⌾ {smallcaps_title('duration')} : {esc(track.get('duration', '0:00'))}\n"
        f"⌾ {smallcaps_title('by')} : {requester_tag}"
    )
    return f"{header}\n\n{body}\n\n{meta}"


async def _send_now_playing(chat_id: int, track: dict, edit_message: Message = None):
    """Now Playing card bhejta hai. `edit_message` ho (skip button) to usi message ko in-place update karta hai."""
    caption = _now_playing_caption(track)
    card = await generate_now_playing_card(track.get("thumbnail"), track["title"], track["duration"])
    total_sec = duration_to_seconds(track.get("duration"))
    markup = _controls_keyboard(0, total_sec)
    media = card or track.get("thumbnail")

    sent = None
    if edit_message is not None:
        try:
            if media:
                sent = await edit_message.edit_media(InputMediaPhoto(media, caption=caption), reply_markup=markup)
            else:
                sent = await edit_message.edit_text(caption, reply_markup=markup)
        except Exception as e:
            LOGGER.warning(f"Now playing in-place edit fail, naya message bhej rahe hain: {e}")

    if sent is None:
        try:
            if media:
                sent = await bot.send_photo(chat_id, media, caption=caption, reply_markup=markup)
            else:
                sent = await bot.send_message(chat_id, caption, reply_markup=markup, disable_web_page_preview=True)
        except Exception as e:
            LOGGER.warning(f"Now playing card send fail: {e}")
            sent = await bot.send_message(chat_id, caption, reply_markup=markup, disable_web_page_preview=True)

    # Progress bar: gaane ke saath 00:00 se aage badhta hai (colors fixed)
    if sent is not None:
        progress.start(chat_id, track["id"])
        progress.start_updater(
            chat_id, sent,
            lambda el, tot: _controls_keyboard(el, tot),
            track["id"], total_sec,
        )
    return sent


# ---------------------------------------------------------------------------
# Stream khatam hone par agla gaana
# ---------------------------------------------------------------------------
# chat_id -> (video_id, retry_count) — gaana shuru hote hi / beech mein ruk jaaye to
# wahin se dobara chalane ki koshish (CPU overload par assistant ka "join karke nikal jaana").
_early_end: dict = {}


@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    track = q.get_now_playing(chat_id)

    if track:
        total = duration_to_seconds(track.get("duration"))
        el = progress.elapsed(chat_id)
        LOGGER.info(f"Stream end: chat={chat_id} elapsed={int(el)}s total={total}s")

        vid = track.get("id")
        rec = _early_end.get(chat_id)
        tries = rec[1] if rec and rec[0] == vid else 0

        if total > 20 and el < total - 10 and tries < 3 and q.get_state(chat_id) != "paused":
            _early_end[chat_id] = (vid, tries + 1)
            try:
                if el < 2:
                    await asyncio.sleep(2)  # CPU ko thoda sambhalne do
                if tries == 2:
                    # Aakhri koshish: cached file kharab ho sakti hai -> delete karke fresh download
                    try:
                        old_path = track.get("stream_url")
                        if old_path and os.path.isfile(old_path):
                            os.remove(old_path)
                        track["stream_url"] = await get_stream_url(vid)
                    except Exception as e:
                        LOGGER.warning(f"Fresh download fail (recover): {e!r}")
                await call_py.change_stream(chat_id, await _piped(track, el if el >= 2 else 0))
                LOGGER.info(f"Stream early-end recover try {tries + 1} at {int(el)}s")
                return
            except Exception as e:
                LOGGER.warning(f"Early-end recover fail: {e!r}")

        if el < 2 and tries >= 3:
            try:
                await bot.send_message(
                    chat_id,
                    f"❌ {smallcaps_title('stream stopped right after starting')}.\n"
                    f"{smallcaps_title('the server may be overloaded (cpu) — please try again in a moment')}.",
                )
            except Exception:
                pass

    _early_end.pop(chat_id, None)
    await _play_next(chat_id, silent_empty=True)


async def _leave_and_clear(chat_id: int):
    try:
        await call_py.leave_group_call(chat_id)
    except Exception:
        pass
    q.clear(chat_id)
    progress.clear(chat_id)


async def _play_next(chat_id: int, edit_message: Message = None, silent_empty: bool = False):
    """Queue mein agla track ho to wahi play karta hai, nahi to VC chhod deta hai.
    Skip button, /skip aur track khatam hone (on_stream_end) — teeno yahi use karte hain."""
    next_track = q.pop_next(chat_id)

    if not next_track:
        await _leave_and_clear(chat_id)
        if not silent_empty:
            text = f"⏭ {smallcaps_title('queue is empty, left the voice chat')}."
            if edit_message is not None:
                try:
                    await edit_message.edit_reply_markup(None)
                except Exception:
                    pass
            await bot.send_message(chat_id, text)
        return

    try:
        await call_py.change_stream(chat_id, await _piped(next_track))
    except Exception as e:
        if _is_peer_error(e):
            await _refresh_assistant_peers()
        try:
            await call_py.join_group_call(chat_id, await _piped(next_track))
        except Exception as e2:
            LOGGER.error(f"Play-next error: {e2!r}", exc_info=True)
            await bot.send_message(chat_id, f"❌ {smallcaps_title('could not continue playback, try again')}.")
            return

    q.set_now_playing(chat_id, next_track)
    await _send_now_playing(chat_id, next_track, edit_message=edit_message)


# ---------------------------------------------------------------------------
# /skip /pause /resume /stop
# ---------------------------------------------------------------------------
async def _pause(chat_id: int):
    await call_py.pause_stream(chat_id)
    q.set_state(chat_id, "paused")
    progress.pause(chat_id)


async def _resume(chat_id: int):
    await call_py.resume_stream(chat_id)
    q.set_state(chat_id, "playing")
    progress.resume(chat_id)


@bot.on_message(filters.command("skip") & filters.group)
async def skip_command(client, message: Message):
    chat_id = message.chat.id
    if not message.from_user:
        return
    if not q.is_playing(chat_id):
        return await _say(message, NOTHING_PLAYING_TEXT)
    if not await _can_control(chat_id, message.from_user.id):
        return await _say(message, NOT_YOUR_REQUEST_TEXT)
    await _play_next(chat_id)


@bot.on_message(filters.command("pause") & filters.group)
async def pause_command(client, message: Message):
    chat_id = message.chat.id
    if not message.from_user:
        return
    if not q.is_playing(chat_id):
        return await _say(message, NOTHING_PLAYING_TEXT)
    if not await _can_control(chat_id, message.from_user.id):
        return await _say(message, NOT_YOUR_REQUEST_TEXT)
    try:
        await _pause(chat_id)
        await _say(message, f"⏸ {smallcaps_title('paused')}.")
    except Exception as e:
        await _say(message, f"❌ {e}")


@bot.on_message(filters.command("resume") & filters.group)
async def resume_command(client, message: Message):
    chat_id = message.chat.id
    if not message.from_user:
        return
    if not q.is_playing(chat_id):
        return await _say(message, NOTHING_PLAYING_TEXT)
    if not await _can_control(chat_id, message.from_user.id):
        return await _say(message, NOT_YOUR_REQUEST_TEXT)
    try:
        await _resume(chat_id)
        await _say(message, f"▶️ {smallcaps_title('resumed')}.")
    except Exception as e:
        await _say(message, f"❌ {e}")


@bot.on_message(filters.command("stop") & filters.group)
async def stop_command(client, message: Message):
    chat_id = message.chat.id
    if not message.from_user:
        return
    if not q.is_playing(chat_id):
        return await _say(message, NOTHING_PLAYING_TEXT)
    if not await _can_control(chat_id, message.from_user.id):
        return await _say(message, NOT_YOUR_REQUEST_TEXT)
    await _leave_and_clear(chat_id)
    await _say(message, f"⏹️ {smallcaps_title('left the voice chat')}.")


# ---------------------------------------------------------------------------
# Now Playing card ke buttons
# ---------------------------------------------------------------------------
@bot.on_callback_query(filters.regex("^m_"))
async def controls_callback(client, cq: CallbackQuery):
    chat_id = cq.message.chat.id
    action = cq.data

    # m_progress (sirf display) aur m_close (sirf panel hide) koi bhi dabaa sakta hai
    if action in ("m_resume", "m_pause", "m_replay", "m_skip", "m_stop", "m_seek_fwd", "m_seek_bwd"):
        if not await _can_control(chat_id, cq.from_user.id):
            return await cq.answer(NOT_YOUR_REQUEST_TEXT, show_alert=True)

    try:
        if action == "m_progress":
            await cq.answer()

        elif action == "m_resume":
            await _resume(chat_id)
            await cq.answer("▶️ Resumed")

        elif action == "m_pause":
            await _pause(chat_id)
            await cq.answer("⏸ Paused")

        elif action == "m_replay":
            track = q.get_now_playing(chat_id)
            if not track:
                return await cq.answer(NOTHING_PLAYING_TEXT, show_alert=True)
            await call_py.change_stream(chat_id, await _piped(track))
            progress.replay(chat_id)
            q.set_state(chat_id, "playing")
            await cq.answer("🔁 Replaying")

        elif action == "m_seek_fwd":
            track = q.get_now_playing(chat_id)
            if not track:
                return await cq.answer(NOTHING_PLAYING_TEXT, show_alert=True)
            total_sec = duration_to_seconds(track.get("duration"))
            new_pos = progress.elapsed(chat_id) + 15
            if total_sec and new_pos >= total_sec - 2:
                return await cq.answer(f"❌ {smallcaps_title('not enough time left to seek')}.", show_alert=True)
            await call_py.change_stream(chat_id, await _piped(track, new_pos))
            progress.seek_to(chat_id, new_pos)
            if progress.is_paused(chat_id):
                progress.resume(chat_id)
            q.set_state(chat_id, "playing")
            await cq.answer("⏩ +15s")

        elif action == "m_seek_bwd":
            track = q.get_now_playing(chat_id)
            if not track:
                return await cq.answer(NOTHING_PLAYING_TEXT, show_alert=True)
            new_pos = max(0, progress.elapsed(chat_id) - 15)
            await call_py.change_stream(chat_id, await _piped(track, new_pos))
            progress.seek_to(chat_id, new_pos)
            if progress.is_paused(chat_id):
                progress.resume(chat_id)
            q.set_state(chat_id, "playing")
            await cq.answer("⏪ -15s")

        elif action == "m_skip":
            await cq.answer("⏭ Skipping")
            await _play_next(chat_id, edit_message=cq.message)

        elif action == "m_stop":
            await _leave_and_clear(chat_id)
            await cq.answer("⏹ Stopped")
            try:
                await cq.message.edit_reply_markup(None)
            except Exception:
                pass
            await bot.send_message(chat_id, f"⏹️ {smallcaps_title('left the voice chat')}.")

        elif action == "m_close":
            progress.cancel_task(chat_id)
            await cq.answer()
            try:
                await cq.message.delete()
            except Exception:
                pass

    except Exception as e:
        LOGGER.warning(f"Callback error ({action}): {e}")
        await cq.answer(f"❌ {e}", show_alert=True)


# ---------------------------------------------------------------------------
# /id /ping
# ---------------------------------------------------------------------------
@bot.on_message(filters.command("id"))
async def id_command(client, message: Message):
    user_id = message.from_user.id if message.from_user else "Unknown"
    lines = [f"👤 **{smallcaps_title('your id')}:** `{user_id}`"]
    if message.chat.type.name != "PRIVATE":
        lines.append(f"👥 **{smallcaps_title('chat id')}:** `{message.chat.id}`")
    if message.reply_to_message and message.reply_to_message.from_user:
        lines.append(f"↩️ **{smallcaps_title('replied user id')}:** `{message.reply_to_message.from_user.id}`")
    await _say(message, "\n".join(lines))


def _uptime_text() -> str:
    s = int(time.monotonic() - START_TIME)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h {m}m {sec}s"


def _sys_lines() -> str:
    try:
        import psutil
        vm = psutil.virtual_memory()
        du = psutil.disk_usage("/")
        cpu = psutil.cpu_percent(interval=0.3)
        gb = 1024 ** 3
        return (
            f"ʀᴧᴍ ᴜsᴧɢє: {vm.used / gb:.2f} / {vm.total / gb:.2f} GB\n"
            f"ᴄᴘᴜ ᴜsᴧɢє: {cpu:.2f}%\n"
            f"ᴅɪsᴋ ᴜsᴧɢє: {du.used / gb:.2f} / {du.total / gb:.2f} GB"
        )
    except Exception as e:
        LOGGER.warning(f"psutil stats fail: {e}")
        return "ʀᴧᴍ/ᴄᴘᴜ/ᴅɪsᴋ: n/a"


@bot.on_message(filters.command("ping"))
async def ping_command(client, message: Message):
    t0 = time.perf_counter()
    m = await bot.send_message(message.chat.id, "🏓 ...")
    ms = int((time.perf_counter() - t0) * 1000)
    await m.edit_text(
        f"🏓 ᴘσηɢ: {ms}ms\n\n"
        f"🤖 𝙈ᴜ𝙨ɪᴄ sʏsᴛєᴍ sᴛᴧᴛ's :\n\n"
        f"ᴜᴘᴛɪᴍє: {_uptime_text()}\n"
        f"{_sys_lines()}"
    )


# ---------------------------------------------------------------------------
# Group mein bot ki har command ka message handler chalne ke BAAD delete
# (group=8 -> main handlers ke baad chalta hai). Delete right na ho to chup-chaap skip.
# ---------------------------------------------------------------------------
@bot.on_message(filters.command(COMMAND_NAMES) & filters.group, group=8)
async def delete_command_message(client, message: Message):
    try:
        await message.delete()
    except Exception:
        pass
