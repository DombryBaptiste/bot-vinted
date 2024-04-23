import datetime
from datetime import datetime, timezone, timedelta
import pandas
import api
from constants import NOTIFICATION_CONTENT
from config import BOT_TOKEN, CHAT_ID
from notification import send_notif
from telegram import Bot, InputMediaPhoto
from time import sleep
from random import randint, random
import logging

logging.basicConfig(filename='alert_log.txt', level=logging.INFO)

def get_content_from_item(item):
    content = NOTIFICATION_CONTENT.format(
        price = item.get("price", "ERR"),
        title = item.get("title", "N/A"),
        brand = item.get("brand_title", "N/A"),
        size = item.get("size_title", "N/A"),
        feedback_reputation = "Non noté ATM",
        url = item.get("url", "N/A")
    )
    logging.info(datetime.now(timezone.utc))
    logging.info(content)
    images = [item["photo"]["full_size_url"]]
    images_to_send = []
    for image in images[:3]:
        image_obj = InputMediaPhoto(media=image, caption=content if image == images[0] else '')
        images_to_send.append(image_obj)

    return images_to_send

def list_to_send():
    list = []
    data = pandas.read_csv("request.csv")
    for index, row in data.iterrows():
        request = row["url"]
        data = api.search(request)
        for item in data:
            created_at = datetime.fromtimestamp(item['photo']['high_resolution']['timestamp'], timezone.utc)
            if ((datetime.now(timezone.utc) - timedelta(minutes=2)) < created_at):
                content = get_content_from_item(item)
                list.append(content)
    return list

def send_message(list):
    bot = Bot(token=BOT_TOKEN)
    for item in list:
        bot.send_media_group(chat_id=CHAT_ID, media=item)
        sleep(1)
        
if __name__ == "__main__":
    while True:
        try:
            print(datetime.now())
            list_item = list_to_send()
            send_message(list_item)
        except Exception as e:
            print(f"An error occurred: {e}")
        sleep(60)
    # {while True:
    #     try:
    #         asyncio.run(update_data())
    #     except Exception:
    #         print("Erreur on Retry")
    #         asyncio.run(update_data())
    #     notification = True
    #     sleep(randint(60, 120) + random())}