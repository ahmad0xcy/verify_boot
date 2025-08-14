# bot.py — Discord Verify Bot (DM-based)
import os
import asyncio
from typing import Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv

# ---- Load environment variables ----
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
VERIFIED_ROLE_NAME = os.getenv("VERIFIED_ROLE", "Verified")
VERIFY_PASSWORD = os.getenv("VERIFY_PASSWORD", "secret123")

if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is missing. Set it in your environment variables.")

# ---- Intents & bot setup ----
intents = discord.Intents.default()
intents.members = True              # required to manage roles & on_member_join
intents.message_content = True      # required to read DM messages

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# ---- Helpers ----
async def ensure_verified_role(guild: discord.Guild) -> discord.Role:
    """Get or create the Verified role."""
    role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)
    if role:
        return role
    # Create role if missing (requires Manage Roles permission)
    role = await guild.create_role(name=VERIFIED_ROLE_NAME, mentionable=True, reason="Create verified role")
    return role


async def add_verified(member: discord.Member) -> bool:
    """Add the Verified role to the given member. Returns True on success."""
    guild = member.guild
    role = await ensure_verified_role(guild)
    # Bot's role must be ABOVE the target role
    await member.add_roles(role, reason="Verification passed")
    return True


def is_dm(channel: discord.abc.Messageable) -> bool:
    return isinstance(channel, discord.DMChannel)


# ---- Events ----
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    if GUILD_ID:
        print(f"ℹ️  Target guild: {GUILD_ID}; verified role name: {VERIFIED_ROLE_NAME}")
    else:
        print("⚠️  GUILD_ID is not set. The bot will try to resolve the guild via mutual guilds.")


@bot.event
async def on_member_join(member: discord.Member):
    """Send the verification prompt to new members via DM."""
    if member.bot:
        return
    try:
        dm = await member.create_dm()
        await dm.send(
            "Hello! 👋\n"
            "This server uses a password-based verification.\n"
            f"Please reply with the password to get the **{VERIFIED_ROLE_NAME}** role."
        )
    except discord.Forbidden:
        # DM is closed – optionally notify staff in a mod channel (not implemented)
        pass


@bot.event
async def on_message(message: discord.Message):
    """Handle DM messages: verify when the correct password is sent."""
    # Ignore messages from the bot itself
    if message.author.bot:
        return

    if is_dm(message.channel):
        # User is messaging the bot in DMs
        content = message.content.strip()
        # Optional: ignore empty/very short messages
        if not content:
            return

        # Try to find the member in the target guild
        target_guild: Optional[discord.Guild] = None
        target_member: Optional[discord.Member] = None

        if GUILD_ID:
            target_guild = bot.get_guild(GUILD_ID)

        # Fallback: detect the first mutual guild if GUILD_ID wasn't set
        if not target_guild and message.author.mutual_guilds:
            target_guild = message.author.mutual_guilds[0]

        if not target_guild:
            await message.channel.send("I couldn't find the target server. Please contact the moderators.")
            return

        target_member = target_guild.get_member(message.author.id)
        if not target_member:
            await message.channel.send("I couldn't find you in the server. Did you leave? Please re-join and try again.")
            return

        # Compare password
        if content == VERIFY_PASSWORD:
            try:
                await add_verified(target_member)
                await message.channel.send("✅ Verification successful! You now have access.")
            except discord.Forbidden:
                await message.channel.send(
                    "⚠️ I don't have permission to assign roles. Please tell an admin to move my role above the verified role."
                )
            except Exception as e:
                await message.channel.send("❌ Something went wrong while assigning the role. Please contact staff.")
                print(f"[verify-error] {repr(e)}")
        else:
            await message.channel.send("❌ Incorrect password. Please try again.")

    # Allow other commands to be processed (e.g., !ping)
    await bot.process_commands(message)


# ---- Commands ----
@bot.command(name="ping")
async def ping(ctx: commands.Context):
    """Simple health check."""
    await ctx.reply("Pong!", mention_author=False)


@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    """Minimal help."""
    await ctx.reply(
        "Available commands:\n"
        "• `!ping` – quick test.\n"
        "Verification is handled in DMs: reply with the correct password to get verified.",
        mention_author=False,
    )


# Slash command to nudge a user with a DM prompt (staff only)
@bot.tree.command(name="manual_verify", description="Send a DM to the user asking for the password.")
@discord.app_commands.describe(user="Member to verify")
@discord.app_commands.checks.has_permissions(manage_roles=True)
async def manual_verify(interaction: discord.Interaction, user: discord.Member):
    if user.bot:
        await interaction.response.send_message("Bots cannot be verified.", ephemeral=True)
        return
    try:
        dm = await user.create_dm()
        await dm.send(
            "Hello! 👋\n"
            "Please reply with the password to complete verification."
        )
        await interaction.response.send_message("Verification message sent via DM ✅", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("I cannot DM this user (DMs disabled).", ephemeral=True)


# Ensure the slash command is synced (especially useful when running on Railway)
@bot.event
async def setup_hook():
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        else:
            await bot.tree.sync()
    except Exception as e:
        print(f"⚠️ Slash command sync failed: {e}")


if __name__ == "__main__":
    bot.run(TOKEN)
