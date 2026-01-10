import os
import glob
import time
import random
import asyncio
import discord
from discord.ext import commands, tasks
from collections import deque
from rapidfuzz import fuzz
import yt_dlp

import config
import state
from state import STATE as plstate
from utils.helpers import (log_error, get_duration, get_progress_bar, 
                           format_time, delete_after_delay)
from ui.views import PlayerControlView, PlaylistSelectView, YouTubeSelectionView



class Music(commands.Cog):
    
    def __init__(self, bot):
        self.bot = bot
        self.live_update.start()
        

    async def cog_unload(self):
        self.live_update.cancel()
    
    
    @tasks.loop(seconds=5)
    async def live_update(self):
        
        if plstate.msg and plstate.start_t > 0:
            # 1. Calculate Progress
            elapsed = (
                (plstate.pause_start - plstate.start_t) 
                if plstate.is_paused 
                else (time.time() - plstate.start_t)
                )
            
            # if the song is over, stop updating so the 'Idle' embed can stay
            if elapsed > plstate.duration + 2: # +2 seconds buffer
                return
            
            bar = get_progress_bar(elapsed, plstate.duration)
            ts = (f"`{format_time(elapsed)}"
                  f"{bar}"
                  f"{format_time(plstate.duration)}`")
            
            # 2. Get "Up Next" Info
            try:
                gid = str(plstate.msg.guild.id)
                if gid in state.SONG_QUEUES and len(state.SONG_QUEUES[gid]) > 0:
                    # Look at the first item in the queue without removing it
                    next_song_title = state.SONG_QUEUES[gid][0][1]
                    up_next_text = f"⏭️ **{next_song_title}**"
                else:
                    up_next_text = "Empty (Add more with !play)"

                # 3. Build Embed
                embed = discord.Embed(
                    title="Now Playing", 
                    description=f"**{plstate.title}**", color=0x3498db)
                embed.add_field(name="Progress", value=ts, inline=False)
                embed.add_field(name="Up Next", value=up_next_text, inline=False)
                
                await plstate.msg.edit(embed=embed)
            except Exception:
                 # Message might be deleted or guild unavailable
                pass

    @live_update.before_loop
    async def before_live_update(self):
        await self.bot.wait_until_ready()

    async def play_next_song(self, vc, gid, channel):
        if gid in state.SONG_QUEUES and state.SONG_QUEUES[gid]:
            file_path, title = state.SONG_QUEUES[gid].popleft()
            (plstate.title, plstate.duration, 
             plstate.start_t, plstate.is_paused) = (
                 title, get_duration(file_path), 
                 time.time(), False)
            
            vc.play(discord.FFmpegPCMAudio(file_path, executable=config.FFMPEG_EXE), 
                    after=lambda e: 
                    asyncio.run_coroutine_threadsafe(
                        self.play_next_song(vc, gid, channel), self.bot.loop))
            
            # PERMANENT PLAYER LOGIC:
            embed = discord.Embed(title="Now Playing", description=f"**{title}**", color=0x3498db)
            if plstate.msg:
                try:
                    await plstate.msg.edit(embed=embed, 
                                              view=PlayerControlView(self))
                except:
                    plstate.msg = await channel.send(embed=embed, view=PlayerControlView(self))
            else:
                plstate.msg = await channel.send(embed=embed, view=PlayerControlView(self))
        else:
            plstate.start_t = 0 # CRITICAL: This tells the loop to stop updating
            plstate.title = ""
            
            # Queue finished: Reset the player to Idle
            idle_embed = discord.Embed(
                title="Halfling Bard | Ready",
                description="🎶 **Queue finished.**\nWaiting for new songs...",
                color=discord.Color.blue()
            )
            if plstate.msg:
                try:
                    await plstate.msg.edit(embed=idle_embed, 
                                              view=PlayerControlView(self))
                except:
                     pass
            plstate.start_t = 0

    async def start_or_queue(self, ctx, message):
        vc = ctx.voice_client or await ctx.author.voice.channel.connect()
        gid = str(ctx.guild.id)
        if not vc.is_playing() and not vc.is_paused():
            await self.play_next_song(vc, gid, ctx.channel)
        else:
            await ctx.send(message, delete_after=5)

    def build_index(self):
        state.CACHED_SONG_INDEX = []
        for root, _, files in os.walk(config.MUSIC_FOLDER):
            for f in files:
                if f.endswith(".opus"):
                    state.CACHED_SONG_INDEX.append({'title': f[:-5], 'path': os.path.join(root, f)})

    async def download_single(self, ctx, url, title, video_id):
        """Checks cache or downloads a single video; returns (file_path, title)."""
        existing = next((i['path'] for i in state.CACHED_SONG_INDEX if f"[{video_id}]" in i['path']), None)
        
        if not existing:
            msg = await ctx.send(f"⏳ Downloading: **{title}**...")
            with yt_dlp.YoutubeDL(config.YDL_OPTIONS) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=True)
                existing = os.path.splitext(ydl.prepare_filename(info))[0] + ".opus"
            self.build_index()
            asyncio.create_task(delete_after_delay(msg, 3))
        
        return existing, title

    async def process_playlist_download(self, ctx, playlist_title, entries):
        """Handles sequential playlist downloading with a progress tracker and cancel flag."""
        state.DOWNLOAD_ABORTED = False
        
        safe_folder = "".join([c for c in playlist_title if c.isalnum() or c in (' ', '-', '_')]).strip()
        playlist_path = os.path.join(config.MUSIC_FOLDER, safe_folder)
        os.makedirs(playlist_path, exist_ok=True)
        
        count = len(entries)
        status_msg = await ctx.send(f"🚀 **Bulk Download:** `{safe_folder}`\n📦 Total: **{count}** songs.")

        opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(playlist_path, '%(title)s [%(id)s].%(ext)s'),
            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'opus','preferredquality': '0'}],
            'quiet': True, 
            'ignoreerrors': True,
            'cookiefile': 'cookies.txt',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'socket_timeout': 30,
            'retries': 3,
        }

        added_tracks = []
        failed_count = 0
        with yt_dlp.YoutubeDL(opts) as ydl:
            for i, entry in enumerate(entries):
                if state.DOWNLOAD_ABORTED:
                    msg = await ctx.send(f"🚫 **Stop:** Saved {len(added_tracks)} songs to `{safe_folder}`.")
                    asyncio.create_task(delete_after_delay(msg, 3))
                    break
                
                if entry:
                    v_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry['id']}"
                    v_title = entry.get('title', 'Unknown Title')
                    try:
                        await status_msg.edit(content=f"⏳ **Downloading ({i+1}/{count}):**\n`{v_title}`")
                        info = await asyncio.to_thread(ydl.extract_info, v_url, download=True)
                        f_path = os.path.splitext(ydl.prepare_filename(info))[0] + ".opus"
                        added_tracks.append((f_path, info.get('title', 'Unknown Title')))
                        await asyncio.sleep(random.uniform(5, 15)) # Protection
                    except Exception as e:
                        err_str = str(e).lower()
                        if "confirm you're not a bot" in err_str or "cookies are no longer valid" in err_str:
                            await ctx.send("🚨 **CRITICAL:** YouTube has invalidated your cookies! Download stopped. Please refresh `cookies.txt`.")
                            state.DOWNLOAD_ABORTED = True 
                            log_error(v_title, "Cookie Rotation/Invalidation")
                            break 
                            
                        failed_count += 1
                        log_error(v_title, str(0)) 
                        continue

        self.build_index()
        
        report = f"✅ **Playlist Ready:** `{safe_folder}`\nQueued **{len(added_tracks)}** songs."
        if failed_count > 0: report += f"\n⚠️ Failed: **{failed_count}** (Check `error_log.txt` for details)"
        msg = await status_msg.edit(content=report)
        asyncio.create_task(delete_after_delay(msg, 3))
        return added_tracks

    async def process_youtube_logic(self, ctx, query, interaction: discord.Interaction = None):
        gid = str(ctx.guild.id)
        is_link = query.startswith(("http://", "https://", "www.", "youtu."))

        fetch_opts = {'quiet': True, 'extract_flat': 'in_playlist', 'no_warnings': True}
        try:
            with yt_dlp.YoutubeDL(fetch_opts) as ydl:
                search_query = query if is_link else f"ytsearch5:{query}"
                info = await asyncio.to_thread(ydl.extract_info, search_query, download=False)
        except yt_dlp.utils.DownloadError:
            msg = await interaction.followup.send("❌ This link is not supported or is unreachable.", ephemeral=True)
            asyncio.create_task(delete_after_delay(msg, 5))
            return

        # --- Case: Playlist ---
        if is_link and 'entries' in info and len(info.get('entries', [])) > 1:
            entries = list(info['entries'])
            view = PlaylistSelectView(ctx.author.id)
            
            prompt = await interaction.followup.send(f"📂 **Playlist:** `{info['title']}` ({len(entries)} tracks). Choice?", view=view, ephemeral=True)
            await view.wait()
            
            try: await prompt.delete()
            except: pass
            
            if view.choice is None:
                return
            elif view.choice == "playlist":
                tracks = await self.process_playlist_download(ctx, info['title'], entries)
                state.SONG_QUEUES[gid].extend(tracks)
                return await self.start_or_queue(ctx, "✅ Playlist added to queue.") 
            elif view.choice == "song":
                query = query.split('&list=')[0].split('?list=')[0]

        # --- Case: YouTube Search Results ---
        if not is_link and 'entries' in info:
            results = info['entries']
            if not results: 
                await interaction.followup.send("❌ No results found on YouTube.", ephemeral=True)
                asyncio.create_task(delete_after_delay(interaction, 3))
                return
            
            menu_text = "\n".join([f"**{i+1}.** {e['title']}" for i, e in enumerate(results)])
            view = YouTubeSelectionView(ctx, results, self)
            await interaction.followup.send(f"**YouTube Results:**\n{menu_text}", view=view, ephemeral=True)
            await view.wait()
            
            if view.selection:
                f_path, title = await self.download_single(ctx, view.selection['url'], view.selection['title'], view.selection['id'])
                state.SONG_QUEUES[gid].append((f_path, title))
                await self.start_or_queue(ctx, f"✅ Queued: **{title}**")
            return

        # --- Case: Single Video Link ---
        v_info = info['entries'][0] if 'entries' in info else info
        f_path, title = await self.download_single(ctx, v_info['webpage_url'] if 'webpage_url' in v_info else query, v_info.get('title', 'Unknown Title'), v_info['id'])
        state.SONG_QUEUES[gid].append((f_path, title))
        msg = await self.start_or_queue(ctx, f"✅ Queued: **{title}**")
        asyncio.create_task(delete_after_delay(msg, 3))

    async def smart_play(self, ctx, query: str, interaction: discord.Interaction = None):
        gid = str(ctx.guild.id)
        if gid not in state.SONG_QUEUES: state.SONG_QUEUES[gid] = deque()
        query_clean = query.strip().lower()

        # 1. Handle Direct Links (Skip local search)
        if query.startswith(("http://", "https://", "www.")):
            return await self.process_youtube_logic(ctx, query, interaction)

        # 2. Local Folder Search
        for entry in os.scandir(config.MUSIC_FOLDER):
            if entry.is_dir() and entry.name.lower() == query_clean:
                items = sorted(glob.glob(os.path.join(entry.path, '*.opus')))
                for p in items: state.SONG_QUEUES[gid].append((p, os.path.basename(p)[:-5]))
                return await self.start_or_queue(ctx, f"📁 Queued folder: **{entry.name}** ({len(items)} songs)")

        # 3. Local Song Search (Fuzzy Match)
        best_match = None
        highest_score = 0
        for item in state.CACHED_SONG_INDEX:
            score = fuzz.token_set_ratio(query_clean, item['title'].lower())
            if score > highest_score:
                highest_score, best_match = score, item

        # 4. Threshold Decision (Adjust 90 to your liking)
        if highest_score >= 90:
            state.SONG_QUEUES[gid].append((best_match['path'], best_match['title']))
            await self.start_or_queue(ctx, f"✅ Found locally: **{best_match['title']}**")
        else:
            # No good local match -> Search YouTube
            if highest_score > 0:
                await ctx.send(f"🔍 Local match weak ({highest_score:.1f}%). Checking YouTube...", delete_after=3)
            await self.process_youtube_logic(ctx, query, interaction)

    @commands.command(name="library", aliases=["lib"])
    async def library(self, ctx, *, query=None):
        gid = str(ctx.guild.id)
        folders = sorted([e.name for e in os.scandir(config.MUSIC_FOLDER) if e.is_dir()])
        
        # Check if query is a number or a name
        target_folder = None
        if query:
            if query.isdigit():
                idx = int(query) - 1
                if gid in state.LAST_VIEWED_LISTS and 0 <= idx < len(state.LAST_VIEWED_LISTS[gid]):
                    potential = state.LAST_VIEWED_LISTS[gid][idx]
                    if potential in folders: target_folder = potential
            else:
                target_folder = next((f for f in folders if f.lower() == query.lower()), None)

        if target_folder:
            files = sorted(glob.glob(os.path.join(config.MUSIC_FOLDER, target_folder, '*.opus')))
            state.LAST_VIEWED_LISTS[gid] = files # Store full paths for songs
            res = f"📁 **{target_folder}**\n" + "\n".join([f"`{i+1:02}.` {os.path.basename(f)[:-5]}" for i,f in enumerate(files)])
            return await ctx.send(res[:2000])

        # Default: Show root folders
        state.LAST_VIEWED_LISTS[gid] = folders # Store folder names
        res = "📂 **Library Playlists**\n" + "\n".join([f"`{i+1:02}.` {f}" for i,f in enumerate(folders)])
        await ctx.send(res)
    
    @commands.command()
    async def cancel(self, ctx):
        state.DOWNLOAD_ABORTED = True
        msg = await ctx.send("🛑 **Cancellation request received.** Finishing current song and stopping the rest...")
        asyncio.create_task(delete_after_delay(msg, 3))
    
    @commands.Cog.listener()
    async def on_ready(self):
        print(f"Music Cog loaded for {self.bot.user}")
        self.build_index()
        
        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name="music")
            if channel:
                # Clean up old bot messages
                try:
                    await channel.purge(limit=10, check=lambda m: m.author == self.bot.user)
                except: pass
                
                idle_embed = discord.Embed(
                    title="Halfling Bard | Ready",
                    description="🎶 **Status:** Idle\nClick 'Add Song' to start the music!",
                    color=discord.Color.blue()
                )
                
                msg = await channel.send(embed=idle_embed, view=PlayerControlView(self))
                plstate.msg = msg  

async def setup(bot):
    await bot.add_cog(Music(bot))
