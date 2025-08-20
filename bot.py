# bot.py — Channel-based verification using **Private Threads** (no DMs)
# Flow:
# 1) In #verify, the user types: verify
# 2) Bot creates a PRIVATE THREAD for that user only (+ admins) and asks for password
# 3) If password OK → ask Name → ask Team → set nickname "Name-Team" → grant Verified role
# 4) Deletes user messages that contain password/name/team for privacy, sends short confirmations
# 5) Auto-archives the thread after finishing
#
# Requirements (Discord permissions for bot):
# - Create Private Threads, Send Messages in Threads, Manage Threads
# - Manage Roles, Change Nickname, Read Messages/View Channel
# Make sure the bot's top role is ABOVE the "Verified" role and most members.

import os
import re
import asyncio
from typing import Optional, Dict, Any

import discord
from discord.ext import commands
from dotenv import load_dotenv

# -------- Load configuration --------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
VERIFIED_ROLE_NAME = os.getenv("VERIFIED_ROLE", "Verified")
VERIFY_PASSWORD = os.getenv("VERIFY_PASSWORD", "secret123")
VERIFY_CHANNEL_NAME = os.getenv("VERIFY_CHANNEL", "verify")  # channel where flow starts
MAX_ATTEMPTS = int(os.getenv("VERIFY_ATTEMPTS", "3"))
THREAD_AUTOARCHIVE_MIN = int(os.getenv("THREAD_AUTOARCHIVE_MIN", "60"))  # 60, 1440, 4320, or 10080
CONFIRM_VISIBLE_SECONDS = int(os.getenv("CONFIRM_VISIBLE_SECONDS", "10"))

if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is missing.")

# -------- Bot setup --------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Session state per user
# { user_id: {"state": str, "attempts": int, "name": Optional[str], "team": Optional[str], "thread_id": int} }
sessions: Dict[int, Dict[str, Any]] = {}

# -------- Helpers --------
async def ensure_verified_role(guild: discord.Guild) -> discord.Role:
    role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)
    if role:
        return role
    return await guild.create_role(name=VERIFIED_ROLE_NAME, mentionable=True, reason="Create verified role")

async def add_verified(member: discord.Member) -> None:
    role = await ensure_verified_role(member.guild)
    await member.add_roles(role, reason="Verification passed")

def is_verify_channel(channel: discord.abc.GuildChannel) -> bool:
    return isinstance(channel, discord.TextChannel) and channel.name.lower() == VERIFY_CHANNEL_NAME.lower()

