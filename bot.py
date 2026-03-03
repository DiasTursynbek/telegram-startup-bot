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





STATE_DIR = Path("state")
POSTED_FILE = STATE_DIR / "load_posted.json"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "-1003812789640")
MESSAGE_THREAD_ID = int(os.getenv("MESSAGE_THREAD_ID", "4"))

def strip_intro_phrases(text: str) -> str:
    patterns = [
        r"^в\s+(понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)\s+",
        r"^кажд(ую|ый|ое)?\s+(понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)\s+",
        r"^в\s+\w+\s+",  
        r"^приглашаем\s+",
        r"^состоится\s+",
        r"^будет\s+",
    ]
    s = text.strip()
    for p in patterns:
        s = re.sub(p, "", s, flags=re.IGNORECASE)
    return s.strip(" -–•,")

def remove_city_from_title(title: str) -> str:
    # Проходим по всем городам из словаря
    emoji_pattern = r"[\U00010000-\U0010ffff\u2600-\u27ff\u2300-\u23ff\u25a0-\u25ff\u2B00-\u2BFF]"
    for city_key in KZ_CITIES.keys():
        # Регулярка ищет город в начале строки или как отдельное слово, игнорируя регистр
        # (?:{emoji_pattern}|\W)* позволяет найти город сразу после эмодзи в начале
        title = re.sub(rf"^(?:{emoji_pattern}|\W)*{city_key}\b", "", title, flags=re.IGNORECASE)
        title = re.sub(rf"\b{city_key}\b", "", title, flags=re.IGNORECASE)
        
    # Чистим двойные пробелы и висячие знаки препинания, которые остались после удаления
    title = re.sub(r"\s{2,}", " ", title)
    title = re.sub(r"^[,\-\s•:!]+", "", title) 
    return title.strip(" -–•:,!")

def fix_glued_words(text: str) -> str:
    # 🔥 УНИВЕРСАЛЬНО: Отклеиваем ЛЮБОЕ время от ЛЮБЫХ букв с обеих сторон (16:00Костанай -> 16:00 Костанай)
    text = re.sub(r'(\d{1,2}:\d{2})([А-Яа-яЁёA-Za-z])', r'\1 \2', text)
    text = re.sub(r'([А-Яа-яЁёA-Za-z])(\d{1,2}:\d{2})', r'\1 \2', text)
    
    # Отклеиваем знаки препинания (100!в -> 100! в)
    text = re.sub(r'([!?,.])([А-Яа-яЁёA-Za-z])', r'\1 \2', text)
    
    # Расклеиваем языки и регистры (вQostanai, Hubпройдет)
    text = re.sub(r'([а-яёА-ЯЁ])([A-Za-z])', r'\1 \2', text)
    text = re.sub(r'([A-Za-z])([а-яёА-ЯЁ])', r'\1 \2', text)
    text = re.sub(r'([а-яё])([А-ЯЁ])', r'\1 \2', text)
    
    # Убираем двойные предлоги
    text = re.sub(r'\b(в|на|во)\s+\1\b', r'\1', text, flags=re.IGNORECASE)
    return text

def extract_city_from_title(title: str) -> Optional[str]:
    lower = title.lower()
    for key, value in KZ_CITIES.items():
        if key in lower:
            return value
    return None

def is_clean_photo(url: str) -> bool:
    url = url.lower()
    # 🔥 ИСПРАВЛЕНО: Убрали "thumbnail" из черного списка, так как Астана Хаб хранит там афиши!
    blacklist = [
        "icon", "logo", "avatar", "svg", "button", "background", "footer"
    ]
    return not any(word in url for word in blacklist)

def remove_weekday_from_start(text: str) -> str:
    lower = text.lower()
    for key in WEEK_DAYS.keys():
        if lower.startswith(key + " "):
            return text[len(key):].strip(" -–•, ")
        if lower.startswith("в " + key + " "):
            return text[len("в " + key):].strip(" -–•, ")
        if lower.startswith("каждую " + key + " "):
            return text[len("каждую " + key):].strip(" -–•, ")
    return text

def generate_universal_description(full_text: str, title: str) -> str:
    text = strip_emoji(full_text)
    text = normalize_glued_text(text)

    if title:
        text = re.sub(re.escape(title), "", text, flags=re.IGNORECASE)

    text = re.sub(r"http\S+", "", text)
    text = re.sub(r'\bв\s+в\b', 'в', text, flags=re.IGNORECASE)
    
    paragraphs = [p.strip() for p in text.split("\n") if len(p.strip()) > 50]

    for p in paragraphs:
        low = p.lower()
        if any(w in low for w in ["сохранить", "telegram", "facebook", "whatsapp", "подробнее", "регистрация"]):
            continue
        if any(x in low for x in ["ул.", "улица", "пр.", "проспект", "этаж", "офис", "конференц", "здание", "район", "останов"]):
            continue
        if re.search(r"\d{1,2}:\d{2}", p):
            continue
        if re.search(r"\d{1,2}\s+[а-яёА-ЯЁ]+", p):
            continue

        words = p.split()
        if len(words) > 12:  
            if len(words) > 40:
                return " ".join(words[:40]) + "..."
            return p
    return ""

