import os
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Optional

import aiohttp
from bs4 import BeautifulSoup
from telegram import Bot
import re
import json
from pathlib import Path

import io
import numpy as np
import cv2
import pytesseract
from PIL import Image





STATE_DIR = Path("state")
POSTED_FILE = STATE_DIR / "load_posted.json"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "-1003812789640")
MESSAGE_THREAD_ID = int(os.getenv("MESSAGE_THREAD_ID", "4"))



def remove_city_from_title(title: str) -> str:
    for city_key in KZ_CITIES.keys():
        pattern = re.compile(rf"{city_key}", re.IGNORECASE)
        title = pattern.sub("", title)

    title = re.sub(r"\s{2,}", " ", title)
    return title.strip(" -–•,")





def fix_glued_words(text: str) -> str:
    # Кириллица + латиница
    text = re.sub(r'([а-яё])([A-Z])', r'\1 \2', text)
    text = re.sub(r'([a-z])([А-ЯЁ])', r'\1 \2', text)
    text = re.sub(r'([а-яё])([А-ЯЁ])', r'\1 \2', text)
    return text




def is_clean_photo(url: str) -> bool:
    url = url.lower()

    blacklist = [
        "banner",
        "poster",
        "event",
        "flyer",
        "afisha",
        "1080x",
        "square",
        "card",
    ]

    return not any(word in url for word in blacklist)





#       OCR

DATE_REGEX = re.compile(
    r"\b\d{1,2}[:.]\d{2}\b|"           # 16:00
    r"\b\d{1,2}\s*(янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)\b|"
    r"\b\d{4}\b|"
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE
)


async def smart_crop_text_zones(session, image_url: str):
    try:
        async with session.get(image_url, timeout=20) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()

        pil_img = Image.open(io.BytesIO(data)).convert("RGB")
        img = np.array(pil_img)

        h, w, _ = img.shape
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        ocr = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)

        crop_top = 0
        crop_bottom = h

        detected_top = []
        detected_bottom = []

        for i, text in enumerate(ocr["text"]):
            text = text.strip()
            if not text:
                continue

            if DATE_REGEX.search(text):
                y = ocr["top"][i]
                bh = ocr["height"][i]

                # верхняя зона
                if y < h * 0.45:
                    detected_top.append(y + bh)

                # нижняя зона
                if y > h * 0.55:
                    detected_bottom.append(y)

        # ───── вычисляем зоны обрезки ─────

        if detected_top:
            crop_top = max(detected_top) + 30  # запас вниз

        if detected_bottom:
            crop_bottom = min(detected_bottom) - 30  # запас вверх

        # защита от слишком сильного обрезания
        if crop_bottom - crop_top < h * 0.45:
            return None

        cropped = img[crop_top:crop_bottom, 0:w]

        # если вдруг пусто
        if cropped.size == 0:
            return None

        final_img = Image.fromarray(cropped)
        buffer = io.BytesIO()
        final_img.save(buffer, format="JPEG", quality=95)
        buffer.seek(0)

        return buffer

    except Exception as e:
        print("OCR crop error:", e)
        return None












def normalize_link(link: str) -> str:
    if not link:
        return ""

    link = link.strip()

    # убираем /s/ из telegram preview
    link = link.replace("https://t.me/s/", "https://t.me/")

    # убираем параметры ?...
    link = link.split("?")[0]

    # убираем завершающий /
    link = link.rstrip("/")

    return link






