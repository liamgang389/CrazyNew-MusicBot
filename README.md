# Aditya Music Bot

Pyrogram + PyTgCalls se bana ek chhota, tez Telegram music bot.

## Repo structure
```
.
├── Aditya/                   ← poora bot code yahin hai
│   ├── __main__.py           (startup)
│   ├── play.py                (commands, buttons, playback)
│   ├── nowplaying.py         (now-playing image card)
│   ├── core/                 ← config, clients, helpers, queue, progress-bar
│   │   ├── config.py
│   │   ├── clients.py
│   │   ├── helpers.py
│   │   ├── music_queue.py
│   │   └── progress.py
│   └── platform/             ← YouTube search/stream + assistant VC-join
│       ├── youtube.py
│       └── assistant_join.py
├── GitHub/                   ← credits
│   ├── CREDITS.md
│   └── AUTHOR.md
├── Nexor_api/                ← free STREAM_API_KEY kaise generate karein
│   └── README.md
├── Dockerfile
├── Procfile
├── requirements.txt
├── sample.env
├── generate_session.py
└── README.md
```
Bot sirf `Aditya` package ke zariye chalta hai — `Aditya/` folder (iske `core/` aur
`platform/` subfolders samet) ke bina na run hoga, na deploy. Har file apni jagah
rehni chahiye, naam ya path badalne se imports toot jayenge.

## Commands
| Command | Kaam |
|---|---|
| `/start` | Start message (Add me / Help / Updates / Support / Owner / Source buttons) |
| `/help` | Commands ka menu |
| `/play [song name]` | Gaana chalao (pehle se baj raha ho to queue mein jaata hai) |
| `/pause` `/resume` | Pause / resume |
| `/skip` | Agla gaana (queue khali ho to VC chhod deta hai) |
| `/stop` | Rok ke VC chhod do |
| `/id` | Apni aur chat ki ID |
| `/ping` | Speed / uptime |

`/pause /resume /skip /stop` (aur Now Playing ke buttons) group admin, owner ya jisne gaana
request kiya wahi use kar sakta hai.

## Features
- Now Playing card: ▶️ ⏸️ 🔁 ⏭️ ⏹️ buttons + 15s+ (15 second aage), fixed colors, live progress bar.
- `/play` bina gaane ke naam ke bheja to quote box mein usage + example aata hai.
- Group mein bot ki command ka message apne-aap delete ho jaata hai (bot ko "delete messages" right chahiye).
- Stream turant ruk jaye (CPU overload) to bot 3 baar dobara try karta hai.

## Gaana kahan se aata hai
Search `youtube_search` se hoti hai, audio isse aata hai:
```
https://nexor-yt-in.lovable.app/stream/audio/<video_id>?key=<STREAM_API_KEY>
```
URL fixed hai (`Aditya/config.py`), sirf apni `STREAM_API_KEY` env mein daalo.

## Setup
`sample.env` ko `.env` (ya Render ke environment variables) mein copy karke bharo.
Zaroori: `API_ID API_HASH BOT_TOKEN STRING_SESSION OWNER_ID STREAM_API_KEY`.
`/start` ki image/video/gif ke liye `START_IMAGE_URL` env hai.
Assistant ki `STRING_SESSION` banane ke liye: `python3 generate_session.py`

```
pip install -r requirements.txt
python3 -m Aditya
```

Docker / Render: repo root par `Dockerfile` hai, CMD `python3 -m Aditya` chalata hai.

## Links
- Owner: [@Heart_broker0](https://t.me/Heart_broker0) (ID `6858251193`)
- Support group: https://t.me/CrazyHubSupport
- Updates channel: https://t.me/nkdcrazy