def generate_fallback_description(title: str) -> str:
    t = title.lower()
    if "career" in t: return "Профориентационное мероприятие для школьников и студентов о выборе профессии и карьерных возможностях."
    if "movie" in t: return "Кино-встреча с обсуждением технологий и трендов в IT."
    if "ai" in t or "искусственный интеллект" in t: return "Мероприятие, посвящённое искусственному интеллекту и его применению в бизнесе и технологиях."
    if "meetup" in t: return "Неформальная встреча профессионалов для обмена опытом и нетворкинга."
    if "форум" in t or "conference" in t: return "Профессиональное событие с участием экспертов и обсуждением актуальных отраслевых тем."
    return "Профессиональное мероприятие для специалистов и предпринимателей."

def extract_program_block(full_text: str) -> str:
    text = strip_emoji(full_text)
    lines = text.split("\n")
    trigger_words = ["что тебя жд", "что вас жд", "в программе", "программа", "вы узнаете"]
    start_index = None

    for i, line in enumerate(lines):
        low = line.lower()
        if any(word in low for word in trigger_words):
            start_index = i
            break

    if start_index is None:
        return ""

    collected = []
    for line in lines[start_index + 1:]:
        clean = line.strip()
        if not clean:
            continue
        if any(x in clean.lower() for x in ["📍", "⏰", "http", "подробнее"]):
            break
        if re.search(r"\d{1,2}:\d{2}", clean):
            break
        if len(clean) < 5:
            continue
        collected.append(clean)
        if len(collected) >= 4:
            break

    if not collected:
        return ""

    result = "\n".join(collected)
    words = result.split()
    if len(words) > 40:
        result = " ".join(words[:40]) + "..."
    return result.strip()

def normalize_link(link: str) -> str:
    if not link: return ""
    link = link.strip()
    link = link.replace("https://t.me/s/", "https://t.me/")
    link = link.split("?")[0]
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

MONTHS_RU = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
MONTHS_SHORT = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}

EVENT_WORDS = [
    "конференция", "conference", "форум", "forum", "summit", "саммит", "meetup", "митап",
    "хакатон", "hackathon", "воркшоп", "workshop", "мастер-класс", "masterclass", "вебинар",
    "webinar", "семинар", "pitch", "питч", "demo day", "акселератор", "accelerator",
    "bootcamp", "буткемп", "выставка", "конкурс", "competition", "тренинг", "training",
    "мероприятие", "ивент", "event", "приглашает", "приглашаем", "зарегистрируйся", "регистрация"
]

NOT_EVENT_WORDS = [
    # ❌ Новости, сводки, политика
    "research", "исследование показало", "инвестировал", "привлек раунд", "млн $", "млрд $",
    "курс доллара", "биржа", "акции", "токаев", "правительство", "назначен", "уволен", "выручка",
    
    # ❌ Госорганы, налоги и бюрократия
    "госдоход", "занятости населения", "инспектор", "государственных", "госорган", 
    "акимат", "министерств", "налогов", "бухгалтер", "кадровой служб", "палат предпринимателей", 
    "атамекен", "госзакуп", "субсиди", "сельского хозяйств", "зко", "вко", "юко", "сқо",
    "пенсионн", "законопроект", "депутат", "маслихат", "мажилис", "налогообложен", "штраф", 
    "проверк", "инспекци", "сдача отчет", "информационно-разъяснительная",
    
    # ❌ Корпоративная душнота, compliance и регламенты
    "кдп", "персональным данным", "персональных данных", "регламент", "регулятор", 
    "комплаенс", "compliance", "требованиям регуляторов", "охрана труда", "техника безопасности",
    
    # ❌ Традиционный малый бизнес и бытуха
    "салон красоты", "маникюр", "повар", "кулинар", "швея", "ремонт", "сантехник",
    "детский сад", "утренник", "школьная ярмарка",
    
    # ❌ Базовое программирование и ML (не для фаундеров)
    "machine learning", "машинное обучение", "машинному обучению", "машинного обучения",
    "python", "javascript", "c++", "c#", "php", "golang", "ruby", "swift", "kotlin", "java",
    "html", "css", "фронтенд", "бэкенд", "frontend", "backend",
    "старт в программировании", "язык программирования", "языков программирования", 
    "научиться кодить", "стань разработчиком", "профессия тестировщик", "войти в it",
    "с нуля до", "обучение программированию", "базовый курс", "для начинающих разработчиков",
    
    # 🔥 НОВОЕ: Туториалы по нейросетям (как на скрине)
    "ai-инструмент", "ai-инструментами", "инструменты ai", "chatgpt", "midjourney", 
    "цифровой помощник", "создание презентаций", "для образования", "как использовать ai", 
    "как использовать нейросети", "нейросетей для", "нейросети для", "ai для работы", 
    "искусственный интеллект как"
]

SITE_STOP_WORDS = [
    "контакты", "о нас", "политика", "войти", "регистрация аккаунта", "подписаться",
    "поиск", "главная", "меню", "все новости", "читать далее", "подробнее", "узнать больше", "privacy", "terms", "cookie"
]

DESCRIPTION_SIGNALS = [
    "формат встречи", "выступление спикеров", "вы узнаете", "мы расскажем", "на мероприятии",
    "в рамках", "состоится встреча", "приглашаем вас", "зарегистрируйтесь", "подробнее по ссылке",
    "свободное общение", "приглашают вас принять участие", "готовы перейти", "поговорим о", "обсудим", "разберем" 
]