def load_posted() -> set:
    if POSTED_FILE.exists():
        try:
            with open(POSTED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()




def save_posted(posted: set):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)

        with open(POSTED_FILE, "w", encoding="utf-8") as f:
            json.dump(list(posted), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения posted_links: {e}")



URLS = [
    {"url": "https://astanahub.com/ru/event/", "name": "Astana Hub"},
    {"url": "https://er10.kz", "name": "ER10"},
    {"url": "https://kapital.kz", "name": "Capital"},
    {"url": "https://forbes.kz", "name": "Forbes kz"},
    {"url": "https://kz.kursiv.media", "name": "Kursiv kz"},
    {"url": "https://ma7.vc", "name": "MA7"},
    {"url": "https://tumarventures.com", "name": "Tumar ventures"},
    {"url": "https://whitehillcapital.io", "name": "White hill capital"},
    {"url": "https://bigsky.vc", "name": "Big sky ventures"},
    {"url": "https://mostfund.vc", "name": "Most ventures"},
    {"url": "https://axiomcapital.com", "name": "Axiom capital"},
    {"url": "https://jastarventures.com", "name": "Jas ventures"},
    {"url": "https://nuris.nu.edu.kz", "name": "NURIS"},
    {"url": "https://tech.kz", "name": "Big Tech"},
]

TELEGRAM_CHANNELS = [
    {"username": "startup_course_com", "name": "Startup Course"},
    {"username": "digitalbusinesskz", "name": "Digital Business KZ"},
    {"username": "vcinsightskz", "name": "VC Insights KZ"},
    {"username": "tech_kz", "name": "Tech KZ"},
    {"username": "startupalmaty", "name": "Startup Almaty"},
    {"username": "astanahub_events", "name": "Astana Hub Events"},
]

MONTHS_RU = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
MONTHS_SHORT = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "май": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}

EVENT_WORDS = [
    "конференция",
    "conference",
    "форум",
    "forum",
    "summit",
    "саммит",
    "meetup",
    "митап",
    "хакатон",
    "hackathon",
    "воркшоп",
    "workshop",
    "мастер-класс",
    "masterclass",
    "вебинар",
    "webinar",
    "семинар",
    "pitch",
    "питч",
    "demo day",
    "акселератор",
    "accelerator",
    "bootcamp",
    "буткемп",
    "выставка",
    "конкурс",
    "competition",
    "тренинг",
    "training",
    "мероприятие",
    "ивент",
    "event",
    "приглашает",
    "приглашаем",
    "зарегистрируйся",
    "регистрация",
]
NOT_EVENT_WORDS = [
    "research",
    "исследование показало",
    "инвестировал",
    "привлек раунд",
    "млн $",
    "млрд $",
    "назначен",
    "уволен",
    "отчет",
    "выручка",
    "курс доллара",
    "биржа",
    "акции",
    "токаев",
    "правительство приняло",
]
SITE_STOP_WORDS = [
    "контакты",
    "о нас",
    "политика",
    "войти",
    "регистрация аккаунта",
    "подписаться",
    "поиск",
    "главная",
    "меню",
    "все новости",
    "читать далее",
    "подробнее",
    "узнать больше",
    "privacy",
    "terms",
    "cookie",
]
DESCRIPTION_SIGNALS = [
    "формат встречи",
    "выступление спикеров",
    "вы узнаете",
    "мы расскажем",
    "на мероприятии",
    "в рамках",
    "состоится встреча",
    "приглашаем вас",
    "зарегистрируйтесь",
    "подробнее по ссылке",
    "свободное общение",
    "приглашают вас принять участие",
    "готовы перейти",
]

KZ_CITIES = {
    "алматы": "Алматы",
    "астана": "Астана",
    "шымкент": "Шымкент",
    "нур-султан": "Астана",
    "усть-каменогорск": "Усть-Каменогорск",
    "кызылорда": "Кызылорда",
    "актобе": "Актобе",
    "тараз": "Тараз",
    "павлодар": "Павлодар",
    "семей": "Семей",
    "атырау": "Атырау",
    "жезказган": "Жезқазған",
    "жезқазған": "Жезқазған",
    "актау": "Актау",
    "онлайн": "Онлайн",
    "online": "Онлайн",
    "zoom": "Онлайн (Zoom)",
    "ташкент": "Ташкент, Узбекистан",
}

EMOJI_RE = re.compile(
    "[\U00010000-\U0010ffff\u2600-\u27ff\u2300-\u23ff\u25a0-\u25ff\u2B00-\u2BFF]",
    re.UNICODE,
)


# ─── Helpers ────────────────────────────────────────────────────────────────

def strip_emoji(s: str) -> str:
    return EMOJI_RE.sub("", s).strip()


def is_future(dt: Optional[datetime]) -> bool:
    if not dt:
        return False
    return dt.date() > datetime.now().date()


