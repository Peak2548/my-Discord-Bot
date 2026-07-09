
AI chat cog for the Discord bot, backed by a local LM Studio server.

Features
    - !ai      Chat with the model. Shares one conversation history per
               Discord channel, so every user in the channel talks to the
               same context (see REQUIREMENTS.md Shared Group Chat).
    - !search  Search the web directly via DuckDuckGo.
    - !models  Pick  hot-swap the model LM Studio should serve.
    - !learn   List the human participants seen recently in a channel.

Notes on the LM Studio integration
    - Some local models (e.g. Qwen3 thinking variants) emit long internal
      reasoning before the real answer. We strip that out and give extra
      `max_tokens` headroom so the real answer isn't cut off.
    - The Qwen3.5 chat template requires the `system` message to be the
      FIRST message in the list — inserting a second `system` message
      later in the conversation raises a hard 400 error from the server.
      Any extra context (like search results) must therefore be folded
      into a `user` message instead.


import asyncio
import logging
import re

import aiohttp
import discord
from discord.ext import commands
from ddgs import DDGS

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

LM_STUDIO_BASE_URL = httplocalhost1234
CHAT_COMPLETIONS_URL = f{LM_STUDIO_BASE_URL}v1chatcompletions
MODELS_URL = f{LM_STUDIO_BASE_URL}v1models
MODEL_LOAD_URL = f{LM_STUDIO_BASE_URL}apiv1modelsload
MODEL_UNLOAD_URL = f{LM_STUDIO_BASE_URL}apiv1modelsunload

REQUEST_TIMEOUT_SECONDS = 150       # Per requirements keep this in the 120-180s range.
MODEL_LOAD_TIMEOUT_SECONDS = 300    # Loading a model from disk can take a while.
MODELS_LIST_TIMEOUT_SECONDS = 5

# Thinking models often burn most of their token budget on internal
# reasoning before writing the real answer. We always reserve at least
# MIN_TOKEN_FLOOR tokens, plus a THINKING_BUFFER on top of whatever the
# caller asked for, so the real answer doesn't get truncated.
MIN_TOKEN_FLOOR = 1024
THINKING_BUFFER = 1024

MAX_HISTORY_LENGTH = 12   # Trim once the channel history grows past this...
HISTORY_KEEP_RECENT = 11  # ...keeping the system prompt + the most recent N messages.

# Qwen3 template trick appending this to a user message tells the model's
# template to skip the internal think block. It's plain text, not an API
# parameter, so unlike `chat_template_kwargs` it can never trigger a 400.
NO_THINK_SUFFIX = no_think

# If the user's message contains any of these, run a web search first and
# hand the model the results as extra context before it answers.
SEARCH_TRIGGER_KEYWORDS = [
    ค้นหา, หาข้อมูล, search, ล่าสุด, วันนี้, ข่าว, google, หาให้หน่อย,
]

# Used only if LM Studio's v1models endpoint can't be reached.
FALLBACK_MODEL_SUGGESTIONS = [llama3.18b, qwenqwen3.5-9b, mistral-large-latest]

THINK_BLOCK_RE = re.compile(rthink.think, re.DOTALL)
UNCLOSED_THINK_RE = re.compile(rthink., re.DOTALL)