KZ_CITIES = {
    # Мегаполисы
    "алматы": "Алматы", "almaty": "Алматы",
    "астана": "Астана", "astana": "Астана", "nur-sultan": "Астана", "nursultan": "Астана", "нур-султан": "Астана", "ақмола": "Астана", "aqmola": "Астана", "целиноград": "Астана", "tselinograd": "Астана",
    "шымкент": "Шымкент", "shymkent": "Шымкент", "чимкент": "Шымкент", "chimkent": "Шымкент",

    # Областные центры и крупные города
    "караганда": "Караганда", "karaganda": "Караганда", "қарағанды": "Караганда", "qaraghandy": "Караганда", "qaragandi": "Караганда",
    "актобе": "Актобе", "aktobe": "Актобе", "ақтөбе": "Актобе", "aqtobe": "Актобе", "актюбинск": "Актобе", "aktyubinsk": "Актобе",
    "тараз": "Тараз", "taraz": "Тараз", "жамбыл": "Тараз", "zhambyl": "Тараз", "джамбул": "Тараз", "djambul": "Тараз", "jambul": "Тараз",
    "павлодар": "Павлодар", "pavlodar": "Павлодар",
    "усть-каменогорск": "Усть-Каменогорск", "ust-kamenogorsk": "Усть-Каменогорск", "өскемен": "Усть-Каменогорск", "oskemen": "Усть-Каменогорск", "ust-kamen": "Усть-Каменогорск",
    "семей": "Семей", "semey": "Семей", "semei": "Семей", "семипалатинск": "Семей", "semipalatinsk": "Семей",
    "атырау": "Атырау", "atyrau": "Атырау", "гурьев": "Атырау", "guriev": "Атырау",
    "костанай": "Костанай", "kostanay": "Костанай", "қостанай": "Костанай", "qostanai": "Костанай", "qostanay": "Костанай", "кустанай": "Костанай", "kustanai": "Костанай", "kustanay": "Костанай",
    "кызылорда": "Кызылорда", "kyzylorda": "Кызылорда", "қызылорда": "Кызылорда", "qyzylorda": "Кызылорда", "kzyil-orda": "Кызылорда",
    "уральск": "Уральск", "uralsk": "Уральск", "орал": "Уральск", "oral": "Уральск",
    "петропавловск": "Петропавловск", "petropavlovsk": "Петропавловск", "петропавл": "Петропавловск", "petropavl": "Петропавловск",
    "туркестан": "Туркестан", "turkestan": "Туркестан", "түркістан": "Туркестан", "turkistan": "Туркестан",
    "актау": "Актау", "aktau": "Актау", "ақтау": "Актау", "aqtau": "Актау", "шевченко": "Актау", "shevchenko": "Актау",
    "темиртау": "Темиртау", "temirtau": "Темиртау",
    "кокшетау": "Кокшетау", "kokshetau": "Кокшетау", "көкшетау": "Кокшетау", "qokshetau": "Кокшетау", "кокчетав": "Кокшетау", "kokchetav": "Кокшетау",
    "талдыкорган": "Талдыкорган", "taldykorgan": "Талдыкорган", "талдықорған": "Талдыкорган", "taldyqorgan": "Талдыкорган", "taldikorgan": "Талдыкорган",
    "экибастуз": "Экибастуз", "ekibastuz": "Экибастуз", "екібастұз": "Экибастуз",
    "рудный": "Рудный", "rudny": "Рудный", "rudniy": "Рудный", "rudnyi": "Рудный",
    "жанаозен": "Жанаозен", "zhanaozen": "Жанаозен", "жаңаөзен": "Жанаозен", "janaozen": "Жанаозен", "новый узень": "Жанаозен",
    "конаев": "Конаев", "konaev": "Конаев", "қонаев": "Конаев", "qonaev": "Конаев", "qonayev": "Конаев", "капчагай": "Конаев", "kapchagay": "Конаев", "қапшағай": "Конаев", "qapshaghay": "Конаев",
    "жезказган": "Жезказган", "zhezkazgan": "Жезказган", "жезқазған": "Жезказган", "jezqazgan": "Жезказган", "джезказган": "Жезказган", "dzhezkazgan": "Жезказган",
    "балхаш": "Балхаш", "balkhash": "Балхаш", "балқаш": "Балхаш", "balqash": "Балхаш",
    "сатпаев": "Сатпаев", "satpayev": "Сатпаев", "сәтбаев": "Сатпаев", "satbayev": "Сатпаев",
    "каскелен": "Каскелен", "kaskelen": "Каскелен", "қаскелең": "Каскелен", "qaskelen": "Каскелен",
    "кульсары": "Кульсары", "kulsary": "Кульсары", "құлсары": "Кульсары", "qulsary": "Кульсары",


    "онлайн": "Онлайн", "online": "Онлайн", "zoom": "Онлайн (Zoom)", "онлайн (zoom)": "Онлайн (Zoom)",
    "ташкент": "Ташкент, Узбекистан", "tashkent": "Ташкент, Узбекистан",
    "бишкек": "Бишкек, Кыргызстан", "bishkek": "Бишкек, Кыргызстан",
}

