import discord
from discord.ext import commands
import asyncio
import config
import state

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

async def main():
    async with bot:
        # Load extensions (cogs)
        await bot.load_extension("cogs.music")
        
        # Run the bot
        if config.TOKEN:
            await bot.start(config.TOKEN)
        else:
            print("Error: DISCORD_TOKEN not found in .env file.")

async def teardown():
    print("\n[Teardown] Bot is closing. Performing final cleanup...")
    if state.STATE.msg:
        try:
            # The bot is still connected to Discord here!
            await state.STATE.msg.delete()
            print("[Teardown] Player UI deleted successfully.")
        except Exception as e:
            print(f"[Teardown] Cleanup failed: {e}")

# We hook our teardown into the bot's close sequence
original_close = bot.close
async def patched_close():
    await teardown()         # Run our cleanup first
    await original_close()   # Then actually shut down
bot.close = patched_close  

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # asyncio.run handles loop cleanup
        pass
