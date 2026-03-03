import asyncio
import logging
from datetime import datetime, time
from typing import List, Dict
import aiohttp
from bs4 import BeautifulSoup
from telegram import Update, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== НАСТРОЙКИ - ИЗМЕНИТЕ ЗДЕСЬ ==========
BOT_TOKEN = "8587519643:AAG-cWoQEV96ABp_dTIR5jDZyjbqjuUxewY"
CHANNEL_ID = "@startup_events_kz"

# Время публикации (по UTC)
MORNING_TIME = time(hour=4, minute=0)   # 09:00 Алматы
EVENING_TIME = time(hour=13, minute=0)  # 18:00 Алматы
#hour=18, #23:00
# ================================================

# Все сайты для парсинга
URLS = [
    # Новостные и бизнес-порталы
    {"url": "https://astanahub.com/ru/event/", "name": "Astana Hub", "type": "events"},
    {"url": "https://er10.kz", "name": "ER10.kz", "type": "news"},
    {"url": "https://kapital.kz", "name": "Kapital.kz", "type": "news"},
    {"url": "https://forbes.kz", "name": "Forbes.kz", "type": "news"},
    {"url": "https://kz.kursiv.media", "name": "Kursiv.media", "type": "news"},
    
    # Венчурные фонды и акселераторы
    {"url": "https://ma7.vc", "name": "MA7.vc", "type": "venture"},
    {"url": "https://tumarventures.com", "name": "Tumar Ventures", "type": "venture"},
    {"url": "https://whitehillcapital.io", "name": "White Hill Capital", "type": "venture"},
    {"url": "https://bigsky.vc", "name": "Big Sky Ventures", "type": "venture"},
    {"url": "https://mostfund.vc", "name": "MOST Fund", "type": "venture"},
    
    # Венчурные компании
    {"url": "https://axiomcapital.com", "name": "Axiom Capital", "type": "venture"},
    {"url": "https://jastarventures.com", "name": "Jastar Ventures", "type": "venture"},
    
    # Университеты
    {"url": "https://nuris.nu.edu.kz", "name": "NURIS", "type": "university"},
]

# Telegram каналы для парсинга
TELEGRAM_CHANNELS = [
    # Основные стартап-каналы Казахстана
    {"username": "startup_course_com", "name": "Startup Course"},  # С фото
    {"username": "astanahub_events", "name": "Astana Hub Events"},
    {"username": "digitalbusinesskz", "name": "Digital Business KZ"},
    {"username": "vcinsightskz", "name": "VC Insights KZ"},
    
    # Стартап-сообщества
    {"username": "startupalmaty", "name": "Startup Almaty"},
    {"username": "tech_kz", "name": "Tech Kazakhstan"},
    {"username": "startups_kz", "name": "Startups KZ"},
    {"username": "kazakhstartups", "name": "Kazakhstan Startups"},
    
    # Бизнес и инновации
    {"username": "innovation_kz", "name": "Innovation KZ"},
    {"username": "business_kz_official", "name": "Business KZ"},
    {"username": "qazaqstartup", "name": "Qazaq Startup"},
    
    # Венчур и инвестиции
    {"username": "venture_kz", "name": "Venture Kazakhstan"},
    {"username": "investkz", "name": "Invest Kazakhstan"},
    
    # IT и технологии
    {"username": "it_kz_official", "name": "IT Kazakhstan"},
    {"username": "devkz", "name": "Dev KZ"},
]


