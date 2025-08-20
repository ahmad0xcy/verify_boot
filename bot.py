# ========= Nickname Setup (Additive Cog) =========
from discord.ext import commands

# جلسات التعيين: user_id -> {"stage": "ask_name"/"ask_team", "name": str}
pending_nickname_sessions: dict[int, dict[str, str]] = {}

class NicknameSetup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # عندما العضو تُضاف له رتبة التحقّق، ابدأ التدفّق
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # تأكد أن الحدث ضمن سيرفر وأن الرتبة المضافة هي VERIFIED_ROLE_NAME
        if before.guild is None or after.guild is None:
            return

        added_roles = set(after.roles) - set(before.roles)
        if not added_roles:
            return

        # تحقق هل رتبة VERIFIED_ROLE_NAME ضمن المضافة
        verified_role = discord.utils.get(after.guild.roles, name=VERIFIED_ROLE_NAME)
        if verified_role and verified_role in added_roles:
            # ابدأ جلسة جمع الاسم/الفريق
            pending_nickname_sessions[after.id] = {"stage": "ask_name", "name": ""}
            # أرسل السؤال في قناة التحقّق
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
    async def on_message(self, message: discord.Message):
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
            # تحققات بسيطة وطول Discord (32 محرف للاسم المستعار)
            base_name = content
            # إزالة @ وأشياء غير ضرورية
            base_name = base_name.replace("@", "").strip()
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

            # قصّ على 32 محرف إذا لزم الأمر
            if len(final_nick) > 32:
                # حاول تقصير الجزءين بشكل معقول
                name_part, team_part = pending_nickname_sessions[user_id]['name'], team
                max_total = 32
                # أعد توزيع الطول: نصفين تقريبا مع شرطة
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