def parse_date(text: str) -> Optional[datetime]:
    """
    Парсит дату. НЕ прибавляет +1 год к прошедшим датам:
    если год не указан и дата прошла — возвращает None.
    """
    t = text.lower()
    now = datetime.now()

    def make_dt(year, month, day):
        try:
            return datetime(year, month, day)
        except Exception:
            return None

    # ДД-ДД Месяц [ГГГГ]
    m = re.search(r"(\d{1,2})[-](\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?", t)
    if m:
        month = MONTHS_RU.get(m.group(3), 0)
        year = int(m.group(4)) if m.group(4) else now.year
        if month:
            return make_dt(year, month, int(m.group(2)))

    # ДД Месяц [ГГГГ]
    m = re.search(r"(\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?", t)
    if m:
        month = MONTHS_RU.get(m.group(2), 0)
        if month:
            year = int(m.group(3)) if m.group(3) else now.year
            return make_dt(year, month, int(m.group(1)))

    # ДД Мес[сокр] [ГГГГ]
    m = re.search(
        r"(\d{1,2})\s+(янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)[а-я]*(?:\s+(\d{4}))?",
        t,
    )
    if m:
        month = MONTHS_SHORT.get(m.group(2)[:3], 0)
        if month:
            year = int(m.group(3)) if m.group(3) else now.year
            return make_dt(year, month, int(m.group(1)))

    # ДД.ММ[.ГГГГ]
    m = re.search(r"(\d{1,2})\.(\d{2})(?:\.(\d{4}))?", t)
    if m:
        month = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if 1 <= month <= 12:
            return make_dt(year, month, int(m.group(1)))

    return None


def format_date(dt: datetime, time_str: str = None) -> str:
    months = {
        1: "января",
        2: "февраля",
        3: "марта",
        4: "апреля",
        5: "мая",
        6: "июня",
        7: "июля",
        8: "августа",
        9: "сентября",
        10: "октября",
        11: "ноября",
        12: "декабря",
    }
    s = f"{dt.day} {months[dt.month]} {dt.year}"
    return f"{s}, {time_str}" if time_str else s


def extract_location(text: str) -> Optional[str]:
    t = text.lower()
    for key, value in KZ_CITIES.items():
        if key in t:
            return value
    return None


def extract_venue(text: str) -> Optional[str]:
    known = [
        "Narxoz",
        "Nazarbayev",
        "KBTU",
        "КБТУ",
        "Astana Hub",
        "IT Park",
        "MOST IT Hub",
        "Holiday Inn",
        "Esentai",
        "Yandex",
        "Smart Point",
        "Almaty Arena",
    ]
    for v in known:
        if v.lower() in text.lower():
            m = re.search(rf"{re.escape(v)}[^\n,.]*", text, re.IGNORECASE)
            if m:
                return m.group(0).strip()[:60]
    at = re.search(r"@\s+([^@\n]+?)(?:\s+(?:https?://|t\.me/)|\s*$)", text)
    if at:
        return at.group(1).strip()[:60]
    return None


def is_real_event(text: str) -> bool:
    t = text.lower()
    return (any(w in t for w in EVENT_WORDS) and not any(w in t for w in NOT_EVENT_WORDS))


def is_site_trash(title: str) -> bool:
    return any(s in title.lower() for s in SITE_STOP_WORDS)


def looks_like_description(title: str) -> bool:
    t = title.lower()
    return any(s in t for s in DESCRIPTION_SIGNALS)


def dedup_title(title: str) -> str:
    half = len(title) // 2
    for i in range(10, half):
        if title[i:].strip() == title[:len(title)-i].strip():
            return title[:len(title)-i].strip()
    return title


def normalize_glued_text(s: str) -> str:
    s = strip_emoji(s).strip()
    # 16:00Онлайн -> 16:00 Онлайн
    s = re.sub(r"(\d{1,2}:\d{2})(?=[A-Za-zА-Яа-яЁё])", r"\1 ", s)
    # "Фев,16:00" -> "Фев, 16:00"
    s = re.sub(r"([а-яёА-ЯЁ]{3,}),(\d{1,2}:\d{2})", r"\1, \2", s)
    # двойные пробелы
    s = re.sub(r"\s{2,}", " ", s)
    return s


