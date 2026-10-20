from datetime import datetime, timedelta, timezone
import os
import random
from threading import Thread
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from flask import Flask
from TikTokLive import TikTokLiveClient

# --- FLASK WEBSERVER VOOR RENDER (HOUDT DE BOT DRAAIEND) ---
app = Flask("")


@app.route("/")
def home():
  return "Bot is online!"


def run():
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


def keep_alive():
  t = Thread(target=run)
  t.start()


# Start de webserver op de achtergrond
keep_alive()

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
  print("FOUT: Geen DISCORD_TOKEN gevonden in je .env bestand!")
  exit()

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- CONFIGURATIE ---
ROLE_ACCEPTEREN_BEHEER = 1556578093081305159
ROLE_PARTNER_ALLOW_EXTRA = [
    1475901447404126340,
    1545038388091166790,
    1562095503645212752,
]
ROLE_PARTNER_BEHEER = 1541819580173779026
ROLE_PARTNER_GEACCEPTEERD = 1558829178541838396

ROLE_DEV_PANEL_ALLOW = [
    1475901447404126340,
    1545038388091166790,
    1562095503645212752,
]
ROLE_DEV_GEACCEPTEERD = 1560268453020049569

OWNER_IDS = [1328766617164972115, 1305271257901695048]

SAY_ROLE_IDS = [
    1545038155508355153,
    1545038388091166790,
    1555907057549312060,
    1475901447404126340,
    1562095503645212752,
]

# ROLLEN DIE ALLES MOGEN:
ROLES_ALLES_MOGEN = [1545038388091166790, 1562095503645212752]

CHANNEL_AANVRAAG = 1555910106040762408
CHANNEL_PARTNER_PUBLIC = 1558743246883131432
CHANNEL_PARTNER_PANEL = 1542844065702350878
CHANNEL_TICKET = 1554523651745783940
CHANNEL_LOGS = 1555929585877524500
CHANNEL_REVIEW = 1487908079373652050

DEV_CATEGORIES = [1505470953021505699, 1530066947037855794]
CHANNEL_DEV_REVIEW = 1560214533900075078
CHANNEL_DEV_ANNOUNCEMENT = 1560267190488277113
CHANNEL_DEV_PROGRESS = 1489653908413350028

TIKTOK_HANDLES = ["faab9999_", "jcd_18"]
NOTIFICATION_CHANNEL_ID = 1555933500274642965

is_live_notified = {handle: False for handle in TIKTOK_HANDLES}

pending_partner_submissions = {}
pending_partner_messages = {}
partner_cooldowns = {}

current_user_assignment = {}
user_reroll_count = {}
claimed_assignments = set()

EXACT_PARTNER_BERICHT = (
    "# 👋 AVJ Online Winkel is een online winkel met verschillende Roblox"
    " producten.\n> \n> • What haben wij te bieden aan jou?\n> \n> 🟢 Heel veel"
    " gratis Roblox producten.\n> \n> 😉 Wij hebben heel veel keuze aan Roblox"
    " producten die je kunt kopen.\n> \n> 🤝 Wij helpen graag mensen die"
    " partner met ons willen worden.\n> \n> 🛠 Wij helpen graag mensen die"
    " problemen hebben met hun Roblox studio.\n> \n> 🤑 We zijn ook nog op zoek"
    " naar medewerkers die bij ons willen werken, dus misschien ben jij wel"
    " geschikt en lijkt het je leuk.\n> \n> ● Iedereen is van harte welkom om"
    " een kijkje te nemen in onze discord server.\n\n> 📸 Video:"
    " https://media.discordapp.net/attachments/1499730647219175464/1499730650272497745/Schermopname_2026-05-01_131436.mp4\n\n> 🔗"
    " https://discord.gg/hBeUBKUAsu"
)


async def safe_defer(interaction: discord.Interaction):
  if not interaction.response.is_done():
    try:
      await interaction.response.defer(ephemeral=True)
    except Exception:
      pass


