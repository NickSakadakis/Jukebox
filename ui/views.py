import discord
import asyncio
import time
import random
import os
import glob
from collections import deque

import config
import state
from utils.helpers import delete_after_delay

# Forward declaration to avoid circular import issues if needed
# But logic functions will be imported from cogs.music or passed as callbacks

class PlayerControlView(discord.ui.View):
    def __init__(self, music_cog):
        super().__init__(timeout=None)
        self.music_cog = music_cog

    @discord.ui.button(label="", style=discord.ButtonStyle.secondary, emoji="⏸️")
    async def play_pause_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        gid = str(interaction.guild.id)

        # 1. Start Engine: Bot is not playing and not paused (Idle state)
        if not vc or (not vc.is_playing() and not vc.is_paused()):
            # Connect if not connected
            if not vc:
                if interaction.user.voice:
                    vc = await interaction.user.voice.channel.connect()
                else:
                    return await interaction.response.send_message("❌ Please join a voice channel first!", ephemeral=True)

            # Check if there is anything to play
            if gid in state.SONG_QUEUES and len(state.SONG_QUEUES[gid]) > 0:
                await self.music_cog.play_next_song(vc, gid, interaction.channel)
                # Update UI to "Playing" state
                button.emoji = "⏸️"
                button.style = discord.ButtonStyle.secondary
            else:
                await interaction.response.send_message("📭 Queue is empty. Add songs via Library or Add Song!", ephemeral=True)
                asyncio.create_task(delete_after_delay(interaction, 3))
                return 

        # 2. Currently Playing -> Pause it
        elif vc.is_playing():
            vc.pause()
            state.STATE.is_paused, state.STATE.pause_start = True, time.time()
            button.emoji = "▶️"
            button.style = discord.ButtonStyle.success # Green for "Resume"

        # 3. Currently Paused -> Resume it
        elif vc.is_paused():
            vc.resume()
            if hasattr(state.STATE, 'pause_start'): # Safety check
                state.STATE.start_t += (time.time() - state.STATE.pause_start)
            state.STATE.is_paused = False
            button.emoji = "⏸️"
            button.style = discord.ButtonStyle.secondary

        # Always update the view to reflect button changes
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild.voice_client: 
            interaction.guild.voice_client.stop()
        await interaction.response.defer()

    @discord.ui.button(label="", style=discord.ButtonStyle.secondary, emoji="🔀")
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = str(interaction.guild.id)
        if gid in state.SONG_QUEUES:
            q_list = list(state.SONG_QUEUES[gid])
            random.shuffle(q_list)
            state.SONG_QUEUES[gid] = deque(q_list)
        await interaction.response.defer()
    
    @discord.ui.button(label="", style=discord.ButtonStyle.secondary, emoji="🗑️")
    async def clear_queue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = str(interaction.guild.id)
        if gid in state.SONG_QUEUES:
            state.SONG_QUEUES[gid].clear()
            # Lively feedback: Change label to show it worked
            button.label = "Cleared!"
            button.disabled = True # Briefly disable to prevent spam
            await interaction.response.edit_message(view=self)
            
            # Wait 2 seconds then reset the button look
            await asyncio.sleep(2)
            button.label = ""
            button.disabled = False
            await interaction.edit_original_response(view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = str(interaction.guild.id)
        if gid in state.SONG_QUEUES: state.SONG_QUEUES[gid].clear()
        
        vc = interaction.guild.voice_client
        if vc:
            state.STATE.start_t = 0
            await vc.disconnect()
            
        # Reset the player to its "Idle" state instead of clearing it
        idle_embed = discord.Embed(
            title="Halfling Bard | Ready",
            description="🎶 **Status:** Idle\nClick 'Add Song' to start the music!",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=idle_embed, view=self)
        
    @discord.ui.button(label="Show Queue", style=discord.ButtonStyle.secondary, emoji="📜")
    async def show_queue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. Tell Discord to wait (This is your first response)
        await interaction.response.defer(ephemeral=True)
        
        gid = str(interaction.guild.id)
        queue_items = list(state.SONG_QUEUES.get(gid, [])) 
        
        if not queue_items:
            # Use followup because we already deferred
            msg = await interaction.followup.send("Queue is currently empty!", ephemeral=True, wait=True)
            asyncio.create_task(delete_after_delay(msg, 3))
            return msg
            
        # 2. Generate pages
        full_list = [f"**{i+1}.** {item[1]}" for i, item in enumerate(queue_items)]
        pages = ["\n".join(full_list[i:i+15]) for i in range(0, len(full_list), 15)]
        
        # 3. Create the view and send via FOLLOWUP
        view = QueueView(pages, interaction.user.id)
        await interaction.followup.send(embed=view.create_embed(), view=view, ephemeral=True)
        
    @discord.ui.button(label="Help", style=discord.ButtonStyle.secondary, emoji="❓", row=1)
    async def help_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🎵 Music Bot Help Menu",
            description="Available commands:",
            color=discord.Color.blue()
        )
        embed.add_field(name="!play <name>", value="Plays a song or folder from the library.", inline=False)
        embed.add_field(name="!search <query/link>", value="Search YT or play a direct link.", inline=False)
        embed.add_field(name="!library", value="Lists all local folders.", inline=False)
        embed.add_field(name="!queue", value="Shows the current song list.", inline=False)
        
        # Because this is a BUTTON click, ephemeral=True works!
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @discord.ui.button(label="Library", style=discord.ButtonStyle.primary, emoji="📁", row=1)
    async def library_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Spawns the new Library Browser
        view = LibraryGrid(interaction.user.id, interaction, self.music_cog)
        embed = view.get_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
    @discord.ui.button(label="Add Song", style=discord.ButtonStyle.success, emoji="🔍", row=1)
    async def search_modal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal(self.music_cog))
        
