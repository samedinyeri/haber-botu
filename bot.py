from telethon import TelegramClient, events
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os
import asyncio
from datetime import datetime, timezone
import logging
import time
import threading
import requests
import json
import base64
import sys
from PIL import Image
import io

# Loglama ayarları
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_log.txt', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Process ID'sini kaydet
with open('bot_pid.txt', 'w') as f:
    f.write(str(os.getpid()))

try:
    # .env dosyasından API bilgilerini yükle
    load_dotenv()
    API_ID = os.getenv('API_ID')
    API_HASH = os.getenv('API_HASH')
    SESSION_STRING = os.getenv('SESSION_STRING')

    # API bilgilerini kontrol et
    if not API_ID or not API_HASH or not SESSION_STRING:
        raise ValueError("API_ID, API_HASH veya SESSION_STRING eksik!")

    # API_ID'yi int'e çevir
    API_ID = int(API_ID)

    logger.info(f"API bilgileri yüklendi: API_ID={API_ID}")
    logger.info(f"Çalışma dizini: {os.getcwd()}")
    logger.info(f"SESSION_STRING uzunluğu: {len(SESSION_STRING)}")
except Exception as e:
    logger.error(f"API bilgileri yüklenirken hata: {e}")
    sys.exit(1)

# Bluesky hesap bilgileri
BLUESKY_HANDLE = "hakikathaber.tr"
BLUESKY_APP_PASSWORD = "ryu3-3cpk-qwio-lfg7"
BLUESKY_API = "https://bsky.social/xrpc"

# Log dosyası ve medya klasörü
LOG_FILE = 'bot_log.txt'
MEDIA_FOLDER = 'bpthaber_media'

# Dosya kilitleme mekanizması
file_lock = threading.Lock()

# Global client değişkeni
client = None

# Medya klasörünü oluştur
if not os.path.exists(MEDIA_FOLDER):
    os.makedirs(MEDIA_FOLDER)

