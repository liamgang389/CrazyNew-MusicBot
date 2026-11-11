# Nexor Stream API — Free Key

Bot ka gaana isi API se aata hai (`Aditya/core/config.py` → `STREAM_API_BASE`):

```
https://nexor-yt-in.lovable.app
```

## Free API key kaise lo

1. Browser me yeh site kholo: **https://nexor-yt-in.lovable.app**
2. Page par **"Key Panel"** section milega — usme **"Get your key"** button hai.
3. Us par click karo → **Log in** karo (jo bhi login option site de rahi hai).
4. Login ke baad **"generate key"** option se apni free key generate karo.
5. Wahi par **"see usage"** se tumhari key ka usage/limit bhi track kar sakte ho.

## Key kahan daalni hai

Jo key mile, usse apni `.env` (ya Render ke Environment Variables) me daalo:

```
STREAM_API_KEY=yaha_apni_key_daalo
```

`STREAM_API_BASE` (URL) **fixed hai** — usse badalna nahi hai, sirf `STREAM_API_KEY`
apni env me set karo. Isi key se bot in endpoints ko call karta hai:

```
GET /stream/audio/<video_id>?key=<STREAM_API_KEY>     → audio (MP3)
GET /stream/video/<video_id>?key=<STREAM_API_KEY>     → video
GET /stream/<video_id>?key=<STREAM_API_KEY>&quality=360|720|1080
```

`&download=1` add karne se file seedha download hoti hai, stream ki jagah.

## Note

- Key site par login karke generate hoti hai — isliye yahan koi key hardcode
  nahi ki gayi hai, khud generate karke apni env me daalna hoga.
- Free tier ki limits site ke "see usage" panel me dikhengi.