class UniversalParser:
    """Универсальный парсер для всех источников"""
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.session = None
        self.posted_events = set()
        
        # Ключевые слова для поиска событий
        self.event_keywords = [
            # Русские
            'мероприятие', 'событие', 'конференция', 'форум', 'встреча',
            'стартап', 'презентация', 'выставка', 'воркшоп', 'workshop',
            'pitch', 'demo day', 'хакатон', 'hackathon', 'meetup', 'митап',
            'акселератор', 'инвестиц', 'венчур', 'startup', 'конкурс',
            'семинар', 'вебинар', 'тренинг', 'обучение', 'курс',
            # English
            'event', 'conference', 'forum', 'meeting', 'pitch', 'demo',
            'hackathon', 'competition', 'accelerator', 'investment',
            'networking', 'summit', 'workshop', 'webinar', 'training'
        ]
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self.headers)
        return self.session
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def fetch_url(self, url: str) -> str:
        try:
            session = await self.get_session()
            async with session.get(url, timeout=15) as response:
                if response.status == 200:
                    return await response.text()
                return ""
        except Exception as e:
            logger.error(f"Ошибка при загрузке {url}: {e}")
            return ""
    
    async def extract_image_from_page(self, url: str, soup: BeautifulSoup) -> str:
        """Извлекает первое релевантное изображение со страницы"""
        try:
            # Ищем Open Graph изображение
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                img_url = og_image['content']
                if not img_url.startswith('http'):
                    from urllib.parse import urljoin
                    img_url = urljoin(url, img_url)
                return img_url
            
            # Ищем изображения в контенте
            images = soup.find_all('img', src=True)
            for img in images:
                src = img.get('src', '')
                
                # Пропускаем иконки, логотипы, маленькие изображения
                if any(skip in src.lower() for skip in ['icon', 'logo', 'avatar', 'emoji']):
                    continue
                
                # Проверяем размеры если указаны
                width = img.get('width')
                height = img.get('height')
                if width and height:
                    try:
                        if int(width) < 200 or int(height) < 200:
                            continue
                    except:
                        pass
                
                if not src.startswith('http'):
                    from urllib.parse import urljoin
                    src = urljoin(url, src)
                
                return src
            
        except Exception as e:
            logger.debug(f"Ошибка извлечения изображения: {e}")
        
        return None
    
    async def parse_astana_hub(self, site: Dict) -> List[Dict]:
        """Специальный парсер для Astana Hub"""
        html = await self.fetch_url(site['url'])
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        events = []
        
        event_links = soup.find_all('a', href=lambda x: x and '/ru/event/' in x and x != '/ru/event/')
        seen_titles = set()
        
        for link_elem in event_links[:5]:
            try:
                link = link_elem.get('href', '')
                if not link or link == '/ru/event/':
                    continue
                
                if not link.startswith('http'):
                    link = 'https://astanahub.com' + link
                
                title_elem = link_elem.find(['h3', 'h2', 'h4', 'div'])
                title = title_elem.get_text(strip=True) if title_elem else link_elem.get_text(strip=True)
                
                if not title or len(title) < 10 or title in seen_titles:
                    continue
                
                seen_titles.add(title)
                
                date = "Дата уточняется"
                parent = link_elem.find_parent()
                if parent:
                    import re
                    date_text = parent.get_text()
                    date_match = re.search(r'(\d{1,2}\s+[А-Яа-я]+,?\s+\d{2}:\d{2})', date_text)
                    if date_match:
                        date = date_match.group(1)
                
                location = "Онлайн"
                if parent:
                    location_match = re.search(r'(Алматы|Астана|Петропавловск|Шымкент|Онлайн)', parent.get_text())
                    if location_match:
                        location = location_match.group(1)
                
                # Ищем изображение
                image_url = None
                img_elem = link_elem.find('img', src=True) or (parent.find('img', src=True) if parent else None)
                if img_elem:
                    image_url = img_elem['src']
                    if not image_url.startswith('http'):
                        image_url = 'https://astanahub.com' + image_url
                
                events.append({
                    'title': title[:200],
                    'date': date,
                    'location': location,
                    'link': link,
                    'source': site['name'],
                    'description': 'Мероприятие в технопарке',
                    'image_url': image_url
                })
                
            except Exception as e:
                continue
        
        return events
    
    async def parse_generic_site(self, site: Dict) -> List[Dict]:
        """Универсальный парсер для любого сайта"""
        html = await self.fetch_url(site['url'])
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        events = []
        
        # СТРОГАЯ ФИЛЬТРАЦИЯ - стоп-слова (то что точно НЕ является событием/стартапом)
        stop_words = [
            # Навигация и служебные страницы
            'портфолио', 'portfolio', 'investment portfolio',
            'о нас', 'about', 'контакты', 'contact',
            'главная', 'home', 'команда', 'team', 'политика', 'privacy', 'terms',
            'использование материалов', 'соглашение', 'agreement', 'copyright',
            'подписка', 'subscription', 'login', 'sign in', 'регистрация',
            
            # Финансы и биржи (не события)
            'курс', 'доллар', 'тенге', 'валют', 'биржа', 'цена', 'котировки',
            'exchange rate', 'currency', 'акции компаний', 'индекс',
            
            # Политика и госновости (не стартапы)
            'безопасность онлайн', 'платежей', 'токаев', 'назарбаев',
            'правительство', 'министр', 'депутат', 'парламент',
            'қазақ тілі', 'на казахском', 'погода', 'спорт',
            'посол', 'ambassador', 'торговля',
            
            # Шаблонные элементы
            'research', 'исследование', 'see all', 'смотреть все',
            'все новости', 'читать далее', 'подробнее', 'архив',
            'лента новостей', 'экономика', 'финансы', 'государство'
        ]
        
        # Ищем все ссылки на странице
        all_links = soup.find_all('a', href=True)
        
        for link_elem in all_links[:100]:  # Увеличил до 100
            try:
                href = link_elem.get('href', '')
                
                # ВАЖНО: Пропускаем ссылки на главную страницу
                if not href or href in ['/', '#', 'javascript:void(0)', 'javascript:']:
                    continue
                
                # Пропускаем навигационные ссылки
                if any(nav in href.lower() for nav in ['/about', '/contact', '/team', '/portfolio', '#']):
                    continue
                
                # Формируем полную ссылку
                if not href.startswith('http'):
                    from urllib.parse import urljoin
                    href = urljoin(site['url'], href)
                
                # Пропускаем если это та же главная страница
                base_domain = site['url'].rstrip('/')
                if href.rstrip('/') == base_domain:
                    continue
                
                # Получаем текст ссылки
                title = link_elem.get_text(strip=True)
                
                # Если текст короткий, ищем в родителе
                if not title or len(title) < 20:
                    parent = link_elem.find_parent(['article', 'div', 'h1', 'h2', 'h3'])
                    if parent:
                        title = parent.get_text(strip=True)
                
                # Пропускаем пустые и очень короткие
                if not title or len(title) < 15:
                    continue
                
                # Пропускаем стоп-слова
                title_lower = title.lower()
                if any(stop in title_lower for stop in stop_words):
                    continue
                
                # Дополнительная проверка на мусорные заголовки
                garbage_patterns = [
                    'лента новостей', 'экономика', 'финансы', 'токаев', 'посол',
                    'қазақ тілі', 'безопасность', 'соглашение', 'материалов',
                    'министр', 'правительство', 'парламент', 'депутат',
                    'погода', 'спорт', 'курс валют', 'биржа'
                ]
                
                if any(garbage in title_lower for garbage in garbage_patterns):
                    continue
                
                # Ищем контекст вокруг ссылки
                parent = link_elem.find_parent(['div', 'article', 'section'])
                parent_text = parent.get_text(strip=True).lower() if parent else ""
                combined_text = title_lower + " " + parent_text
                
                # СТРОГАЯ ФИЛЬТРАЦИЯ - проверяем наличие СТАРТАП/СОБЫТИЙНЫХ ключевых слов
                startup_keywords = [
                    'стартап', 'startup', 'стартапер', 'предприниматель', 'entrepreneur',
                    'pitch', 'питч', 'demo day', 'демо день', 'хакатон', 'hackathon',
                    'акселератор', 'accelerator', 'инкубатор', 'incubator',
                    'инвестиц', 'investment', 'венчур', 'venture', 'фонд', 'fund',
                    'бизнес-ангел', 'angel investor', 'раунд', 'funding round'
                ]
                
                event_keywords = [
                    'мероприятие', 'событие', 'event', 
                    'конференция', 'conference', 'форум', 'forum', 'summit', 'саммит',
                    'встреча', 'встречи', 'meeting', 'networking', 'нетворкинг',
                    'workshop', 'воркшоп', 'мастер-класс', 'masterclass',
                    'meetup', 'митап', 'meetup', 
                    'конкурс', 'competition', 'contest',
                    'семинар', 'seminar', 'webinar', 'вебинар', 
                    'тренинг', 'training', 'обучение', 'bootcamp', 'буткемп'
                ]
                
                # Должно быть хотя бы одно ключевое слово из стартап ИЛИ событий
                has_startup_keyword = any(keyword in combined_text for keyword in startup_keywords)
                has_event_keyword = any(keyword in combined_text for keyword in event_keywords)
                
                if not (has_startup_keyword or has_event_keyword):
                    continue
                
                # Проверяем что это прямая ссылка на статью/событие (не главная)
                # Обычно у статей есть ID, slug или дата в URL
                import re
                is_article_link = any([
                    re.search(r'/\d+/', href),  # Есть число в URL (ID)
                    re.search(r'/20\d{2}/', href),  # Есть год
                    len(href.split('/')) > 4,  # Глубокая вложенность
                    re.search(r'/[a-z]+-[a-z]+', href),  # Slug с дефисами
                ])
                
                if not is_article_link:
                    continue
                
                # Проверяем дубликаты
                if any(e['link'] == href for e in events):
                    continue
                
                # Ищем дату
                date = datetime.now().strftime("%d.%m.%Y")
                date_patterns = [
                    r'(\d{1,2}\s+[А-Яа-я]+,?\s+\d{2}:\d{2})',
                    r'(\d{1,2}\s+[А-Яа-я]+\s+\d{4})',
                    r'(\d{2}\.\d{2}\.\d{4})',
                    r'(\d{4}-\d{2}-\d{2})'
                ]
                
                for pattern in date_patterns:
                    date_match = re.search(pattern, combined_text)
                    if date_match:
                        date = date_match.group(1)
                        break
                
                # Определяем место проведения
                location = "Онлайн"
                location_match = re.search(
                    r'(Алматы|Астана|Петропавловск|Шымкент|Караганда|Актобе|Тараз|Онлайн|Online)',
                    combined_text
                )
                if location_match:
                    location = location_match.group(1)
                
                # Ищем изображение
                image_url = None
                img_elem = link_elem.find('img', src=True)
                if not img_elem and parent:
                    img_elem = parent.find('img', src=True)
                
                if img_elem:
                    image_url = img_elem['src']
                    if not image_url.startswith('http'):
                        from urllib.parse import urljoin
                        image_url = urljoin(site['url'], image_url)
                
                # Создаем краткое описание из заголовка
                description = title[:150] + '...' if len(title) > 150 else title
                
                events.append({
                    'title': title[:200],
                    'date': date,
                    'location': location,
                    'link': href,
                    'source': site['name'],
                    'description': description,
                    'image_url': image_url
                })
                
                # Ограничиваем до 3 событий с одного сайта
                if len(events) >= 3:
                    break
                    
            except Exception as e:
                continue
        
        return events
    
    async def parse_telegram_channel(self, channel: Dict, context: ContextTypes.DEFAULT_TYPE) -> List[Dict]:
        """Парсинг Telegram канала"""
        try:
            events = []
            username = channel['username']
            
            # Получаем последние сообщения из канала (максимум 10)
            try:
                # Пытаемся получить информацию о канале
                chat = await context.bot.get_chat(f"@{username}")
                
                # Телеграм API не позволяет читать историю чужих каналов напрямую через бота
                # Но мы можем использовать публичный preview
                logger.info(f"✅ Канал @{username} найден: {chat.title}")
                
                # АЛЬТЕРНАТИВА: парсим через t.me preview
                preview_url = f"https://t.me/s/{username}"
                html = await self.fetch_url(preview_url)
                
                if not html:
                    return []
                
                soup = BeautifulSoup(html, 'html.parser')
                
                # Ищем посты в канале
                messages = soup.find_all('div', class_='tgme_widget_message')
                
                for msg in messages[:10]:  # Последние 10 постов
                    try:
                        # Получаем текст сообщения
                        text_div = msg.find('div', class_='tgme_widget_message_text')
                        if not text_div:
                            continue
                        
                        text = text_div.get_text(strip=True)
                        
                        if not text or len(text) < 20:
                            continue
                        
                        # Проверяем на стартап/событийные ключевые слова
                        text_lower = text.lower()
                        
                        startup_keywords = [
                            'стартап', 'startup', 'pitch', 'demo day', 'хакатон', 'hackathon',
                            'акселератор', 'accelerator', 'инвестиц', 'investment', 'венчур', 'venture'
                        ]
                        
                        event_keywords = [
                            'мероприятие', 'событие', 'event', 'конференция', 'conference',
                            'форум', 'forum', 'встреча', 'meeting', 'workshop', 'воркшоп',
                            'meetup', 'митап', 'семинар', 'webinar', 'вебинар'
                        ]
                        
                        has_startup = any(kw in text_lower for kw in startup_keywords)
                        has_event = any(kw in text_lower for kw in event_keywords)
                        
                        if not (has_startup or has_event):
                            continue
                        
                        # Получаем ссылку на пост
                        link_elem = msg.find('a', class_='tgme_widget_message_date')
                        post_link = link_elem['href'] if link_elem else f"https://t.me/{username}"
                        
                        # Ищем дату
                        date_elem = msg.find('time')
                        date = date_elem.get('datetime', datetime.now().strftime("%Y-%m-%d")) if date_elem else datetime.now().strftime("%Y-%m-%d")
                        
                        # Форматируем дату
                        try:
                            from datetime import datetime as dt
                            date_obj = dt.fromisoformat(date.replace('Z', '+00:00'))
                            date = date_obj.strftime("%d.%m.%Y")
                        except:
                            date = datetime.now().strftime("%d.%m.%Y")
                        
                        # Ищем изображение
                        image_url = None
                        img_div = msg.find('a', class_='tgme_widget_message_photo_wrap')
                        if img_div:
                            style = img_div.get('style', '')
                            import re
                            img_match = re.search(r"url\('([^']+)'\)", style)
                            if img_match:
                                image_url = img_match.group(1)
                        
                        # Создаем краткое описание
                        description = text[:150] + '...' if len(text) > 150 else text
                        
                        events.append({
                            'title': text[:100],
                            'date': date,
                            'location': 'Telegram',
                            'link': post_link,
                            'source': channel['name'],
                            'description': description,
                            'image_url': image_url
                        })
                        
                    except Exception as e:
                        logger.debug(f"Ошибка обработки поста: {e}")
                        continue
                
                return events
                
            except Exception as e:
                logger.warning(f"⚠️ Не удалось получить @{username}: {e}")
                return []
                
        except Exception as e:
            logger.error(f"Ошибка парсинга Telegram канала {channel['name']}: {e}")
            return []
    
    async def parse_site(self, site: Dict, context: ContextTypes.DEFAULT_TYPE = None) -> List[Dict]:
        """Парсинг конкретного сайта"""
        try:
            # Специальный парсер для Astana Hub
            if 'astanahub.com' in site['url']:
                return await self.parse_astana_hub(site)
            
            # Универсальный парсер для всех остальных
            return await self.parse_generic_site(site)
            
        except Exception as e:
            logger.error(f"Ошибка парсинга {site['name']}: {e}")
            return []
    
    async def get_all_events(self, context: ContextTypes.DEFAULT_TYPE = None) -> List[Dict]:
        """Собрать события со всех источников"""
        all_events = []
        
        total_sources = len(URLS) + len(TELEGRAM_CHANNELS)
        logger.info(f"🔍 Начинаю парсинг {total_sources} источников ({len(URLS)} сайтов + {len(TELEGRAM_CHANNELS)} Telegram каналов)...")
        
        # Парсим все сайты параллельно
        tasks = [self.parse_site(site, context) for site in URLS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            site_name = URLS[i]['name']
            if isinstance(result, Exception):
                logger.error(f"❌ {site_name}: Ошибка - {result}")
            else:
                all_events.extend(result)
                if result:
                    logger.info(f"✅ {site_name}: найдено {len(result)} событий")
                else:
                    logger.info(f"⚠️ {site_name}: событий не найдено")
        
        # Парсим Telegram каналы
        if context and TELEGRAM_CHANNELS:
            tg_tasks = [self.parse_telegram_channel(channel, context) for channel in TELEGRAM_CHANNELS]
            tg_results = await asyncio.gather(*tg_tasks, return_exceptions=True)
            
            for i, result in enumerate(tg_results):
                channel_name = TELEGRAM_CHANNELS[i]['name']
                if isinstance(result, Exception):
                    logger.error(f"❌ TG {channel_name}: Ошибка - {result}")
                else:
                    all_events.extend(result)
                    if result:
                        logger.info(f"✅ TG {channel_name}: найдено {len(result)} событий")
                    else:
                        logger.info(f"⚠️ TG {channel_name}: событий не найдено")
        
        logger.info(f"📊 Всего найдено: {len(all_events)} событий из {total_sources} источников")
        
        return all_events


parser = UniversalParser()


async def post_to_channel(context: ContextTypes.DEFAULT_TYPE):
    """Автоматическая публикация в канал"""
    logger.info("📢 Начинаю публикацию событий в канал...")
    
    try:
        events = await parser.get_all_events(context)
        
        if not events:
            logger.warning("⚠️ Не найдено событий для публикации")
            return
        
        posted_count = 0
        for event in events[:20]:  # Максимум 20 событий за раз
            event_id = f"{event['title']}_{event['source']}"
            
            if event_id in parser.posted_events:
                logger.info(f"⏭️ Пропускаю: {event['title'][:40]}...")
                continue
            
            # Формируем текст как на скриншоте
            caption = f"<b>{event['source']}</b>\n\n"
            caption += f"{event['description']}\n\n"
            caption += f"{event['link']}"
            
            try:
                # Если есть изображение - отправляем с фото
                if event.get('image_url'):
                    await context.bot.send_photo(
                        chat_id=CHANNEL_ID,
                        photo=event['image_url'],
                        caption=caption,
                        parse_mode='HTML'
                    )
                else:
                    # Если нет изображения - просто текст
                    await context.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=caption,
                        parse_mode='HTML',
                        disable_web_page_preview=False
                    )
                
                parser.posted_events.add(event_id)
                posted_count += 1
                logger.info(f"✅ Опубликовано ({posted_count}): {event['title'][:40]}...")
                
                await asyncio.sleep(3)  # Задержка между постами
                
            except Exception as e:
                logger.error(f"❌ Ошибка публикации: {e}")
                # Если не получилось с картинкой, пробуем без неё
                try:
                    await context.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=caption,
                        parse_mode='HTML',
                        disable_web_page_preview=False
                    )
                    parser.posted_events.add(event_id)
                    posted_count += 1
                except:
                    pass
        
        if len(parser.posted_events) > 200:
            parser.posted_events = set(list(parser.posted_events)[-100:])
        
        logger.info(f"✅ Публикация завершена! Опубликовано: {posted_count} событий")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в post_to_channel: {e}")


