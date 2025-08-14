# bot.py — Channel-based verification (no DMs)
import os
from typing import Optional, Dict

import discord
from discord.ext import commands
from dotenv import load_dotenv

# -------- Load configuration --------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
VERIFIED_ROLE_NAME = os.getenv("VERIFIED_ROLE", "Verified")
VERIFY_PASSWORD = os.getenv("VERIFY_PASSWORD", "secret123")
VERIFY_CHANNEL_NAME = os.getenv("VERIFY_CHANNEL", "verify")  # channel where flow happens
MAX_ATTEMPTS = int(os.getenv("VERIFY_ATTEMPTS", "3"))

if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is missing.")

# -------- Bot setup --------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Track who is in a verification session (user_id -> attempts_left)
pending_sessions: Dict[int, int] = {}


# -------- Helpers --------
async def ensure_verified_role(guild: discord.Guild) -> discord.Role:
    role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)
    if role:
        return role
    # Create role if missing
    return await guild.create_role(name=VERIFIED_ROLE_NAME, mentionable=True, reason="Create verified role")


async def add_verified(member: discord.Member) -> None:
    role = await ensure_verified_role(member.guild)
    await member.add_roles(role, reason="Verification passed")


def is_verify_channel(channel: discord.abc.GuildChannel) -> bool:
    return isinstance(channel, discord.TextChannel) and channel.name.lower() == VERIFY_CHANNEL_NAME.lower()


# -------- Events --------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"ℹ️ Guild: {GUILD_ID or 'auto'} | Verify channel: #{VERIFY_CHANNEL_NAME} | Role: {VERIFIED_ROLE_NAME}")


@bot.event
async def on_member_join(member: discord.Member):
    # Optional: Nudge newcomer in-channel if verify channel exists
    channel = discord.utils.get(member.guild.text_channels, name=VERIFY_CHANNEL_NAME)
    if channel:
        try:
            await channel.send(f"Welcome {member.mention}! Type **verify** to start verification.")
        except discord.Forbidden:
            pass


@bot.event
async def on_message(message: discord.Message):
    # Ignore bot messages
    if message.author.bot:
        return

    # Only handle inside the verify channel
    if not is_verify_channel(message.channel):
        await bot.process_commands(message)
        return

    guild: Optional[discord.Guild] = message.guild
    if not guild:
        await bot.process_commands(message)
        return

    # If user already has the verified role, ignore
    verified_role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)
    if verified_role and isinstance(message.author, discord.Member) and verified_role in message.author.roles:
        await message.add_reaction("✅")
        return

    content = message.content.strip()

    # 1) User types the trigger word "verify"
    if content.lower() == "verify":
        pending_sessions[message.author.id] = MAX_ATTEMPTS
        await message.reply(
            "Please enter the **password** to verify.\n"
            f"You have **{MAX_ATTEMPTS}** attempts.",
            mention_author=True
        )
        return

    # 2) If user is in a session, treat next messages as password attempts
    if message.author.id in pending_sessions:
        # Try to delete the user's password message for privacy
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            pass

        attempts_left = pending_sessions.get(message.author.id, MAX_ATTEMPTS)

        if content == VERIFY_PASSWORD:
            try:
                member = guild.get_member(message.author.id)
                if not member:
                    await message.channel.send("I couldn't find your member record. Please re-join the server.")
                    return
                await add_verified(member)
                await message.channel.send(f"{message.author.mention} ✅ Verified! Welcome 🎉")
            except discord.Forbidden:
                await message.channel.send(
                    f"{message.author.mention} ⚠️ I can't assign roles. Please ask an admin to move my role **above** `{VERIFIED_ROLE_NAME}`."
                )
            finally:
                pending_sessions.pop(message.author.id, None)
            return
        else:
            attempts_left -= 1
            if attempts_left <= 0:
                pending_sessions.pop(message.author.id, None)
                await message.channel.send(f"{message.author.mention} ❌ Incorrect password. No attempts left. Please contact a moderator.")
            else:
                pending_sessions[message.author.id] = attempts_left
                await message.channel.send(
                    f"{message.author.mention} ❌ Incorrect password. Attempts left: **{attempts_left}**.\n"
                    "Type the password again."
                )
            return

    # If none of the above and user typed something else, lightly guide them
    if content and content.lower() != "verify":
        await message.reply("Type **verify** to start verification.", mention_author=True)

    await bot.process_commands(message)


# -------- Simple health command --------
@bot.command(name="ping")
async def ping(ctx: commands.Context):
    await ctx.reply("Pong!", mention_author=False)


if __name__ == "__main__":
    bot.run(TOKEN)