def strip_leading_datetime_from_title(title: str) -> str:
    """
    На всякий случай: если заголовок начинается с даты/времени — срезаем.
    Примеры:
    "24 Фев, 16:00 Онлайн Внедрение..." -> "Онлайн Внедрение..."
    "24 февраля 16:00Внедрение..." -> "Внедрение..."
    """
    t = strip_emoji(title).strip()

    # убираем приклеенное время внутри
    t = normalize_glued_text(t)

    # 24 фев, 16:00 ...
    t = re.sub(
        r"^\s*\d{1,2}\s+[А-Яа-яЁёA-Za-z]{3,}[,]?\s+\d{1,2}:\d{2}\s*",
        "",
        t,
        flags=re.IGNORECASE,
    )
    # 24 февраля 2026 ...
    t = re.sub(
        r"^\s*\d{1,2}\s+[а-яё]{3,}(?:\s+\d{4})?\s*",
        "",
        t,
        flags=re.IGNORECASE,
    )
    # 24.02.2026 ...
    t = re.sub(r"^\s*\d{1,2}\.\d{2}(?:\.\d{4})?\s*", "", t)

    return t.strip(" -–•.,").strip()










def clean_title_deterministic(raw_title: str) -> Optional[str]:

    s = strip_leading_datetime_from_title(raw_title)
    s = fix_glued_words(s)
    s = dedup_title(s)
    s = remove_city_from_title(s)

    # обрезаем хвост описания
    low = s.lower()
    for sig in DESCRIPTION_SIGNALS:
        idx = low.find(sig)
        if idx != -1 and idx > 12:
            s = s[:idx].strip(" -–•.,")
            break

    s = re.sub(r"\s{2,}", " ", s).strip()

    if len(s) < 5:
        return None

    if looks_like_description(s):
        return None

    return s[:120]







# ─── Parse glued line: "09 Фев, 17:00Шымкент Название" ───────────────────────

_GLUE_RE = re.compile(
    r"^(\d{1,2})\s+"                      # day
    r"([А-ЯЁа-яёA-Za-z]{3,})"             # month
    r"[,\s]+"
    r"(\d{1,2}:\d{2})"                    # time
    r"\s*"
    r"(?:(Онлайн|online|zoom|Алматы|Астана|Шымкент|Жезказган|Жезқазған|Караганда|Костанай|Павлодар|Семей|Атырау|Актау|Актобе|Тараз|Кызылорда)\s*)?"
    r"(.+)$",                             # title rest
    re.IGNORECASE,
)


def parse_glued_line(line: str) -> Optional[Dict]:
    line = normalize_glued_text(line)
    m = _GLUE_RE.match(line)
    if not m:
        return None

    day_s, month_s = m.group(1), m.group(2).lower()
    time_str = m.group(3)
    possible_city = (m.group(4) or "").strip()
    title_raw = m.group(5).strip()

    month_num = MONTHS_SHORT.get(month_s[:3], 0)
    if not month_num:
        for k, v in MONTHS_RU.items():
            if month_s.startswith(k[:3]):
                month_num = v
                break
    if not month_num:
        return None

    try:
        dt = datetime(datetime.now().year, month_num, int(day_s))
    except Exception:
        return None

    if not is_future(dt):
        return None

    city = None
    if possible_city:
        city = KZ_CITIES.get(possible_city.lower(), possible_city)

    title_raw = dedup_title(title_raw)

    if len(title_raw) < 5:
        return None

    return {
        "dt": dt,
        "time_str": time_str,
        "city": city,
        "title_raw": title_raw[:300],
        "date_formatted": format_date(dt, time_str),
    }


# ─── Formatting post (NO date in title) ───────────────────────────────────────

