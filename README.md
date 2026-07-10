# my-Discord-Bot 🤖

A powerful Discord bot with AI chat, music player, image generation, and web search capabilities. Powered by LM Studio and Stable Diffusion.

---

## ✨ Features

- **🧠 AI Chat** - Conversational AI with shared group chat memory
- **🔍 Web Search** - Automatic web search for relevant queries
- **🎵 Music Player** - Play music from URLs (YouTube, Spotify, etc.)
- **🖼️ Image Generation** - Generate images via Stable Diffusion
- **💬 Code Generator** - Get code snippets for various tasks
- **📝 Text Summarization** - Summarize long texts
- **⏸️ Pause/Resume** - Control bot responses

---

## 🚀 Quick Start

```bash
# Create virtual environment
python -m venv venv

# Activate it
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup .env file with your Discord bot token
echo "TOKEN=your-discord-bot-token-here" > .env

# Run the bot
.\Start.bat
```

---

## 🔧 Installation

### System Requirements

- **Python**: 3.8+ (3.12+ requires `audioop-linalg`)
- **FFmpeg**: For music playback (install from [ffmpeg.org](https://ffmpeg.org/download.html))
- **LM Studio**: Running on port 1234 with a model loaded
- **Stable Diffusion WebUI**: Running on port 7860 (for image generation)

### Dependencies

```bash
pip install -r requirements.txt
```

**Critical:** If you get `ModuleNotFoundError: No module named 'audioop'`, run:
```bash
pip install audioop-linalg
```

---

## ⚙️ Configuration

Create a `.env` file in the root directory:

```env
TOKEN=your-discord-bot-token-here
```

### AI Model Configuration

The bot uses LM Studio with default model `"local-model"`. You can switch models using `!models`.

**API**: `http://127.0.0.1:1234/v1/chat/completions`

### Image Generation

Default checkpoint: `"sd-v1-4.ckpt"` (must exist or set to empty string/your checkpoint name)

**API**: `http://127.0.0.1:7860/sdapi/v1/txt2img`

---

## 📖 Usage Commands

### Music Commands
| Command | Description |
|---------|-------------|
| `!p <url>` | Play song from URL |
| `!j` | Join voice channel |
| `!skip` / `!sk` | Skip current song |
| `!stop` / `!s` | Stop and disconnect |
| `!queue` / `!q` | Show queue |

### AI Commands
| Command | Description |
|---------|-------------|
| `!ai <message>` | Chat with AI (shared group chat, auto web search) |
| `!aiclear` | Clear AI chat history |
| `!models` | Select AI model via dropdown |
| `!summarize <text>` | Summarize text |

### Image Generation
| Command | Description |
|---------|-------------|
| `!image <prompt>` | Generate image (Stable Diffusion required) |

### Manual Search
| Command | Description |
|---------|-------------|
| `!search <query>` | Search the web |
| `!s <query>` | Short alias for search |

---

## 🏗️ Architecture

- **MainBot.py**: Entry point, environment loading, DNS resolver fix
- **BotCommands.py**: Music player, AI chat, image generation cogs
- **AI.py**: Main AI cog implementation with shared group chat memory

### AI Cog Details

- Default model: `"local-model"` (auto-uses whatever LM Studio has loaded)
- Uses shared conversation history per Discord channel
- Auto-trims history to last 11 messages after system prompt
- Web search auto-triggered by Thai keywords or "search/google/latest"

---

## ⚠️ Troubleshooting

### Python 3.12+ `audioop` Module Error
**Error**: `ModuleNotFoundError: No module named 'audioop'`  
**Fix**: `pip install audioop-linalg`

### Missing .env File
Bot exits with "TOKEN not found" error if `.env` is missing.  
**Fix**: `echo "TOKEN=your-bot-token-here" > .env`

### aiohttp DNS Resolution Fix
MainBot.py uses `aiohttp.ThreadedResolver()` to avoid DNS failures on some systems. Do not remove this line.

### Missing pause Command
If `!pause` doesn't work, check BotCommands.py line 259-265 for missing decorator.

### Blocking requests in async functions
Ensure `requests.post()` is wrapped with `loop.run_in_executor(None, ...)` or use `aiohttp`.

### Voice Channel Connection Issues
Bot has built-in retry logic (3 attempts). If still failing:
- Check Discord server voice settings
- Ensure you're in a voice channel when using commands

---

## 🧪 Testing Checklist

1. ✅ Python version ≥ 3.8
2. ✅ LM Studio running with model loaded on port 1234
3. ✅ Stable Diffusion running on port 7860 (for image gen)
4. ✅ FFmpeg installed system-wide
5. ✅ .env file with valid TOKEN
6. ✅ aiohttp version < 4

---

## 📝 License

This project is licensed under the MIT License.

---

## 🔗 Support

For issues or questions, please open an issue on GitHub.
