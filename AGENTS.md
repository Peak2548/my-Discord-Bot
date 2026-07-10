# Discord Bot Setup & Troubleshooting

## 🚀 Quick Start

```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
echo "TOKEN=your-discord-token-here" > .env
.\Start.bat
```

## ⚠️ Critical Issues & Fixes

### 1. Python 3.12+ `audioop` Module Error
**Error**: `ModuleNotFoundError: No module named 'audioop'`  
**Fix**: `pip install audioop-linalg`

### 2. Missing .env File
Bot exits with "TOKEN not found" error if `.env` is missing.  
**Fix**: `echo "TOKEN=your-bot-token-here" > .env`

### 3. aiohttp DNS Resolution Fix
MainBot.py line 40 uses `aiohttp.ThreadedResolver()` to avoid DNS failures on some systems. Do not remove this line.

### 4. Missing pause Command
BotCommands.py line 259-265: `pause` method missing `@commands.command(name="pause")` decorator - bot won't respond to `!pause`.

### 5. Blocking requests in async functions
BotCommands.py line 304/375: `requests.post()` must be wrapped with `loop.run_in_executor(None, ...)` or use `aiohttp` instead.

## 🛠️ External Services Required

| Service | Port | Status Check |
|---------|------|--------------|
| LM Studio | 1234 | `http://localhost:1234` - verify model loaded in UI |
| Stable Diffusion WebUI | 7860 | `http://localhost:7860` - ensure checkpoint loaded |

## 📦 Dependencies

```bash
discord.py==2.3.2
python-dotenv
requests
yt-dlp
Pillow
ffmpeg  # System dependency, install from website
pynacl
davey
aiohttp<4,>=3.7.4  # Must be <4 for ThreadedResolver fix
```

## 🔧 Architecture Notes

- **MainBot.py**: Entry point, env loading, DNS resolver fix
- **BotCommands.py**: Music player, AI chat, image generation cogs (loads via `await bot.load_extension("AI")`)
- **AI.py**: Main AI cog implementation with shared group chat memory per channel; deprecated alternative is in BotCommands.py

### AI Cog Details
- Default model: `"local-model"` (auto-uses whatever LM Studio has loaded)
- API: `http://127.0.0.1:1234/v1/chat/completions`
- Uses shared conversation history per Discord channel (see `channel_conversations`)
- Auto-trims history to last 11 messages after system prompt
- Web search auto-triggered by Thai keywords or "search/google/latest"

### Image Generation
- API: `http://127.0.0.1:7860/sdapi/v1/txt2img`
- Default checkpoint: `"sd-v1-4.ckpt"` (line 373 in BotCommands.py)
- Either have the checkpoint file OR change line 373 to your checkpoint name or empty string

## 🔧 Common Fixes

### Voice Channel Connection Issues
Bot has built-in retry logic (3 attempts). If still failing:
- Check Discord server voice settings
- Ensure you're in a voice channel when using commands

## 🧪 Testing Checklist

1. ✅ Python version ≥ 3.8 (use backport for 3.12+)
2. ✅ LM Studio running with model loaded
3. ✅ Stable Diffusion running (for image gen)
4. ✅ FFmpeg installed system-wide
5. ✅ .env file with valid TOKEN
6. ✅ aiohttp version < 4

## 📝 Commands Reference

| Command | Description |
|---------|-------------|
| `!p <url>` | Play song from URL |
| `!j` | Join voice channel |
| `!skip` / `!sk` | Skip current song |
| `!stop` / `!s` | Stop and disconnect |
| `!queue` / `!q` | Show queue |
| `!ai <message>` | Chat with AI (shared group chat, auto web search) |
| `!code <task>` | Generate code |
| `!aiclear` | Clear AI chat history |
| `!models` | Select AI model via dropdown |
| `!summarize <text>` | Summarize text |
| `!image <prompt>` | Generate image (SD required) |
