from telegram import Bot, InputMediaPhoto
from config import BOT_TOKEN, CHAT_ID
import time
from telegram.ext import ContextTypes

bot = Bot(BOT_TOKEN)

async def send_notif(content, images):
    try:
        images_to_send = []
        for image in images[:3]:
            image_obj = InputMediaPhoto(media=image, caption=content if image == images[0] else '')
            images_to_send.append(image_obj)

        await bot.send_media_group(chat_id=CHAT_ID, media=images_to_send)

    except Exception as e:
        if "FloodWait" in str(e):
            print("Flood control exceeded. Waiting for 35 seconds before retrying.")
            time.sleep(35)
            await send_notif(content, images)
        else:
            print("Error while sending media group:", e)