WEEK_DAYS = {
    "понедельник": "Понедельник", "понедельника": "Понедельник", "понедельнику": "Понедельник", "понедельником": "Понедельник", "monday": "Понедельник",
    "вторник": "Вторник", "вторника": "Вторник", "вторнику": "Вторник", "tuesday": "Вторник",
    "среда": "Среда", "среду": "Среда", "среды": "Среда", "среде": "Среда", "wednesday": "Среда",
    "четверг": "Четверг", "четверга": "Четверг", "четвергу": "Четверг", "thursday": "Четверг",
    "пятница": "Пятница", "пятницу": "Пятница", "пятницы": "Пятница", "пятнице": "Пятница", "friday": "Пятница",
    "суббота": "Суббота", "субботу": "Суббота", "субботы": "Суббота", "saturday": "Суббота",
    "воскресенье": "Воскресенье", "воскресенья": "Воскресенье", "воскресенью": "Воскресенье", "sunday": "Воскресенье",
}

EMOJI_RE = re.compile("[\U00010000-\U0010ffff\u2600-\u27ff\u2300-\u23ff\u25a0-\u25ff\u2B00-\u2BFF]", re.UNICODE)

def strip_emoji(s: str) -> str:
    return EMOJI_RE.sub("", s).strip()

def is_future(dt: Optional[datetime]) -> bool:
    if not dt: return False
    return dt.date() > datetime.now().date()

def parse_date(text: str) -> Optional[datetime]:
    t = text.lower()
    now = datetime.now()

    def make_dt(year, month, day):
        try: return datetime(year, month, day)
        except: return None

    m = re.search(r"(\d{1,2})[-](\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?", t)
    if m:
        month = MONTHS_RU.get(m.group(3), 0)
        year = int(m.group(4)) if m.group(4) else now.year
        if month: return make_dt(year, month, int(m.group(2)))

    m = re.search(r"(\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?", t)
    if m:
        month = MONTHS_RU.get(m.group(2), 0)
        if month:
            year = int(m.group(3)) if m.group(3) else now.year
            return make_dt(year, month, int(m.group(1)))

    m = re.search(r"(\d{1,2})\s+(янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)[а-я]*(?:\s+(\d{4}))?", t)
    if m:
        month = MONTHS_SHORT.get(m.group(2)[:3], 0)
        if month:
            year = int(m.group(3)) if m.group(3) else now.year
            return make_dt(year, month, int(m.group(1)))

    m = re.search(r"(\d{1,2})\.(\d{2})(?:\.(\d{4}))?", t)
    if m:
        month = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if 1 <= month <= 12: return make_dt(year, month, int(m.group(1)))

    return None

def format_date(dt: datetime, time_str: str = None) -> str:
    months = {1:"января", 2:"февраля", 3:"марта", 4:"апреля", 5:"мая", 6:"июня", 7:"июля", 8:"августа", 9:"сентября", 10:"октября", 11:"ноября", 12:"декабря"}
    
    # 🔥 УНИВЕРСАЛЬНО: Собираем формат "Год День Месяц"
    s = f"{dt.year} {dt.day} {months[dt.month]}"
    
    # Если парсер нашел время, приклеиваем его в конец через пробел
    return f"{s} {time_str}" if time_str else s

def extract_location(text: str) -> Optional[str]:
    t = text.lower()
    for key, value in KZ_CITIES.items():
        if key in t: return value
    return None

def extract_venue(text: str) -> Optional[str]:
    known = ["Narxoz", "Nazarbayev", "KBTU", "КБТУ", "Astana Hub", "IT Park", "MOST IT Hub", "Holiday Inn", "Esentai", "Yandex", "Smart Point", "Almaty Arena"]
    for v in known:
        if v.lower() in text.lower():
            m = re.search(rf"{re.escape(v)}[^\n,.]*", text, re.IGNORECASE)
            if m: return m.group(0).strip()[:60]
    at = re.search(r"@\s+([^@\n]+?)(?:\s+(?:https?://|t\.me/)|\s*$)", text)
    if at: return at.group(1).strip()[:60]
    return None