class SearchModal(discord.ui.Modal, title="Request a Song or Link"):
    query = discord.ui.TextInput(label="Song Name or YouTube Link", placeholder="e.g. Linkin Park Numb", required=True)

    def __init__(self, music_cog):
        super().__init__()
        self.music_cog = music_cog

    async def on_submit(self, interaction: discord.Interaction):

        
        # 1. Defer to give the bot time for fuzzy searching and YT API calls
        await interaction.response.defer(ephemeral=True)
        msg = await interaction.followup.send(f"✅ Processing: **{self.query.value}**", ephemeral=True) 
        
        # 2. Voice Check & Auto-Join (Essential for the play logic to follow)
        if not interaction.user.voice:
            return await interaction.followup.send("❌ You must be in a voice channel first!", ephemeral=True)
            
        vc = interaction.guild.voice_client
        if not vc:
            vc = await interaction.user.voice.channel.connect()
        elif vc.channel != interaction.user.voice.channel:
            await vc.move_to(interaction.user.voice.channel)

        # 3. Create Context and fix the author
        ctx = await self.music_cog.bot.get_context(interaction.message)
        ctx.author = interaction.user 

        # 4. Trigger the "Smart" logic we just built
        await self.music_cog.smart_play(ctx, self.query.value, interaction)
        
        asyncio.create_task(delete_after_delay(msg, 2))  
        
        