def heeft_toestemming(interaction: discord.Interaction) -> bool:
  """Controleert of iemand owner is of een van de toegestane beheerrollen heeft."""
  if interaction.user.id in OWNER_IDS:
    return True
  if interaction.guild and hasattr(interaction.user, "roles"):
    user_role_ids = [r.id for r in interaction.user.roles]
    if any(r in user_role_ids for r in ROLES_ALLES_MOGEN):
      return True
    alle_toegestane_rollen = set(
        [ROLE_ACCEPTEREN_BEHEER, ROLE_PARTNER_BEHEER]
        + ROLE_PARTNER_ALLOW_EXTRA
        + ROLE_DEV_PANEL_ALLOW
        + SAY_ROLE_IDS
    )
    if any(rid in alle_toegestane_rollen for rid in user_role_ids):
      return True
  return False


async def get_guild_channel_safe(guild: discord.Guild, channel_id: int):
  if guild:
    channel = guild.get_channel(channel_id)
    if channel:
      return channel
    try:
      return await guild.fetch_channel(channel_id)
    except Exception:
      pass

  for g in bot.guilds:
    ch = g.get_channel(channel_id)
    if ch:
      return ch
    try:
      ch = await g.fetch_channel(channel_id)
      if ch:
        return ch
    except Exception:
      pass
  return None


async def get_random_dev_assignment(
    guild: discord.Guild, exclude_name: str = None
) -> str:
  candidates = []
  for cat_id in DEV_CATEGORIES:
    category = await get_guild_channel_safe(guild, cat_id)
    if category and isinstance(category, discord.CategoryChannel):
      for channel in category.channels:
        if isinstance(channel, discord.ForumChannel) or hasattr(
            channel, "threads"
        ):
          threads_to_check = list(channel.threads)
          try:
            archived = [t async for t in channel.archived_threads(limit=50)]
            threads_to_check.extend(archived)
          except Exception:
            pass
          for thread in threads_to_check:
            post_name = thread.name.strip()
            full_display = f"{post_name} (in <#{channel.id}>)"
            if (
                full_display not in claimed_assignments
                and full_display != exclude_name
            ):
              candidates.append(full_display)
        else:
          clean_name = f"{channel.name.replace('-', ' ').title()} (in <#{channel.id}>)"
          if (
              clean_name not in claimed_assignments
              and clean_name != exclude_name
          ):
            candidates.append(clean_name)
  return (
      random.choice(candidates)
      if candidates
      else "Algemene Roblox Ontwikkeling Opdracht"
  )


class TicketView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(
      label="Ticket aanmaken",
      style=discord.ButtonStyle.primary,
      emoji="🎫",
      custom_id="avj_create_ticket_v15",
  )
  async def create_ticket(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await safe_defer(interaction)
    guild = interaction.guild
    category = interaction.channel.category

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(
            read_messages=True, send_messages=True
        ),
        guild.me: discord.PermissionOverwrite(
            read_messages=True, send_messages=True
        ),
    }

    ticket_channel = await guild.create_text_channel(
        name=f"ticket-{interaction.user.name}",
        overwrites=overwrites,
        category=category,
    )

    await ticket_channel.send(
        f"Welkom {interaction.user.mention}! Een medewerker zal je zo snel"
        " mogelijk helpen. Stuur alvast je vraag of opmerking."
    )
    await interaction.followup.send(
        f"Je ticket is aangemaakt: {ticket_channel.mention}", ephemeral=True
    )


class DevPriceModal(discord.ui.Modal, title="Prijsopgave Developer Opdracht"):
  prijs = discord.ui.TextInput(
      label="Hoeveel geld zou jij hiervoor willen?",
      style=discord.TextStyle.short,
      placeholder="Bijv: €15.00 of 1500 Robux",
      required=True,
  )

  def __init__(self, assignment_name: str):
    super().__init__()
    self.assignment_name = assignment_name

  async def on_submit(self, interaction: discord.Interaction):
    await safe_defer(interaction)
    guild = interaction.guild or (
        interaction.client.guilds[0] if interaction.client.guilds else None
    )
    review_channel = await get_guild_channel_safe(guild, CHANNEL_DEV_REVIEW)

    if not review_channel:
      await interaction.followup.send(
          "❌ Fout: Het reviewkanaal kon niet worden gevonden.", ephemeral=True
      )
      return

    embed = discord.Embed(
        title="🛠️ Nieuwe Developer Opdracht Aanvraag",
        description=(
            "Een developer wil graag een opdracht uitvoeren voor **AVJ**."
        ),
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="👨‍💻 Developer",
        value=f"{interaction.user.mention} (`{interaction.user.id}`)",
        inline=False,
    )
    embed.add_field(
        name="📦 Gekozen Opdracht", value=f"{self.assignment_name}", inline=False
    )
    embed.add_field(
        name="💰 Vraagprijs", value=f"**{self.prijs.value}**", inline=False
    )
    embed.set_footer(
        text="AVJ Developer Beheer", icon_url=interaction.user.display_avatar.url
    )

    await review_channel.send(
        embed=embed,
        view=DevReviewActionView(
            applicant_id=interaction.user.id,
            assignment=self.assignment_name,
            price=self.prijs.value,
        ),
    )
    await interaction.followup.send(
        "✅ Je prijsopgave is succesvol ingediend!", ephemeral=True
    )


