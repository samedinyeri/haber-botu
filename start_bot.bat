@echo off
cd /d C:\xampp\htdocs\bpt

REM Modüllerin yüklü olup olmadığını kontrol et
python -c "import PIL, telethon, dotenv, requests" 2>nul
if errorlevel 1 (
    echo Gerekli modüller yükleniyor...
    pip install pillow telethon python-dotenv requests
)

REM Botu başlat
python bot.py
pause 