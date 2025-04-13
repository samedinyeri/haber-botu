from telethon import TelegramClient, events
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os
import asyncio
from datetime import datetime, timezone
import logging
import requests
import json
from PIL import Image
import io
import threading
from flask import Flask

# Loglama
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# .env yükle
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
BLUESKY_HANDLE = os.getenv("BLUESKY_HANDLE")
BLUESKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD")
BLUESKY_API = "https://bsky.social/xrpc"
MEDIA_FOLDER = "bpthaber_media"

# Klasör oluştur
if not os.path.exists(MEDIA_FOLDER):
    os.makedirs(MEDIA_FOLDER)

# Bluesky'ye gönder
async def post_to_bluesky(text, media_paths=None):
    try:
        logger.info("Bluesky oturumu açılıyor...")
        session = requests.Session()
        auth_response = session.post(
            f"{BLUESKY_API}/com.atproto.server.createSession",
            json={"identifier": BLUESKY_HANDLE, "password": BLUESKY_APP_PASSWORD}
        )
        auth_response.raise_for_status()
        access_token = auth_response.json()["accessJwt"]
        session.headers["Authorization"] = f"Bearer {access_token}"
        logger.info("Bluesky oturumu başarıyla açıldı")

        media_refs = []
        if media_paths:
            for path in media_paths:
                with open(path, 'rb') as f:
                    media_data = f.read()
                upload_response = session.post(
                    f"{BLUESKY_API}/com.atproto.repo.uploadBlob",
                    headers={"Content-Type": "image/jpeg"},
                    data=media_data
                )
                upload_response.raise_for_status()
                media_refs.append(upload_response.json()["blob"])
                logger.info(f"Medya yüklendi: {path}")

        post_data = {
            "repo": BLUESKY_HANDLE,
            "collection": "app.bsky.feed.post",
            "record": {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": datetime.now(timezone.utc).isoformat()
            }
        }

        if media_refs:
            post_data["record"]["embed"] = {
                "$type": "app.bsky.embed.images",
                "images": [{"image": ref, "alt": ""} for ref in media_refs]
            }

        response = session.post(f"{BLUESKY_API}/com.atproto.repo.createRecord", json=post_data)
        response.raise_for_status()
        logger.info("Gönderi Bluesky'ye başarıyla gönderildi")

    except Exception as e:
        logger.error(f"Bluesky'ye gönderim hatası: {e}")

# Mesajı işle
async def process_message(client, message):
    try:
        text = message.text or getattr(message, 'caption', '') or ""
        media_paths = []

        if message.media:
            media_path = f"{MEDIA_FOLDER}/{message.id}.jpg"
            await client.download_media(message.media, media_path)

            with Image.open(media_path) as img:
                if img.mode in ('RGBA', 'LA'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1])
                    img = background
                img.save(media_path, 'JPEG', quality=95, optimize=True)

            media_paths.append(media_path)

        await post_to_bluesky(text, media_paths)

        for path in media_paths:
            os.remove(path)

    except Exception as e:
        logger.error(f"Mesaj işleme hatası: {e}")

# Telegram bot
async def main():
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    logger.info("Telegram'a bağlanıldı")

    target_channels = ['clontv', 'bpthaber', 'bot_haber']
    for channel in target_channels:
        logger.info(f"{channel} kanalı dinleniyor...")
        @client.on(events.NewMessage(chats=channel))
        async def handler(event):
            await process_message(client, event.message)

    await client.run_until_disconnected()

# Flask sunucusu (UptimeRobot için)
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot çalışıyor!"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# Her şey burada başlıyor
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    asyncio.run(main())