def make_post(event: Dict) -> str:
    title = (event.get("title") or "").strip()
    date_str = (event.get("date") or "").strip()
    link = (event.get("link") or "").strip()

    if not title or len(title) < 5 or not date_str or not link:
        return ""

    location = event.get("location", "")
    venue = event.get("venue", "")

    # важно: дата в заголовке убирается всегда
    title = strip_leading_datetime_from_title(title)

    lines = [f"🎯 <b>{title}</b>"]

    if location in ("Онлайн", "Онлайн (Zoom)"):
        lines.append("🌐 Онлайн")
    elif location:
        lines.append(f"🇰🇿 Казахстан, 🏙 {location}")
    else:
        lines.append("🇰🇿 Казахстан")

    if venue:
        lines.append(f"📍 {venue}")

    lines.append(f"📅 {date_str}")
    lines.append(f"🔗 <a href='{link}'>Читать →</a>")

    return "\n".join(lines)















# ─── Bot ─────────────────────────────────────────────────────────────────────

class EventBot:
    def __init__(self):
        self.session = None
        self.posted = load_posted()

    async def get_session(self) -> aiohttp.ClientSession:
        if not self.session:
            self.session = aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"})
        return self.session

    async def close(self):
        if self.session:
            await self.session.close()

    async def fetch(self, url: str) -> str:
        try:
            s = await self.get_session()
            async with s.get(url, timeout=15) as r:
                return await r.text() if r.status == 200 else ""
        except Exception as e:
            logger.error(f"fetch {url}: {e}")
            return ""

    # ── Digest parsing ───────────────────────────────────────────────────────

    def parse_digest(self, text: str, post_link: str, source: str, image_url: str) -> List[Dict]:
        events = []
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            dm = re.match(
                r"^(\d{1,2}[-]?\d{0,2}[.\s]\d{2}(?:\.\d{4})?"
                r"|\d{1,2}\s+(?:янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)[а-я]*"
                r"(?:\s+\d{4})?)",
                line,
                re.IGNORECASE,
            )
            if not dm:
                i += 1
                continue

            date_raw = dm.group(0)
            rest = line[dm.end():].strip()

            tm = re.search(r"(?:в\s*)?(\d{1,2}:\d{2})", rest)
            time_str = tm.group(1) if tm else None
            if tm:
                rest = (rest[:tm.start()] + rest[tm.end():]).strip()

            title_raw = strip_emoji(rest).strip(" -–•")

            link = None
            lm = re.search(r"((?:https?://|t\.me/)\S+)", line)
            if lm:
                link = lm.group(1)
                if not link.startswith("http"):
                    link = "https://" + link
                title_raw = title_raw.replace(strip_emoji(lm.group(0)), "").strip()
            else:
                for j in range(i + 1, min(i + 4, len(lines))):
                    lm2 = re.search(r"((?:https?://|t\.me/)\S+)", lines[j])
                    if lm2:
                        link = lm2.group(1)
                        if not link.startswith("http"):
                            link = "https://" + link
                        break

            if len(title_raw) < 5 and i + 1 < len(lines):
                nxt = strip_emoji(lines[i + 1]).strip()
                if len(nxt) > 5 and not re.match(r"^\d", nxt):
                    title_raw = nxt

            if len(title_raw) < 5:
                i += 1
                continue

            dt = parse_date(date_raw)
            if not is_future(dt):
                logger.info(f"⏭️ Прошедшее (дайджест): {title_raw[:40]}")
                i += 1
                continue

            ctx = line + " " + (lines[i + 1] if i + 1 < len(lines) else "")
            location = extract_location(ctx) or extract_location(text)

            title_clean = clean_title_deterministic(title_raw) or dedup_title(title_raw[:120])
            if not title_clean:
                i += 1
                continue

            events.append(
                {
                    "title": title_clean,
                    "date": format_date(dt, time_str),
                    "location": location or "",
                    "venue": extract_venue(ctx),
                    "link": link or post_link,
                    "source": source,
                    "image_url": image_url,
                }
            )
            i += 1
        return events

    # ── Telegram channels ────────────────────────────────────────────────────

    async def parse_channel(self, channel: Dict) -> List[Dict]:
        html = await self.fetch(f"https://t.me/s/{channel['username']}")
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        all_events = []

        for msg in soup.find_all("div", class_="tgme_widget_message")[:20]:
            try:
                td = msg.find("div", class_="tgme_widget_message_text")
                if not td:
                    continue

                text = td.get_text(separator="\n", strip=True)
                if len(text) < 30:
                    continue

                le = msg.find("a", class_="tgme_widget_message_date")
                post_link = le["href"] if le else f"https://t.me/{channel['username']}"
                norm_link = normalize_link(post_link)

