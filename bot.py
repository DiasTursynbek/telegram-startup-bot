import os
import asyncio
import logging
import json
from datetime import datetime
from typing import List, Dict, Optional
import aiohttp
from bs4 import BeautifulSoup
from telegram import Bot
import re

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID', "-1003812789640")
MESSAGE_THREAD_ID = int(os.getenv('MESSAGE_THREAD_ID', '4'))

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
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
}
MONTHS_SHORT = {
    'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4,
    'май': 5, 'июн': 6, 'июл': 7, 'авг': 8,
    'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12,
}

# Пост берём ТОЛЬКО если есть хотя бы одно из этих слов
EVENT_WORDS = [
    'конференция', 'conference', 'форум', 'forum', 'summit', 'саммит',
    'meetup', 'митап', 'хакатон', 'hackathon',
    'воркшоп', 'workshop', 'мастер-класс', 'masterclass',
    'вебинар', 'webinar', 'семинар',
    'pitch', 'питч', 'demo day',
    'акселератор', 'accelerator', 'bootcamp', 'буткемп',
    'выставка', 'конкурс', 'competition',
    'тренинг', 'training',
    'мероприятие', 'ивент', 'event',
    'приглашает', 'приглашаем', 'зарегистрируйся', 'регистрация',
]

# Пост ВЫБРАСЫВАЕМ если есть хотя бы одно из этих слов
NOT_EVENT_WORDS = [
    'research', 'исследование показало', 'инвестировал', 'привлек раунд',
    'млн $', 'млрд $', 'назначен', 'уволен', 'отчет', 'выручка',
    'курс доллара', 'биржа', 'акции', 'токаев', 'правительство приняло',
]

# Навигационный мусор с сайтов
SITE_STOP_WORDS = [
    'контакты', 'о нас', 'политика', 'войти', 'регистрация аккаунта',
    'подписаться', 'поиск', 'главная', 'меню', 'все новости',
    'читать далее', 'подробнее', 'узнать больше', 'privacy', 'terms', 'cookie',
]

KZ_CITIES = {
    'алматы': 'Алматы', 'астана': 'Астана', 'шымкент': 'Шымкент',
    'нур-султан': 'Астана', 'усть-каменогорск': 'Усть-Каменогорск',
    'кызылорда': 'Кызылорда', 'актобе': 'Актобе', 'тараз': 'Тараз',
    'павлодар': 'Павлодар', 'семей': 'Семей', 'атырау': 'Атырау',
    'онлайн': 'Онлайн', 'online': 'Онлайн', 'zoom': 'Онлайн (Zoom)',
    'ташкент': 'Ташкент, Узбекистан',
}

# Эмодзи-регулярка — НЕ трогает кириллицу
EMOJI_RE = re.compile(
    '[\U00010000-\U0010ffff'
    '\u2600-\u27ff'
    '\u2300-\u23ff'
    '\u25a0-\u25ff'
    '\u2B00-\u2BFF'
    ']',
    re.UNICODE
)


def strip_emoji(s: str) -> str:
    return EMOJI_RE.sub('', s).strip()


# ──────────────────────────────────────────────
# ДАТА
# ──────────────────────────────────────────────

def parse_date(text: str) -> Optional[datetime]:
    t = text.lower()
    try:
        m = re.search(r'(\d{1,2})[-](\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?', t)
        if m:
            day = int(m.group(2))
            month = MONTHS_RU.get(m.group(3), 0)
            year = int(m.group(4)) if m.group(4) else datetime.now().year
            if month:
                return datetime(year, month, day)

        m = re.search(r'(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?', t)
        if m:
            day = int(m.group(1))
            month = MONTHS_RU.get(m.group(2), 0)
            year = int(m.group(3)) if m.group(3) else datetime.now().year
            if month:
                dt = datetime(year, month, day)
                if not m.group(3) and dt.date() < datetime.now().date():
                    dt = datetime(year + 1, month, day)
                return dt

        m = re.search(r'(\d{1,2})\s+(янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)[а-я]*(?:\s+(\d{4}))?', t)
        if m:
            day = int(m.group(1))
            month = MONTHS_SHORT.get(m.group(2)[:3], 0)
            year = int(m.group(3)) if m.group(3) else datetime.now().year
            if month:
                dt = datetime(year, month, day)
                if not m.group(3) and dt.date() < datetime.now().date():
                    dt = datetime(year + 1, month, day)
                return dt

        m = re.search(r'(\d{1,2})\.(\d{2})(?:\.(\d{4}))?', t)
        if m:
            day = int(m.group(1))
            month = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else datetime.now().year
            if 1 <= month <= 12:
                return datetime(year, month, day)
    except Exception:
        pass
    return None


