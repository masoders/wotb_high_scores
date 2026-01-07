import discord
from discord import app_commands
import datetime as dt

from . import config, db, backup, health, webdash, logging_setup
from .commands import help_cmd, highscore, tank, backup_cmd

intents = discord.Intents.default()
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

def _guild_obj():
    return discord.Object(id=config.GUILD_ID) if config.GUILD_ID else None

@bot.event
async def on_ready():
    logging_setup.setup_logging()
    await db.init_db()

    # Start dashboard (read-only HTTP)
    webdash.start_dashboard()

    # Start backup scheduler
    if not backup.weekly_backup_loop.is_running():
        backup.weekly_backup_loop.start(bot)

    # Register commands
    guild = _guild_obj()
    help_cmd.register(tree)
    highscore.register(tree, bot, guild=guild)
    tank.register(tree, bot, guild=guild)
    backup_cmd.register(tree, bot, guild=guild)

    # System health group
    tree.add_command(health.system, guild=guild)

    # Sync
    if guild:
        await tree.sync(guild=guild)
    else:
        await tree.sync()

    print(f"Logged in as {bot.user} (id={bot.user.id})")

def run():
    if not config.DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing")
    bot.run(config.DISCORD_TOKEN)