# 🔥 ИЩЕМ ПЕРВОИСТОЧНИК В ТЕКСТЕ
                external_link = None
                links_in_text = re.findall(r"(https?://[^\s]+)", text)

                for l in links_in_text:
                    clean_l = normalize_link(l)
                    if "t.me" not in clean_l:   # исключаем telegram
                        external_link = clean_l
                        break

# если нашли внешний источник — используем его
                final_link = external_link if external_link else norm_link

                # ❗ ПРОВЕРКА ТОЛЬКО ЗДЕСЬ
                if norm_link in self.posted:
                    continue
                
                # 🔥 ИЩЕМ ПЕРВОИСТОЧНИК
                external_link = None

# 1️⃣ сначала ищем <a href=...>
                for a in td.find_all("a", href=True):
                    href = normalize_link(a["href"])
                    if "t.me" not in href:
                        external_link = href
                        break

# 2️⃣ если не нашли — fallback на regex
                if not external_link:
                    links_in_text = re.findall(r"(https?://[^\s]+)", text)
                    for l in links_in_text:
                        clean_l = normalize_link(l)
                        if "t.me" not in clean_l:
                            external_link = clean_l
                            break

# 3️⃣ выбираем финальную ссылку
                final_link = external_link if external_link else norm_link

                image_url = None

# Telegram photo preview
                photo_wrap = msg.find("a", class_="tgme_widget_message_photo_wrap")
                if photo_wrap:
                    style = photo_wrap.get("style", "")
                    match = re.search(r"url\('([^']+)'\)", style)
                    if match:
                        image_url = match.group(1)

# если нет — попробуем img внутри текста
                if not image_url:
                    img_tag = td.find("img")
                    if img_tag and img_tag.get("src"):
                        image_url = img_tag["src"]

                # Дайджест
                if re.search(r"\d{1,2}[.\-]\d{2}\s+(?:в\s+)?\d{1,2}:\d{2}", text):
                    evs = self.parse_digest(text, post_link, channel["name"], image_url)
                    all_events.extend(evs)
                    continue

                if not is_real_event(text):
                    continue

                dt = parse_date(text)
                if not is_future(dt):
                    continue

                # Определяем заголовок
                title_candidate = None
                for ln in text.split("\n"):
                    ln = strip_emoji(ln).strip()
                    if len(ln) > 10:
                        title_candidate = ln
                        break

                title = clean_title_deterministic(title_candidate or "")
                if not title:
                    continue

                tm2 = re.search(r"\d{1,2}\s+[а-яёА-ЯЁ]{3,}[,\s]+(\d{1,2}:\d{2})", text)
                time_str = tm2.group(1) if tm2 else None

                all_events.append(
                    {
                        "title": title,
                        "date": format_date(dt, time_str),
                        "location": extract_location(text) or "",
                        "venue": extract_venue(text),
                        "link": final_link,
                        "source": channel["name"],
                        "image_url": image_url,
                    }
                )

            except Exception as e:
                logger.error(f"parse_channel error: {e}")
                continue

        return all_events
    
    async def get_all_events(self) -> List[Dict]:
        all_events = []

        logger.info(f"🌐 Парсинг {len(URLS)} сайтов...")
        for site in URLS:
            evs = await self.parse_site(site)
            all_events.extend(evs)

        logger.info(f"📱 Парсинг {len(TELEGRAM_CHANNELS)} каналов...")
        for ch in TELEGRAM_CHANNELS:
            evs = await self.parse_channel(ch)
            all_events.extend(evs)

        return all_events




   

    
    # ── Sites ────────────────────────────────────────────────────────────────

    async def parse_site(self, site: Dict) -> List[Dict]:

        html = await self.fetch(site["url"])
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        events = []

        for link in soup.find_all("a", href=True)[:80]:
            try:
                href = link.get("href", "")
                title_raw = link.get_text(strip=True)

                if not href or not title_raw or len(title_raw) < 15:
                    continue

                if not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(site["url"], href)

                # 🔥 нормализация ссылки
                href = normalize_link(href)

                if href.rstrip("/") == normalize_link(site["url"]).rstrip("/"):
                    continue

                # 🔥 проверка дубля через нормализованную ссылку
                if href in self.posted:
                    continue

                if is_site_trash(title_raw):
                    continue

                if not is_real_event(title_raw):
                    continue

                parent = link.find_parent(["div", "article", "li", "section"])
                context = parent.get_text(separator=" ", strip=True) if parent else title_raw
                dt = parse_date(context)

                if not is_future(dt):
                    continue

                image_url = None