def is_real_event(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in EVENT_WORDS) and not any(w in t for w in NOT_EVENT_WORDS)

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
    s = re.sub(r"(\d{1,2}:\d{2})(?=[A-Za-zА-Яа-яЁё])", r"\1 ", s)
    s = re.sub(r"([а-яёА-ЯЁ]{3,}),(\d{1,2}:\d{2})", r"\1, \2", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s

def strip_leading_datetime_from_title(title: str) -> str:
    t = strip_emoji(title).strip()
    t = normalize_glued_text(t)
    
    # Сносим любое "одинокое" время в начале заголовка (например, "16:00 Идея может стоить...")
    t = re.sub(r"^\s*\d{1,2}:\d{2}\s*", "", t)
    
    # Сносим даты
    t = re.sub(r"^\s*\d{1,2}\s+[А-Яа-яЁёA-Za-z]{3,}[,]?\s+\d{1,2}:\d{2}\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*\d{1,2}\s+[а-яё]{3,}(?:\s+\d{4})?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*\d{1,2}\.\d{2}(?:\.\d{4})?\s*", "", t)
    
    return t.strip(" -–•.,").strip()

def remove_dates_and_times(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\b\d{1,2}:\d{2}(?:-\d{1,2}:\d{2})?(?:\s*[aApP][mM])?\b', '', text)
    text = re.sub(r'\b\d{1,2}(?:-[а-я]{1,2})?\s+(?:янв[а-я]*|фев[а-я]*|мар[а-я]*|апр[а-я]*|мая|май|июн[а-я]*|июл[а-я]*|авг[а-я]*|сен[а-я]*|окт[а-я]*|ноя[а-я]*|дек[а-я]*)\s*(?:,?\s*\d{4}(?:\s*г\.?)?)?\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(?:jan[a-z]*|feb[a-z]*|mar[a-z]*|apr[a-z]*|may|jun[a-z]*|jul[a-z]*|aug[a-z]*|sep[a-z]*|oct[a-z]*|nov[a-z]*|dec[a-z]*)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d{1,2}\s+(?:jan[a-z]*|feb[a-z]*|mar[a-z]*|apr[a-z]*|may|jun[a-z]*|jul[a-z]*|aug[a-z]*|sep[a-z]*|oct[a-z]*|nov[a-z]*|dec[a-z]*)\s*(?:,?\s*\d{4})?\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b', '', text)
    text = re.sub(r',\s*\|', ' |', text) 
    text = re.sub(r'\|\s*\|', '|', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip(" -–•.,|")

def clean_title_deterministic(raw_title: str) -> Optional[str]:
    # Удаляем ссылки из заголовка
    s = re.sub(r"http\S+", "", raw_title)
    s = strip_leading_datetime_from_title(s)
    s = remove_weekday_from_start(s)
    s = strip_intro_phrases(s)
    s = fix_glued_words(s)
    s = dedup_title(s)
    s = remove_city_from_title(s)

    low = s.lower()
    for sig in DESCRIPTION_SIGNALS:
        idx = low.find(sig)
        if idx != -1 and idx > 12:
            s = s[:idx].strip(" -–•.,")
            break

    # Убираем повисшие предлоги в конце и двойные предлоги ("в в Hub")
    s = re.sub(r'\bв\s+в\b', 'в', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+(в|на|с|и|для|от|за|к|по|из|у|о|об|at|in|on|for|and|to|the)\s*$', '', s, flags=re.IGNORECASE)
    s = re.sub(r"\s{2,}", " ", s).strip(" -–•.,")
    
    if len(s) < 5 or looks_like_description(s): return None
    return s[:120]

city_pattern = "|".join([re.escape(v) for v in KZ_CITIES.values()])
_GLUE_RE = re.compile(
    rf"^(\d{{1,2}})\s+([А-ЯЁа-яёA-Za-z]{{3,}})[,\s]+(\d{{1,2}}:\d{{2}})\s*(?:(Онлайн|online|zoom|{city_pattern})\s*)?(.+)$",
    re.IGNORECASE
)

def parse_glued_line(line: str) -> Optional[Dict]:
    line = normalize_glued_text(line)
    m = _GLUE_RE.match(line)
    if not m: return None

    day_s, month_s, time_str = m.group(1), m.group(2).lower(), m.group(3)
    possible_city, title_raw = (m.group(4) or "").strip(), m.group(5).strip()

    month_num = MONTHS_SHORT.get(month_s[:3], 0)
    if not month_num:
        for k, v in MONTHS_RU.items():
            if month_s.startswith(k[:3]):
                month_num = v
                break
    if not month_num: return None

    try: dt = datetime(datetime.now().year, month_num, int(day_s))
    except: return None
    if not is_future(dt): return None

    city = KZ_CITIES.get(possible_city.lower(), possible_city) if possible_city else None
    title_raw = dedup_title(title_raw)
    if len(title_raw) < 5: return None

    return {"dt": dt, "time_str": time_str, "city": city, "title_raw": title_raw[:300], "date_formatted": format_date(dt, time_str)}


def remove_city_and_hub_from_text(text: str) -> str:
    if not text:
        return ""

    # Удаляем конструкции типа "в Qostanai Hub"
    text = re.sub(r'\bв\s+[A-Za-zА-Яа-яЁё-]+\s+Hub\b', '', text, flags=re.IGNORECASE)

    # Удаляем все города из словаря KZ_CITIES
    for city_key in KZ_CITIES.keys():
        text = re.sub(rf'\b{city_key}\b', '', text, flags=re.IGNORECASE)

    # Чистим двойные пробелы
    text = re.sub(r'\s{2,}', ' ', text)

    # Убираем пробел перед точкой
    text = re.sub(r'\s+\.', '.', text)

    return text.strip()
# ─── Formatting post ───────────────────────────────────────
def make_post(event: Dict) -> str:
    title = (event.get("title") or "").strip()
    date_str = (event.get("date") or "").strip()
    link = (event.get("link") or "").strip()

    if not title or len(title) < 5 or not date_str or not link:
        return ""

    location = event.get("location", "")
    venue = event.get("venue", "")
    
    # 🔥 1. Принудительная очистка заголовка от города и лишних дат в начале
    title = remove_city_from_title(title)
    title = strip_leading_datetime_from_title(title)

    # Достаем сырой текст и текст с сайта
    full_text_raw = event.get("full_text", "")
    deep_description = event.get("deep_description", "")

    # 🔥 2. УМНЫЙ ВЫБОР ДАТЫ (ищем финал, а не дедлайн)
    context = (full_text_raw + " " + deep_description).lower()
    # Ищем фразы "финал", "питчинг", "дата проведения" и саму дату рядом
    match = re.search(r"(?:финал|питчинг|дата проведения|состоится)\s*[-—]?\s*(\d{1,2}\s+(?:янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)[а-я]*)", context)
    
    if match:
        parsed_final = parse_date(match.group(1))
        if parsed_final:
            # Сохраняем время из оригинальной даты, если оно было
            tm_match = re.search(r"\d{1,2}:\d{2}", date_str)
            time_str = tm_match.group(0) if tm_match else None
            date_str = format_date(parsed_final, time_str)

    # Извлекаем дату и время в явные переменные ДО удаления из текста
    event_time_match = re.search(r"\d{1,2}:\d{2}", date_str)
    event_time = event_time_match.group(0) if event_time_match else ""
    event_date = date_str.replace(event_time, "").strip() if event_time else date_str

    # 🔥 3. ПРИОРИТЕТ ОПИСАНИЯ
    # Берем длинное описание с сайта, если оно есть
    if deep_description and len(deep_description) > 50:
        description = deep_description
    else:
        # Иначе ищем программу или берем универсальное
        program_block = extract_program_block(full_text_raw)
        if program_block and len(program_block) > 40:
            description = program_block
        else:
            description = generate_universal_description(full_text_raw, title)

    # Заглушка, если текста вообще нет
    if not description:
        description = generate_fallback_description(title)

    # Убираем дублирование, если описание прилипло к заголовку
    if description:
        desc_clean = strip_emoji(description).strip()
        desc_prefix = desc_clean[:25]
        if len(desc_prefix) > 15:
            idx = title.lower().find(desc_prefix.lower())
            if idx > 3:
                title = title[:idx].strip(" -–•.,:;|")
                title = re.sub(r'\s+(в|на|с|и|для|от|за|к|по|из|у|о|об|at|in|on|for|and|to|the)\s*$', '', title, flags=re.IGNORECASE)

# 🔥 4. ФИНАЛЬНАЯ ЗАЧИСТКА
    # Сначала расклеиваем (16:00Костанай -> 16:00 Костанай), затем удаляем время!
    title = remove_dates_and_times(fix_glued_words(title))
    title = re.sub(r"http\S+", "", title).strip()
    
    description = remove_dates_and_times(fix_glued_words(description))

# 🔥 УБИРАЕМ ГОРОДА И HUB ИЗ ТЕКСТА (НО НЕ ИЗ location)
    title = remove_city_and_hub_from_text(title)
    description = remove_city_and_hub_from_text(description)

    # 🔥 5. СБОРКА ПОСТА ПО ШАБЛОНУ
    lines = [f"🎯 <b>{title.strip()}</b>"]

    if description:
        lines.append(f"📝 {description.strip()}")

    # Локация
    is_online = location in ("Онлайн", "Онлайн (Zoom)")
    
    # Если локация - чужая страна или город не из КЗ и не онлайн - отбрасываем
    # (Здесь location будет либо пустой (Казахстан), либо один из КЗ городов, 
    # либо "Онлайн". Если это Ташкент или Бишкек, выкидываем пост на этапе сборки)
    if location and not is_online and "Узбекистан" in location or "Кыргызстан" in location or "Словения" in location or "Slovenia" in location:
        return ""

    if is_online:
        lines.append("🌐 Онлайн")
    elif location:
        lines.append(f"🇰🇿 Казахстан, 🏙 {location}")
    else:
        lines.append("🇰🇿 Казахстан")

    # Площадка
    if venue: 
        lines.append(f"📍 {venue}")

    # Дата 
    if event_time:
        final_date_str = f"{event_date} в {event_time}".strip()
    else:
        final_date_str = event_date.strip()
        
    # Удаляем двойные пробелы
    final_date_str = re.sub(r'\s+', ' ', final_date_str)
    lines.append(f"📅 {final_date_str}")
    
    # Ссылка
    lines.append(f"🔗 <a href='{link}'>Читать →</a>")

    return "\n".join(lines)




class EventBot:
    def __init__(self):
        self.session = None
        self.posted = load_posted()

    async def get_session(self) -> aiohttp.ClientSession:
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"}
            )
        return self.session

    async def close(self):
        if self.session: await self.session.close()

    async def fetch(self, url: str) -> str:
        try:
            s = await self.get_session()
            async with s.get(url, timeout=15) as r:
                return await r.text() if r.status == 200 else ""
        except Exception as e:
            logger.error(f"fetch {url}: {e}")
            return ""

    async def fetch_event_details(self, url: str) -> Dict[str, str]:
        result = {"desc": "", "image": ""}
        if not url or not url.startswith("http") or "t.me" in url:
            return result

        try:
            html = await self.fetch(url)
            if not html: return result
            soup = BeautifulSoup(html, "html.parser")

            # 1. Фото (og:image)
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                img_url = og_image["content"]
                if not img_url.startswith("http"):
                    from urllib.parse import urljoin
                    img_url = urljoin(url, img_url)
                result["image"] = img_url

            # Очистка
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "menu", "form"]):
                tag.decompose()

            # 🔥 2. СОБИРАЕМ ПОЛНОЕ ОПИСАНИЕ
            content_area = soup.find("main") or soup.find("article") or soup.body
            collected_chunks = []
            
            if content_area:
                # Берем параграфы и элементы списков (где обычно лежат призы и условия)
                for elem in content_area.find_all(['p', 'li']):
                    txt = elem.get_text(separator=" ", strip=True)
                    if len(txt) > 30 and not any(bad in txt.lower() for bad in ["cookie", "войти", "регистрация"]):
                        if elem.name == 'li':
                            collected_chunks.append("• " + txt)
                        else:
                            collected_chunks.append(txt)
                    
                    # Если набрали 4-5 хороших абзацев — этого хватит для "вкусного" описания
                    if len(collected_chunks) >= 5:
                        break
            
            # 🔥 Формируем красивое описание с переносами строк и лимитом в 100 слов
            word_count = 0
            final_chunks = []
            for chunk in collected_chunks:
                chunk_words = chunk.split()
                if word_count + len(chunk_words) > 100:
                    needed = 100 - word_count
                    if needed > 0:
                        final_chunks.append(" ".join(chunk_words[:needed]) + "...")
                    break
                else:
                    final_chunks.append(chunk)
                    word_count += len(chunk_words)
                    
            if final_chunks:
                result["desc"] = "\n".join(final_chunks)
                    
        except Exception:
            pass
            
        return result

    def parse_digest(self, text: str, post_link: str, source: str, image_url: str) -> List[Dict]:
        events = []
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            dm = re.match(r"^(\d{1,2}[-]?\d{0,2}[.\s]\d{2}(?:\.\d{4})?|\d{1,2}\s+(?:янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)[а-я]*(?:\s+\d{4})?)", line, re.IGNORECASE)
            if not dm:
                i += 1; continue

            date_raw = dm.group(0)
            rest = line[dm.end():].strip()
            # Более надежный парсинг времени
            tm = re.search(r"(?:в\s*|начало\s*в\s*|-?\s*)?(\d{1,2}:\d{2})", rest, re.IGNORECASE)
            time_str = tm.group(1) if tm else None
            if tm: rest = (rest[:tm.start()] + rest[tm.end():]).strip()

            title_raw = strip_emoji(rest).strip(" -–•")
            link = None
            lm = re.search(r"((?:https?://|t\.me/)\S+)", line)
            if lm:
                link = lm.group(1)
                if not link.startswith("http"): link = "https://" + link
                title_raw = title_raw.replace(strip_emoji(lm.group(0)), "").strip()
            else:
                for j in range(i + 1, min(i + 4, len(lines))):
                    lm2 = re.search(r"((?:https?://|t\.me/)\S+)", lines[j])
                    if lm2:
                        link = lm2.group(1)
                        if not link.startswith("http"): link = "https://" + link
                        break

            if len(title_raw) < 5 and i + 1 < len(lines):
                nxt = strip_emoji(lines[i + 1]).strip()
                if len(nxt) > 5 and not re.match(r"^\d", nxt): title_raw = nxt

            if len(title_raw) < 5:
                i += 1; continue

            dt = parse_date(date_raw)
            if not is_future(dt):
                i += 1; continue

            ctx = line + " " + (lines[i + 1] if i + 1 < len(lines) else "")
            location = extract_location(ctx) or extract_location(text)
            title_clean = clean_title_deterministic(title_raw) or dedup_title(title_raw[:120])
            if not title_clean:
                i += 1; continue

            events.append({
                "title": title_clean, "date": format_date(dt, time_str), "location": location or "",
                "venue": extract_venue(ctx), "link": link or post_link, "source": source, "image_url": image_url
            })
            i += 1
        return events

    async def parse_channel(self, channel: Dict) -> List[Dict]:
        html = await self.fetch(f"https://t.me/s/{channel['username']}")
        if not html: return []
        soup = BeautifulSoup(html, "html.parser")
        all_events = []

        for msg in soup.find_all("div", class_="tgme_widget_message")[:20]:
            try:
                td = msg.find("div", class_="tgme_widget_message_text")
                if not td: continue
                text = td.get_text(separator="\n", strip=True)
                if len(text) < 30: continue

                le = msg.find("a", class_="tgme_widget_message_date")
                post_link = le["href"] if le else f"https://t.me/{channel['username']}"
                norm_link = normalize_link(post_link)

                external_link = None
                links_in_text = re.findall(r"(https?://[^\s]+)", text)
                for l in links_in_text:
                    clean_l = normalize_link(l)
                    if "t.me" not in clean_l:
                        external_link = clean_l
                        break

                final_link = external_link if external_link else norm_link
                if norm_link in self.posted: continue

                external_link = None
                for a in td.find_all("a", href=True):
                    href = normalize_link(a["href"])
                    if "t.me" not in href:
                        external_link = href
                        break

                if not external_link:
                    links_in_text = re.findall(r"(https?://[^\s]+)", text)
                    for l in links_in_text:
                        clean_l = normalize_link(l)
                        if "t.me" not in clean_l:
                            external_link = clean_l
                            break

                final_link = external_link if external_link else norm_link
                image_url = None

                photo_wrap = msg.find("a", class_="tgme_widget_message_photo_wrap")
                if photo_wrap:
                    style = photo_wrap.get("style", "")
                    match = re.search(r"url\('([^']+)'\)", style)
                    if match: image_url = match.group(1)

                if not image_url:
                    img_tag = td.find("img")
                    if img_tag and img_tag.get("src"): image_url = img_tag["src"]

                if re.search(r"\d{1,2}[.\-]\d{2}\s+(?:в\s+)?\d{1,2}:\d{2}", text):
                    evs = self.parse_digest(text, post_link, channel["name"], image_url)
                    all_events.extend(evs)
                    continue

                if not is_real_event(text): continue
                dt = parse_date(text)
                if not is_future(dt): continue

                title_candidate = None
                for ln in text.split("\n"):
                    ln = strip_emoji(ln).strip()
                    # Игнорируем строки, которые начинаются с http
                    if ln.startswith("http"): continue
                    
                    if len(ln) > 10:
                        title_candidate = ln
                        break

                raw_title = title_candidate or ""
                city_from_title = extract_city_from_title(raw_title)
                title = clean_title_deterministic(raw_title)
                if not title: continue

                tm2 = re.search(r"(?:в\s*|начало\s*в\s*|-?\s*)?(\d{1,2}:\d{2})", text, re.IGNORECASE)
                time_str = tm2.group(1) if tm2 else None

                all_events.append({
                    "title": title, "date": format_date(dt, time_str), "location": extract_location(text) or city_from_title or "",
                    "venue": extract_venue(text), "link": final_link, "source": channel["name"], "full_text": text, "image_url": image_url
                })
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

    async def parse_site(self, site: Dict) -> List[Dict]:
        html = await self.fetch(site["url"])
        if not html: return []
        soup = BeautifulSoup(html, "html.parser")
        events = []

        for link in soup.find_all("a", href=True)[:80]:
            try:
                href = link.get("href", "")
                title_raw = link.get_text(strip=True)

                if not href or not title_raw or len(title_raw) < 15: continue
                if not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(site["url"], href)

                href = normalize_link(href)
                if href.rstrip("/") == normalize_link(site["url"]).rstrip("/"): continue
                if href in self.posted: continue
                if is_site_trash(title_raw): continue
                if not is_real_event(title_raw): continue

                parent = link.find_parent(["div", "article", "li", "section"])
                context = parent.get_text(separator=" ", strip=True) if parent else title_raw
                dt = parse_date(context)

                if not is_future(dt): continue
                
                # Достаем время из блока
                tm3 = re.search(r"(?:в\s*|начало\s*в\s*|-?\s*)?(\d{1,2}:\d{2})", context, re.IGNORECASE)
                time_str = tm3.group(1) if tm3 else None
                
                image_url = None

                if parent:
                    imgs = parent.find_all("img")
                    for img in imgs:
                        src = img.get("src") or img.get("data-src")
                        if not src: continue
                        if not src.startswith("http"):
                            from urllib.parse import urljoin
                            src = urljoin(site["url"], src)
                        if is_clean_photo(src):
                            image_url = src
                            break

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

                title_clean = clean_title_deterministic(title_raw) or strip_emoji(dedup_title(title_raw))[:120]
                events.append({
                    "title": title_clean, "date": format_date(dt, time_str), "location": extract_location(context) or "",
                    "venue": extract_venue(context), "link": href, "full_text": context, "source": site["name"], "image_url": image_url
                })
                if len(events) >= 5: break
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

            if norm_link in bot_obj.posted:
                logger.info(f"⏭️ Уже публиковалось: {event.get('title')[:50]}")
                continue

            # 🔥 1. Получаем описание и качественное фото
            details = await bot_obj.fetch_event_details(norm_link)
            
            # На случай, если details это словарь (с новым кодом)
            if isinstance(details, dict):
                if details.get("desc"):
                    event["deep_description"] = details["desc"]
                if details.get("image"):
                    event["image_url"] = details["image"]
            # На случай, если details это просто строка (со старым кодом)
            elif isinstance(details, str) and details:
                event["deep_description"] = details

            text = make_post(event)
            if not text:
                continue

            try:
                photo_url = event.get("image_url")
                
                if photo_url:
                    # 🔥 2. НАДЕЖНАЯ ОТПРАВКА: Скачиваем фото в буфер, чтобы Телеграм не капризничал
                    try:
                        session = await bot_obj.get_session()
                        async with session.get(photo_url, timeout=15) as resp:
                            if resp.status == 200:
                                photo_bytes = await resp.read()
                                await bot_api.send_photo(
                                    chat_id=CHANNEL_ID,
                                    message_thread_id=MESSAGE_THREAD_ID,
                                    photo=photo_bytes,
                                    caption=text,
                                    parse_mode="HTML",
                                )
                            else:
                                raise Exception("Bad HTTP status for image")
                    except Exception as img_e:
                        logger.warning(f"Не удалось скачать фото, отправляем текст. Ошибка: {img_e}")
                        await bot_api.send_message(
                            chat_id=CHANNEL_ID,
                            message_thread_id=MESSAGE_THREAD_ID,
                            text=text,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                else:
                    # Если фото вообще не найдено
                    await bot_api.send_message(
                        chat_id=CHANNEL_ID,
                        message_thread_id=MESSAGE_THREAD_ID,
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )

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