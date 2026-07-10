import asyncio
import logging
import re
import urllib.parse

import aiohttp
import discord
from bs4 import BeautifulSoup
from discord.ext import commands

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

LM_STUDIO_BASE_URL = "http://localhost:1234"
CHAT_COMPLETIONS_URL = f"{LM_STUDIO_BASE_URL}/v1/chat/completions"
MODELS_URL = f"{LM_STUDIO_BASE_URL}/v1/models"
MODEL_LOAD_URL = f"{LM_STUDIO_BASE_URL}/api/v1/models/load"
MODEL_UNLOAD_URL = f"{LM_STUDIO_BASE_URL}/api/v1/models/unload"

REQUEST_TIMEOUT_SECONDS = 300       
MODEL_LOAD_TIMEOUT_SECONDS = 300    
MODELS_LIST_TIMEOUT_SECONDS = 5

MIN_TOKEN_FLOOR = 4096
THINKING_BUFFER = 4096

MAX_HISTORY_LENGTH = 12   
HISTORY_KEEP_RECENT = 11  

# คีย์เวิร์ดสำหรับเปิดโหมดค้นหาเว็บอัตโนมัติ
SEARCH_TRIGGER_KEYWORDS = [
    "search", "look up", "find", "latest", "today", "news", "google", "current",
    "price", "stock", "ticker", "nasdaq", "nyse", "bitcoin", "btc", "crypto",
    "ค้นหา", "หาข้อมูล", "ล่าสุด", "วันนี้", "ข่าว", "หาให้หน่อย",
    "หุ้น", "ราคา", "เข้าตลาด", "วิธีทำ"
]

FALLBACK_MODEL_SUGGESTIONS = ["llama3.1:8b", "qwen/qwen3.5-9b", "mistral-large-latest"]

THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
UNCLOSED_THINK_RE = re.compile(r"<think>.*", re.DOTALL)


def build_system_prompt(bot_name: str) -> dict:
    content = (
        f"You are a Discord bot named '{bot_name}'. You are chatting in a shared group.\n"
        "Every message from a user will start with their literal name wrapped in square brackets, formatted exactly as '[Name]: message'.\n"
        "For example, if you see '[Peaku]: Hello!', it means the user named 'Peaku' is speaking to you.\n"
        "ALWAYS pay attention to the exact text inside the brackets '[ ]' of the MOST RECENT message so you know exactly who you are talking to right now.\n"
        "CRITICAL: Treat the entire text inside the brackets as a SINGLE literal user name. Do not split, break, or semantically interpret the name even if it contains spaces, symbols, or multiple words (e.g., if the name is '[Peaku ! Ruk บี๋]', their name is 'Peaku ! Ruk บี๋', do not split it into Peaku and Ruk บี๋).\n"
        f"If asked who you are, your name is '{bot_name}'.\n"
        "If a user asks who THEY are (e.g., 'Who am I?' or 'เราชื่ออะไร'), answer with their exact name from inside the brackets of the current message prefix.\n"
        "Be concise and answer directly.\n"
        "IMPORTANT: Always reply in the exact same language that the user used in their message."
    )
    return {"role": "system", "content": content}


