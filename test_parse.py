import sys
import asyncio

sys.path.append("/Users/diastursynbek/Downloads/PROga/PYT PROJECT/Event_bot")

from bot import EventBot, make_post

async def main():
    bot_obj = EventBot()
    print("Fetching events from Telegram (Startup Course) for testing...")
    channel = {"username": "startup_course_com", "name": "Startup Course"}
    events = await bot_obj.parse_channel(channel)
    
    if not events:
        print("No events found!")
    
    for event in events[:3]:  # Тестируем на 3 первых ивентах
        print(f"\nProcessing: {event['link']}")
        details = await bot_obj.fetch_event_details(event["link"])
        
        if isinstance(details, dict):
            if details.get("desc"):
                event["deep_description"] = details["desc"]
            if details.get("image"):
                event["image_url"] = details["image"]
        elif isinstance(details, str) and details:
            event["deep_description"] = details
            
        post_text = make_post(event)
        print("="*40)
        print("СГЕНЕРИРОВАННЫЙ ПОСТ:")
        print("-" * 20)
        print(post_text)
        print("="*40)

    await bot_obj.close()

if __name__ == "__main__":
    asyncio.run(main())
