import os
import asyncio
import logging
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

# Настройки
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID', "-1003812789640")
MESSAGE_THREAD_ID = int(os.getenv('MESSAGE_THREAD_ID', '4'))

# Telegram каналы с дайджестами событий
TELEGRAM_CHANNELS = [
    {"username": "startup_course_com", "name": "Startup Course"},
    {"username": "astanahub_events", "name": "Astana Hub Events"},
    {"username": "digitalbusinesskz", "name": "Digital Business KZ"},
    {"username": "vcinsightskz", "name": "VC Insights KZ"},
    {"username": "startupalmaty", "name": "Startup Almaty"},
]

# Месяцы
MONTHS_RU = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}


def parse_date_str(date_str: str) -> Optional[datetime]:
    """Преобразовать строку даты в datetime"""
    try:
        text = date_str.lower().strip()

        # "14-15.02" или "14-15.02.2026"
        match = re.search(r'(\d{1,2})[-–](\d{1,2})\.(\d{2})(?:\.(\d{4}))?', text)
        if match:
            day = int(match.group(2))
            month = int(match.group(3))
            year = int(match.group(4)) if match.group(4) else datetime.now().year
            return datetime(year, month, day)

        # "12.02" или "12.02.2026"
        match = re.search(r'(\d{1,2})\.(\d{2})(?:\.(\d{4}))?', text)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else datetime.now().year
            return datetime(year, month, day)

        # "14-15 февраля 2026"
        match = re.search(r'(\d{1,2})[-–](\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?', text)
        if match:
            day = int(match.group(2))
            month = MONTHS_RU.get(match.group(3), 0)
            year = int(match.group(4)) if match.group(4) else datetime.now().year
            if month:
                return datetime(year, month, day)

        # "14 февраля 2026"
        match = re.search(r'(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?', text)
        if match:
            day = int(match.group(1))
            month = MONTHS_RU.get(match.group(2), 0)
            year = int(match.group(3)) if match.group(3) else datetime.now().year
            if month:
                return datetime(year, month, day)

    except Exception as e:
        logger.debug(f"Ошибка парсинга даты '{date_str}': {e}")

    return None


def is_future(date_str: str) -> bool:
    """Событие в будущем? Строгая проверка"""
    if not date_str:
        return False  # Если дата неизвестна - НЕ берем (было True, стало False)

    dt = parse_date_str(date_str)
    if not dt:
        return False  # Если не смогли распознать дату - НЕ берем

    return dt.date() > datetime.now().date()  # Строго больше (не сегодня, а завтра+)


def extract_events_from_digest(text: str, source_link: str, source_name: str) -> List[Dict]:
    """
    Разбить дайджест на отдельные события.
    Пример строки: "12.02 в 10:00 ☁️ Конференция PRO-DATA CLOUD @ Holiday Inn t.me/..."
    """
    events = []

    # Паттерн строки события:
    # "12.02 в 10:00" или "14-15.02 в 10:00" + текст + ссылка
    event_pattern = re.compile(
        r'(\d{1,2}[-–]?\d{0,2}[.\s]\d{2}(?:\.\d{4})?)\s*(?:в\s*(\d{1,2}:\d{2}))?\s*([^\n]+?)(?:\s+((?:https?://|t\.me/)\S+))?(?:\n|$)',
        re.MULTILINE
    )

    lines = text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Ищем строку с датой в начале (признак события в дайджесте)
        date_match = re.match(
            r'^(\d{1,2}[-–]?\d{0,2}[.\s]\d{2}(?:\.\d{4})?)\s*(?:в\s*(\d{1,2}:\d{2}))?',
            line
        )

        if date_match:
            date_str = date_match.group(1).replace(' ', '.')
            time_str = date_match.group(2)

            # Убираем дату и время из строки - остается описание
            event_text = line[date_match.end():].strip()

            # Убираем эмодзи в начале
            event_text = re.sub(r'^[\U00010000-\U0010ffff\u2600-\u27ff\s]+', '', event_text).strip()

            # Ищем ссылку в этой или следующей строке
            link = None
            link_match = re.search(r'((?:https?://|t\.me/)\S+)', event_text)
            if link_match:
                link = link_match.group(1)
                if not link.startswith('http'):
                    link = 'https://' + link
                event_text = event_text[:link_match.start()].strip()
            elif i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                link_match = re.search(r'((?:https?://|t\.me/)\S+)', next_line)
                if link_match:
                    link = link_match.group(1)
                    if not link.startswith('http'):
                        link = 'https://' + link

            # Ищем место "@"
            venue = None
            venue_match = re.search(r'@\s+([^@\n]+?)(?:\s+(?:https?://|t\.me/)|\s*$)', event_text)
            if venue_match:
                venue = venue_match.group(1).strip()
                event_text = event_text[:venue_match.start()].strip()

            if not event_text or len(event_text) < 5:
                i += 1
                continue

            # Проверяем что дата в будущем (строго)
            if not is_future(date_str):
                logger.info(f"⏭️ Пропускаем прошедшее: {event_text[:40]} ({date_str})")
                i += 1
                continue

            # Определяем место
            location = venue or extract_location(event_text)

            # Пропускаем если нет места
            if not location:
                logger.info(f"⏭️ Пропускаем без места: {event_text[:40]}")
                i += 1
                continue

            # Форматируем дату красиво
            formatted_date = format_date(date_str, time_str)

            events.append({
                'title': event_text[:150],
                'date': formatted_date,
                'date_raw': date_str,
                'venue': location,
                'link': link or source_link,
                'source': source_name,
                'image_url': None
            })

        i += 1

    return events