def build_system_prompt(bot_name str) - dict
    Build the system message that seeds every new channel's history.
    content = (
        fYou are a Discord bot named '{bot_name}'. You are the assistant (role assistant) 
        in this shared group chat — you are NOT one of the human users.n
        1. Messages are formatted as 'Name message'. That 'Name' is the human who sent that 
        specific message, NOT you. Never confuse a user's name with your own name.n
        2. All users in this channel share this single conversation history. Multiple 
        different people may have similar names (e.g. 'Peak' and 'Peaku') — they are 
        DIFFERENT people. Always answer based on the name attached to the CURRENT message 
        only, never reuse a different, earlier sender's name.n
        f3. If asked your own name, answer '{bot_name}'. If asked a user's name, answer 
        with the name from that user's own current message.n
        3b. Thai language note casual Thai often uses 'เรา' informally to mean 'Ime' 
        (the speaker themself), not 'we'. So if a user asks something like 'เราชื่อไร' 
        or 'ชื่อเราคืออะไร', they are most likely asking about THEIR OWN name (from 
        their current message's sender name), NOT your name as the bot. Only answer 
        with your own name when they clearly ask about you specifically, e.g. 
        'นายชื่อไร', 'คุณชื่ออะไร', 'บอทชื่ออะไร', or 'what's your name'.n
        4. Be concise and respond directly. Do NOT think step-by-step out loud. 
        Do NOT use think tags — answer directly with only the final response.
    )
    return {role system, content content}


def strip_think_tags(raw_content str) - str
    Remove any think...think reasoning block that leaked into the content.
    content = THINK_BLOCK_RE.sub(, raw_content).strip()
    content = UNCLOSED_THINK_RE.sub(, content).strip()

    # Defensive cleanup for an occasional stray artifact from some prompts.
    if You are in content
        content = content.split(You are, 1)[1]

    return content.strip()


class AI(commands.Cog)
    AI chat + web search cog, backed by a local LM Studio server.

    def __init__(self, bot commands.Bot)
        self.bot = bot
        self.chat_model = local-model  # local-model = auto-use whatever LM Studio has loaded.
        self.channel_conversations dict[int, list[dict]] = {}
        self.active_voice_channel discord.VoiceChannel  None = None

    # ----------------------------------------------------------------
    # Conversation history
    # ----------------------------------------------------------------

    def get_channel_history(self, channel_id int) - list[dict]
        Get (or lazily create) the shared conversation history for a channel.
        if channel_id not in self.channel_conversations
            bot_name = self.bot.user.name if self.bot.user else AI
            self.channel_conversations[channel_id] = [build_system_prompt(bot_name)]
        return self.channel_conversations[channel_id]

    def _trim_history(self, channel_id int, history list[dict]) - None
        Keep the system prompt plus the most recent messages, drop the rest.
        if len(history)  MAX_HISTORY_LENGTH
            self.channel_conversations[channel_id] = [history[0]] + history[-HISTORY_KEEP_RECENT]

    # ----------------------------------------------------------------
    # Web search
    # ----------------------------------------------------------------

    async def execute_search(self, query str) - str
        Run a DuckDuckGo search and return a short, formatted summary.
        try
            with DDGS() as ddgs
                results = list(ddgs.text(query, max_results=3, timeout=10))
                if not results
                    return 🔍 No relevant search results found.

                lines = []
                for i, result in enumerate(results, 1)
                    title = result.get(title, No title)[70]
                    href = result.get(href, )
                    body = result.get(body, )[150]
                    lines.append(f{i}. {title}n   🔗 {href}n   📄 {body})
                return 🔍 Search Resultsn + n.join(lines)
        except Exception
            logger.exception(Web search failed)
            return ⚠️ Could not search the web.

    @commands.command(name=search, aliases=[s])
    async def search_command(self, ctx commands.Context, , query str)
        ค้นหาเว็บด้วย DuckDuckGo โดยตรง
        if not query
            await ctx.send(❌ โปรดใส่คำค้นหาหลังคำสั่ง)
            return
        async with ctx.typing()
            result = await self.execute_search(query)
        await ctx.send(result)

    # ----------------------------------------------------------------
    # LM Studio generation
    # ----------------------------------------------------------------

    async def generate(
        self,
        model_id str,
        messages list[dict],
        temperature float = 0.5,
        num_predict int = 1024,
    ) - tuple[str, bool]
        Call LM Studio's chat completion endpoint and return cleaned text.

        Returns a (reply, needs_search) tuple. `needs_search` is currently
        unused (search is decided by keyword matching before this is called)
        but kept for forward compatibility.
        
        max_tokens = max(num_predict, MIN_TOKEN_FLOOR) + THINKING_BUFFER
        payload = {
            model model_id,
            messages messages,
            temperature temperature,
            max_tokens max_tokens,
            presence_penalty 0.0,
            frequency_penalty 0.0,
            # Intentionally NOT set
            #  - stop would cut generation short whenever the model sees
            #    Name or think patterns that naturally occur in the
            #    shared chat history, producing empty replies.
            #  - chat_template_kwargs some LM Studiollama.cpp versions
            #    fail with a 400 Unable to generate parser for this
            #    template error when unrecognized fields are present.
        }
        headers = {Authorization Bearer lm-studio}

        try
            async with aiohttp.ClientSession() as session
                timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
                async with session.post(CHAT_COMPLETIONS_URL, headers=headers, json=payload, timeout=timeout) as resp
                    if resp.status == 503
                        return ⏳ Model is loading, please wait a moment..., False

                    if resp.status != 200
                        error_text = await resp.text()
                        logger.error(LM Studio API error %s (full body) %s, resp.status, error_text)

                        if No models loaded in error_text
                            return (
                                ❌ LM Studio ยังไม่มีสมอง (โมเดล) ครับ! รบกวนพิมพ์คำสั่ง `!models` 
                                แล้วเลือกโมเดลจากเมนูให้ผมก่อนนะครับ 🧠,
                                False,
                            )
                        return (
                            ⚠️ ตอนนี้เชื่อมต่อกับโมเดลไม่สำเร็จครับ ลองพิมพ์คำถามใหม่อีกครั้ง 
                            หรือใช้ `!models` เปลี่ยนโมเดลดูนะครับ,
                            False,
                        )

                    data = await resp.json()

            raw_content = data.get(choices, [{}])[0].get(message, {}).get(content) or 
            content = strip_think_tags(raw_content)

            if not content and think in raw_content and think not in raw_content
                # The model spent its whole token budget reasoning and never
                # got to a closing think tag — i.e. it ran out of room
                # before writing an actual answer.
                logger.warning(
                    Model ran out of tokens mid-think block (max_tokens=%d). 
                    Consider raising num_predict.,
                    max_tokens,
                )

            return content, False

        except asyncio.TimeoutError
            logger.error(LM Studio request timed out after %ds, REQUEST_TIMEOUT_SECONDS)
            return (
                f⚠️ โมเดลใช้เวลาประมวลผลนานเกิน {REQUEST_TIMEOUT_SECONDS} วินาที 
                (อาจเกิดจากสเปคคอมพิวเตอร์หรือโมเดลติดหลูปรอบความคิด) 
                ลองใช้คำสั่ง `!models` เปลี่ยนเป็นโมเดลตัวอื่นดูครับ,
                False,
            )
        except aiohttp.ClientError
            logger.exception(Connection error while calling LM Studio)
            return ⚠️ Connection to AI service failed. Please check if LM Studio is running., False
        except Exception
            logger.exception(Unexpected error during generation)
            return ❌ Something went wrong with the AI response., False

    # ----------------------------------------------------------------
    # Voice-channel housekeeping (currently unused by any command, but
    # kept available in case voice features get wired up later)
    # ----------------------------------------------------------------

    async def eject_non_chat_voice_channels(self)
        Disconnect any voice channel that isn't the active AI chat channel.
        if not self.active_voice_channel
            return
        for vc in self.bot.voice_clients
            if vc.channel and vc.channel.id != self.active_voice_channel.id
                try
                    await vc.disconnect()
                except discord.DiscordException
                    pass

    # ----------------------------------------------------------------
    # Commands
    # ----------------------------------------------------------------

    @commands.command(name=learn)
    async def learn_about_chat(self, ctx commands.Context)
        Command to help AI learn about who's in the chat.
        if not isinstance(ctx.channel, (discord.TextChannel, discord.Thread))
            return
        try
            history = self.channel_conversations.get(ctx.channel.id, [])

            participants = set()
            for msg in history[-10]
                content = msg.get(content, )
                if  in content
                    name_part = content.split()[0].strip()
                    if name_part and not name_part.startswith()
                        participants.add(name_part)

            participant_list = , .join(sorted(participants)) or No active participants found in recent AI chats
            await ctx.send(f📋 รายชื่อคนที่อยู่ในวงสนทนาตอนนี้n{participant_list})
        except Exception
            logger.exception(Error while listing chat participants)

    @commands.command(name=ai)
    async def ai_chat(self, ctx commands.Context, , message str)
        Chat with AI (shared group chat memory, one history per channel).
        if not message
            await ctx.send(❌ Please provide a question after the command.)
            return

        self.active_voice_channel = ctx.author.voice.channel if ctx.author.voice else None

        history = self.get_channel_history(ctx.channel.id)
        user_content = f{ctx.author.display_name} {message} {NO_THINK_SUFFIX}

        needs_search = any(keyword in message.lower() for keyword in SEARCH_TRIGGER_KEYWORDS)
        if needs_search
            async with ctx.typing()
                search_result = await self.execute_search(message)
            # Fold the search result into the SAME user message rather than
            # adding a second system message — the Qwen3.5 template requires
            # `system` to be the very first message in the list, so inserting
            # one mid-conversation raises a hard 400 error.
            user_content = (
                f{user_content}nn
                f[ผลการค้นหาเว็บล่าสุดสำหรับคำถามข้างต้น]n{search_result}n
                (กรุณาตอบคำถามของผู้ใช้โดยอ้างอิงข้อมูลค้นหานี้)
            )

        history.append({role user, content user_content})

        async with ctx.typing()
            reply, _ = await self.generate(self.chat_model, history, num_predict=2048)

        logger.info(AI replied to [%s], ctx.author.display_name)

        if not reply or not reply.strip()
            reply = (
                ⚠️ ขออภัยครับ โมเดลคิดประมวลผลนานเกินไปและไม่ได้ส่งคำตอบกลับมา 
                ลองเปลี่ยนคำถามหรือใช้โมเดลตัวอื่นดูนะครับ
            )

        await ctx.send(reply)

        history.append({role assistant, content reply[1500]})
        self._trim_history(ctx.channel.id, history)

    # ----------------------------------------------------------------
    # Model selection
    # ----------------------------------------------------------------

    async def get_available_models(self) - list[str]
        List model IDs currently known to LM Studio (falls back to a static list).
        try
            timeout = aiohttp.ClientTimeout(total=MODELS_LIST_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession() as session
                async with session.get(MODELS_URL, timeout=timeout) as resp
                    if resp.status == 200
                        data = await resp.json()
                        models = [m[id] for m in data.get(data, [])]
                        if models
                            return models
        except Exception
            logger.exception(Could not fetch model list from LM Studio)
        return FALLBACK_MODEL_SUGGESTIONS

    @commands.command(name=models)
    async def select_model(self, ctx commands.Context)
        Select AI model via dropdown menu and auto-load it.
        available_models = await self.get_available_models()
        if not available_models
            await ctx.send(❌ ไม่พบรายชื่อโมเดล ลองเช็คว่าเปิด LM Studio ทิ้งไว้หรือยังครับ)
            return

        options = [
            discord.SelectOption(
                label=🟢 local-model (Auto) if self.chat_model == local-model else local-model (Auto),
                value=local-model,
                description=ใช้อัตโนมัติตามที่เปิดอยู่ใน LM Studio,
            )
        ]
        for model_id in available_models[24]
            label = f🟢 {model_id} if model_id == self.chat_model else model_id
            options.append(discord.SelectOption(label=label[100], value=model_id))

        view = ModelPickerView(self, options)
        await ctx.send(f🤖 เปลี่ยนสมอง AIn(ปัจจุบันเลือกใช้ `{self.chat_model}`), view=view)


class ModelPickerSelect(discord.ui.Select)
    Dropdown that lets a user pick and hot-load an LM Studio model.

    def __init__(self, cog AI, options list[discord.SelectOption])
        self.cog = cog
        super().__init__(placeholder=🔽 เลือกโมเดลที่ต้องการโหลด..., min_values=1, max_values=1, options=options)

    async def callback(self, interaction discord.Interaction)
        selected = self.values[0]
        self.cog.chat_model = selected

        if selected == local-model
            await interaction.response.send_message(
                ✅ บอทสลับมาใช้ระบบ Auto (อิงตามโมเดลที่รันอยู่ใน LM Studio) แล้วครับ
            )
            return

        await interaction.response.send_message(
            f⏳ กำลังจัดเตรียมโมเดล `{selected}`n
            🧹 กำลังสั่งเคลียร์ RAM...n
            🚀 กำลังโหลดโมเดลใหม่...n
            (โปรดรอสักครู่)
        )
        await self._unload_and_load(interaction, selected)

    async def _unload_and_load(self, interaction discord.Interaction, selected str)
        headers = {Content-Type applicationjson, Authorization Bearer lm-studio}

        try
            async with aiohttp.ClientSession() as session
                await self._unload_all_models(session, headers)

                load_timeout = aiohttp.ClientTimeout(total=MODEL_LOAD_TIMEOUT_SECONDS)
                load_payload = {model selected}
                async with session.post(MODEL_LOAD_URL, headers=headers, json=load_payload, timeout=load_timeout) as resp
                    if resp.status == 200
                        await interaction.followup.send(
                            f✅ โหลดเสร็จสิ้น! โมเดลถูกเปลี่ยนเป็น `{selected}` และ RAM ถูกเคลียร์เรียบร้อยครับ!
                        )
                    else
                        await interaction.followup.send(f⚠️ สั่งโหลดไปแล้วแต่ระบบตอบ Error {resp.status})
        except Exception
            logger.exception(Error while switching LM Studio model)
            await interaction.followup.send(❌ ไม่สามารถเชื่อมต่อกับ LM Studio ได้ครับ โปรแกรมอาจจะปิดอยู่)

    @staticmethod
    async def _unload_all_models(session aiohttp.ClientSession, headers dict) - None
        Best-effort ask LM Studio to unload every currently loaded model.
        try
            async with session.get(MODELS_URL, timeout=MODELS_LIST_TIMEOUT_SECONDS) as resp
                if resp.status != 200
                    return
                data = await resp.json()
                loaded_model_ids = [m[id] for m in data.get(data, [])]

            unload_tasks = [
                session.post(MODEL_UNLOAD_URL, headers=headers, json={instance_id model_id}, timeout=3)
                for model_id in loaded_model_ids
            ]
            if unload_tasks
                await asyncio.gather(unload_tasks, return_exceptions=True)
        except Exception as e
            logger.warning(Non-fatal error while force-unloading models %s, e)


class ModelPickerView(discord.ui.View)
    View wrapping the model-picker dropdown, shown by `!models`.

    def __init__(self, cog AI, options list[discord.SelectOption])
        super().__init__(timeout=60)
        self.add_item(ModelPickerSelect(cog, options))


async def setup(bot commands.Bot)
    await bot.add_cog(AI(bot))