class DevReviewActionView(discord.ui.View):

  def __init__(self, applicant_id: int, assignment: str, price: str):
    super().__init__(timeout=None)
    self.applicant_id = applicant_id
    self.assignment = assignment
    self.price = price

  @discord.ui.button(
      label="Akkoord",
      style=discord.ButtonStyle.green,
      emoji="✅",
      custom_id="avj_dev_review_accept_v15",
  )
  async def accept_dev(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await safe_defer(interaction)
    guild = interaction.guild or (bot.guilds[0] if bot.guilds else None)

    for child in self.children:
      child.disabled = True
    try:
      await interaction.message.edit(view=self)
    except Exception:
      pass

    member = None
    if guild:
      try:
        member = await guild.fetch_member(self.applicant_id)
      except discord.NotFound:
        member = guild.get_member(self.applicant_id)
      if member:
        role = guild.get_role(ROLE_DEV_GEACCEPTEERD)
        if role:
          try:
            await member.add_roles(role)
          except Exception as e:
            print(f"Fout bij toewijzen rol: {e}")

    claimed_assignments.add(self.assignment)
    dm_text = (
        "Uw opdracht-aanvraag is **goedgekeurd**! U kunt nu aan de slag.\n\nZorg"
        " ervoor dat u te allen tijde foto's blijft sturen van uw project in het"
        f" kanaal: <#{CHANNEL_DEV_PROGRESS}>.\nZodra uw project klaar is kunt u"
        " <@1328766617164972115> een dm sturen met uw download bestand."
    )

    user_to_dm = member or await bot.fetch_user(self.applicant_id)
    if user_to_dm:
      try:
        await user_to_dm.send(dm_text)
      except discord.Forbidden:
        pass

    announcement_channel = await get_guild_channel_safe(
        guild, CHANNEL_DEV_ANNOUNCEMENT
    )
    if announcement_channel and user_to_dm:
      embed_ann = discord.Embed(
          title="🚀 Nieuwe Developer Gestart!",
          description=(
              f"Developer {user_to_dm.mention} is gestart met:"
              f" **{self.assignment}**!"
          ),
          color=discord.Color.green(),
          timestamp=datetime.now(timezone.utc),
      )
      await announcement_channel.send(
          content=f"🎉 {user_to_dm.mention}", embed=embed_ann
      )

    await interaction.followup.send("✅ Goedgekeurd!", ephemeral=True)

  @discord.ui.button(
      label="Deny",
      style=discord.ButtonStyle.red,
      emoji="❌",
      custom_id="avj_dev_review_deny_v15",
  )
  async def deny_dev(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await safe_defer(interaction)
    for child in self.children:
      child.disabled = True
    try:
      await interaction.message.edit(view=self)
    except Exception:
      pass

    try:
      user_to_dm = await bot.fetch_user(self.applicant_id)
      if user_to_dm:
        await user_to_dm.send(
            f"Uw aanvraag voor **{self.assignment}** is helaas afgekeurd."
        )
    except discord.Forbidden:
      pass

    await interaction.followup.send("❌ Afgekeurd.", ephemeral=True)


class DevChoiceView(discord.ui.View):

  def __init__(self, user_id: int, current_assignment: str):
    super().__init__(timeout=300)
    self.user_id = user_id
    self.current_assignment = current_assignment

  @discord.ui.button(
      label="Akkoord gaan met opdracht",
      style=discord.ButtonStyle.green,
      emoji="✅",
      custom_id="avj_dev_choice_accept_v15",
  )
  async def accept_assignment(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    for child in self.children:
      child.disabled = True
    try:
      await interaction.message.edit(view=self)
    except Exception:
      pass
    await interaction.response.send_modal(
        DevPriceModal(assignment_name=self.current_assignment)
    )

  @discord.ui.button(
      label="Maak een andere opdracht",
      style=discord.ButtonStyle.secondary,
      emoji="🔀",
      custom_id="avj_dev_choice_reroll_v15",
  )
  async def reroll_assignment(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await safe_defer(interaction)
    current_count = user_reroll_count.get(self.user_id, 0)
    if current_count >= 1:
      await interaction.followup.send(
          "⚠️ Je hebt je maximale aantal wissels al gebruikt!", ephemeral=True
      )
      return

    user_reroll_count[self.user_id] = current_count + 1
    guild = interaction.guild or (
        interaction.client.guilds[0] if interaction.client.guilds else None
    )
    new_assignment = await get_random_dev_assignment(
        guild, exclude_name=self.current_assignment
    )
    current_user_assignment[self.user_id] = new_assignment

    for child in self.children:
      child.disabled = True
    try:
      await interaction.message.edit(view=self)
    except Exception:
      pass

    embed = discord.Embed(
        title="🛠️ Nieuwe Opdracht",
        description=f"**{new_assignment}**\n\nGa je akkoord?",
        color=discord.Color.purple(),
    )
    try:
      await interaction.user.send(
          embed=embed, view=DevChoiceViewSingle(self.user_id, new_assignment)
      )
      await interaction.followup.send(
          "Nieuwe opdracht gestuurd via DM!", ephemeral=True
      )
    except discord.Forbidden:
      await interaction.followup.send(
          "❌ Kan geen DM sturen.", ephemeral=True
      )


class DevChoiceViewSingle(discord.ui.View):

  def __init__(self, user_id: int, current_assignment: str):
    super().__init__(timeout=300)
    self.user_id = user_id
    self.current_assignment = current_assignment

  @discord.ui.button(
      label="Akkoord gaan met opdracht",
      style=discord.ButtonStyle.green,
      emoji="✅",
      custom_id="avj_dev_choice_single_accept_v15",
  )
  async def accept_assignment(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    for child in self.children:
      child.disabled = True
    try:
      await interaction.message.edit(view=self)
    except Exception:
      pass
    await interaction.response.send_modal(
        DevPriceModal(assignment_name=self.current_assignment)
    )


class DevStartView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(
      label="Opdracht Maken voor AVJ",
      style=discord.ButtonStyle.primary,
      emoji="💼",
      custom_id="avj_dev_start_btn_v15",
  )
  async def start_dev(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await safe_defer(interaction)
    user_id = interaction.user.id
    guild = interaction.guild or (bot.guilds[0] if bot.guilds else None)

    assignment = await get_random_dev_assignment(guild)
    current_user_assignment[user_id] = assignment
    user_reroll_count[user_id] = 0

    embed = discord.Embed(
        title="✨ Developer Programma",
        description=f"**Opdracht:**\n> {assignment}\n\nWat wil je doen?",
        color=discord.Color.gold(),
    )
    try:
      dm = await interaction.user.create_dm()
      await dm.send(embed=embed, view=DevChoiceView(user_id, assignment))
      await interaction.followup.send("Privébericht verzonden!", ephemeral=True)
    except discord.Forbidden:
      await interaction.followup.send(
          "❌ Zet je DM's open.", ephemeral=True
      )


class DenyReasonModal(discord.ui.Modal, title="Aanvraag Afkeuren"):
  reden = discord.ui.TextInput(
      label="Reden van afkeuring",
      style=discord.TextStyle.paragraph,
      required=True,
  )

  def __init__(
      self,
      member: discord.Member,
      original_message: discord.Message,
      view_instance: discord.ui.View,
  ):
    super().__init__()
    self.member = member
    self.original_message = original_message
    self.view_instance = view_instance

  async def on_submit(self, interaction: discord.Interaction):
    await safe_defer(interaction)
    for child in self.view_instance.children:
      child.disabled = True
    try:
      await self.original_message.edit(view=self.view_instance)
    except Exception:
      pass

    try:
      await self.member.send(
          f"❌ Afgekeurd.\n**Reden:** {self.reden.value}"
      )
    except discord.Forbidden:
      pass

    partner_cooldowns.pop(self.member.id, None)
    await interaction.followup.send("Aanvraag afgekeurd.", ephemeral=True)


class PartnerReviewView(discord.ui.View):

  def __init__(self, member: discord.Member):
    super().__init__(timeout=None)
    self.member = member

  async def interaction_check(self, interaction: discord.Interaction) -> bool:
    if heeft_toestemming(interaction):
      return True
    await interaction.response.send_message("❌ Geen toestemming.", ephemeral=True)
    return False

  @discord.ui.button(
      label="Accepteren",
      style=discord.ButtonStyle.green,
      custom_id="avj_partner_accept_btn_v15",
  )
  async def accept_partner(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await safe_defer(interaction)
    guild = interaction.guild or (bot.guilds[0] if bot.guilds else None)

    for child in self.children:
      child.disabled = True
    try:
      await interaction.message.edit(view=self)
    except Exception:
      pass

    if guild:
      try:
        member = await guild.fetch_member(self.member.id)
      except discord.NotFound:
        member = guild.get_member(self.member.id)
      if member:
        role = guild.get_role(ROLE_PARTNER_GEACCEPTEERD)
        if role:
          try:
            await member.add_roles(role)
          except Exception as e:
            print(f"Fout bij toewijzen rol: {e}")

    try:
      await self.member.send("✅ Je partner-aanvraag is geaccepteerd!")
    except discord.Forbidden:
      pass

    partner_kanaal = await get_guild_channel_safe(guild, CHANNEL_PARTNER_PUBLIC)
    if partner_kanaal:
      await partner_kanaal.send(
          content=pending_partner_messages.get(self.member.id, "Geen bericht.")
      )

    log_kanaal = await get_guild_channel_safe(guild, CHANNEL_LOGS)
    if log_kanaal:
      embed_log = discord.Embed(
          title="✅ Partner Geaccepteerd",
          description=f"**Aanvrager:** {self.member.mention}",
          color=discord.Color.green(),
      )
      await log_kanaal.send(embed=embed_log)

    pending_partner_submissions.pop(self.member.id, None)
    pending_partner_messages.pop(self.member.id, None)
    partner_cooldowns.pop(self.member.id, None)
    await interaction.followup.send("Geaccepteerd!", ephemeral=True)

  @discord.ui.button(
      label="Afkeuren",
      style=discord.ButtonStyle.red,
      custom_id="avj_partner_deny_btn_v15",
  )
  async def deny_partner(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(
        DenyReasonModal(self.member, interaction.message, self)
    )


class PartnerMemberCheckView(discord.ui.View):

  def __init__(self, user_id: int):
    super().__init__(timeout=300)
    self.user_id = user_id

  @discord.ui.button(
      label="Ja",
      style=discord.ButtonStyle.green,
      custom_id="avj_partner_members_yes",
  )
  async def members_yes(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await safe_defer(interaction)
    for child in self.children:
      child.disabled = True
    try:
      await interaction.message.edit(view=self)
    except Exception:
      pass

    await interaction.followup.send(
        f"✅ Top!\n\nPlaats dit bericht in jouw"
        f" server:\n\n{EXACT_PARTNER_BERICHT}\n\n📸 **Stuur daarna een screenshot"
        " in deze DM:**",
        ephemeral=False,
    )

  @discord.ui.button(
      label="Nee",
      style=discord.ButtonStyle.red,
      custom_id="avj_partner_members_no",
  )
  async def members_no(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await safe_defer(interaction)
    for child in self.children:
      child.disabled = True
    try:
      await interaction.message.edit(view=self)
    except Exception:
      pass

    partner_cooldowns.pop(self.user_id, None)
    await interaction.followup.send(
        "❌ Helaas, je hebt minimaal 15 leden nodig om partner te kunnen"
        " worden met AVJ Online Winkel.",
        ephemeral=False,
    )


class PartnerStartView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(
      label="Start Partner Aanvraag",
      style=discord.ButtonStyle.green,
      custom_id="avj_partner_start_btn_v15",
  )
  async def start_partner_button(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await safe_defer(interaction)
    user_id = interaction.user.id
    now = datetime.now(timezone.utc)

    if user_id in partner_cooldowns and now - partner_cooldowns[
        user_id
    ] < timedelta(hours=12):
      await interaction.followup.send(
          "⏳ Je kunt dit maar 1x per 12 uur doen.", ephemeral=True
      )
      return

    partner_cooldowns[user_id] = now
    try:
      dm = await interaction.user.create_dm()
      await dm.send(
          "❓ **Heb je 15 of meer leden in je Discord server?**",
          view=PartnerMemberCheckView(user_id),
      )
      await interaction.followup.send("Check je DM!", ephemeral=True)
    except discord.Forbidden:
      partner_cooldowns.pop(user_id, None)
      await interaction.followup.send(
          "❌ Kan geen DM sturen.", ephemeral=True
      )


@tasks.loop(seconds=30)
async def check_tiktok_live():
  global is_live_notified
  for handle in TIKTOK_HANDLES:
    try:
      client = TikTokLiveClient(unique_id=handle)
      is_live = await client.is_live()
      if is_live and not is_live_notified[handle]:
        is_live_notified[handle] = True
        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if channel:
          await channel.send(f"Live: https://www.tiktok.com/@{handle}/live")
      elif not is_live:
        is_live_notified[handle] = False
    except Exception as e:
      print(f"TikTok fout: {e}")


@check_tiktok_live.before_loop
async def before_check_tiktok_live():
  await bot.wait_until_ready()


@bot.event
async def on_ready():
  print(f"Ingelogd als {bot.user.name}")
  bot.add_view(PartnerStartView())
  bot.add_view(DevStartView())
  bot.add_view(TicketView())

  try:
    for guild in bot.guilds:
      bot.tree.copy_global_to(guild=guild)
      await bot.tree.sync(guild=guild)
    print("✅ Commands gesynchroniseerd!")
  except Exception as e:
    print(f"Sync fout: {e}")

  if not check_tiktok_live.is_running():
    check_tiktok_live.start()


@bot.event
async def on_message(message):
  if message.author.bot:
    return

  if isinstance(message.channel, discord.DMChannel):
    user_id = message.author.id

    if message.attachments:
      if user_id not in pending_partner_submissions:
        pending_partner_submissions[user_id] = message.attachments[0].url
        await message.channel.send(
            "📸 Ontvangen! Stuur nu je partner bericht in deze DM:"
        )

    elif message.content:
      if (
          user_id in pending_partner_submissions
          and user_id not in pending_partner_messages
      ):
        pending_partner_messages[user_id] = message.content
        aanvraag_kanaal = await get_guild_channel_safe(None, CHANNEL_AANVRAAG)

        if aanvraag_kanaal:
          embed = discord.Embed(
              title="🤝 Nieuwe Partner Aanvraag",
              description=(
                  f"**Gebruiker:**"
                  f" {message.author.mention}\n\n{message.content}"
              ),
              color=discord.Color.blue(),
          )
          if pending_partner_submissions.get(user_id):
            embed.set_image(url=pending_partner_submissions[user_id])
          await aanvraag_kanaal.send(
              embed=embed, view=PartnerReviewView(message.author)
          )
          await message.channel.send(
              "✅ Ingediend bij het beheerteam!"
          )
        else:
          await message.channel.send(
              "❌ Er is een fout opgetreden: het aanvraagkanaal kon niet worden"
              " gevonden."
          )

  await bot.process_commands(message)


@bot.tree.command(
    name="devopdracht", description="Plaats het paneel voor developer opdrachten."
)
async def devopdracht_panel(interaction: discord.Interaction):
  await safe_defer(interaction)
  if not heeft_toestemming(interaction):
    await interaction.followup.send("❌ Geen toestemming.", ephemeral=True)
    return

  embed = discord.Embed(
      title="💼 Developer Opdrachten",
      description="Klik hieronder om te starten!",
      color=discord.Color.blue(),
  )
  await interaction.channel.send(embed=embed, view=DevStartView())
  await interaction.followup.send("✅ Geplaatst!", ephemeral=True)


@bot.tree.command(
    name="resetpartner", description="Reset de partner cooldown van een gebruiker."
)
@app_commands.describe(
    gebruiker="De gebruiker wiens cooldown gereset moet worden"
)
async def resetpartner(interaction: discord.Interaction, gebruiker: discord.User):
  await safe_defer(interaction)
  if not heeft_toestemming(interaction):
    await interaction.followup.send("❌ Geen toestemming.", ephemeral=True)
    return

  partner_cooldowns.pop(gebruiker.id, None)
  keys_to_delete = [
      k for k in partner_cooldowns.keys() if str(k) == str(gebruiker.id)
  ]
  for k in keys_to_delete:
    partner_cooldowns.pop(k, None)

  await interaction.followup.send(
      f"✅ Partner cooldown voor {gebruiker.mention} is succesvol gereset!",
      ephemeral=True,
  )


@bot.tree.command(name="review", description="Geef een review.")
@app_commands.describe(naam="Naam", sterren="Sterren 1-5", tips_of_uitleg="Uitleg")
@app_commands.choices(
    sterren=[
        app_commands.Choice(name="⭐ 1 Ster", value=1),
        app_commands.Choice(name="⭐⭐ 2 Sterren", value=2),
        app_commands.Choice(name="⭐⭐⭐ 3 Sterren", value=3),
        app_commands.Choice(name="⭐⭐⭐⭐ 4 Sterren", value=4),
        app_commands.Choice(name="⭐⭐⭐⭐⭐ 5 Sterren", value=5),
    ]
)
async def review_command(
    interaction: discord.Interaction,
    naam: str,
    sterren: int,
    tips_of_uitleg: str,
):
  await safe_defer(interaction)
  guild = interaction.guild
  review_kanaal = await get_guild_channel_safe(guild, CHANNEL_REVIEW)
  if not review_kanaal:
    await interaction.followup.send(
        "Review kanaal niet gevonden.", ephemeral=True
    )
    return

  embed = discord.Embed(
      title="🌟 Nieuwe Review",
      color=discord.Color.gold(),
      timestamp=datetime.now(timezone.utc),
  )
  embed.add_field(name="Service", value=naam, inline=False)
  embed.add_field(name="Beoordeling", value="⭐" * sterren, inline=False)
  embed.add_field(name="Uitleg", value=tips_of_uitleg, inline=False)
  await review_kanaal.send(embed=embed)
  await interaction.followup.send("Review geplaatst!", ephemeral=True)


@bot.tree.command(name="say", description="Laat de bot een bericht sturen.")
@app_commands.describe(bericht="Bericht", afbeelding="Afbeelding")
async def say_command(
    interaction: discord.Interaction,
    bericht: str,
    afbeelding: discord.Attachment = None,
):
  await safe_defer(interaction)
  if not heeft_toestemming(interaction):
    await interaction.followup.send("❌ Geen toestemming.", ephemeral=True)
    return

  file = await afbeelding.to_file() if afbeelding else None
  await interaction.channel.send(content=bericht, file=file)
  await interaction.followup.send("Verzonden!", ephemeral=True)


@bot.tree.command(
    name="partnerpanel",
    description="Plaats het korte partner paneel in het juiste kanaal.",
)
async def partnerpanel(interaction: discord.Interaction):
  await safe_defer(interaction)
  if not heeft_toestemming(interaction):
    await interaction.followup.send("❌ Geen toestemming.", ephemeral=True)
    return

  target = await get_guild_channel_safe(interaction.guild, CHANNEL_PARTNER_PANEL)
  if not target:
    await interaction.followup.send(
        "❌ Partner panel kanaal kon niet worden gevonden.", ephemeral=True
    )
    return

  try:
    async for message in target.history(limit=50):
      if message.author == bot.user or message.webhook_id is not None:
        if message.embeds and any(
            "Partner" in (e.title or "") for e in message.embeds
        ):
          try:
            await message.delete()
          except Exception:
            pass
  except Exception as e:
    print(f"Fout bij opschonen kanaal: {e}")

  embed = discord.Embed(
      title="🤝 Partner Worden",
      description="Klik op de knop om partner te worden!",
      color=discord.Color.blurple(),
  )

  await target.send(embed=embed, view=PartnerStartView())
  await interaction.followup.send(
      f"✅ Partner panel succesvol geplaatst in {target.mention}!", ephemeral=True
  )


bot.run(TOKEN)