class LibraryGrid(discord.ui.View):
    def __init__(self, user_id, interaction, music_cog, folder=None, page=0):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.folder = folder
        self.page = page
        self.files = []
        self.confirm_play_all = False
        self.opening_interaction = interaction
        self.music_cog = music_cog
        if folder:
            path = os.path.join(config.MUSIC_FOLDER, folder)
            # Find all opus files in the selected folder
            self.files = sorted(glob.glob(os.path.join(path, '*.opus')))
        
        self.create_interface()

    def create_interface(self):
        self.clear_items()
        
        # --- FOLDER VIEW (Logic remains same) ---
        if not self.folder:
            folders = sorted([e.name for e in os.scandir(config.MUSIC_FOLDER) if e.is_dir()])
            for f_name in folders[:25]:
                btn = discord.ui.Button(label=f_name[:20], style=discord.ButtonStyle.secondary, emoji="📁")
                btn.callback = self.make_folder_callback(f_name)
                self.add_item(btn)
            return

        # --- SONG VIEW (Dynamic Numbering) ---
        start_index = self.page * 20
        end_index = start_index + 20
        current_batch = self.files[start_index:end_index]

        for i, full_path in enumerate(current_batch):
            title = os.path.basename(full_path)[:-5]
            
            # This calculates 21, 22, 23... on page 1
            display_number = start_index + i + 1 
            
            btn = discord.ui.Button(
                label=str(display_number), 
                style=discord.ButtonStyle.primary,
                row=i // 5  # Keep buttons in 4 rows of 5
            )
            btn.callback = self.make_song_callback(full_path, title)
            self.add_item(btn)

        self.add_nav_row()

    async def play_all_folder(self, interaction: discord.Interaction):
        # 1. First Click: Priming and Locking the button
        if not self.confirm_play_all:
            self.confirm_play_all = True
            
            # Find the button and LOCK it
            for item in self.children:
                if getattr(item, 'label', None) == "Play All":
                    item.label = "Wait..."
                    item.style = discord.ButtonStyle.secondary # Grey for "Inactive"
                    item.disabled = True 
                    item.emoji = "⏳"
            
            await interaction.response.edit_message(view=self)
            
            # Phase A: Wait 3 seconds
            await asyncio.sleep(3)
            
            # Phase B: Enable the button for the "Confirmation Window"
            for item in self.children:
                if getattr(item, 'label', None) == "Wait...":
                    item.label = "Confirm: Play All?"
                    item.style = discord.ButtonStyle.danger # Red for "Action needed"
                    item.disabled = False 
                    item.emoji = "⚠️"
            
            await interaction.edit_original_response(view=self)
            
            # Phase C: Wait 5 more seconds for the user to click
            await asyncio.sleep(5)
            
            # Reset if no click happens
            if self.confirm_play_all:
                self.confirm_play_all = False
                for item in self.children:
                    if getattr(item, 'label', None) == "Confirm: Play All?":
                        item.label = "Play All"
                        item.style = discord.ButtonStyle.success 
                        item.disabled = False
                        item.emoji = "📁"
                try:
                    await interaction.edit_original_response(view=self)
                except: pass
            return

        # 2. Second Click: Execution
        self.confirm_play_all = False 
        await interaction.response.defer(ephemeral=True)
        
        gid = str(interaction.guild.id)
        if gid not in state.SONG_QUEUES: state.SONG_QUEUES[gid] = deque()
        
        for full_path in self.files:
            title = os.path.basename(full_path)[:-5]
            state.SONG_QUEUES[gid].append((full_path, title))
            
        msg = await interaction.followup.send(f"✅ Added {len(self.files)} songs to queue!", ephemeral=True)
        asyncio.create_task(delete_after_delay(interaction, 3))

        # Revert button appearance
        for item in self.children:
            if getattr(item, 'label', None) == "Are you sure?":
                item.label = "Play All"
                item.style = discord.ButtonStyle.success
                item.emoji = "📁"
        await interaction.edit_original_response(view=self)

        # --- FIX: START ENGINE WITH JOIN LOGIC ---
        vc = interaction.guild.voice_client
        
        # If not in VC, try to join the user
        if not vc:
            if interaction.user.voice:
                vc = await interaction.user.voice.channel.connect()
            else:
                # We can't use interaction.response here because we already deferred
                return await interaction.followup.send("You need to be in a voice channel!", ephemeral=True)

        if vc and not vc.is_playing() and not vc.is_paused():
            await self.music_cog.play_next_song(vc, gid, interaction.channel)

    def add_nav_row(self):
        # 1. Back to Folders (Always Row 4)
        back_btn = discord.ui.Button(label="Folders", style=discord.ButtonStyle.danger, row=4)
        back_btn.callback = self.go_back
        self.add_item(back_btn)

        # 2. Previous Page Arrow
        # Disabled if we are on the first page (0)
        is_first_page = (self.page == 0)
        prev_btn = discord.ui.Button(
            emoji="◀️", 
            style=discord.ButtonStyle.secondary, 
            row=4, 
            disabled=is_first_page
        )
        prev_btn.callback = self.prev_page
        self.add_item(prev_btn)
        
        play_all_btn = discord.ui.Button(
            label="Play All", 
            emoji="📁", 
            style=discord.ButtonStyle.success, 
            row=4)
        play_all_btn.callback = self.play_all_folder
        self.add_item(play_all_btn)
            
        # 3. Next Page Arrow
        # Disabled if there are no more songs to show
        is_last_page = len(self.files) <= (self.page + 1) * 20
        next_btn = discord.ui.Button(
            emoji="▶️", 
            style=discord.ButtonStyle.secondary, 
            row=4, 
            disabled=is_last_page
        )
        next_btn.callback = self.next_page
        self.add_item(next_btn)

        # 4. Close Menu
        close_btn = discord.ui.Button(label="Close", style=discord.ButtonStyle.secondary, row=4)
        close_btn.callback = self.close_menu
        self.add_item(close_btn)

    def get_embed(self):
        if not self.folder:
            return discord.Embed(title="📚 Music Library", description="Select a folder", color=discord.Color.blue())

        start_index = self.page * 20
        current_batch = self.files[start_index : start_index + 20]
        
        song_list = ""
        for i, path in enumerate(current_batch):
            title = os.path.basename(path)[:-5]
            # Match the button number in the text list
            display_number = start_index + i + 1
            song_list += f"`{display_number:02}.` {title[:50]}\n"

        embed = discord.Embed(
            title=f"📁 {self.folder}",
            description=song_list or "Empty.",
            color=discord.Color.gold()
        )
        total_pages = (len(self.files) - 1) // 20 + 1
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages} | Songs {start_index + 1}-{start_index + len(current_batch)}")
        return embed

    # --- Callbacks ---
    def make_folder_callback(self, name):
        async def callback(interaction: discord.Interaction):
            new_view = LibraryGrid(self.user_id, interaction, self.music_cog, folder=name)
            await interaction.response.edit_message(embed=new_view.get_embed(), view=new_view)
        return callback

    def make_song_callback(self, path, title):
        async def callback(interaction: discord.Interaction):
            # 1. ADD THIS LINE - It fixes the "Unknown Webhook" error
            await interaction.response.defer(ephemeral=True)

            gid = str(interaction.guild.id)
            if gid not in state.SONG_QUEUES: state.SONG_QUEUES[gid] = deque()
            state.SONG_QUEUES[gid].append((path, title))
            
            # 2. Use .send() (Correct for followups)
            msg = await interaction.followup.send(f"✅ Queued: **{title}**", ephemeral=True)
            
            # 3. Handle deletion in the background 
            # (So the bot starts playing music IMMEDIATELY without waiting 5 seconds)
            asyncio.create_task(delete_after_delay(interaction, 5))
            
            # 4. Voice logic
            vc = interaction.guild.voice_client
            # Add auto-connect if bot isn't in channel
            if not vc and interaction.user.voice:
                vc = await interaction.user.voice.channel.connect()

            if vc and not vc.is_playing() and not vc.is_paused():
                await self.music_cog.play_next_song(vc, gid, interaction.channel)

        return callback

    async def go_back(self, interaction):
        new_view = LibraryGrid(self.user_id,interaction, self.music_cog, folder=None)
        await interaction.response.edit_message(embed=new_view.get_embed(), view=new_view)

    async def next_page(self, interaction):
        self.page += 1
        self.create_interface()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def prev_page(self, interaction):
        self.page -= 1
        self.create_interface()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def close_menu(self, interaction):
        await interaction.response.edit_message(content="Library closed.", embed=None, view=None, delete_after=2)
    
    async def on_timeout(self):
        """This triggers automatically after 60 seconds of inactivity."""
        try:
            # Check if we have the interaction stored to perform the delete
            if hasattr(self, 'opening_interaction'):
                await self.opening_interaction.delete_original_response()
            else:
                # If you haven't renamed 'user_id' to store the interaction yet,
                # you'll need to pass the interaction in your __init__ 
                # as we discussed in the previous step!
                pass
        except Exception:
            pass # Message likely already deleted or interaction expired
    

