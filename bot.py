import os
import sqlite3
import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from credits_manager import verify_and_get_credit

# Load environment variables from .env file
load_dotenv()

# Verify encrypted author attribution lock
CREATOR_CREDIT = verify_and_get_credit()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
PORT = int(os.getenv("PORT", 8080))  # Render sets PORT automatically (default: 10000)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Render Web Server (For Ping Bot / UptimeRobot) ---
async def handle_ping(request):
    """Health check endpoint for ping monitors like UptimeRobot"""
    return web.Response(text="🟢 Bot is alive and running!", content_type="text/plain")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web server started on port {PORT} (ready for pings)")


# --- SQLite Database Initialization ---
DB_PATH = "counters.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS server_configs (
        guild_id TEXT PRIMARY KEY,
        channel_id TEXT NOT NULL,
        yt_channel_id TEXT NOT NULL,
        yt_title TEXT NOT NULL,
        display_template TEXT DEFAULT '🔴 Subs: {subs}'
    )
    """
)
conn.commit()


def format_sub_count(count: int) -> str:
    """Format large numbers cleanly (e.g. 1500 -> 1.5K, 2400000 -> 2.4M)."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.2f}M"
    elif count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


async def fetch_youtube_data(yt_query: str) -> tuple[str | None, str | None, int | None]:
    """
    Resolves YouTube Channel ID, Title, and Subscriber Count.
    Accepts:
      - Channel ID: 'UC_x5XG1OV2P6uZZ5FSM9Ttw'
      - Handle: '@MrBeast' or 'MrBeast'
    Returns: (channel_id, title, subscriber_count) or (None, None, None) on failure.
    """
    yt_query = yt_query.strip()
    base_url = "https://www.googleapis.com/youtube/v3/channels"

    # Determine whether user gave handle (@name) or direct channel ID (UC...)
    if yt_query.startswith("UC") and len(yt_query) == 24:
        params = {"part": "snippet,statistics", "id": yt_query, "key": YOUTUBE_API_KEY}
    else:
        handle = yt_query if yt_query.startswith("@") else f"@{yt_query}"
        params = {"part": "snippet,statistics", "forHandle": handle, "key": YOUTUBE_API_KEY}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(base_url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("items", [])
                    if items:
                        item = items[0]
                        channel_id = item.get("id")
                        title = item.get("snippet", {}).get("title", "Unknown")
                        stats = item.get("statistics", {})
                        subs = int(stats.get("subscriberCount", 0))
                        return channel_id, title, subs
                else:
                    err_json = await resp.json()
                    print(f"YouTube API Error [{resp.status}]: {err_json}")
        except Exception as e:
            print(f"Network error querying YouTube API: {e}")

    return None, None, None


@bot.event
async def setup_hook():
    # Start web server for Render & ping monitors
    await start_web_server()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"✨ Verified Author: {CREATOR_CREDIT}")
    try:
        synced = await bot.tree.sync()
        print(f"Successfully synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Error syncing slash commands: {e}")

    if not counter_update_loop.is_running():
        counter_update_loop.start()


# --- Slash Commands ---