def safe_write_to_file(content, mode='a'):
    """Güvenli dosya yazma işlemi"""
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            with file_lock:
                with open(LOG_FILE, mode, encoding='utf-8') as f:
                    f.write(content + '\n')
            return True
        except Exception as e:
            logger.warning(f"Dosya yazma denemesi {attempt + 1}/{max_retries} başarısız: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.error(f"Dosya yazma işlemi başarısız: {e}")
                return False

async def get_media_group(client, message):
    try:
        # Mesajın grup ID'sini al
        group_id = message.grouped_id
        if not group_id:
            logger.info("Tek görselli post tespit edildi")
            return [message]
        
        # Mesajın bulunduğu kanalı al
        channel = await client.get_entity(message.peer_id)
        
        # Son 20 mesajı al
        messages = await client.get_messages(channel, limit=20)
        
        # Aynı grup ID'sine sahip mesajları filtrele
        group_messages = [msg for msg in messages if hasattr(msg, 'grouped_id') and msg.grouped_id == group_id]
        
        # Mesajları ID'ye göre sırala
        group_messages.sort(key=lambda x: x.id)
        
        logger.info(f"Grup medyasında {len(group_messages)} adet mesaj bulundu")
        return group_messages
        
    except Exception as e:
        logger.error(f"Medya grubu alınırken hata: {e}")
        logger.error(f"Hata detayı: {str(e)}")
        return None

async def get_last_posts(client, channel, limit=3):
    """Son gönderileri al"""
    try:
        messages = await client.get_messages(channel, limit=limit)
        return messages
    except Exception as e:
        logger.error(f"Son gönderileri alma hatası: {e}")
        return []

async def process_and_share_posts(client, channel):
    """Son gönderileri işle ve paylaş"""
    try:
        logger.info("Son gönderiler alınıyor...")
        messages = await get_last_posts(client, channel)
        
        for message in messages:
            try:
                logger.info(f"Mesaj işleniyor: {message.id}")
                message_text = message.text if message.text else ""
                media_paths = []
                
                # Mesajı log dosyasına kaydet
                safe_write_to_file(f"Mesaj işleniyor: {message.id}")
                safe_write_to_file(f"Mesaj metni: {message_text}")
                
                if message.media:
                    try:
                        if hasattr(message.media, 'photo'):
                            if hasattr(message.media, 'grouped_id'):
                                media_group = await get_media_group(client, message)
                                for msg in media_group:
                                    media_path = await client.download_media(msg, f"{MEDIA_FOLDER}/temp_media_{len(media_paths)}.jpg")
                                    media_paths.append(media_path)
                                    logger.info(f"Grup medyası indirildi: {media_path}")
                            else:
                                media_path = await client.download_media(message, f"{MEDIA_FOLDER}/temp_media_0.jpg")
                                media_paths.append(media_path)
                                logger.info(f"Tekli medya indirildi: {media_path}")
                    except Exception as e:
                        logger.error(f"Medya indirme hatası: {e}")
                
                # Bluesky'ye gönder
                try:
                    if media_paths:
                        success = await post_to_bluesky(message_text, media_paths)
                        logger.info(f"Medya ile birlikte Bluesky'ye gönderildi: {success}")
                        safe_write_to_file(f"Bluesky'ye gönderildi: {success}")
                    elif message_text:
                        success = await post_to_bluesky(message_text, None)
                        logger.info(f"Metin Bluesky'ye gönderildi: {success}")
                        safe_write_to_file(f"Bluesky'ye gönderildi: {success}")
                except Exception as e:
                    logger.error(f"Bluesky'ye gönderme hatası: {e}")
                    safe_write_to_file(f"Bluesky'ye gönderme hatası: {e}")
                
                # Medya dosyalarını temizle
                for media_path in media_paths:
                    if media_path and os.path.exists(media_path):
                        os.remove(media_path)
                        
            except Exception as e:
                logger.error(f"Mesaj işleme hatası: {e}")
                safe_write_to_file(f"Mesaj işleme hatası: {e}")
                
    except Exception as e:
        logger.error(f"Gönderi işleme hatası: {e}")
        safe_write_to_file(f"Gönderi işleme hatası: {e}")

async def process_message(client, message):
    try:
        logger.info(f"Mesaj işleniyor: {message.id}")
        
        # Metni al
        text = message.text or getattr(message, 'caption', '') or ""
        
        # Metin uzunluğunu kontrol et
        if len(text) > 300:
            logger.info(f"Metin çok uzun ({len(text)} karakter), paylaşılmıyor...")
            return
            
        # Medya dosyalarını indir
        media_paths = []
        if message.media:
            logger.info("Medya indiriliyor...")
            
            # Grup medyası kontrolü
            if hasattr(message, 'grouped_id'):
                logger.info("Grup medyası tespit edildi")
                try:
                    # Medya grubunu al
                    media_group = await get_media_group(client, message)
                    if not media_group:
                        logger.warning("Medya grubu bulunamadı")
                        return
                    
                    # Eğer bu mesaj grup medyasının ilk mesajı değilse, işleme
                    if message.id != media_group[0].id:
                        logger.info("Bu mesaj grup medyasının ilk mesajı değil, atlanıyor...")
                        return
                    
                    logger.info(f"Medya grubunda {len(media_group)} adet medya bulundu")
                    
                    # Her medyayı indir ve optimize et
                    for i, msg in enumerate(media_group):
                        media_path = f"bpthaber_media/{message.id}_{i}.jpg"
                        await client.download_media(msg.media, media_path)
                        
                        # Görüntüyü aç ve optimize et
                        with Image.open(media_path) as img:
                            # Kaliteyi artır
                            if img.mode in ('RGBA', 'LA'):
                                background = Image.new('RGB', img.size, (255, 255, 255))
                                background.paste(img, mask=img.split()[-1])
                                img = background
                            
                            # Boyutları kontrol et ve optimize et
                            max_size = 2000
                            if img.width > max_size or img.height > max_size:
                                ratio = min(max_size/img.width, max_size/img.height)
                                new_size = (int(img.width * ratio), int(img.height * ratio))
                                img = img.resize(new_size, Image.Resampling.LANCZOS)
                            
                            # JPEG olarak kaydet (yüksek kalite)
                            img.save(media_path, 'JPEG', quality=95, optimize=True)
                        
                        media_paths.append(media_path)
                        logger.info(f"Grup medyası indirildi: {media_path}")
                    
                    # Tüm medyaları indirdikten sonra tek seferde gönder
                    if media_paths:
                        logger.info(f"{len(media_paths)} adet grup medyası Bluesky'ye gönderiliyor...")
                        await post_to_bluesky(text, media_paths)
                        
                        # Medya dosyalarını temizle
                        for path in media_paths:
                            try:
                                os.remove(path)
                                logger.info(f"Medya dosyası silindi: {path}")
                            except Exception as e:
                                logger.error(f"Medya dosyası silinirken hata: {e}")
                        return
                        
                except Exception as e:
                    logger.error(f"Grup medyası işlenirken hata: {e}")
                    logger.error(f"Hata detayı: {str(e)}")
            
            # Tekli medya kontrolü
            elif hasattr(message.media, 'photo') or hasattr(message.media, 'document'):
                try:
                    media_path = f"bpthaber_media/{message.id}_0.jpg"
                    await client.download_media(message.media, media_path)
                    
                    # Görüntüyü aç ve optimize et
                    with Image.open(media_path) as img:
                        # Kaliteyi artır
                        if img.mode in ('RGBA', 'LA'):
                            background = Image.new('RGB', img.size, (255, 255, 255))
                            background.paste(img, mask=img.split()[-1])
                            img = background
                        
                        # Boyutları kontrol et ve optimize et
                        max_size = 2000
                        if img.width > max_size or img.height > max_size:
                            ratio = min(max_size/img.width, max_size/img.height)
                            new_size = (int(img.width * ratio), int(img.height * ratio))
                            img = img.resize(new_size, Image.Resampling.LANCZOS)
                        
                        # JPEG olarak kaydet (yüksek kalite)
                        img.save(media_path, 'JPEG', quality=95, optimize=True)
                    
                    media_paths.append(media_path)
                    logger.info(f"Tekli medya indirildi: {media_path}")
                    
                    # Tekli medyayı gönder
                    if media_paths:
                        logger.info("Tekli medya Bluesky'ye gönderiliyor...")
                        await post_to_bluesky(text, media_paths)
                        
                        # Medya dosyasını temizle
                        try:
                            os.remove(media_path)
                            logger.info(f"Medya dosyası silindi: {media_path}")
                        except Exception as e:
                            logger.error(f"Medya dosyası silinirken hata: {e}")
                        return
                        
                except Exception as e:
                    logger.error(f"Tekli medya işlenirken hata: {e}")
                    logger.error(f"Hata detayı: {str(e)}")
        
        # Sadece metin varsa
        if not media_paths and text:
            logger.info("Metin Bluesky'ye gönderiliyor...")
            await post_to_bluesky(text)
            
    except Exception as e:
        logger.error(f"Mesaj işlenirken hata: {e}")
        logger.error(f"Hata detayı: {str(e)}")

async def post_to_bluesky(text, media_paths=None):
    try:
        logger.info("Bluesky oturumu açılıyor...")
        
        # Bluesky API bilgileri
        handle = BLUESKY_HANDLE
        app_password = BLUESKY_APP_PASSWORD
        endpoint = f"{BLUESKY_API}/com.atproto.repo.createRecord"
        
        # Oturum aç
        session = requests.Session()
        auth_response = session.post(
            f"{BLUESKY_API}/com.atproto.server.createSession",
            json={
                "identifier": handle,
                "password": app_password
            }
        )
        auth_response.raise_for_status()
        access_token = auth_response.json()["accessJwt"]
        session.headers["Authorization"] = f"Bearer {access_token}"
        
        logger.info("Bluesky oturumu başarıyla açıldı")
        
        # Medya varsa önce onları yükle
        media_refs = []
        if media_paths:
            logger.info("Medya yükleniyor...")
            for path in media_paths:
                with open(path, 'rb') as f:
                    media_data = f.read()
                
                # Medya yükle
                upload_response = session.post(
                    f"{BLUESKY_API}/com.atproto.repo.uploadBlob",
                    headers={
                        "Content-Type": "image/jpeg"
                    },
                    data=media_data
                )
                upload_response.raise_for_status()
                media_ref = upload_response.json()["blob"]
                media_refs.append(media_ref)
                logger.info(f"Medya yüklendi: {path}")
        
        # Gönderi oluştur
        post_data = {
            "repo": handle,
            "collection": "app.bsky.feed.post",
            "record": {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": datetime.now(timezone.utc).isoformat()
            }
        }
        
        # Medya varsa ekle
        if media_refs:
            post_data["record"]["embed"] = {
                "$type": "app.bsky.embed.images",
                "images": [
                    {
                        "image": ref,
                        "alt": ""
                    } for ref in media_refs
                ]
            }
        
        logger.info("Gönderi Bluesky'ye gönderiliyor...")
        logger.info(f"Gönderi verisi: {json.dumps(post_data, indent=2)}")
        response = session.post(endpoint, json=post_data)
        response.raise_for_status()
        
        logger.info("Mesaj Bluesky'ye başarıyla gönderildi")
        logger.info(f"Yanıt: {response.text}")
        
        if media_paths:
            logger.info(f"{len(media_paths)} adet medya Bluesky'ye gönderildi")
        else:
            logger.info("Metin Bluesky'ye gönderildi")
            
    except Exception as e:
        logger.error(f"Bluesky'ye gönderi yapılırken hata: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Hata yanıtı: {e.response.text}")
        raise

async def main():
    try:
        # API bilgilerini yükle
        load_dotenv()
        logger.info(f"API bilgileri yüklendi: API_ID={os.getenv('API_ID')}")
        
        # Çalışma dizinini kontrol et
        current_dir = os.getcwd()
        logger.info(f"Çalışma dizini: {current_dir}")
        
        # SESSION_STRING uzunluğunu kontrol et
        session_string = os.getenv('SESSION_STRING')
        logger.info(f"SESSION_STRING uzunluğu: {len(session_string)}")
        
        # Telegram istemcisini başlat
        logger.info("Bot başlatılıyor...")
        client = TelegramClient(StringSession(session_string), os.getenv('API_ID'), os.getenv('API_HASH'))
        
        # İstemciyi başlat
        await client.start()
        logger.info("Telegram'a bağlanıldı")
        
        # Hedef kanalları belirt
        target_channels = ['clontv', 'bot_haber', 'bpthaber']
        logger.info(f"Hedef kanallar: {', '.join(target_channels)}")
        
        # Her kanal için ayrı bir dinleyici başlat
        for channel in target_channels:
            logger.info(f"{channel} kanalı için mesajlar dinleniyor...")
            @client.on(events.NewMessage(chats=channel))
            async def handler(event):
                try:
                    message = event.message
                    logger.info(f"Yeni mesaj alındı: {message.text or getattr(message, 'caption', '') or '...'}")
                    await process_message(client, message)
                except Exception as e:
                    logger.error(f"Mesaj işlenirken hata: {e}")
                    logger.error(f"Hata detayı: {str(e)}")
        
        logger.info("Bot başlatıldı ve mesajları dinliyor...")
        
        # Bot çalışmaya devam etsin
        await client.run_until_disconnected()
        
    except Exception as e:
        logger.error(f"Bot başlatılırken hata: {e}")
        logger.error(f"Hata detayı: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot kullanıcı tarafından durduruldu")
    except Exception as e:
        logger.error(f"Kritik hata: {e}")
        safe_write_to_file(f"Kritik hata: {e}") 