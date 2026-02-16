import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import aiohttp
from bs4 import BeautifulSoup
from telegram import Bot

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Настройки
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID', "@vc_supergroup")
MESSAGE_THREAD_ID = int(os.getenv('MESSAGE_THREAD_ID', '4'))  # Топик "Анонсы мероприятий"

# Источники
URLS = [
    # Новостные порталы
    {"url": "https://astanahub.com/ru/event/", "name": "Astana Hub"},
    {"url": "https://er10.kz", "name": "ER10"},
    {"url": "https://kapital.kz", "name": "Capital"},
    {"url": "https://forbes.kz", "name": "Forbes kz"},
    {"url": "https://kz.kursiv.media", "name": "Kursiv kz"},
    
    # Венчурные фонды
    {"url": "https://ma7.vc", "name": "MA7"},
    {"url": "https://tumarventures.com", "name": "Tumar ventures"},
    {"url": "https://whitehillcapital.io", "name": "White hill capital"},
    {"url": "https://bigsky.vc", "name": "Big sky ventures"},
    {"url": "https://mostfund.vc", "name": "Most ventures"},
    {"url": "https://axiomcapital.com", "name": "Axiom capital"},
    {"url": "https://jastarventures.com", "name": "Jas ventures"},
    
    # Университеты
    {"url": "https://nuris.nu.edu.kz", "name": "NURIS"},
    
    # Big Tech / Дополнительные
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


class Parser:
    def __init__(self):
        self.session = None
        self.posted_cache = set()  # Кэш опубликованных ссылок
    
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
        
        keywords = ['стартап', 'startup', 'pitch', 'конференция', 'event', 'meetup']
        stop = ['контакты', 'о нас', 'политика']
        
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
                
                # Пропускаем если уже публиковали
                if href in self.posted_cache:
                    continue
                
                events.append({
                    'source': site['name'],
                    'description': title[:150],
                    'link': href
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
            
            # Только посты за последние 2 дня
            cutoff_date = datetime.now() - timedelta(days=2)
            
            for msg in soup.find_all('div', class_='tgme_widget_message')[:10]:
                text_div = msg.find('div', class_='tgme_widget_message_text')
                if not text_div:
                    continue
                
                text = text_div.get_text(strip=True)
                if len(text) < 20:
                    continue
                
                # Проверяем дату поста
                time_elem = msg.find('time')
                if time_elem:
                    try:
                        post_date_str = time_elem.get('datetime', '')
                        post_date = datetime.fromisoformat(post_date_str.replace('Z', '+00:00'))
                        
                        # Пропускаем старые посты
                        if post_date < cutoff_date:
                            continue
                    except:
                        pass
                
                keywords = ['стартап', 'event', 'meetup', 'конференция', 'хакатон', 'pitch']
                if not any(k in text.lower() for k in keywords):
                    continue
                
                link_elem = msg.find('a', class_='tgme_widget_message_date')
                link = link_elem['href'] if link_elem else f"https://t.me/{channel['username']}"
                
                events.append({
                    'source': channel['name'],
                    'description': text[:150],
                    'link': link
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
        
        # Удаляем дубликаты по ссылке
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
                text = f"<b>{event['source']}</b>\n\n{event['description']}\n\n{event['link']}"
                
                await bot.send_message(
                    chat_id=CHANNEL_ID,
                    message_thread_id=MESSAGE_THREAD_ID,  # Публикуем в топик
                    text=text,
                    parse_mode='HTML',
                    disable_web_page_preview=False
                )
                
                parser.posted_cache.add(event['link'])
                posted += 1
                logger.info(f"✅ Опубликовано ({posted})")
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"❌ Ошибка: {e}")
        
        logger.info(f"✅ Готово! Опубликовано: {posted}")
        
    finally:
        await parser.close()


if __name__ == '__main__':
    asyncio.run(main())