class QueueView(discord.ui.View):
    def __init__(self, pages, author_id, current_page=0):
        super().__init__(timeout=60)
        self.pages = pages
        self.author_id = author_id
        self.current_page = current_page

    def create_embed(self):
        # Fallback if pages list is somehow empty to prevent IndexError
        if not self.pages:
            return discord.Embed(title="🎶 Current Queue", description="The queue is currently empty.", color=0x3498db)
            
        page_content = self.pages[self.current_page]
        embed = discord.Embed(
            title="🎶 Current Queue", 
            description=page_content, 
            color=0x3498db
        )
        embed.set_footer(text=f"Page {self.current_page + 1} of {len(self.pages)}")
        return embed

    @discord.ui.button(label="", emoji="⬅️", style=discord.ButtonStyle.gray)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="", emoji="➡️", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.defer()
            
class PlaylistSelectView(discord.ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=30)
        self.choice = None
        self.author_id = author_id

    @discord.ui.button(label="Just the Song", style=discord.ButtonStyle.primary)
    async def song_only(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id: 
            return await interaction.response.send_message("This isn't your menu!", ephemeral=True)
        self.choice = "song"
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Entire Playlist", style=discord.ButtonStyle.success)
    async def entire_playlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id: 
            return await interaction.response.send_message("This isn't your menu!", delete_after=3)
        self.choice = "playlist"
        self.stop()
        await interaction.response.defer()
    
    




class YouTubeSelectionView(discord.ui.View):
    def __init__(self, ctx, results, music_cog):
        super().__init__(timeout=30)
        self.ctx = ctx
        self.results = results
        self.music_cog = music_cog
        self.selection = None

    async def handle_selection(self, interaction: discord.Interaction, index: int):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message("This isn't your search!", ephemeral=True)
        
        self.selection = self.results[index]
        self.stop()
        # CHECK THE FOLLOWING CODE SEE IF YOU CAN REMOVE THE IF AND MAKE SURE AN INTERACTION EXISTS OR NOT.
        if interaction.response.is_done(): msg = await interaction.edit_original_response(content=f"✅ Selected: **{self.selection['title']}**", view=None)
        else: 
            await interaction.response.edit_message(content=f"✅ Selected: **{self.selection['title']}**", view=None)
            msg = await interaction.original_response()
        asyncio.create_task(delete_after_delay(msg, 3))

    @discord.ui.button(label="1", style=discord.ButtonStyle.primary)
    async def sel_1(self, interaction, button): await self.handle_selection(interaction, 0)
    @discord.ui.button(label="2", style=discord.ButtonStyle.primary)
    async def sel_2(self, interaction, button): await self.handle_selection(interaction, 1)
    @discord.ui.button(label="3", style=discord.ButtonStyle.primary)
    async def sel_3(self, interaction, button): await self.handle_selection(interaction, 2)
    @discord.ui.button(label="4", style=discord.ButtonStyle.primary)
    async def sel_4(self, interaction, button): await self.handle_selection(interaction, 3)
    @discord.ui.button(label="5", style=discord.ButtonStyle.primary)
    async def sel_5(self, interaction, button): await self.handle_selection(interaction, 4)
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        self.stop()
        if interaction.response.is_done(): msg = await interaction.edit_original_response(content="❌ Search cancelled.", view=None)
        else: 
            await interaction.response.edit_message(content="❌ Search cancelled.", view=None)
            msg = await interaction.original_response()
        
        asyncio.create_task(delete_after_delay(msg, 3))
