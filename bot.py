# bot.py — Channel-based verification (no DMs) + Nickname Setup Cog
from __future__ import annotations

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
        await bot.process_commands(message)
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


# ========= Nickname Setup (Additive Cog) =========
# جلسات التعيين: user_id -> {"stage": "ask_name"/"ask_team", "name": str}
# استخدمنا dict المدمج لتفادي مشاكل typing
pending_nickname_sessions: dict[int, dict[str, str]] = {}

class NicknameSetup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # عندما العضو تُضاف له رتبة التحقّق، ابدأ التدفّق
    @commands.Cog.listener()
    async def on_member_update(self, before: "discord.Member", after: "discord.Member"):
        # نتأكد أن رتبة VERIFIED_ROLE_NAME تمت إضافتها الآن
        if before.guild is None or after.guild is None:
            return

        added_roles = set(after.roles) - set(before.roles)
        if not added_roles:
            return

        verified_role = discord.utils.get(after.guild.roles, name=VERIFIED_ROLE_NAME)
        if verified_role and verified_role in added_roles:
            # ابدأ جلسة جمع الاسم/الفريق
            pending_nickname_sessions[after.id] = {"stage": "ask_name", "name": ""}
            channel = discord.utils.get(after.guild.text_channels, name=VERIFY_CHANNEL_NAME)
            if channel:
                try:
                    await channel.send(
                        f"{after.mention} تم التحقّق ✅\n"
                        "اكتب اسمك الذي تريد ظهوره في السيرفر (بدون فريق)."
                    )
                except discord.Forbidden:
                    pass

    # تابع التدفّق برسائل المستخدم داخل قناة #verify
    @commands.Cog.listener()
    async def on_message(self, message: "discord.Message"):
        # تجاهل البوتات
        if message.author.bot:
            return
        # فقط داخل قناة التحقّق
        if not is_verify_channel(message.channel):
            return

        user_id = message.author.id
        session = pending_nickname_sessions.get(user_id)

        # أمر يدوي لبدء التدفّق إن احتاج
        if message.content.strip().lower().startswith("!setnick"):
            pending_nickname_sessions[user_id] = {"stage": "ask_name", "name": ""}
            await message.reply("ابدأ، اكتب اسمك (بدون فريق).", mention_author=True)
            return

        if not session:
            return  # لا جلسة حالية

        stage = session["stage"]
        content = message.content.strip()

        # حاول حذف الرسالة للتقليل من الضوضاء (اختياري)
        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        # المرحلة 1: الاسم
        if stage == "ask_name":
            base_name = content.replace("@", "").strip()
            if not base_name:
                await message.channel.send(
                    f"{message.author.mention} الرجاء إدخال اسم صالح."
                )
                return

            pending_nickname_sessions[user_id]["name"] = base_name
            pending_nickname_sessions[user_id]["stage"] = "ask_team"
            await message.channel.send(
                f"{message.author.mention} تمام! الآن اكتب اسم الفريق."
            )
            return

        # المرحلة 2: الفريق
        if stage == "ask_team":
            team = content.replace("@", "").strip()
            if not team:
                await message.channel.send(
                    f"{message.author.mention} الرجاء إدخال اسم فريق صالح."
                )
                return

            # جهّز الاسم النهائي
            final_nick = f"{pending_nickname_sessions[user_id]['name']}-{team}"

            # قصّ على 32 محرف إذا لزم الأمر (حد ديسكورد)
            if len(final_nick) > 32:
                name_part, team_part = pending_nickname_sessions[user_id]['name'], team
                max_total = 32
                # اترك 1 للشرطة
                half = (max_total - 1) // 2
                name_part = (name_part[:half]).rstrip()
                team_part = (team_part[:max_total - 1 - len(name_part)]).rstrip()
                final_nick = f"{name_part}-{team_part}"
                # ضمان عدم الفراغ
                if not name_part or not team_part:
                    final_nick = final_nick[:32].rstrip("-")

            # نفّذ التغيير
            guild = message.guild
            member = guild.get_member(user_id) if guild else None
            if not member:
                await message.channel.send(
                    f"{message.author.mention} تعذّر العثور على حسابك. حاول مجددًا."
                )
                pending_nickname_sessions.pop(user_id, None)
                return

            try:
                await member.edit(nick=final_nick, reason="Nickname setup: Name-Team")
                await message.channel.send(
                    f"{message.author.mention} تم ضبط اسمك: **{final_nick}** ✅"
                )
            except discord.Forbidden:
                await message.channel.send(
                    f"{message.author.mention} ⚠️ لا أستطيع تغيير الأسماء المستعارة. "
                    "رجاءً ارفع رتبة البوت فوق الأعضاء وتأكد من تفعيل **Manage Nicknames**."
                )
            except discord.HTTPException:
                await message.channel.send(
                    f"{message.author.mention} حدث خطأ غير متوقع أثناء تغيير الاسم."
                )
            finally:
                # إنهاء الجلسة
                pending_nickname_sessions.pop(user_id, None)

# سجّل الـ Cog
bot.add_cog(NicknameSetup(bot))
# ========= End Nickname Setup =========


if __name__ == "__main__":
    bot.run(TOKEN)
