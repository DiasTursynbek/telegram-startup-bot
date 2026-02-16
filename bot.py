import os
import asyncio
import logging
from datetime import datetime, timedelta
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

# Источники
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


class EventExtractor:
    """Извлечение структурированной информации о событии"""
    
    @staticmethod
    def extract_location(text: str) -> Optional[str]:
        """Извлечь город/место"""
        cities = ['Алматы', 'Астана', 'Нур-Султан', 'Шымкент', 'Караганда', 
                  'Актобе', 'Тараз', 'Павлодар', 'Петропавловск', 'Онлайн', 'Online']
        
        for city in cities:
            if city.lower() in text.lower():
                return city
        return None
    
    @staticmethod
    def extract_date(text: str) -> Optional[str]:
        """Извлечь дату"""
        # Формат: "20 февраля", "15.02.2026", "2026-02-20"
        patterns = [
            r'\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)',
            r'\d{2}\.\d{2}\.\d{4}',
            r'\d{4}-\d{2}-\d{2}'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        return None
    
    @staticmethod
    def parse_date_to_datetime(date_str: str) -> Optional[datetime]:
        """Преобразовать строку даты в datetime для сравнения"""
        if not date_str:
            return None
        
        # Месяцы на русском
        months_ru = {
            'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
            'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
            'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
        }
        
        try:
            # Формат: "20 февраля"
            match = re.search(r'(\d{1,2})\s+([а-я]+)', date_str.lower())
            if match:
                day = int(match.group(1))
                month_name = match.group(2)
                month = months_ru.get(month_name)
                if month:
                    year = datetime.now().year
                    # Если месяц уже прошел - берем следующий год
                    event_date = datetime(year, month, day)
                    if event_date < datetime.now():
                        event_date = datetime(year + 1, month, day)
                    return event_date
            
            # Формат: "15.02.2026"
            match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', date_str)
            if match:
                day, month, year = map(int, match.groups())
                return datetime(year, month, day)
            
            # Формат: "2026-02-20"
            match = re.search(r'(\d{4})-(\d{2})-(\d{2})', date_str)
            if match:
                year, month, day = map(int, match.groups())
                return datetime(year, month, day)
        except:
            pass
        
        return None
    
    @staticmethod
    def is_future_event(date_str: str) -> bool:
        """Проверить что событие в будущем"""
        event_date = EventExtractor.parse_date_to_datetime(date_str)
        if not event_date:
            # Если дату не удалось определить - считаем что событие актуально
            return True
        
        # Событие должно быть как минимум сегодня или в будущем
        return event_date.date() >= datetime.now().date()
    
    @staticmethod
    def extract_time(text: str) -> Optional[str]:
        """Извлечь время"""
        pattern = r'\d{1,2}:\d{2}'
        match = re.search(pattern, text)
        return match.group(0) if match else None
    
    @staticmethod
    def extract_venue(text: str) -> Optional[str]:
        """Извлечь место проведения"""
        venues = ['Astana Hub', 'IT Park', 'Dostyk Plaza', 'Ramstore', 
                  'Esentai', 'МФЦА', 'технопарк', 'коворкинг']
        
        for venue in venues:
            if venue.lower() in text.lower():
                return venue
        return None
    
    @staticmethod
    def clean_title(title: str) -> str:
        """Очистить заголовок - оставить только суть"""
        # Убрать лишние символы
        title = re.sub(r'[«»""„]', '', title)
        title = re.sub(r'\s+', ' ', title).strip()
        
        # Ограничить длину
        if len(title) > 100:
            title = title[:97] + '...'
        
        return title


class Parser:
    def __init__(self):
        self.session = None
        self.posted_cache = set()
        self.extractor = EventExtractor()
    
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
            async with session.get(url, timeout=10) as resp:
                return await resp.text() if resp.status == 200 else ""
        except Exception as e:
            logger.error(f"Ошибка загрузки {url}: {e}")
            return ""
    
    async def parse_site(self, site: Dict) -> List[Dict]:
        html = await self.fetch(site['url'])
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        events = []
        
        keywords = ['стартап', 'startup', 'pitch', 'конференция', 'event', 'meetup', 'хакатон']
        stop = ['контакты', 'о нас', 'политика', 'токаев', 'министр']
        
        for link in soup.find_all('a', href=True)[:30]:
            try:
                href = link.get('href', '')
                title = link.get_text(strip=True)
                
                if not href or not title or len(title) < 15:
                    continue
                
                if any(s in title.lower() for s in stop):
                    continue
                
                if not any(k in title.lower() for k in keywords):
                    continue
                
                if not href.startswith('http'):
                    from urllib.parse import urljoin
                    href = urljoin(site['url'], href)
                
                if href in self.posted_cache:
                    continue
                
                # Извлечь детали
                parent = link.find_parent(['div', 'article'])
                context = parent.get_text() if parent else title
                
                location = self.extractor.extract_location(context)
                date = self.extractor.extract_date(context)
                time = self.extractor.extract_time(context)
                venue = self.extractor.extract_venue(context)
                
                # ФИЛЬТР: Пропускаем прошедшие события
                if date and not self.extractor.is_future_event(date):
                    logger.debug(f"Пропущено прошедшее событие: {title[:50]} ({date})")
                    continue
                
                # Найти ОДНО главное изображение
                image_url = None
                if parent:
                    img = parent.find('img', src=True)
                    if img:
                        image_url = img['src']
                        if not image_url.startswith('http'):
                            from urllib.parse import urljoin
                            image_url = urljoin(site['url'], image_url)
                
                events.append({
                    'source': site['name'],
                    'title': self.extractor.clean_title(title),
                    'link': href,
                    'location': location,
                    'date': date,
                    'time': time,
                    'venue': venue,
                    'image_url': image_url
                })
                
                if len(events) >= 2:
                    break
            except:
                continue
        
        return events
    
    async def parse_telegram(self, channel: Dict) -> List[Dict]:
        try:
            url = f"https://t.me/s/{channel['username']}"
            html = await self.fetch(url)
            if not html:
                return []
            
            soup = BeautifulSoup(html, 'html.parser')
            events = []
            cutoff_date = datetime.now() - timedelta(days=2)
            
            for msg in soup.find_all('div', class_='tgme_widget_message')[:10]:
                text_div = msg.find('div', class_='tgme_widget_message_text')
                if not text_div:
                    continue
                
                text = text_div.get_text(strip=True)
                if len(text) < 20:
                    continue
                
                # Проверка даты
                time_elem = msg.find('time')
                if time_elem:
                    try:
                        post_date_str = time_elem.get('datetime', '')
                        post_date = datetime.fromisoformat(post_date_str.replace('Z', '+00:00'))
                        if post_date < cutoff_date:
                            continue
                    except:
                        pass
                
                keywords = ['стартап', 'event', 'meetup', 'конференция', 'хакатон', 'pitch']
                if not any(k in text.lower() for k in keywords):
                    continue
                
                link_elem = msg.find('a', class_='tgme_widget_message_date')
                link = link_elem['href'] if link_elem else f"https://t.me/{channel['username']}"
                
                # Извлечь детали
                location = self.extractor.extract_location(text)
                date = self.extractor.extract_date(text)
                time = self.extractor.extract_time(text)
                venue = self.extractor.extract_venue(text)
                
                # ФИЛЬТР: Пропускаем прошедшие события
                if date and not self.extractor.is_future_event(date):
                    logger.debug(f"Пропущено прошедшее TG событие ({date})")
                    continue
                
                # ОДНО изображение
                image_url = None
                img_div = msg.find('a', class_='tgme_widget_message_photo_wrap')
                if img_div:
                    style = img_div.get('style', '')
                    img_match = re.search(r"url\('([^']+)'\)", style)
                    if img_match:
                        image_url = img_match.group(1)
                
                events.append({
                    'source': channel['name'],
                    'title': self.extractor.clean_title(text[:100]),
                    'link': link,
                    'location': location,
                    'date': date,
                    'time': time,
                    'venue': venue,
                    'image_url': image_url
                })
            
            return events
        except Exception as e:
            logger.error(f"Ошибка TG {channel['name']}: {e}")
            return []
    
    async def get_all_events(self) -> List[Dict]:
        all_events = []
        
        logger.info(f"🔍 Парсинг {len(URLS)} сайтов...")
        for site in URLS:
            events = await self.parse_site(site)
            all_events.extend(events)
            if events:
                logger.info(f"✅ {site['name']}: {len(events)} событий")
        
        logger.info(f"🔍 Парсинг {len(TELEGRAM_CHANNELS)} Telegram каналов...")
        for channel in TELEGRAM_CHANNELS:
            events = await self.parse_telegram(channel)
            all_events.extend(events)
            if events:
                logger.info(f"✅ TG {channel['name']}: {len(events)} событий")
        
        logger.info(f"📊 Всего: {len(all_events)} событий")
        return all_events


def format_event_post(event: Dict) -> str:
    """Форматировать пост в красивом виде"""
    
    # Заголовок
    post = f"🎯 <b>{event['title']}</b>\n\n"
    
    # Детали события (4-5 строк)
    details = []
    
    if event.get('location'):
        country = "Kazakhstan" if event['location'] not in ['Онлайн', 'Online'] else ""
        location_str = f"📍 {event['location']}"
        if country:
            location_str += f", {country}"
        details.append(location_str)
    
    if event.get('date'):
        date_str = f"📅 {event['date']}"
        if event.get('time'):
            date_str += f", {event['time']}"
        details.append(date_str)
    
    if event.get('venue'):
        details.append(f"🏢 {event['venue']}")
    
    # Источник
    details.append(f"📰 {event['source']}")
    
    post += "\n".join(details)
    
    # Ссылка
    post += f"\n\n🔗 <a href='{event['link']}'>Подробнее</a>"
    
    return post


async def main():
    logger.info("🚀 Старт публикации...")
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не установлен!")
        return
    
    parser = Parser()
    bot = Bot(token=BOT_TOKEN)
    
    try:
        events = await parser.get_all_events()
        
        if not events:
            logger.warning("⚠️ Событий не найдено")
            return
        
        # Удаляем дубликаты
        unique_events = []
        seen_links = set()
        for event in events:
            if event['link'] not in seen_links:
                unique_events.append(event)
                seen_links.add(event['link'])
        
        logger.info(f"📊 Уникальных событий: {len(unique_events)}")
        
        posted = 0
        for event in unique_events[:10]:
            try:
                text = format_event_post(event)
                
                # Если есть фото - отправляем с фото
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
                        # Если фото не загрузилось - без фото
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
                
                parser.posted_cache.add(event['link'])
                posted += 1
                logger.info(f"✅ Опубликовано ({posted}): {event['title'][:40]}")
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"❌ Ошибка: {e}")
        
        logger.info(f"✅ Готово! Опубликовано: {posted}")
        
    finally:
        await parser.close()


if __name__ == '__main__':
    asyncio.run(main())
