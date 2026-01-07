import datetime
import subprocess
import asyncio
import discord
import os

# Import configuration to access paths
import config

def log_error(song_title, error_message):
    """Saves download failures to a text file for later review."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("error_log.txt", "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] SONG: {song_title} | ERROR: {error_message}\n")

def get_duration(file_path):
    """Uses your local ffprobe to get song length."""
    try:
        cmd = [config.FFPROBE_EXE, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return float(result.stdout)
    except: return 0

def get_progress_bar(elapsed, total, bar_length=29): # Increased default to 28
    """Calculates bar size to match the width of Discord button rows."""
    if total <= 0: return "▬" * bar_length
    progress_ratio = min(max(elapsed / total, 0), 1)
    filled_length = int(progress_ratio * bar_length)
    
    # Using '▬' for the empty part and '━' for the filled part can also look sleeker
    bar = "━" * filled_length + "🔘" + "▬" * (bar_length - filled_length)
    return bar

def format_time(seconds):
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}:{secs:02}"

async def delete_after_delay(msg, delay: int=1):
    """
    Background task to delete a message after a set number of seconds.
    Works with standard messages and interaction followups.
    """    
    await asyncio.sleep(delay)
    try:
        # Check if the target is an Interaction (Buttons/Modals)
        if isinstance(msg, discord.Interaction): await msg.delete_original_response()
        # Check if it's a standard Message (like from ctx.send)
        elif hasattr(msg, 'delete'): await msg.delete()
    except Exception:
        pass # Silently fail if already deleted or expired