def is_future(dt: Optional[datetime]) -> bool:
    if not dt:
        return False
    return dt.date() > datetime.now().date()


def format_date(dt: datetime, time_str: str = None) -> str:
    months = {
        1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
        5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
        9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря',
    }
    result = f"{dt.day} {months[dt.month]} {dt.year}"
    if time_str:
        result += f", {time_str}"
    return result


# ──────────────────────────────────────────────
# МЕСТО
# ──────────────────────────────────────────────

def extract_location(text: str) -> Optional[str]:
    t = text.lower()
    for key, value in KZ_CITIES.items():
        if key in t:
            return value
    return None


def extract_venue(text: str) -> Optional[str]:
    venues = [
        'Narxoz', 'Nazarbayev', 'KBTU', 'KБТУ', 'Astana Hub',
        'IT Park', 'MOST IT Hub', 'Holiday Inn', 'Esentai',
        'Yandex', 'Smart Point', 'Almaty Arena',
    ]
    for v in venues:
        if v.lower() in text.lower():
            m = re.search(rf'{v}[^\n,.]*', text, re.IGNORECASE)
            if m:
                return m.group(0).strip()[:60]
    at_m = re.search(r'@\s+([^@\n]+?)(?:\s+(?:https?://|t\.me/)|\s*$)', text)
    if at_m:
        return at_m.group(1).strip()[:60]
    return None


# ──────────────────────────────────────────────
# ЗАГОЛОВОК
# ──────────────────────────────────────────────

def extract_title(text: str) -> Optional[str]:
    lines = text.strip().split('\n')
    for line in lines:
        clean = strip_emoji(line).strip(' -\u2013\u2022\xb7.,')
        clean = re.sub(r'\s+', ' ', clean).strip()
        if len(clean) < 10:
            continue
        if 't.me/' in clean or 'http' in clean:
            continue

        # Убираем дату+время+город в начале строки:
        # Примеры: "20 Фев, 15:00Актай..." / "23 Фев, 17:30Кокшетай..."
        clean = re.sub(
            r'^\d{1,2}\s+[А-ЯЁа-яё]{3,}[,.]?\s*\d{1,2}:\d{2}\s*[А-ЯЁA-Za-z\-]*\s*',
            '', clean
        ).strip()
        # Убираем просто "20 Фев, ..." без времени
        clean = re.sub(
            r'^\d{1,2}\s+[А-ЯЁа-яё]{3,}[,.]?\s*[А-ЯЁA-Za-z\-]*\s*',
            '', clean
        ).strip()
        # Убираем дубли: "Текст текст" когда первая часть == вторая
        half = len(clean) // 2
        if half > 20 and clean[:half].strip() == clean[half:half*2].strip():
            clean = clean[:half].strip()

        # Пропускаем строки начинающиеся с цифры (дата)
        if re.match(r'^\d{1,2}[.\-:\s]', clean):
            continue

        # Пропускаем если похоже на имя автора (Имя Фамилия без других слов)
        if re.match(r'^[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+$', clean):
            continue

        if len(clean) < 10:
            continue
        return clean[:120]
    return None


# ──────────────────────────────────────────────
# ФИЛЬТРЫ
# ──────────────────────────────────────────────

def is_real_event(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in EVENT_WORDS) and not any(w in t for w in NOT_EVENT_WORDS)


def is_site_trash(title: str) -> bool:
    t = title.lower()
    return any(s in t for s in SITE_STOP_WORDS)


# ──────────────────────────────────────────────
# ПАМЯТЬ ОШИБОК
# ──────────────────────────────────────────────

ERRORS_FILE = "grammar_errors.json"