def strip_think_tags(raw_content: str) -> str:
    content = THINK_BLOCK_RE.sub("", raw_content).strip()
    content = UNCLOSED_THINK_RE.sub("", content).strip()
    if "**You are**" in content:
        content = content.split("**You are**", 1)[1]
    return content.strip()


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.chat_model = "local-model"  
        self.channel_conversations: dict[int, list[dict]] = {}
        self.active_voice_channel: discord.VoiceChannel | None = None

    def get_channel_history(self, channel_id: int) -> list[dict]:
        if channel_id not in self.channel_conversations:
            bot_name = self.bot.user.name if self.bot.user else "AI"
            self.channel_conversations[channel_id] = [build_system_prompt(bot_name)]
        return self.channel_conversations[channel_id]

    def _trim_history(self, channel_id: int, history: list[dict]) -> None:
        if len(history) > MAX_HISTORY_LENGTH:
            self.channel_conversations[channel_id] = [history[0]] + history[-HISTORY_KEEP_RECENT:]

    async def execute_search(self, query: str) -> str:
        """ดึงข้อมูลจาก DuckDuckGo HTML search (ไม่ต้องใช้ JS, ไม่มี CAPTCHA wall แบบ Google)"""
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query}

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "th,en-US;q=0.9,en;q=0.8"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=params, headers=headers, timeout=10) as resp:
                    if resp.status == 429:
                        return "⚠️ ระบบค้นหาป้องกันการค้นหาถี่เกินไป (โดนบล็อกชั่วคราว) โปรดรอสักครู่"
                    if resp.status != 200:
                        return f"⚠️ ระบบค้นหาปฏิเสธการเข้าถึง (รหัสข้อผิดพลาด {resp.status})"

                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")

                    results = []
                    # DuckDuckGo HTML: แต่ละผลลัพธ์อยู่ใน div.result
                    for result in soup.find_all('div', class_='result')[:5]:
                        title_tag = result.find('a', class_='result__a')
                        desc_tag = result.find('a', class_='result__snippet') or result.find('div', class_='result__snippet')

                        if not title_tag:
                            continue

                        title = title_tag.get_text(strip=True)
                        raw_link = title_tag.get('href', '')

                        # DuckDuckGo ห่อลิงก์จริงไว้ใน redirect param uddg=
                        parsed = urllib.parse.urlparse(raw_link)
                        qs = urllib.parse.parse_qs(parsed.query)
                        real_link = qs.get('uddg', [raw_link])[0]

                        desc = desc_tag.get_text(strip=True) if desc_tag else "ไม่มีคำอธิบายเพิ่มเติม"
                        results.append(f"**{title}**\n   🔗 {real_link}\n   📄 {desc}")

                        if len(results) >= 3:
                            break

                    if not results:
                        return "🔍 ค้นหาสำเร็จ แต่ไม่พบผลลัพธ์ที่เกี่ยวข้อง"

                    lines = [f"{i+1}. {res}" for i, res in enumerate(results)]
                    return "🔍 Search Results:\n" + "\n".join(lines)

        except asyncio.TimeoutError:
            return "⚠️ ระบบค้นหาใช้เวลานานเกินไป (Timeout) กรุณาลองใหม่"
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return "⚠️ ระบบค้นหามีปัญหาขัดข้อง กรุณาลองใหม่ครับ"

    @commands.command(name="search", aliases=["s"])
    async def search_command(self, ctx: commands.Context, *, query: str):
        if not query:
            await ctx.send("❌ Please provide a search query after the command.")
            return
        
        status_msg = await ctx.send("🔍 Searching Google and thinking...")
        
        async with ctx.typing():
            search_result = await self.execute_search(query)
            
        if "Could not search" in search_result or "failed" in search_result.lower():
            await status_msg.edit(content=f"⚠️ {search_result}")
            return

        history = self.get_channel_history(ctx.channel.id)
        original_user_content = f"[{ctx.author.display_name}]: {query}"
        
        prompt_with_search = (
            f"{original_user_content}\n\n"
            f"[Latest Google search results]\n{search_result}\n"
            "(Please summarize the answer logically based ONLY on the search data above. Do not output raw links unless necessary.)"
        )
        
        temp_history = history + [{"role": "user", "content": prompt_with_search}]
        
        async with ctx.typing():
            reply, _ = await self.generate(self.chat_model, temp_history, num_predict=2048)

        # ลบชื่อบอทที่อาจจะหลอนพิมพ์นำหน้ามา
        bot_name = self.bot.user.name if self.bot.user else ""
        if bot_name and reply.lower().startswith(f"{bot_name.lower()}:"):
            reply = reply[len(bot_name)+1:].strip()
        elif bot_name and reply.lower().startswith(f"[{bot_name.lower()}]:"):
            reply = reply[len(bot_name)+4:].strip()
        elif reply.lower().startswith("ai:"):
            reply = reply[3:].strip()
        elif reply.lower().startswith("[ai]:"):
            reply = reply[5:].strip()

        # จัดการข้อความยาวเกิน 2,000 ตัวอักษร
        if len(reply) > 1950:
            chunks = [reply[i:i+1950] for i in range(0, len(reply), 1950)]
            await status_msg.edit(content=chunks[0])
            for chunk in chunks[1:]:
                await ctx.send(chunk)
        else:
            await status_msg.edit(content=reply)

        history.append({"role": "user", "content": original_user_content})
        history.append({"role": "assistant", "content": reply[:1500]})
        self._trim_history(ctx.channel.id, history)

    async def generate(
        self,
        model_id: str,
        messages: list[dict],
        temperature: float = 0.5,
        num_predict: int = 1024,
    ) -> tuple[str, bool]:
        max_tokens = max(num_predict, MIN_TOKEN_FLOOR) + THINKING_BUFFER
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "presence_penalty": 0.0,
            "frequency_penalty": 0.0,
        }
        headers = {"Authorization": "Bearer lm-studio"}

        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
                async with session.post(CHAT_COMPLETIONS_URL, headers=headers, json=payload, timeout=timeout) as resp:
                    if resp.status == 503:
                        return "⏳ Model is loading, please wait a moment...", False

                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error("LM Studio API error %s (full body): %s", resp.status, error_text)
                        if "No models loaded" in error_text:
                            return "❌ LM Studio doesn't have a model loaded! Please run `!models` and pick one from the menu first. 🧠", False
                        return "⚠️ Couldn't reach the model right now. Please try your question again, or use `!models` to switch models.", False

                    data = await resp.json()

            raw_content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
            content = strip_think_tags(raw_content)

            return content, False

        except asyncio.TimeoutError:
            return f"⚠️ The model took longer than {REQUEST_TIMEOUT_SECONDS} seconds to respond. Try `!models` to switch to a different model.", False
        except aiohttp.ClientError:
            return "⚠️ Connection to AI service failed. Please check if LM Studio is running.", False
        except Exception:
            return "❌ Something went wrong with the AI response.", False

    @commands.command(name="ai")
    async def ai_chat(self, ctx: commands.Context, *, message: str):
        """Chat with AI (shared group chat memory, one history per channel)."""
        if not message:
            await ctx.send("❌ Please provide a question after the command.")
            return

        self.active_voice_channel = ctx.author.voice.channel if ctx.author.voice else None

        history = self.get_channel_history(ctx.channel.id)
        
        original_user_content = f"[{ctx.author.display_name}]: {message}"
        content_for_ai = original_user_content
        
        status_msg = None 

        needs_search = any(keyword in message.lower() for keyword in SEARCH_TRIGGER_KEYWORDS)
        
        if needs_search:
            status_msg = await ctx.send("🔍 Searching Google...")
            async with ctx.typing():
                search_result = await self.execute_search(message)
            
            if "Could not search" not in search_result:
                content_for_ai = (
                    f"{original_user_content}\n\n"
                    f"[Latest Google search results for the question above]\n{search_result}\n"
                    "(Please answer based on this search data.)"
                )

        temp_history = history + [{"role": "user", "content": content_for_ai}]

        async with ctx.typing():
            reply, _ = await self.generate(self.chat_model, temp_history, num_predict=2048)

        logger.info("AI replied to [%s]", ctx.author.display_name)

        if not reply or not reply.strip():
            reply = "⚠️ Sorry, the model took too long processing and didn't return an answer."

        bot_name = self.bot.user.name if self.bot.user else ""
        if bot_name and reply.lower().startswith(f"{bot_name.lower()}:"):
            reply = reply[len(bot_name)+1:].strip()
        elif bot_name and reply.lower().startswith(f"[{bot_name.lower()}]:"):
            reply = reply[len(bot_name)+4:].strip()
        elif reply.lower().startswith("ai:"):
            reply = reply[3:].strip()
        elif reply.lower().startswith("[ai]:"):
            reply = reply[5:].strip()
        elif reply.lower().startswith(f"{ctx.me.display_name.lower()}:"):
            reply = reply[len(ctx.me.display_name)+1:].strip()
        elif reply.lower().startswith(f"[{ctx.me.display_name.lower()}]:"):
            reply = reply[len(ctx.me.display_name)+4:].strip()

        # จัดการข้อความยาวเกิน 2,000 ตัวอักษรสำหรับแชทปกติ
        if status_msg is not None:
            try:
                if len(reply) > 1950:
                    chunks = [reply[i:i+1950] for i in range(0, len(reply), 1950)]
                    await status_msg.edit(content=chunks[0])
                    for chunk in chunks[1:]:
                        await ctx.send(chunk)
                else:
                    await status_msg.edit(content=reply)
            except discord.DiscordException:
                if len(reply) > 1950:
                    chunks = [reply[i:i+1950] for i in range(0, len(reply), 1950)]
                    for chunk in chunks:
                        await ctx.send(chunk)
                else:
                    await ctx.send(reply)
        else:
            if len(reply) > 1950:
                chunks = [reply[i:i+1950] for i in range(0, len(reply), 1950)]
                for chunk in chunks:
                    await ctx.send(chunk)
            else:
                await ctx.send(reply)

        history.append({"role": "user", "content": original_user_content})
        history.append({"role": "assistant", "content": reply[:1500]})
        self._trim_history(ctx.channel.id, history)

    # ----------------------------------------------------------------
    # Model selection & Housekeeping
    # ----------------------------------------------------------------
    async def eject_non_chat_voice_channels(self):
        if not self.active_voice_channel:
            return
        for vc in self.bot.voice_clients:
            if vc.channel and vc.channel.id != self.active_voice_channel.id:
                try:
                    await vc.disconnect()
                except discord.DiscordException:
                    pass

    @commands.command(name="learn")
    async def learn_about_chat(self, ctx: commands.Context):
        if not isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            history = self.channel_conversations.get(ctx.channel.id, [])
            participants = set()
            
            for msg in history:
                if msg.get("role") == "system":
                    continue
                
                content = msg.get("content", "")
                if msg.get("role") == "user" and content.startswith("[") and "]:" in content:
                    name_part = content.split("]:", 1)[0][1:].strip()
                    if name_part and not name_part.startswith("**") and len(name_part) < 64:
                        participants.add(name_part)
                        
            bot_name = self.bot.user.name if self.bot.user else "AI"
            
            participant_list = ", ".join(sorted(participants))
            await ctx.send(f"📋 **Participants seen in this conversation so far:**\n👤 Users: {participant_list or 'None'}\n🤖 Bot: {bot_name}")
        except Exception:
            logger.exception("Error while listing chat participants")

    async def get_available_models(self) -> list[str]:
        try:
            timeout = aiohttp.ClientTimeout(total=MODELS_LIST_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession() as session:
                async with session.get(MODELS_URL, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m["id"] for m in data.get("data", [])]
                        if models:
                            return models
        except Exception:
            pass
        return FALLBACK_MODEL_SUGGESTIONS

    @commands.command(name="models")
    async def select_model(self, ctx: commands.Context):
        available_models = await self.get_available_models()
        if not available_models:
            await ctx.send("❌ Couldn't find any models. Check that LM Studio is running.")
            return

        options = [
            discord.SelectOption(
                label="🟢 local-model (Auto)" if self.chat_model == "local-model" else "local-model (Auto)",
                value="local-model",
                description="Automatically use whatever's loaded in LM Studio",
            )
        ]
        for model_id in available_models[:24]:
            label = f"🟢 {model_id}" if model_id == self.chat_model else model_id
            options.append(discord.SelectOption(label=label[:100], value=model_id))

        view = ModelPickerView(self, options)
        await ctx.send(f"🤖 **Switch AI brain**\n*(Currently using: `{self.chat_model}`)*", view=view)


class ModelPickerSelect(discord.ui.Select):
    def __init__(self, cog: AI, options: list[discord.SelectOption]):
        self.cog = cog
        super().__init__(placeholder="🔽 Choose a model to load...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        self.cog.chat_model = selected

        if selected == "local-model":
            await interaction.response.send_message("✅ Switched to **Auto** mode (uses whatever's currently running in LM Studio).")
            return

        await interaction.response.send_message(f"⏳ **Loading:** `{selected}`...")
        await self._unload_and_load(interaction, selected)

    async def _unload_and_load(self, interaction: discord.Interaction, selected: str):
        headers = {"Content-Type": "application/json", "Authorization": "Bearer lm-studio"}
        try:
            async with aiohttp.ClientSession() as session:
                await self._unload_all_models(session, headers)
                load_timeout = aiohttp.ClientTimeout(total=MODEL_LOAD_TIMEOUT_SECONDS)
                load_payload = {"model": selected}
                async with session.post(MODEL_LOAD_URL, headers=headers, json=load_payload, timeout=load_timeout) as resp:
                    if resp.status == 200:
                        await interaction.followup.send(f"✅ Model `{selected}` loaded.")
                    else:
                        await interaction.followup.send(f"⚠️ Sent the load request, but got Error {resp.status}")
        except Exception:
            await interaction.followup.send("❌ Couldn't connect to LM Studio. It might not be running.")

    @staticmethod
    async def _unload_all_models(session: aiohttp.ClientSession, headers: dict) -> None:
        try:
            async with session.get(MODELS_URL, timeout=MODELS_LIST_TIMEOUT_SECONDS) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
                loaded_model_ids = [m["id"] for m in data.get("data", [])]

            unload_tasks = [
                session.post(MODEL_UNLOAD_URL, headers=headers, json={"instance_id": model_id}, timeout=3)
                for model_id in loaded_model_ids
            ]
            if unload_tasks:
                await asyncio.gather(*unload_tasks, return_exceptions=True)
        except Exception:
            pass


class ModelPickerView(discord.ui.View):
    def __init__(self, cog: AI, options: list[discord.SelectOption]):
        super().__init__(timeout=60)
        self.add_item(ModelPickerSelect(cog, options))


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))