def sanitize(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text

MAX_NICK = 32

async def set_member_nick(member: discord.Member, name: str, team: str) -> str:
    name = sanitize(name)
    team = sanitize(team)
    desired = f"{name}-{team}" if team else name
    if len(desired) > MAX_NICK:
        over = len(desired) - MAX_NICK
        if len(team) > over + 1:
            team = team[: max(1, len(team) - over - 1)]
        else:
            name = name[: max(1, len(name) - (over - max(0, len(team) - 1)))]
        desired = f"{name}-{team}"
        desired = desired[:MAX_NICK]
    await member.edit(nick=desired, reason="Verification nickname set (Name-Team)")
    return desired

async def create_user_thread(channel: discord.TextChannel, member: discord.Member) -> discord.Thread:
    thread = await channel.create_thread(
        name=f"verify-{member.name}-{member.id}",
        type=discord.ChannelType.private_thread,
        auto_archive_duration=THREAD_AUTOARCHIVE_MIN,
        reason="Start private verification thread",
        invitable=False,
    )
    # Ensure the user is added
    try:
        await thread.add_user(member)
    except discord.Forbidden:
        pass
    return thread

async def delete_user_message(msg: discord.Message):
    try:
        await msg.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

# -------- Events --------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"ℹ️ Guild: {GUILD_ID or 'auto'} | Verify channel: #{VERIFY_CHANNEL_NAME} | Role: {VERIFIED_ROLE_NAME}")

@bot.event
async def on_member_join(member: discord.Member):
    channel = discord.utils.get(member.guild.text_channels, name=VERIFY_CHANNEL_NAME)
    if channel:
        try:
            await channel.send(f"Welcome {member.mention}! Type **verify** to start.")
        except discord.Forbidden:
            pass

@bot.event
async def on_message(message: discord.Message):
    # Ignore bot messages
    if message.author.bot:
        return

    guild: Optional[discord.Guild] = message.guild
    if not guild:
        return

    verified_role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)

    # --- Case A: Message in main #verify channel ---
    if is_verify_channel(message.channel):
        # If already verified, just react ✅ and ignore
        if verified_role and isinstance(message.author, discord.Member) and verified_role in message.author.roles:
            with contextlib.suppress(discord.HTTPException):
                await message.add_reaction("✅")
            return

        content = message.content.strip().lower()
        if content == "verify":
            # Create a private thread for this user (reuse if already open)
            existing = sessions.get(message.author.id)
            if existing:
                # ping them to go back to their thread
                thread = guild.get_thread(existing.get("thread_id")) if existing.get("thread_id") else None
                if isinstance(thread, discord.Thread):
                    await thread.send(f"{message.author.mention} Continue here.")
                    return

            thread = await create_user_thread(message.channel, message.author)
            sessions[message.author.id] = {
                "state": "await_password",
                "attempts": MAX_ATTEMPTS,
                "name": None,
                "team": None,
                "thread_id": thread.id,
            }
            await thread.send(
                f"{message.author.mention} Please enter the **password** to verify. You have **{MAX_ATTEMPTS}** attempts."
            )
        else:
            # Light hint
            await message.reply("Type **verify** to start verification.", mention_author=True)
        return

    # --- Case B: Message inside a thread we created ---
    if isinstance(message.channel, discord.Thread):
        # Only process if this thread is owned by a session for the author
        st = sessions.get(message.author.id)
        if not st or st.get("thread_id") != message.channel.id:
            return

        # For privacy, delete the user's message after reading
        raw = message.content
        await delete_user_message(message)

        # If user became verified mid-process, finish silently
        if verified_role and isinstance(message.author, discord.Member) and verified_role in message.author.roles:
            sessions.pop(message.author.id, None)
            return

        # Step machine
        state = st.get("state")
        attempts_left = st.get("attempts", MAX_ATTEMPTS)

        if state == "await_password":
            if raw == VERIFY_PASSWORD:
                st["state"] = "await_name"
                await message.channel.send("✅ Password accepted. Please type your **Name**.")
            else:
                attempts_left -= 1
                if attempts_left <= 0:
                    sessions.pop(message.author.id, None)
                    await message.channel.send("❌ Incorrect password. No attempts left. Please contact a moderator.")
                    # Optionally archive thread soon
                    await asyncio.sleep(3)
                    with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                        await message.channel.edit(archived=True, locked=True)
                else:
                    st["attempts"] = attempts_left
                    await message.channel.send(f"❌ Wrong password. Attempts left: **{attempts_left}**.")
            return

        if state == "await_name":
            name = sanitize(raw)
            if not name:
                await message.channel.send("⚠️ Name can't be empty. Please type your **Name**.")
                return
            st["name"] = name
            st["state"] = "await_team"
            await message.channel.send("Got it. Now type your **Team** name.")
            return

        if state == "await_team":
            team = sanitize(raw)
            if not team:
                await message.channel.send("⚠️ Team can't be empty. Please type your **Team** name.")
                return
            st["team"] = team

            member = guild.get_member(message.author.id)
            if not member:
                await message.channel.send("I couldn't find your member record. Please re-join the server.")
                sessions.pop(message.author.id, None)
                return

            # Apply nickname + role
            try:
                new_nick = await set_member_nick(member, st["name"], st["team"])
            except discord.Forbidden:
                await message.channel.send(
                    "⚠️ I can't change your nickname. Ask an admin to move my role above yours."
                )
                sessions.pop(message.author.id, None)
                return
            except discord.HTTPException:
                await message.channel.send("❌ Error while changing nickname. Try again later.")
                sessions.pop(message.author.id, None)
                return

            try:
                await add_verified(member)
            except discord.Forbidden:
                await message.channel.send(
                    f"⚠️ I can't assign roles. Ask an admin to move my role above {VERIFIED_ROLE_NAME}."
                )
                sessions.pop(message.author.id, None)
                return
            except discord.HTTPException:
                await message.channel.send("❌ Error while assigning role. Try again later.")
                sessions.pop(message.author.id, None)
                return

            # Success!
            confirm = await message.channel.send(
                f"✅ Verified! Nickname set to **{new_nick}** and role **{VERIFIED_ROLE_NAME}** granted. Welcome!"
            )
            sessions.pop(message.author.id, None)
            try:
                await asyncio.sleep(CONFIRM_VISIBLE_SECONDS)
                with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                    await confirm.delete()
                await message.channel.edit(archived=True, locked=True)
            except Exception:
                pass
            return

# -------- Simple health command --------
@bot.command(name="ping")
async def ping(ctx: commands.Context):
    await ctx.reply("Pong!", mention_author=False)

if __name__ == "__main__":
    bot.run(TOKEN)
