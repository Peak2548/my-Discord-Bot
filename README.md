# my-Discord-Bot 🤖

A powerful Discord bot with AI chat, music player, image generation, and web search capabilities. Powered by LM Studio and Stable Diffusion.

---

## ✨ Features

- **🧠 AI Chat** - Conversational AI with shared group chat memory
- **🔍 Web Search** - Automatic web search for relevant queries using `beautifulsoup4`
- **🎵 Music Player** - Play music from URLs (YouTube, Spotify, etc.)
- **🖼️ Image Generation** - Generate images via Stable Diffusion
- **💬 Code Generator** - Get code snippets for various tasks
- **📝 Text Summarization** - Summarize long texts
- **⏸️ Pause/Resume** - Control bot responses

---

## ☁️ Cloud Deployment (Render + Docker) — ⭐ RECOMMENDED

To host this bot 24/7 on **Render** without `audioop` or `FFmpeg` missing errors, deploy it using **Docker**:

1. Ensure you have `Dockerfile` (using `python:3.11-slim`) and `.dockerignore` in your repository root.
2. Push your latest code (including `beautifulsoup4` in `requirements.txt`) to **GitHub**.
3. On [Render.com](https://render.com), create a **New Web Service** and connect your repository.
4. Set **Language/Runtime** to **`Docker`**.
5. Select the **Free** instance type ($0/month).
6. Under **Environment Variables**, add:
   - **Key:** `TOKEN`
   - **Value:** `your-discord-bot-token-here`
7. Click **Deploy Web Service**.

---

## 🚀 Quick Start (Local Machine)

```bash
# Create virtual environment
python -m venv venv

# Activate it (Windows PowerShell)
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup .env file with your Discord bot token
echo "TOKEN=your-discord-bot-token-here" > .env

# Run the bot
.\Start.bat