def format_date(date_str: str, time_str: Optional[str] = None) -> str:
    """Красиво форматировать дату"""
    months_names = {
        1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
        5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
        9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'
    }

    dt = parse_date_str(date_str)
    if dt:
        result = f"{dt.day} {months_names[dt.month]} {dt.year}"
        if time_str:
            result += f", {time_str}"
        return result

    return date_str


def extract_location(text: str) -> Optional[str]:
    """Извлечь город"""
    cities = {
        'Алматы': 'Алматы', 'Астана': 'Астана', 'Нур-Султан': 'Астана',
        'Шымкент': 'Шымкент', 'Онлайн': 'Онлайн', 'ОНЛАЙН': 'Онлайн',
        'Online': 'Онлайн', 'ZOOM': 'Онлайн (Zoom)', 'Ташкент': 'Ташкент'
    }
    for key, value in cities.items():
        if key.lower() in text.lower():
            return value
    return None


def format_post(event: Dict) -> str:
    """Форматировать один пост"""
    lines = []

    # Заголовок
    title = event['title']
    if len(title) > 120:
        title = title[:117] + '...'
    lines.append(f"🎯 <b>{title}</b>")
    lines.append("")

    # Дата
    if event.get('date'):
        lines.append(f"📅 {event['date']}")

    # Место
    location = event.get('venue') or extract_location(event['title'])
    if location:
        lines.append(f"📍 {location}")

    # Организатор
    lines.append(f"📌 {event['source']}")

    # Ссылка
    lines.append("")
    lines.append(f"🔗 <a href='{event['link']}'>Подробнее →</a>")

    return "\n".join(lines)


