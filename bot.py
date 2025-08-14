import os, asyncio
import discord
from dotenv import load_dotenv

print("🔎 starting verify-bot…")

# 1) حمّل .env
env_loaded = load_dotenv()
print(f"📄 .env loaded: {env_loaded}")

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
VERIFIED_ROLE_NAME = os.getenv("VERIFIED_ROLE", "Verified")
VERIFY_PASSWORD = os.getenv("VERIFY_PASSWORD", "secret123")

print(f"✅ TOKEN present: {bool(TOKEN)}")
print(f"ℹ️  GUILD_ID: {GUILD_ID}")
print(f"ℹ️  VERIFIED_ROLE: {VERIFIED_ROLE_NAME}")
print(f"ℹ️  VERIFY_PASSWORD set: {bool(VERIFY_PASSWORD)}")

if not TOKEN:
    raise SystemExit("❌ DISCORD_TOKEN مفقود في .env")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class Client(discord.Client):
    async def on_ready(self):
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")

    async def on_error(self, event_method, *args, **kwargs):
        import traceback
        print("❗ on_error:", event_method)
        traceback.print_exc()

client = Client(intents=intents)

@client.event
async def on_member_join(member: discord.Member):
    if member.bot: 
        return
    print(f"👋 member joined: {member} ({member.id})")
    try:
        dm = await member.create_dm()
        await dm.send("أهلًا! أرسل كلمة السر للتحقق.")
    except discord.Forbidden:
        print("⚠️ لا أستطيع مراسلة العضو في الخاص.")

try:
    print("🔗 connecting to Discord…")
    client.run(TOKEN)
except Exception as e:
    print("💥 FATAL:", repr(e))
    raise
