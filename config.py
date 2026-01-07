import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MUSIC_FOLDER = os.path.join(BASE_DIR, "Library")
SINGLES_FOLDER = os.path.join(MUSIC_FOLDER, "Singles")

# Path to your local tools
FFMPEG_EXE = r"C:\Users\nsaka\Documents\ffmpeg\bin\ffmpeg.exe"
FFPROBE_EXE = r"C:\Users\nsaka\Documents\ffmpeg\bin\ffprobe.exe"

os.makedirs(SINGLES_FOLDER, exist_ok=True)

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': os.path.join(SINGLES_FOLDER, '%(title)s [%(id)s].%(ext)s'),
    'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'opus','preferredquality': '0'}],
    'quiet': True,
    'noplaylist': True,
    'ignoreerrors': True,
    'cookiefile': 'cookies.txt',
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'socket_timeout': 30, # Give up after 30 seconds of no data
    'retries': 3,          # Try 3 times before skipping
}