class DigestParser:
    def __init__(self):
        self.session = None
        self.posted_cache = set()

    async def get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers={'User-Agent': 'Mozilla/5.0'}
            )
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
            logger.error(f"Ошибка загрузки {url}: {e}")
            return ""

    async def parse_telegram(self, channel: Dict) -> List[Dict]:
        """Парсинг Telegram канала - каждое событие отдельно"""
        try:
            url = f"https://t.me/s/{channel['username']}"
            html = await self.fetch(url)
            if not html:
                return []

            soup = BeautifulSoup(html, 'html.parser')
            all_events = []

            for msg in soup.find_all('div', class_='tgme_widget_message'):
                try:
                    text_div = msg.find('div', class_='tgme_widget_message_text')
                    if not text_div:
                        continue

                    text = text_div.get_text(strip=True, separator='\n')
                    if len(text) < 20:
                        continue

                    # Ссылка на пост
                    link_elem = msg.find('a', class_='tgme_widget_message_date')
                    post_link = link_elem['href'] if link_elem else f"https://t.me/{channel['username']}"

                    if post_link in self.posted_cache:
                        continue

                    # Добавляем в кэш СРАЗУ чтобы не дублировать
                    self.posted_cache.add(post_link)

                    # Картинка поста
                    image_url = None
                    img_div = msg.find('a', class_='tgme_widget_message_photo_wrap')
                    if img_div:
                        style = img_div.get('style', '')
                        img_match = re.search(r"url\('([^']+)'\)", style)
                        if img_match:
                            image_url = img_match.group(1)

                    # Проверяем: это дайджест (список событий)?
                    is_digest = bool(re.search(
                        r'\d{1,2}[.\-]\d{2}\s+(?:в\s+)?\d{1,2}:\d{2}',
                        text
                    ))

                    if is_digest:
                        # Разбиваем дайджест на отдельные события
                        events = extract_events_from_digest(text, post_link, channel['name'])
                        logger.info(f"📋 Дайджест в {channel['name']}: найдено {len(events)} событий")
                        for event in events:
                            event['image_url'] = image_url
                            all_events.append(event)
                    else:
                        # Обычный пост - одно событие
                        event_kw = ['конференция', 'meetup', 'хакатон', 'workshop',
                                    'вебинар', 'pitch', 'акселератор', 'воркшоп',
                                    'мероприятие', 'event', 'тренинг', 'конкурс']

                        if not any(kw in text.lower() for kw in event_kw):
                            continue

                        date_str = None
                        date_match = re.search(
                            r'(\d{1,2}[-–]?\d{0,2}[.\s]\d{2}(?:\.\d{4})?)',
                            text
                        )
                        if date_match:
                            date_str = date_match.group(1)

                        time_match = re.search(r'в\s*(\d{1,2}:\d{2})', text)
                        time_str = time_match.group(1) if time_match else None

                        # Пропускаем если нет даты
                        if not date_str:
                            logger.info(f"⏭️ Пропускаем пост без даты")
                            continue

                        # Пропускаем прошедшие
                        if not is_future(date_str):
                            logger.info(f"⏭️ Пропускаем прошедшее ({date_str})")
                            continue

                        # Пропускаем если нет места
                        location = extract_location(text)
                        if not location:
                            logger.info(f"⏭️ Пропускаем пост без места проведения")
                            continue

                        formatted_date = format_date(date_str, time_str)

                        # Берем первые 100 символов как заголовок
                        title = text.split('\n')[0][:150]

                        all_events.append({
                            'title': title,
                            'date': formatted_date,
                            'date_raw': date_str,
                            'venue': location,
                            'link': post_link,
                            'source': channel['name'],
                            'image_url': image_url
                        })

                except Exception as e:
                    logger.error(f"Ошибка обработки сообщения: {e}")
                    continue

            return all_events

        except Exception as e:
            logger.error(f"Ошибка TG {channel['name']}: {e}")
            return []

    async def get_all_events(self) -> List[Dict]:
        all_events = []

        for channel in TELEGRAM_CHANNELS:
            events = await self.parse_telegram(channel)
            all_events.extend(events)
            if events:
                logger.info(f"✅ {channel['name']}: {len(events)} событий")

        return all_events


async def main():
    logger.info("🚀 Ищем предстоящие события...")

    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не установлен!")
        return

    parser = DigestParser()
    bot = Bot(token=BOT_TOKEN)

    try:
        events = await parser.get_all_events()

        if not events:
            logger.warning("⚠️ Событий не найдено")
            return

        # Убираем дубликаты
        unique_events = []
        seen = set()
        for event in events:
            key = event['title'][:50]
            if key not in seen:
                unique_events.append(event)
                seen.add(key)

        logger.info(f"📊 Уникальных событий: {len(unique_events)}")

        posted = 0
        for event in unique_events[:15]:
            try:
                text = format_post(event)

                if event.get('image_url'):
                    try:
                        await bot.send_photo(
                            chat_id=CHANNEL_ID,
                            message_thread_id=MESSAGE_THREAD_ID,
                            photo=event['image_url'],
                            caption=text,
                            parse_mode='HTML'
                        )
                    except:
                        await bot.send_message(
                            chat_id=CHANNEL_ID,
                            message_thread_id=MESSAGE_THREAD_ID,
                            text=text,
                            parse_mode='HTML',
                            disable_web_page_preview=True  # Убираем зеленую рамку
                        )
                else:
                    await bot.send_message(
                        chat_id=CHANNEL_ID,
                        message_thread_id=MESSAGE_THREAD_ID,
                        text=text,
                        parse_mode='HTML',
                        disable_web_page_preview=True  # Убираем зеленую рамку
                    )

                posted += 1
                logger.info(f"✅ ({posted}) {event['title'][:50]}")
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"❌ Ошибка: {e}")

        logger.info(f"✅ Готово! Опубликовано: {posted} событий")

    finally:
        await parser.close()


if __name__ == '__main__':
    asyncio.run(main())