import os
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Optional
import aiohttp
from bs4 import BeautifulSoup
from telegram import Bot
import re

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID', "-1003812789640")
MESSAGE_THREAD_ID = int(os.getenv('MESSAGE_THREAD_ID', '4'))

TELEGRAM_CHANNELS = [
    {"username": "startup_course_com", "name": "Startup Course"},
    {"username": "digitalbusinesskz", "name": "Digital Business KZ"},
    {"username": "vcinsightskz", "name": "VC Insights KZ"},
    {"username": "tech_kz", "name": "Tech KZ"},
    {"username": "startupalmaty", "name": "Startup Almaty"},
    {"username": "astanahub_events", "name": "Astana Hub Events"},
    # добавляй сюда другие каналы, если нужно
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

KZ_CITIES = {
    'алматы': 'Алматы', 'астана': 'Астана', 'шымкент': 'Шымкент',
    'нур-султан': 'Астана', 'усть-каменогорск': 'Усть-Каменогорск',
    'кызылорда': 'Кызылорда', 'актобе': 'Актобе', 'тараз': 'Тараз',
    'павлодар': 'Павлодар', 'семей': 'Семей', 'атырау': 'Атырау',
    'актау': 'Актау', 'кокшетау': 'Кокшетау', 'жезказган': 'Жезказган',
    'онлайн': 'Онлайн', 'zoom': 'Онлайн (Zoom)',
}

EMOJI_RE = re.compile(r'[\U0001F000-\U0001FFFF]', re.UNICODE)


def strip_emoji(s: str) -> str:
    return EMOJI_RE.sub('', s).strip()


def parse_date_from_text(text: str) -> Optional[datetime]:
    t = text.lower()
    for pattern, month_dict in [
        (r'(\d{1,2})\s+([а-я]{3,})\s*(\d{4})?', MONTHS_RU),
        (r'(\d{1,2})\s+(янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)', MONTHS_SHORT),
    ]:
        m = re.search(pattern, t, re.I)
        if m:
            day = int(m.group(1))
            month_str = m.group(2).lower()[:3] if len(m.groups()) > 1 else m.group(2)
            year = int(m.group(3)) if len(m.groups()) > 2 and m.group(3) else None

            month = month_dict.get(month_str, 0)
            if month:
                y = year if year else datetime.now().year
                try:
                    dt = datetime(y, month, day)
                    # если дата уже прошла и год не указан явно — берём следующий год
                    if not year and dt.date() < datetime.now().date():
                        dt = dt.replace(year=dt.year + 1)
                    return dt
                except ValueError:
                    pass
    return None


def is_future_event(dt: Optional[datetime]) -> bool:
    return dt is not None and dt.date() > datetime.now().date()


def format_event_date(dt: datetime, time_str: Optional[str] = None) -> str:
    months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
              'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
    s = f"{dt.day} {months[dt.month - 1]} {dt.year}"
    if time_str:
        s += f", {time_str}"
    return s


def extract_city(text: str) -> str:
    t = text.lower()
    for k, v in KZ_CITIES.items():
        if k in t:
            return v
    return ""


def get_clean_title_and_desc(raw_text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Основная функция очистки: возвращает (заголовок, описание или None)
    """
    lines = [strip_emoji(l).strip() for l in raw_text.splitlines() if strip_emoji(l).strip()]

    if not lines:
        return None, None

    # Первая строка — обычно шапка
    header = lines[0]

    # Паттерн для твоего формата: 25 Фев, 11:00АлматыНазвание...
    m = re.search(
        r'(?:\d{1,2}\s+[а-я]{3,}[,\s]*\d{2}:\d{2})'
        r'([А-ЯЁ][а-яё]*?)'
        r'(.+)',
        header, re.IGNORECASE | re.UNICODE
    )

    if m:
        # m.group(1) — город
        # m.group(2) — название + возможно описание
        content = m.group(2).strip(' :–—•')

        # Пытаемся отделить описание от заголовка
        # (по первой точке после 20+ символов или по заглавной после пробела)
        split_match = re.search(r'(?:[.!?]\s+|\s{2,})([А-ЯЁ«"0-9])', content)
        if split_match and split_match.start() > 15:
            title = content[:split_match.start()].strip()
            desc = content[split_match.start():].strip()
        else:
            title = content
            desc = None

        if len(title) > 8:
            return title, desc

    # Fallback: ищем самую длинную строку без ссылок и даты в начале
    candidates = []
    for line in lines:
        clean = re.sub(r'^\d{1,2}\s+[а-я]{3,}[,\s]*\d{2}:\d{2}\s*[А-Я][а-яё]*\s*', '', line, flags=re.I)
        clean = clean.strip(' :–—-')
        if 12 < len(clean) < 300 and 'http' not in clean and 't.me' not in clean:
            candidates.append(clean)

    if candidates:
        longest = max(candidates, key=len)
        split_m = re.search(r'(?:[.!?]\s+|\s{2,})([А-ЯЁ«"0-9])', longest)
        if split_m and split_m.start() > 20:
            return longest[:split_m.start()].strip(), longest[split_m.start():].strip()
        return longest, None

    return None, None


def make_post(event: Dict) -> str:
    raw_text = event.get('raw_text', '')
    if not raw_text:
        return ""

    title, description = get_clean_title_and_desc(raw_text)
    if not title:
        return ""

    dt = parse_date_from_text(raw_text)
    if not is_future_event(dt):
        return ""

    time_match = re.search(r'(\d{1,2}:\d{2})', raw_text)
    time_str = time_match.group(1) if time_match else None

    lines = [f"🎯 <b>{title}</b>"]

    if description:
        lines.append(description)

    city = extract_city(raw_text)
    if city:
        if 'онлайн' in city.lower():
            lines.append("🌐 Онлайн")
        else:
            lines.append(f"🇰🇿 Казахстан, 🏙 {city}")
    else:
        lines.append("🇰🇿 Казахстан")

    lines.append(f"📅 {format_event_date(dt, time_str)}")
    lines.append(f"🔗 <a href=\"{event['link']}\">Читать →</a>")

    return "\n".join(lines)


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
            async with session.get(url, timeout=12) as resp:
                return await resp.text() if resp.status == 200 else ""
        except Exception as e:
            logger.error(f"fetch error {url}: {e}")
            return ""

    async def parse_channel(self, channel: Dict) -> List[Dict]:
        url = f"https://t.me/s/{channel['username']}"
        html = await self.fetch(url)
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        events = []

        for msg in soup.find_all('div', class_='tgme_widget_message')[:30]:
            text_div = msg.find('div', class_='tgme_widget_message_text')
            if not text_div:
                continue

            raw_text = text_div.get_text(separator='\n', strip=True)
            if len(raw_text) < 40:
                continue

            link_elem = msg.find('a', class_='tgme_widget_message_date')
            post_link = link_elem['href'] if link_elem else f"https://t.me/{channel['username']}"

            if post_link in self.posted:
                continue
            self.posted.add(post_link)

            title, _ = get_clean_title_and_desc(raw_text)
            if not title:
                continue

            dt = parse_date_from_text(raw_text)
            if not is_future_event(dt):
                logger.info(f"Прошедшее событие пропущено: {title[:50]}")
                continue

            time_match = re.search(r'(\d{1,2}:\d{2})', raw_text)
            time_str = time_match.group(1) if time_match else None

            events.append({
                'raw_text': raw_text,
                'title': title,
                'date': format_event_date(dt, time_str),
                'location': extract_city(raw_text),
                'link': post_link,
            })

        return events


async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не найден")
        return

    bot_obj = EventBot()
    bot = Bot(token=BOT_TOKEN)

    try:
        all_events = []
        for channel in TELEGRAM_CHANNELS:
            events = await bot_obj.parse_channel(channel)
            all_events.extend(events)

        # Убираем дубликаты по заголовку + дате
        seen = set()
        unique = []
        for e in all_events:
            key = (e['title'][:80].lower(), e['date'])
            if key not in seen:
                seen.add(key)
                unique.append(e)

        logger.info(f"Уникальных будущих событий: {len(unique)}")

        posted = 0
        for event in unique[:10]:  # лимит на отправку за один запуск
            text = make_post(event)
            if not text:
                continue

            try:
                await bot.send_message(
                    chat_id=CHANNEL_ID,
                    message_thread_id=MESSAGE_THREAD_ID,
                    text=text,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
                posted += 1
                logger.info(f"Отправлено: {event['title'][:60]}")
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Ошибка отправки: {e}")

        logger.info(f"Всего отправлено: {posted}")

    finally:
        await bot_obj.close()


if __name__ == '__main__':
    asyncio.run(main())
