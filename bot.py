import os
import re
import asyncio
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
intents.members = True
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


def parse_youtube_input(yt_query: str) -> list[dict]:
    """
    Parses any YouTube profile URL, channel link, handle, or channel ID.
    Accepts:
      - Full profile URLs: https://www.youtube.com/@Cr7busta_7
      - Profile URLs with subpaths/query: https://www.youtube.com/@Cr7busta_7/videos?si=123
      - Direct Channel URLs: https://www.youtube.com/channel/UCvXwFBdljcafO-bkOELVU9g
      - Custom URLs: https://www.youtube.com/c/CustomName
      - Legacy URLs: https://www.youtube.com/user/UserName
      - Handles: @Cr7busta_7 or Cr7busta_7
      - Direct Channel IDs: UCvXwFBdljcafO-bkOELVU9g
    """
    query = yt_query.strip()

    # 1. Direct Channel ID (starts with UC and has 24 chars)
    channel_id_match = re.search(r"(UC[a-zA-Z0-9_\-]{22})", query)
    if channel_id_match:
        return [{"id": channel_id_match.group(1)}]

    # 2. @Handle anywhere in the URL or text
    handle_match = re.search(r"@([a-zA-Z0-9_\-\.]+)", query)
    if handle_match:
        handle = "@" + handle_match.group(1)
        return [{"forHandle": handle}]

    # 3. /user/ or /c/ in URL
    user_match = re.search(r"/(?:user|c)/([a-zA-Z0-9_\-]+)", query)
    if user_match:
        name = user_match.group(1)
        return [{"forHandle": f"@{name}"}, {"forUsername": name}]

    # 4. Clean URL fallback
    if "youtube.com" in query or "youtu.be" in query:
        clean_name = query.split("?")[0].rstrip("/").split("/")[-1]
        if clean_name:
            return [{"forHandle": f"@{clean_name.lstrip('@')}"}, {"forUsername": clean_name}]

    # 5. Raw string fallback
    clean_str = query.lstrip("@").strip()
    return [{"forHandle": f"@{clean_str}"}, {"forUsername": clean_str}]


async def fetch_youtube_data(yt_query: str) -> tuple[str | None, str | None, int | None]:
    """Resolves YouTube Channel ID, Title, and Subscriber Count from any link or handle."""
    base_url = "https://www.googleapis.com/youtube/v3/channels"
    attempts = parse_youtube_input(yt_query)

    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for params in attempts:
            params["part"] = "snippet,statistics"
            params["key"] = YOUTUBE_API_KEY
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
            except Exception as e:
                print(f"Error querying YouTube with {params}: {e}")

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
    try:
        # Resolve real channel object from guild or bot
        actual_channel = interaction.guild.get_channel(channel.id) or channel

        # Fetch YouTube details fast
        yt_id, yt_title, subs = await fetch_youtube_data(youtube_channel)
        if yt_id is None or subs is None:
            await interaction.response.send_message(
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

        # Format count & prepare embed
        formatted_count = format_sub_count(subs)
        new_name = template.replace("{subs}", formatted_count)

        embed = discord.Embed(
            title="✅ Counter Configured Successfully!",
            description=f"Now tracking **{yt_title}** in {actual_channel.mention}",
            color=discord.Color.green()
        )
        embed.add_field(name="YouTube Channel", value=f"**{yt_title}** (`{yt_id}`)", inline=False)
        embed.add_field(name="Counter Channel", value=actual_channel.mention, inline=True)
        embed.add_field(name="Current Subscribers", value=formatted_count, inline=True)
        embed.add_field(name="Display Format", value=f"`{new_name}`", inline=False)
        embed.set_footer(text=f"{CREATOR_CREDIT} • Updates every 1m")

        # Send response INSTANTLY with send_message (ZERO loading animation / NO "thinking...")
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Run channel rename in background so Discord never lags
        async def background_rename():
            try:
                chan = interaction.guild.get_channel(channel.id) or await bot.fetch_channel(channel.id)
                await chan.edit(name=new_name)
                print(f"[SETUP] Renamed channel to '{new_name}'")
            except Exception as rename_err:
                print(f"[SETUP] Note on rename: {rename_err}")

        asyncio.create_task(background_rename())

    except Exception as e:
        print(f"Error in setup_counter: {e}")
        if interaction.response.is_done():
            await interaction.followup.send(f"⚠️ Error: {e}", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ Error: {e}", ephemeral=True)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"Global App Command Error: {error}")
    msg = f"❌ Error: {error}"
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


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


@bot.tree.command(name="stop-counter", description="Remove and disable the YouTube sub counter for this server.")
@app_commands.checks.has_permissions(manage_channels=True)
async def stop_counter(interaction: discord.Interaction):
    cursor.execute("DELETE FROM server_configs WHERE guild_id = ?", (str(interaction.guild_id),))
    conn.commit()
    await interaction.response.send_message("✅ Counter disabled and removed from this server.", ephemeral=True)


# --- 1-Minute Background Refresh Task ---
@tasks.loop(minutes=1)
async def counter_update_loop():
    """
    Checks YouTube every 1 minute.
    Only renames the channel if the subscriber count actually changed.
    Uses non-blocking timeout to prevent Discord 429 rate-limit freezes.
    """
    cursor.execute("SELECT guild_id, channel_id, yt_channel_id, display_template FROM server_configs")
    configs = cursor.fetchall()

    if not configs:
        return

    print(f"[LOOP] Running update check for {len(configs)} configured counter(s)...")

    for guild_id, channel_id, yt_id, template in configs:
        try:
            # Fetch channel reliably across cache and API
            channel = bot.get_channel(int(channel_id))
            if not channel:
                try:
                    channel = await bot.fetch_channel(int(channel_id))
                except Exception as fetch_err:
                    print(f"[LOOP] Could not fetch channel {channel_id}: {fetch_err}")
                    continue

            _, yt_title, subs = await fetch_youtube_data(yt_id)
            if subs is not None:
                formatted = format_sub_count(subs)
                target_name = template.replace("{subs}", formatted)
                print(f"[LOOP] Channel: '{channel.name}' | YouTube: {subs} subs | Target: '{target_name}'")

                if channel.name != target_name:
                    try:
                        # Non-blocking rename (so Discord 429 rate limits don't freeze the loop)
                        await asyncio.wait_for(channel.edit(name=target_name), timeout=3.0)
                        print(f"[LOOP] Successfully renamed channel to '{target_name}'")
                    except asyncio.TimeoutError:
                        print(f"[LOOP] Discord rate-limited channel {channel_id} (max 2 per 10m). Will retry next minute.")
                    except Exception as edit_err:
                        print(f"[LOOP] Error editing channel {channel_id}: {edit_err}")
        except Exception as e:
            print(f"[LOOP] Error updating guild {guild_id}: {e}")


@counter_update_loop.before_loop
async def before_counter_update_loop():
    await bot.wait_until_ready()


if __name__ == "__main__":
    if not DISCORD_TOKEN or not YOUTUBE_API_KEY:
        print("CRITICAL: Set DISCORD_TOKEN and YOUTUBE_API_KEY before running the bot.")
    else:
        bot.run(DISCORD_TOKEN)
