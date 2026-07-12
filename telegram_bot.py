Skip to content
ItzJustEren
TK-UI
Repository navigation
Code
Issues
Pull requests
Actions
Projects
Wiki
Security and quality
Insights
Settings
Files
Go to file
t
T
README.md
main.py
pages.py
relay_vless.py
requirements.txt
telegram_bot.py
xhttp_siz10.py
TK-UI
/
telegram_bot.py
in
main

Edit

Preview
Indent mode

Spaces
Indent size

4
Line wrap mode

No wrap
Editing telegram_bot.py file contents
1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
29
30
31
32
33
34
35
36
37
38
39
40
41
42
43
44
45
46
47
48
49
50
51
52
53
54
55
56
57
58
59
60
61
62
# telegram_bot.py
# ══════════════════════════════════════════════════════════════════════════════
# ربات مدیریت تلگرام — ساخت/حذف/فعال‌غیرفعال/مشاهده‌ی کانفیگ‌ها، فقط برای ادمین‌های
# مجاز (TELEGRAM_ADMIN_IDS). با long polling کار می‌کنه، نیازی به دامنه/webhook نداره.
# ══════════════════════════════════════════════════════════════════════════════

import asyncio
import os
import re

import httpx

from datetime import datetime, timedelta

from main import (
    LINKS,
    make_link,
    remove_link,
    set_link_active,
    vless_link_for_link,
    get_host,
    fmt_bytes,
    is_link_allowed,
    logger,
    PROTOCOLS,
    DEFAULT_PROTOCOL,
    FINGERPRINTS,
    DEFAULT_FINGERPRINT,
    DEFAULT_ALPN_BY_PROTOCOL,
    DEFAULT_PORT,
    DEFAULT_SPEED_LIMIT,
    MIN_PORT,
    MAX_PORT,
    parse_size_to_bytes,
    parse_speed_to_bytes,
    SUBS,
    create_sub_group,
    set_link_sub,
    remove_sub_group,
)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
_admin_ids_raw = os.environ.get("TELEGRAM_ADMIN_IDS", "").strip()
ADMIN_IDS = {int(x) for x in _admin_ids_raw.replace(" ", "").split(",") if x.isdigit()} if _admin_ids_raw else set()

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
PAGE_SIZE = 6

_client: httpx.AsyncClient | None = None
_poll_task: asyncio.Task | None = None
_running = False
_pending: dict = {}   # chat_id -> {"action": "wizard", "step": "...", "data": {...}}

# ── Config creation wizard ────────────────────────────────────────────────────
# مراحل ساخت کانفیگ جدید، دقیقاً هم‌راستا با فیلدهایی که پنل وب موقع ساخت کاربر می‌گیره:
# برچسب، پروتکل، fingerprint، ALPN، پورت، محدودیت حجم، محدودیت سرعت، محدودیت آی‌پی، روز انقضا.
WIZARD_STEPS = ["label", "protocol", "fingerprint", "alpn", "port", "volume", "speed", "iplimit", "days"]

PROTOCOL_LABELS = {
    "vless-ws": "VLESS + WebSocket",
    "xhttp-packet-up": "XHTTP (packet-up)",
    "xhttp-stream-up": "XHTTP (stream-up)",
Use Control + Shift + m to toggle the tab key moving focus. Alternatively, use esc then tab to move to the next interactive element on the page.
