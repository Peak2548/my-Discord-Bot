import asyncio
import logging
from typing import Optional

import aiohttp
import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

# --- Configuration ---
LM_STUDIO_BASE_URL = "http://localhost:1234"
CHAT_COMPLETIONS_URL = f"{LM_STUDIO_BASE_URL}/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 180
RP_MAX_HISTORY = 10  # Maximum messages to keep before sliding window kicks in

class RP(commands.Cog):
    """Roleplay cog with a shared group memory and compacting features."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Single shared session for everyone: {"persona": str, "summary": str, "history": list}
        self.shared_session: Optional[dict] = None

    async def generate_response(self, messages: list[dict], max_tokens: int = 1024) -> Optional[str]:
        """Helper function to call the LM Studio API."""
        
        # Dynamically fetch the current model from AI cog if available
        ai_cog = self.bot.get_cog("AI")
        current_model = ai_cog.chat_model if ai_cog else "local-model"

        payload = {
            "model": current_model,
            "messages": messages,
            "temperature": 0.7, 
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": "Bearer lm-studio"}

        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
                async with session.post(CHAT_COMPLETIONS_URL, headers=headers, json=payload, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        raw_content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if "</think>" in raw_content:
                            raw_content = raw_content.split("</think>")[-1].strip()
                        return raw_content
                    else:
                        logger.error(f"LM Studio API Error: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"RP Generation failed: {e}")
            return None

    def build_context(self) -> list[dict]:
        """Builds the 'Sandwich Memory' for the API request."""
        session = self.shared_session
        
        system_content = (
            f"You are playing a roleplay character. Your persona is: {session['persona']}. "
            "Stay in character at all times. Do not break character. "
            "Reply naturally in the exact same language that the user uses to speak to you."
        )
        context = [{"role": "system", "content": system_content}]

        # 2. Middle Layer: The Summary
        if session["summary"]:
            summary_content = f"[Story Summary so far: {session['summary']}]"
            context.append({"role": "system", "content": summary_content})

        # 3. Bottom Layer: Raw Recent Chat History
        context.extend(session["history"])
        
        return context

    @commands.command(name="role")
    async def set_role(self, ctx: commands.Context):
        """Select an AI character role for the group roleplay."""
        view = RolePickerView(self)
        embed = discord.Embed(
            title="🎭 Choose The AI Character",
            description="Select a role! Once selected, **everyone** can interact with this character using `!rp`.",
            color=discord.Color.dark_magenta()
        )
        await ctx.send(embed=embed, view=view)

    @commands.command(name="rp")
    async def roleplay_chat(self, ctx: commands.Context, *, message: str):
        """Talk to the shared roleplay character."""
        # Block if no role is selected yet
        if not self.shared_session:
            await ctx.send("❌ **No role is currently set!** Someone needs to use `!role` first.")
            return
        
        # Append user message (includes display name so the AI knows who is talking)
        user_msg = f"[{ctx.author.display_name}]: {message}"
        self.shared_session["history"].append({"role": "user", "content": user_msg})

        # Build context and generate
        context = self.build_context()
        
        async with ctx.typing():
            reply = await self.generate_response(context)

        if not reply:
            self.shared_session["history"].pop() # Revert history on failure
            await ctx.send("⚠️ The AI failed to respond. Please check if LM Studio is running.")
            return

        # Append assistant response
        self.shared_session["history"].append({"role": "assistant", "content": reply})

        # Sliding Window logic
        if len(self.shared_session["history"]) > RP_MAX_HISTORY:
            self.shared_session["history"] = self.shared_session["history"][-RP_MAX_HISTORY:]

        await ctx.send(reply)

    @commands.command(name="compact")
    async def compact_memory(self, ctx: commands.Context):
        """Summarize the story to save memory for the Local LLM."""
        if not self.shared_session:
            await ctx.send("❌ There is no active roleplay session to compact.")
            return
        
        if len(self.shared_session["history"]) < 4:
            await ctx.send("⚠️ The story is too short to compact right now. Play a bit more first!")
            return

        status_msg = await ctx.send("🔄 **Compacting memory...** (The AI is reading the story so far)")

        summary_prompt = [{"role": "system", "content": "You are a helpful assistant summarizing a roleplay story."}]
        summary_prompt.extend(self.shared_session["history"])
        summary_prompt.append({
            "role": "user", 
            "content": "Please write a concise 3-4 sentence summary of the key events and current situation in this roleplay. Do not write anything else."
        })

        async with ctx.typing():
            summary = await self.generate_response(summary_prompt, max_tokens=300)

        if not summary:
            await status_msg.edit(content="❌ Failed to compact memory. Please try again later.")
            return

        # Update the session
        self.shared_session["summary"] = summary.strip()
        self.shared_session["history"] = self.shared_session["history"][-2:]

        embed = discord.Embed(
            title="📦 Group Memory Compacted!",
            description=f"**New Story Summary:**\n*{self.shared_session['summary']}*",
            color=discord.Color.green()
        )
        await status_msg.edit(content=None, embed=embed)


# --- UI Components for !role ---

class RolePickerSelect(discord.ui.Select):
    def __init__(self, cog: RP):
        self.cog = cog
        options = [
            discord.SelectOption(label="The Wicked Eye", emoji="👁️", description="A dramatic Chunibyo teenager."),
            discord.SelectOption(label="Shadow Agent", emoji="🕵️‍♂️", description="A clumsy 'secret agent' Chunibyo."),
            discord.SelectOption(label="Dark Lord", emoji="📜", description="Broke student acting as a Dark Lord."),
            discord.SelectOption(label="Custom Character", emoji="✏️", description="Create a custom role!"),
        ]
        super().__init__(placeholder="Select a character...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]

        if selected == "Custom Character":
            modal = CustomRoleModal(self.cog)
            await interaction.response.send_modal(modal)
        else:
            personas = {
                "The Wicked Eye": "You are a teenager suffering from severe 'Chunibyo'. You genuinely believe you possess the 'Wicked Eye of the Abyss' hidden beneath a cheap eyepatch. You speak in overly dramatic, apocalyptic terms for mundane things. You try to act dark and mysterious, but if someone points out your delusions, you get extremely embarrassed and flustered. Describe your awkward but dramatic poses using asterisks.",
                "Shadow Agent": "You are a highly delusional Chunibyo who believes you are a top-tier 'Shadow Agent' hunted by a secret global organization. You treat normal people as 'enemy NPCs' and use fake, dramatic military jargon. However, you are extremely clumsy. Whenever you make a mistake, you claim it was a 'calculated tactical maneuver'. Describe your ridiculous actions in asterisks.",
                "Dark Lord": "You are a broke student who firmly believes you are the reincarnation of the 'Dark Lord of the Crimson Realm'. You speak with immense arrogance and use dramatic, archaic words. However, your biggest weaknesses are being totally broke, spicy food, and a crippling fear of stray dogs or bugs. If confronted with these mundane problems, your majestic persona immediately crumbles into a panicking teenager. Describe your actions in asterisks."
            }
            
            persona_text = personas[selected]
            
            # Reset global memory
            self.cog.shared_session = {
                "persona": persona_text,
                "summary": "",
                "history": []
            }
            
            # Announce to the channel
            embed = discord.Embed(
                title=f"🎭 Role Changed: {selected}",
                description=f"**Persona:**\n*{persona_text}*",
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Set by {interaction.user.display_name}. Everyone can now use !rp to chat!")
            
            await interaction.response.edit_message(embed=embed, view=None)


class CustomRoleModal(discord.ui.Modal, title="Create Custom Role"):
    def __init__(self, cog: RP):
        super().__init__()
        self.cog = cog

    persona_input = discord.ui.TextInput(
        label="Describe the character",
        style=discord.TextStyle.paragraph,
        placeholder="e.g., You are a grumpy wizard who secretly cares about the user...",
        required=True,
        max_length=800
    )

    async def on_submit(self, interaction: discord.Interaction):
        custom_persona = self.persona_input.value

        # Reset global memory
        self.cog.shared_session = {
            "persona": custom_persona,
            "summary": "",
            "history": []
        }

        # Announce to the channel
        embed = discord.Embed(
            title="🎭 Custom Role Applied!",
            description=f"**Persona:**\n*{custom_persona}*",
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Set by {interaction.user.display_name}. Everyone can now use !rp to chat!")
        
        await interaction.response.edit_message(embed=embed, view=None)


class RolePickerView(discord.ui.View):
    def __init__(self, cog: RP):
        super().__init__(timeout=120)
        self.add_item(RolePickerSelect(cog))


async def setup(bot: commands.Bot):
    """Load the RP cog."""
    await bot.add_cog(RP(bot))