# обычный img
                image_url = None

                if parent:
                    imgs = parent.find_all("img")

                    for img in imgs:
                        src = img.get("src") or img.get("data-src")
                        if not src:
                            continue

                        if not src.startswith("http"):
                            from urllib.parse import urljoin
                            src = urljoin(site["url"], src)

                        # фильтруем постеры
                        if is_clean_photo(src):
                            image_url = src
                            break

                # fallback — background-image
                if not image_url and parent:
                    style = parent.get("style", "")
                    match = re.search(r"url\(['\"]?([^'\")]+)", style)

                    if match:
                        src = match.group(1)

                        if not src.startswith("http"):
                            from urllib.parse import urljoin
                            src = urljoin(site["url"], src)

                        if is_clean_photo(src):
                            image_url = src


                title_clean = (
                    clean_title_deterministic(title_raw)
                    or strip_emoji(dedup_title(title_raw))[:120]
                )

                events.append(
                    {
                        "title": title_clean,
                        "date": format_date(dt),
                        "location": extract_location(context) or "",
                        "venue": extract_venue(context),
                        "link": href,
                        "source": site["name"],
                        "image_url": image_url,
                    }
                )

                if len(events) >= 5:
                    break

            except Exception:
                continue

        return events
        
        




    






# ─── main ────────────────────────────────────────────────────────────────────
async def main():
    logger.info("🚀 Старт...")

    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден!")
        return

    bot_obj = EventBot()
    bot_api = Bot(token=BOT_TOKEN)

    try:
        events = await bot_obj.get_all_events()

        # Убираем дубли по заголовку
        unique, seen = [], set()
        for e in events:
            key = (e.get("title", "")[:60]).lower()
            if key and key not in seen:
                unique.append(e)
                seen.add(key)

        logger.info(f"📊 Уникальных будущих событий: {len(unique)}")
        logger.info(f"📦 Уже опубликовано: {len(bot_obj.posted)}")

        posted = 0

        for event in unique[:15]:

            norm_link = normalize_link(event.get("link", ""))

            # ───── Проверка дубля ─────
            if norm_link in bot_obj.posted:
                logger.info(f"⏭️ Уже публиковалось: {event.get('title')[:50]}")
                continue

            text = make_post(event)
            if not text:
                continue

            try:
                photo_to_send = None

                # ───── OCR авто-обрезка текста ─────
                if event.get("image_url"):
                    session = await bot_obj.get_session()
                    photo_to_send = await smart_crop_text_zones(
                        session,
                        event["image_url"]
                    )

                # ───── Отправка ─────
                if photo_to_send:
                    await bot_api.send_photo(
                        chat_id=CHANNEL_ID,
                        message_thread_id=MESSAGE_THREAD_ID,
                        photo=photo_to_send,
                        caption=text,
                        parse_mode="HTML",
                    )
                else:
                    await bot_api.send_message(
                        chat_id=CHANNEL_ID,
                        message_thread_id=MESSAGE_THREAD_ID,
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )

                # ───── Сохраняем в state только после успешной отправки ─────
                bot_obj.posted.add(norm_link)
                save_posted(bot_obj.posted)

                posted += 1
                logger.info(f"✅ ({posted}) {event.get('title','')[:50]}")

                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"❌ Ошибка отправки: {e}")

        logger.info(f"✅ Готово! Опубликовано новых: {posted}")

    finally:
        await bot_obj.close()


if __name__ == "__main__":
    asyncio.run(main())