@bot.tree.command(
    name="setup-counter",
    description="Set or edit the YouTube subscriber counter channel for this server."
)
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(
    channel="The Voice or Text channel to rename with the live count",
    youtube_channel="Channel ID (UC...) or Handle (@MrBeast)",
    template="Name format (default: '🔴 Subs: {subs}')"
)
async def setup_counter(
    interaction: discord.Interaction,
    channel: discord.abc.GuildChannel,
    youtube_channel: str,
    template: str = "🔴 Subs: {subs}"
):
    await interaction.response.defer(ephemeral=True)

    # Permission check: can the bot manage this channel?
    bot_member = interaction.guild.me
    if not channel.permissions_for(bot_member).manage_channels:
        await interaction.followup.send(
            f"❌ I do not have permission to manage {channel.mention}. "
            "Please ensure my bot role has **Manage Channels** and is placed higher than this channel in role hierarchy.",
            ephemeral=True
        )
        return

    # Fetch YouTube details
    yt_id, yt_title, subs = await fetch_youtube_data(youtube_channel)
    if yt_id is None or subs is None:
        await interaction.followup.send(
            f"❌ Could not find YouTube channel for `{youtube_channel}`.\n"
            "Try using the exact channel ID (starts with `UC...`) or handle (e.g., `@YouTube`).",
            ephemeral=True
        )
        return

    # Validate template
    if "{subs}" not in template:
        template += " {subs}"

    # Save to SQLite
    cursor.execute(
        """
        INSERT OR REPLACE INTO server_configs (guild_id, channel_id, yt_channel_id, yt_title, display_template)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(interaction.guild_id), str(channel.id), yt_id, yt_title, template)
    )
    conn.commit()

    # Immediate channel rename
    formatted_count = format_sub_count(subs)
    new_name = template.replace("{subs}", formatted_count)
    try:
        await channel.edit(name=new_name)
        embed = discord.Embed(
            title="✅ Counter Configured Successfully!",
            color=discord.Color.green()
        )
        embed.add_field(name="YouTube Channel", value=f"**{yt_title}** (`{yt_id}`)", inline=False)
        embed.add_field(name="Counter Channel", value=channel.mention, inline=True)
        embed.add_field(name="Current Subscribers", value=formatted_count, inline=True)
        embed.add_field(name="Display Format", value=f"`{new_name}`", inline=False)
        embed.set_footer(text=f"{CREATOR_CREDIT} • Updates every 10m")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(
            f"⚠️ Saved to database, but failed to rename {channel.mention}. Check bot channel permissions.",
            ephemeral=True
        )


@bot.tree.command(name="credits", description="View creator and bot attribution details.")
async def credits_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Bot Information",
        description=f"**{CREATOR_CREDIT}**\n\nAutomated YouTube Live Subscriber Counter Bot for Discord.",
        color=discord.Color.gold()
    )
    embed.set_footer(text="Protected by Creator Lock (Passcode Protected)")
    await interaction.response.send_message(embed=embed, ephemeral=False)


@bot.tree.command(name="counter-status", description="Check the current counter configuration for this server.")
async def counter_status(interaction: discord.Interaction):
    cursor.execute(
        "SELECT channel_id, yt_channel_id, yt_title, display_template FROM server_configs WHERE guild_id = ?",
        (str(interaction.guild_id),)
    )
    row = cursor.fetchone()

    if not row:
        await interaction.response.send_message(
            "ℹ️ No counter has been configured for this server yet. Use `/setup-counter` to get started.",
            ephemeral=True
        )
        return

    channel_id, yt_id, yt_title, template = row
    channel = interaction.guild.get_channel(int(channel_id))
    channel_text = channel.mention if channel else f"Deleted Channel (`{channel_id}`)"

    embed = discord.Embed(title="📊 YouTube Sub Counter Status", color=discord.Color.blue())
    embed.add_field(name="Target Channel", value=channel_text, inline=True)
    embed.add_field(name="YouTube Channel", value=f"**{yt_title}** (`{yt_id}`)", inline=True)
    embed.add_field(name="Template", value=f"`{template}`", inline=False)
    embed.set_footer(text=CREATOR_CREDIT)
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="stop-counter", description="Remove and disable the YouTube sub counter for this server.")
@app_commands.checks.has_permissions(manage_channels=True)
async def stop_counter(interaction: discord.Interaction):
    cursor.execute("DELETE FROM server_configs WHERE guild_id = ?", (str(interaction.guild_id),))
    conn.commit()
    await interaction.response.send_message("✅ Counter disabled and removed from this server.", ephemeral=True)


# --- 10-Minute Background Refresh Task ---
@tasks.loop(minutes=10)
async def counter_update_loop():
    """
    Discord restricts channel renames to 2 per 10 minutes per channel.
    Running every 10 minutes guarantees no rate-limit bans (HTTP 429).
    """
    cursor.execute("SELECT guild_id, channel_id, yt_channel_id, display_template FROM server_configs")
    configs = cursor.fetchall()

    for guild_id, channel_id, yt_id, template in configs:
        try:
            guild = bot.get_guild(int(guild_id))
            if not guild:
                continue

            channel = guild.get_channel(int(channel_id))
            if not channel:
                continue

            _, _, subs = await fetch_youtube_data(yt_id)
            if subs is not None:
                formatted = format_sub_count(subs)
                target_name = template.replace("{subs}", formatted)
                if channel.name != target_name:
                    await channel.edit(name=target_name)
        except Exception as e:
            print(f"Error updating guild {guild_id}: {e}")


@counter_update_loop.before_loop
async def before_counter_update_loop():
    await bot.wait_until_ready()


if __name__ == "__main__":
    if not DISCORD_TOKEN or not YOUTUBE_API_KEY:
        print("CRITICAL: Set DISCORD_TOKEN and YOUTUBE_API_KEY before running the bot.")
    else:
        bot.run(DISCORD_TOKEN)