async def manual_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручная публикация (команда /post)"""
    await update.message.reply_text("🔄 Начинаю публикацию событий...")
    await post_to_channel(context)
    await update.message.reply_text("✅ Публикация завершена!")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    message = f"""
🤖 <b>Универсальный бот для публикации событий</b>

Я автоматически публикую мероприятия в канал {CHANNEL_ID}

📋 <b>Источники:</b>
🌐 Сайтов: {len(URLS)}
• Astana Hub, ER10.kz, Kapital.kz, Forbes.kz
• MA7.vc, Tumar Ventures, White Hill Capital
• Big Sky, MOST Fund, Axiom Capital, Jastar Ventures
• NURIS и другие

📱 Telegram каналов: {len(TELEGRAM_CHANNELS)}
• Astana Hub Events, Digital Business KZ
• Startup Almaty, VC Insights KZ и другие

⏰ <b>Расписание:</b>
• Утром в 08:00 (Алматы)
• Вечером в 17:00 (Алматы)

<b>Команды:</b>
/post - Ручная публикация
/status - Статус бота
    """
    
    await update.message.reply_text(message, parse_mode='HTML')


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статус бота"""
    status_msg = f"""
📊 <b>Статус бота</b>

✅ Бот работает
📝 Опубликовано событий: {len(parser.posted_events)}
📢 Канал: {CHANNEL_ID}
🌐 Сайтов: {len(URLS)}
📱 Telegram каналов: {len(TELEGRAM_CHANNELS)}

⏰ Следующая публикация:
• Утром в 08:00 (Алматы)
• Вечером в 17:00 (Алматы)
    """
    
    await update.message.reply_text(status_msg, parse_mode='HTML')


def main():
    """Запуск бота"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("post", manual_post))
    application.add_handler(CommandHandler("status", status))
    
    try:
        if application.job_queue is not None:
            application.job_queue.run_daily(
                post_to_channel,
                time=MORNING_TIME,
                name='morning_post'
            )
            
            application.job_queue.run_daily(
                post_to_channel,
                time=EVENING_TIME,
                name='evening_post'
            )
            
            logger.info("🚀 Универсальный бот запущен!")
            logger.info(f"📢 Канал: {CHANNEL_ID}")
            logger.info(f"🌐 Парсинг {len(URLS)} сайтов + {len(TELEGRAM_CHANNELS)} Telegram каналов")
            logger.info(f"⏰ Публикации: 08:00 и 17:00 (Алматы)")
        else:
            logger.warning("⚠️ JobQueue не доступен")
            logger.info("🚀 Бот запущен в РУЧНОМ режиме")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    try:
        main()
    finally:
        asyncio.run(parser.close())