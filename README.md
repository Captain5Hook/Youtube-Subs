# YouTube Subscriber Counter Discord Bot 🔴

A multi-server Discord bot that automatically tracks YouTube subscriber counts and updates a dedicated channel name every 10 minutes.

---

## ⚡ Features
- **Per-Server Customization**: Each server can track its own YouTube channel, select its own channel, and customize the name format.
- **Handles & Channel IDs**: Supports `@handles` (e.g. `@MrBeast`) or Channel IDs (`UC...`).
- **Slash Commands**:
  - `/setup-counter <channel> <youtube_channel> [template]`: Configure or edit the counter.
  - `/counter-status`: Check current server configuration.
  - `/stop-counter`: Disable tracking for the server.
- **Discord Rate-Limit Compliant**: Runs updates every 10 minutes to respect Discord's strict 2-edits-per-10-minute channel rename limit.
- **Zero Cost 24/7 Hosting Ready**: Pre-configured with `discloud.config` for 100% free hosting.

---

## 🛠️ Step 1: Getting Required API Keys

### 1. Discord Bot Token
1. Go to [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application**, name it, and go to **Bot**.
3. Click **Reset Token** and copy the token.
4. Under **Privileged Gateway Intents**, enable:
   - `Server Members Intent`
5. Go to **OAuth2 > URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Manage Channels`, `Send Messages`, `View Channels`, `Connect`
   - Copy the invite link and invite the bot to your server.
   > **Important**: In Server Settings > Roles, make sure the bot's role is positioned **above** the counter channels.

### 2. YouTube Data API v3 Key
1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (or select an existing one).
3. Search for **YouTube Data API v3** in the search bar and click **Enable**.
4. Go to **Credentials** > **Create Credentials** > **API Key**.
5. Copy the generated API key.

---

## 💻 Step 2: Running Locally

1. Create a `.env` file from `.env.example`:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and fill in your keys:
   ```env
   DISCORD_TOKEN=your_bot_token
   YOUTUBE_API_KEY=your_youtube_api_key
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the bot:
   ```bash
   python bot.py
   ```

---

## 🌐 Step 3: Deploy to Render & Keep 24/7 Online with a Ping Bot

Render shuts down inactive free web services after 15 minutes unless an HTTP request hits it. The bot now includes a lightweight web server built-in so ping services can keep it awake forever!

### 1. Push your code to GitHub
1. Create a **Private or Public** repository on [GitHub](https://github.com/new).
2. Upload the bot files (`bot.py`, `requirements.txt`, `README.md`).
   > ⚠️ **Never commit your `.env` file or your Discord/YouTube tokens to GitHub!**

### 2. Create Web Service on Render
1. Go to [Render](https://dashboard.render.com/) and click **New > Web Service**.
2. Connect your GitHub repository.
3. Configure the settings:
   - **Name**: `yt-counter-bot`
   - **Language**: `Python 3`
   - **Region**: Choose the closest one to you
   - **Branch**: `main`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
   - **Instance Type**: `Free`
4. Under **Environment Variables**, add:
   - Key: `DISCORD_TOKEN` -> Value: `your_discord_bot_token`
   - Key: `YOUTUBE_API_KEY` -> Value: `your_google_cloud_api_key`
5. Click **Deploy Web Service**.
6. When deployment finishes, copy your Render app URL (e.g., `https://yt-counter-bot-xxxx.onrender.com`).

### 3. Set Up Free Ping Bot (e.g. UptimeRobot or Cron-job.org)
1. Go to [UptimeRobot](https://uptimerobot.com/) (100% free for 50 monitors).
2. Click **Add New Monitor**:
   - **Monitor Type**: `HTTP(s)`
   - **Friendly Name**: `Discord Bot Pinger`
   - **URL (or IP)**: Paste your Render URL (`https://yt-counter-bot-xxxx.onrender.com`)
   - **Monitoring Interval**: `5 minutes` or `10 minutes`
3. Click **Create Monitor**.

🎉 Every 5–10 minutes, UptimeRobot will ping your Render service, preventing it from ever going to sleep!