def load_error_memory() -> List[str]:
    """Загружает историю исправленных ошибок из файла."""
    if os.path.exists(ERRORS_FILE):
        try:
            with open(ERRORS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_error_memory(errors: List[str]):
    """Сохраняет историю ошибок (не более 50 последних)."""
    try:
        with open(ERRORS_FILE, 'w', encoding='utf-8') as f:
            json.dump(errors[-50:], f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения памяти: {e}")


# ──────────────────────────────────────────────
# AI ИСПРАВЛЕНИЕ ТЕКСТА
# ──────────────────────────────────────────────

CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY', '')

async def ai_fix_text(title: str, session: aiohttp.ClientSession) -> tuple[str, List[str]]:
    """
    Исправляет заголовок через Claude API.
    Возвращает (исправленный текст, список новых ошибок для памяти).
    Если API недоступен — возвращает оригинал.
    """
    if not CLAUDE_API_KEY:
        return title, []

    error_memory = load_error_memory()
    memory_block = ""
    if error_memory:
        memory_block = "\n\nРанее исправленные ошибки (не повторяй их):\n" + "\n".join(
            f"- {e}" for e in error_memory[-20:]
        )

    prompt = f"""Исправь грамматику и пунктуацию в заголовке новости. Правила:
1. Только исправляй ошибки — не перефразируй
2. Расставь запятые где нужно
3. Заглавные буквы в начале
4. Верни JSON: {{"fixed": "исправленный текст", "errors": ["ошибка1", "ошибка2"]}}
5. Если ошибок нет — верни тот же текст и пустой список errors{memory_block}

Заголовок: {title}"""

    try:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=10
        ) as resp:
            if resp.status != 200:
                return title, []
            data = await resp.json()
            raw = data['content'][0]['text'].strip()
            raw = re.sub(r'^```json|```$', '', raw, flags=re.MULTILINE).strip()
            result = json.loads(raw)
            fixed = result.get('fixed', title)
            new_errors = result.get('errors', [])

            # Сохраняем новые ошибки в память
            if new_errors:
                memory = load_error_memory()
                memory.extend(new_errors)
                save_error_memory(memory)
                logger.info(f"📝 Исправлено ошибок: {len(new_errors)} — {new_errors}")

            return fixed, new_errors
    except Exception as e:
        logger.warning(f"AI коррекция недоступна: {e}")
        return title, []


# ──────────────────────────────────────────────
# ПОСТ
# ──────────────────────────────────────────────

def make_post(event: Dict) -> str:
    """
    Формат поста (4–5 строк):
    🎯 Что: <название>
    🌍 Страна / 🏙 Город / 📍 Место
    📅 Дата и время
    🔗 Ссылка на оригинал
    """
    title = (event.get('title') or '').strip()
    if not title or len(title) < 5:
        return ""
    if not event.get('date'):
        return ""

    location = event.get('location', '')
    venue = event.get('venue', '')

    # Строка 1 — что проходит
    lines = [f"🎯 <b>{title}</b>"]

    # Строка 2 — страна + город
    if location in ('Онлайн', 'Онлайн (Zoom)'):
        lines.append(f"🌐 Онлайн")
    elif location:
        lines.append(f"🇰🇿 Казахстан, 🏙 {location}")
    else:
        lines.append(f"🇰🇿 Казахстан")

    # Строка 3 — место (если есть)
    if venue:
        lines.append(f"📍 {venue}")

    # Строка 4 — дата и время
    lines.append(f"📅 {event['date']}")

    # Строка 5 — ссылка на оригинальную новость
    lines.append(f"🔗 <a href='{event['link']}'>Читать →</a>")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# БОТ
# ──────────────────────────────────────────────

class EventBot:
    def __init__(self):
        self.session = None
        self.posted = set()

    async def get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0'})
        return self.session

    async def close(self):
        if self.session:
            await self.session.close()

    async def fetch(self, url: str) -> str:
        try:
            session = await self.get_session()
            async with session.get(url, timeout=15) as resp:
                return await resp.text() if resp.status == 200 else ""
        except Exception as e:
            logger.error(f"Ошибка: {url} - {e}")
            return ""

    def parse_digest(self, text: str, post_link: str, source: str, image_url: str) -> List[Dict]:
        events = []
        lines = text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            date_match = re.match(
                r'^(\d{1,2}[-]?\d{0,2}[.\s]\d{2}(?:\.\d{4})?'
                r'|\d{1,2}\s+(?:янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)[а-я]*'
                r'(?:\s+\d{4})?)',
                line, re.IGNORECASE
            )
            if not date_match:
                i += 1
                continue

            date_raw = date_match.group(0)
            rest = line[date_match.end():].strip()

            time_match = re.search(r'(?:в\s*)?(\d{1,2}:\d{2})', rest)
            time_str = time_match.group(1) if time_match else None
            if time_match:
                rest = (rest[:time_match.start()] + rest[time_match.end():]).strip()

            title_raw = strip_emoji(rest).strip(' -\u2013\u2022')

            link = None
            lm = re.search(r'((?:https?://|t\.me/)\S+)', line)
            if lm:
                link = lm.group(1)
                if not link.startswith('http'):
                    link = 'https://' + link
                title_raw = title_raw.replace(strip_emoji(lm.group(0)), '').strip()
            else:
                for j in range(i + 1, min(i + 4, len(lines))):
                    lm = re.search(r'((?:https?://|t\.me/)\S+)', lines[j])
                    if lm:
                        link = lm.group(1)
                        if not link.startswith('http'):
                            link = 'https://' + link
                        break

            venue = None
            at_m = re.search(r'@\s+([^@\n]+?)(?:\s+(?:https?://|t\.me/)|\s*$)', title_raw)
            if at_m:
                venue = at_m.group(1).strip()
                title_raw = title_raw[:at_m.start()].strip()

            if len(title_raw) < 5 and i + 1 < len(lines):
                next_line = strip_emoji(lines[i + 1]).strip()
                if len(next_line) > 5 and not re.match(r'^\d', next_line):
                    title_raw = next_line

            if len(title_raw) < 5:
                i += 1
                continue

            dt = parse_date(date_raw)
            if not is_future(dt):
                logger.info(f"\u23ed\ufe0f Прошедшее: {title_raw[:40]} ({date_raw})")
                i += 1
                continue

            context = line + ' ' + (lines[i + 1] if i + 1 < len(lines) else '')
            location = extract_location(context) or extract_location(text)
            if not venue:
                venue = extract_venue(context)

            events.append({
                'title': title_raw[:120],
                'date': format_date(dt, time_str),
                'location': location or '',
                'venue': venue,
                'link': link or post_link,
                'source': source,
                'image_url': image_url,
            })
            i += 1
        return events

    async def parse_channel(self, channel: Dict) -> List[Dict]:
        url = f"https://t.me/s/{channel['username']}"
        html = await self.fetch(url)
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        all_events = []

        for msg in soup.find_all('div', class_='tgme_widget_message')[:20]:
            try:
                text_div = msg.find('div', class_='tgme_widget_message_text')
                if not text_div:
                    continue

                text = text_div.get_text(separator='\n', strip=True)
                if len(text) < 30:
                    continue

                link_elem = msg.find('a', class_='tgme_widget_message_date')
                post_link = link_elem['href'] if link_elem else f"https://t.me/{channel['username']}"

                if post_link in self.posted:
                    continue
                self.posted.add(post_link)

                image_url = None
                img_div = msg.find('a', class_='tgme_widget_message_photo_wrap')
                if img_div:
                    style = img_div.get('style', '')
                    m = re.search(r"url\('([^']+)'\)", style)
                    if m:
                        image_url = m.group(1)

                is_digest = bool(re.search(
                    r'\d{1,2}[.\-]\d{2}\s+(?:в\s+)?\d{1,2}:\d{2}', text
                ))

                if is_digest:
                    events = self.parse_digest(text, post_link, channel['name'], image_url)
                    all_events.extend(events)
                    logger.info(f"\U0001f4cb Дайджест {channel['name']}: {len(events)} событий")
                    continue

                # Фильтр 1: ключевые слова
                if not is_real_event(text):
                    logger.info(f"\u23ed\ufe0f Не ивент: {text[:50].strip()}")
                    continue

                # Фильтр 2: дата в будущем
                dt = parse_date(text)
                if not is_future(dt):
                    logger.info(f"\u23ed\ufe0f {'Прошедшее' if dt else 'Нет даты'}: {text[:50].strip()}")
                    continue

                # Фильтр 3: заголовок отдельно от даты
                title = extract_title(text)
                if not title:
                    logger.info(f"\u23ed\ufe0f Нет заголовка: {text[:50].strip()}")
                    continue
                # Если заголовок — имя автора (Имя Фамилия), ищем тему в следующих строках
                if re.match(r'^[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+$', title.strip()):
                    lines_all = text.strip().split('\n')
                    title = None
                    for ln in lines_all[1:]:
                        ln_c = strip_emoji(ln).strip()
                        if len(ln_c) > 15 and not re.match(r'^\d', ln_c) and 'http' not in ln_c:
                            if not re.match(r'^[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+$', ln_c):
                                title = ln_c[:120]
                                break
                if not title:
                    logger.info(f"\u23ed\ufe0f Только автор, нет темы: {text[:50].strip()}")
                    continue

                time_m = re.search(r'(?:в\s+)(\d{1,2}:\d{2})', text)
                time_str = time_m.group(1) if time_m else None

                all_events.append({
                    'title': title,
                    'date': format_date(dt, time_str),
                    'location': extract_location(text) or '',
                    'venue': extract_venue(text),
                    'link': post_link,
                    'source': channel['name'],
                    'image_url': image_url,
                })

            except Exception as e:
                logger.error(f"Ошибка: {e}")
                continue

        return all_events

    async def parse_site(self, site: Dict) -> List[Dict]:
        html = await self.fetch(site['url'])
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        events = []

        for link in soup.find_all('a', href=True)[:80]:
            try:
                href = link.get('href', '')
                title_raw = link.get_text(strip=True)

                if not href or not title_raw or len(title_raw) < 15:
                    continue
                if not href.startswith('http'):
                    from urllib.parse import urljoin
                    href = urljoin(site['url'], href)
                if href.rstrip('/') == site['url'].rstrip('/'):
                    continue
                if href in self.posted:
                    continue

                # Навигационный мусор
                if is_site_trash(title_raw):
                    continue

                # Ивент-слова
                if not is_real_event(title_raw):
                    continue

                parent = link.find_parent(['div', 'article', 'li', 'section'])
                context = parent.get_text(separator=' ', strip=True) if parent else title_raw
                dt = parse_date(context)

                # Только будущие
                if not is_future(dt):
                    continue

                location = extract_location(context) or ''
                venue = extract_venue(context)

                image_url = None
                img = (link.find('img', src=True) or
                       (parent.find('img', src=True) if parent else None))
                if img:
                    src = img.get('src', '')
                    if src and not src.startswith('http'):
                        from urllib.parse import urljoin
                        src = urljoin(site['url'], src)
                    image_url = src or None

                self.posted.add(href)
                events.append({
                    'title': strip_emoji(title_raw)[:120],
                    'date': format_date(dt),
                    'location': location,
                    'venue': venue,
                    'link': href,
                    'source': site['name'],
                    'image_url': image_url,
                })

                if len(events) >= 5:
                    break

            except Exception:
                continue

        return events

    async def get_all_events(self) -> List[Dict]:
        all_events = []

        logger.info(f"\U0001f310 Парсинг {len(URLS)} сайтов...")
        for site in URLS:
            events = await self.parse_site(site)
            all_events.extend(events)
            if events:
                logger.info(f"\u2705 {site['name']}: {len(events)}")

        logger.info(f"\U0001f4f1 Парсинг {len(TELEGRAM_CHANNELS)} Telegram каналов...")
        for channel in TELEGRAM_CHANNELS:
            events = await self.parse_channel(channel)
            all_events.extend(events)
            if events:
                logger.info(f"\u2705 {channel['name']}: {len(events)}")

        return all_events


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

async def main():
    logger.info("\U0001f680 Старт...")
    if not BOT_TOKEN:
        logger.error("\u274c BOT_TOKEN не найден!")
        return

    bot_obj = EventBot()
    bot = Bot(token=BOT_TOKEN)

    try:
        events = await bot_obj.get_all_events()

        unique, seen = [], set()
        for e in events:
            key = e['title'][:40].lower()
            if key not in seen:
                unique.append(e)
                seen.add(key)

        logger.info(f"\U0001f4ca Уникальных событий: {len(unique)}")

        posted = 0
        for event in unique[:15]:
            # AI исправление заголовка (с памятью ошибок)
            if CLAUDE_API_KEY:
                fixed_title, _ = await ai_fix_text(event['title'], bot_obj.session or await bot_obj.get_session())
                event['title'] = fixed_title

            text = make_post(event)
            if not text:
                continue
            try:
                if event.get('image_url'):
                    try:
                        await bot.send_photo(
                            chat_id=CHANNEL_ID,
                            message_thread_id=MESSAGE_THREAD_ID,
                            photo=event['image_url'],
                            caption=text,
                            parse_mode='HTML'
                        )
                    except Exception:
                        await bot.send_message(
                            chat_id=CHANNEL_ID,
                            message_thread_id=MESSAGE_THREAD_ID,
                            text=text,
                            parse_mode='HTML',
                            disable_web_page_preview=True
                        )
                else:
                    await bot.send_message(
                        chat_id=CHANNEL_ID,
                        message_thread_id=MESSAGE_THREAD_ID,
                        text=text,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                posted += 1
                logger.info(f"\u2705 ({posted}) {event['title'][:50]}")
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"\u274c {e}")

        logger.info(f"\u2705 Готово! Опубликовано: {posted}")

    finally:
        await bot_obj.close()


if __name__ == '__main__':
    asyncio.run(main())
