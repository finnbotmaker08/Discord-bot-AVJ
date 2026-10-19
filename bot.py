from datetime import datetime, timedelta, timezone
import os
import random
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from TikTokLive import TikTokLiveClient

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
ROLE_ACCEPTEREN_BEHEER = 1556578093081305159  # Standaard partner beheer rol
ROLE_PARTNER_ALLOW_EXTRA = [1475901447404126340, 1545038388091166790]  # Extra rollen toegestaan voor partner beoordeling
ROLE_PARTNER_BEHEER = 1541819580173779026
ROLE_PARTNER_GEACCEPTEERD = 1558829178541838396  # Rol die automatisch wordt gegeven bij partner acceptatie

# Developer Opdracht Configuraties
ROLE_DEV_PANEL_ALLOW = [1475901447404126340, 1545038388091166790]  # Rollen toegestaan voor /devopdracht
ROLE_DEV_GEACCEPTEERD = 1560268453020049569                       # Rol voor geaccepteerde developers

# Discord ID's die ALTIJD overal toegang toe hebben
OWNER_IDS = [1328766617164972115, 1305271257901695048]

# Rollen die toegang hebben tot het /say commando
SAY_ROLE_IDS = [
    1545038155508355153,
    1545038388091166790,
    1555907057549312060,
    1475901447404126340
]

# Kanalen
CHANNEL_AANVRAAG = 1555910106040762408        # 1e indiening Partner (Beoordelingskanaal)
CHANNEL_PARTNER_PUBLIC = 1558743246883131432  # 2e indiening Partner (Openbaar partnerkanaal)
CHANNEL_PARTNER_PANEL = 1542844065702350878   # Waar het partnerpanel staat
CHANNEL_TICKET = 1554523651745783940          # Waar het ticketpanel staat
CHANNEL_LOGS = 1555929585877524500            # Logkanaal
CHANNEL_REVIEW = 1487908079373652050          # Reviewkanaal

# Dev Opdracht Kanalen & Categorieën
DEV_CATEGORIES = [1505470953021505699, 1530066947037855794]
CHANNEL_DEV_REVIEW = 1560214533900075078      # Goedkeuringskanaal voor dev opdrachten
CHANNEL_DEV_ANNOUNCEMENT = 1560267190488277113  # Kanaal voor goedgekeurde opdrachten
CHANNEL_DEV_PROGRESS = 1489653908413350028      # Voortgangskanaal voor developers

# --- TIKTOK LIVE CONFIGURATIE ---
TIKTOK_HANDLES = ["faab9999_", "jcd_18"]
NOTIFICATION_CHANNEL_ID = 1555933500274642965

is_live_notified = {handle: False for handle in TIKTOK_HANDLES}

# Geheugen
pending_partner_submissions = {}  # user_id -> image_url
pending_partner_messages = {}     # user_id -> partner bericht tekst
partner_cooldowns = {}            # user_id -> datetime van laatste aanvraag

# Dev Opdrachten Geheugen
current_user_assignment = {}     # user_id -> gekozen opdracht weergave
user_reroll_count = {}           # user_id -> aantal keren dat er is gekozen voor "andere opdracht"
claimed_assignments = set()      # Unieke opdrachten die al geaccepteerd/geclaimd zijn

EXACT_PARTNER_BERICHT = (
    "# 👋 AVJ Online Winkel is een online winkel met verschillende Roblox producten.\n"
    "> \n"
    "> • What haben wij te bieden aan jou?\n"
    "> \n"
    "> 🟢 Heel veel gratis Roblox producten.\n"
    "> \n"
    "> 😉 Wij hebben heel veel keuze aan Roblox producten die je kunt kopen.\n"
    "> \n"
    "> 🤝 Wij helpen graag mensen die partner met ons willen worden.\n"
    "> \n"
    "> 🛠 Wij helpen graag mensen die problemen hebben met hun Roblox studio.\n"
    "> \n"
    "> 🤑 We zijn ook nog op zoek naar medewerkers die bij ons willen werken, dus misschien ben jij wel geschikt en lijkt het je leuk.\n"
    "> \n"
    "> ● Iedereen is van harte welkom om een kijkje te nemen in onze discord server.\n\n"
    "> 📸 Video: https://media.discordapp.net/attachments/1499730647219175464/1499730650272497745/Schermopname_2026-05-01_131436.mp4\n\n"
    "> 🔗 https://discord.gg/hBeUBKUAsu"
)


async def safe_defer(interaction: discord.Interaction):
    """Zorgt ervoor dat defer nooit vastloopt op verlopen of reeds beantwoorde interacties."""
    if not interaction.response.is_done():
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass


async def get_guild_channel_safe(guild: discord.Guild, channel_id: int):
    """Haalt een kanaal op via cache of API om 'None' fouten te voorkomen."""
    if not guild:
        return None
    channel = guild.get_channel(channel_id)
    if not channel:
        try:
            channel = await guild.fetch_channel(channel_id)
        except Exception:
            pass
    return channel


async def get_random_dev_assignment(guild: discord.Guild, exclude_name: str = None) -> str:
    """Haalt forum-posts (threads) op uit de opgegeven categorieën en voegt de kanaaltag toe."""
    candidates = []

    for cat_id in DEV_CATEGORIES:
        category = await get_guild_channel_safe(guild, cat_id)
        if category and isinstance(category, discord.CategoryChannel):
            for channel in category.channels:
                if isinstance(channel, discord.ForumChannel) or hasattr(channel, 'threads'):
                    threads_to_check = list(channel.threads)
                    try:
                        archived = [t async for t in channel.archived_threads(limit=50)]
                        threads_to_check.extend(archived)
                    except Exception:
                        pass

                    for thread in threads_to_check:
                        post_name = thread.name.strip()
                        full_display = f"{post_name} (in <#{channel.id}>)"

                        if full_display not in claimed_assignments and full_display != exclude_name:
                            candidates.append(full_display)
                else:
                    clean_name = f"{channel.name.replace('-', ' ').title()} (in <#{channel.id}>)"
                    if clean_name not in claimed_assignments and clean_name != exclude_name:
                        candidates.append(clean_name)

    if not candidates:
        fallback_list = [
            "Augurtenfabriek (in <#1505470953021505699>)",
            "Fabriekmachine (in <#1505470953021505699>)",
            "Luxe Appartement (in <#1505470953021505699>)",
            "Hoge Woning (in <#1505470953021505699>)"
        ]
        candidates = [f for f in fallback_list if f not in claimed_assignments and f != exclude_name]

    return random.choice(candidates) if candidates else "Algemene Roblox Ontwikkeling Opdracht"


# --- TICKET SYSTEEM VIEWS ---

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket aanmaken", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="avj_create_ticket_v2")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safe_defer(interaction)
        guild = interaction.guild
        category = interaction.channel.category

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            overwrites=overwrites,
            category=category
        )

        await ticket_channel.send(f"Welkom {interaction.user.mention}! Een medewerker zal je zo snel mogelijk helpen. Stuur alvast je vraag of opmerking.")
        await interaction.followup.send(f"Je ticket is aangemaakt: {ticket_channel.mention}", ephemeral=True)


# --- DEV OPDRACHT VIEWS & MODALS ---

class DevPriceModal(discord.ui.Modal, title="Prijsopgave Developer Opdracht"):
    prijs = discord.ui.TextInput(
        label="Hoeveel geld zou jij hiervoor willen?",
        style=discord.TextStyle.short,
        placeholder="Bijv: €15.00 of 1500 Robux",
        required=True
    )

    def __init__(self, assignment_name: str):
        super().__init__()
        self.assignment_name = assignment_name

    async def on_submit(self, interaction: discord.Interaction):
        await safe_defer(interaction)

        guild = interaction.guild or (interaction.client.guilds[0] if interaction.client.guilds else None)
        review_channel = await get_guild_channel_safe(guild, CHANNEL_DEV_REVIEW) if guild else None

        if not review_channel:
            await interaction.followup.send("❌ Fout: Het reviewkanaal voor opdrachten kon niet worden gevonden.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🛠️ Nieuwe Developer Opdracht Aanvraag",
            description=f"Een developer wil graag een opdracht uitvoeren voor **AVJ**.",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="👨‍💻 Developer", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="📦 Gekozen Opdracht", value=f"{self.assignment_name}", inline=False)
        embed.add_field(name="💰 Vraagprijs", value=f"**{self.prijs.value}**", inline=False)
        embed.set_footer(text="AVJ Developer Beheer", icon_url=interaction.user.display_avatar.url)

        await review_channel.send(
            embed=embed,
            view=DevReviewActionView(applicant_id=interaction.user.id, assignment=self.assignment_name, price=self.prijs.value)
        )

        await interaction.followup.send("✅ Je prijsopgave is succesvol ingediend! De staf zal je aanvraag beoordelen.", ephemeral=True)


class DevReviewActionView(discord.ui.View):
    def __init__(self, applicant_id: int, assignment: str, price: str):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.assignment = assignment
        self.price = price

    @discord.ui.button(label="Akkoord", style=discord.ButtonStyle.green, emoji="✅", custom_id="avj_dev_review_accept_v2")
    async def accept_dev(self, interaction: discord.Interaction, button: discord.ui.Button):
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
                        print(f"Fout bij toewijzen dev rol: {e}")

        claimed_assignments.add(self.assignment)

        dm_text = (
            f"Uw opdracht-aanvraag is **goedgekeurd**! U kunt nu aan de slag.\n\n"
            f"Zorg ervoor dat u te allen tijde foto's blijft sturen van uw project in het kanaal: <#{CHANNEL_DEV_PROGRESS}>.\n"
            f"Zodra uw project klaar is kunt u <@1328766617164972115> een dm sturen. Met de informatie welke opdracht en uw download bestand van uw eindresultaat."
        )

        user_to_dm = member or await bot.fetch_user(self.applicant_id)
        if user_to_dm:
            try:
                await user_to_dm.send(dm_text)
            except discord.Forbidden:
                pass

        if guild:
            announcement_channel = await get_guild_channel_safe(guild, CHANNEL_DEV_ANNOUNCEMENT)
            if announcement_channel and user_to_dm:
                embed_ann = discord.Embed(
                    title="🚀 Nieuwe Developer Gestart!",
                    description=(
                        f"Developer {user_to_dm.mention} is officieel gestart met een nieuwe opdracht voor **AVJ Online Winkel**!\n\n"
                        f"📌 **Opdracht:** {self.assignment}\n"
                        f"💼 **Status:** In Ontwikkeling\n\n"
                        f"Veel succes met het bouwen van het project!"
                    ),
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed_ann.set_thumbnail(url=user_to_dm.display_avatar.url)
                await announcement_channel.send(content=f"🎉 {user_to_dm.mention}", embed=embed_ann)

        await interaction.followup.send("✅ Developer-aanvraag goedgekeurd, rol toegewezen en aankondiging geplaatst!", ephemeral=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red, emoji="❌", custom_id="avj_dev_review_deny_v2")
    async def deny_dev(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safe_defer(interaction)

        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        dm_text = (
            f"Uw aanvraag voor de opdracht **{self.assignment}** is helaas **afgekeurd**.\n\n"
            f"Dit kan de volgende redenen hebben:\n"
            f"1. De prijs is te hoog.\n"
            f"2. Dit product is al in de maak."
        )

        try:
            user_to_dm = await bot.fetch_user(self.applicant_id)
            if user_to_dm:
                await user_to_dm.send(dm_text)
        except discord.Forbidden:
            pass

        await interaction.followup.send("❌ Developer-aanvraag afgekeurd en bericht gestuurd naar de aanvrager.", ephemeral=True)


class DevChoiceView(discord.ui.View):
    def __init__(self, user_id: int, current_assignment: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.current_assignment = current_assignment

    @discord.ui.button(label="Akkoord gaan met opdracht", style=discord.ButtonStyle.green, emoji="✅", custom_id="avj_dev_choice_accept_v2")
    async def accept_assignment(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        await interaction.response.send_modal(DevPriceModal(assignment_name=self.current_assignment))

    @discord.ui.button(label="Maak een andere opdracht", style=discord.ButtonStyle.secondary, emoji="🔀", custom_id="avj_dev_choice_reroll_v2")
    async def reroll_assignment(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safe_defer(interaction)

        current_count = user_reroll_count.get(self.user_id, 0)
        if current_count >= 1:
            await interaction.followup.send("⚠️ Je hebt je maximale aantal wissels (MAX 1X) al gebruikt!", ephemeral=True)
            return

        user_reroll_count[self.user_id] = current_count + 1

        guild = interaction.guild or (interaction.client.guilds[0] if interaction.client.guilds else None)
        new_assignment = await get_random_dev_assignment(guild, exclude_name=self.current_assignment)
        current_user_assignment[self.user_id] = new_assignment

        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        embed = discord.Embed(
            title="🛠️ Jouw Nieuwe Developer Opdracht",
            description=(
                f"Je hebt gekozen voor een andere opdracht.\n\n"
                f"📋 **Nieuwe Opdracht:**\n> {new_assignment}\n\n"
                f"Ga je akkoord met deze nieuwe opdracht?"
            ),
            color=discord.Color.purple()
        )

        try:
            await interaction.user.send(embed=embed, view=DevChoiceViewSingle(self.user_id, new_assignment))
            await interaction.followup.send("Ik heb je een nieuwe opdracht gestuurd via DM!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Ik kon je geen DM sturen.", ephemeral=True)


class DevChoiceViewSingle(discord.ui.View):
    def __init__(self, user_id: int, current_assignment: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.current_assignment = current_assignment

    @discord.ui.button(label="Akkoord gaan met opdracht", style=discord.ButtonStyle.green, emoji="✅", custom_id="avj_dev_choice_single_accept_v2")
    async def accept_assignment(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        await interaction.response.send_modal(DevPriceModal(assignment_name=self.current_assignment))


class DevStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Opdracht Maken voor AVJ", style=discord.ButtonStyle.primary, emoji="💼", custom_id="avj_dev_start_btn_v2")
    async def start_dev(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safe_defer(interaction)
        user_id = interaction.user.id
        guild = interaction.guild or (bot.guilds[0] if bot.guilds else None)

        assignment = await get_random_dev_assignment(guild)
        current_user_assignment[user_id] = assignment
        user_reroll_count[user_id] = 0

        embed = discord.Embed(
            title="✨ Welkom bij het AVJ Developer Programma!",
            description=(
                f"Beste **{interaction.user.display_name}**,\n\n"
                f"Fijn dat je interesse hebt om een ontwikkeling te realiseren voor **AVJ Online Winkel**!\n\n"
                f"📋 **Geselecteerde Opdracht:**\n> {assignment}\n\n"
                f"Wat wil je doen met deze opdracht?"
            ),
            color=discord.Color.gold()
        )

        try:
            dm = await interaction.user.create_dm()
            await dm.send(embed=embed, view=DevChoiceView(user_id, assignment))
            await interaction.followup.send("Ik heb je een privébericht gestuurd met je toegewezen opdracht!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Ik kon je geen privébericht sturen. Zorg ervoor dat je DM's openstaan!", ephemeral=True)


# --- PARTNER SYSTEEM VIEWS & MODALS ---

class DenyReasonModal(discord.ui.Modal, title="Aanvraag Afkeuren"):
    reden = discord.ui.TextInput(
        label="Reden van afkeuring",
        style=discord.TextStyle.paragraph,
        placeholder="Geef hier de reden op...",
        required=True
    )

    def __init__(self, member: discord.Member, original_message: discord.Message, view_instance: discord.ui.View):
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
            await self.member.send(f"❌ Jouw aanvraag is helaas **afgekeurd**.\n**Reden:** {self.reden.value}")
        except discord.Forbidden:
            pass

        partner_cooldowns.pop(self.member.id, None)
        await interaction.followup.send(f"Aanvraag afgekeurd met reden: {self.reden.value}", ephemeral=True)


class PartnerReviewView(discord.ui.View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)
        self.member = member

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in OWNER_IDS:
            return True
        
        role_ids = [role.id for role in interaction.user.roles] if interaction.guild else []
        if ROLE_ACCEPTEREN_BEHEER in role_ids or any(rid in role_ids for rid in ROLE_PARTNER_ALLOW_EXTRA):
            return True

        await interaction.response.send_message("❌ Jij hebt geen toestemming om deze partneraanvraag te beoordelen.", ephemeral=True)
        return False

    @discord.ui.button(label="Accepteren", style=discord.ButtonStyle.green, custom_id="avj_partner_accept_btn_v2")
    async def accept_partner(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            await self.member.send("✅ Jouw partner-aanvraag is **geaccepteerd**!")
        except discord.Forbidden:
            pass

        partner_kanaal = await get_guild_channel_safe(guild, CHANNEL_PARTNER_PUBLIC) if guild else None
        if partner_kanaal:
            user_partner_msg = pending_partner_messages.get(self.member.id, "Geen bericht.")
            await partner_kanaal.send(content=user_partner_msg)

        log_kanaal = await get_guild_channel_safe(guild, CHANNEL_LOGS) if guild else None
        if log_kanaal:
            embed_log = discord.Embed(
                title="✅ Partner Geaccepteerd",
                description=f"**Aanvrager:** {self.member.mention}\n**Door:** {interaction.user.mention}\n**Rol Toegewezen:** <@&{ROLE_PARTNER_GEACCEPTEERD}>",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            await log_kanaal.send(embed=embed_log)

        pending_partner_submissions.pop(self.member.id, None)
        pending_partner_messages.pop(self.member.id, None)
        partner_cooldowns.pop(self.member.id, None)

        await interaction.followup.send("Partner succesvol geaccepteerd, rol toegewezen en geplaatst in het partnerkanaal!", ephemeral=True)

    @discord.ui.button(label="Afkeuren", style=discord.ButtonStyle.red, custom_id="avj_partner_deny_btn_v2")
    async def deny_partner(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DenyReasonModal(self.member, interaction.message, self))


class PartnerStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Start Partner Aanvraag", style=discord.ButtonStyle.green, custom_id="avj_partner_start_btn_v2")
    async def start_partner_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safe_defer(interaction)
        user_id = interaction.user.id
        now = datetime.now(timezone.utc)

        if user_id in partner_cooldowns and now - partner_cooldowns[user_id] < timedelta(hours=12):
            await interaction.followup.send("⏳ Je kunt dit maar 1 keer per 12 uur doen.", ephemeral=True)
            return

        partner_cooldowns[user_id] = now
        try:
            dm = await interaction.user.create_dm()
            await dm.send(f"Plaats dit bericht in jouw server:\n\n{EXACT_PARTNER_BERICHT}\n\n📸 **Stuur na het plaatsen een screenshot in deze DM als bewijs:**")
            await interaction.followup.send("Check je DM!", ephemeral=True)
        except discord.Forbidden:
            partner_cooldowns.pop(user_id, None)
            await interaction.followup.send("❌ Kan geen DM sturen.", ephemeral=True)


# --- BACKGROUND TIKTOK LOOP ---
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
                    await channel.send(f"Deze persoon is live! https://www.tiktok.com/@{handle}/live")
            elif not is_live:
                is_live_notified[handle] = False
        except Exception as e:
            print(f"TikTok check fout voor {handle}: {e}")

@check_tiktok_live.before_loop
async def before_check_tiktok_live():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Ingelogd als {bot.user.name} (ID: {bot.user.id})")

    bot.add_view(PartnerStartView())
    bot.add_view(DevStartView())
    bot.add_view(TicketView())

    try:
        synced = await bot.tree.sync()
        print(f"Gesynchroniseerd: {len(synced)} commando('s).")
    except Exception as e:
        print(f"Sync fout: {e}")

    try:
        ticket_kanaal = bot.get_channel(CHANNEL_TICKET)
        if ticket_kanaal:
            has_view = False
            async for message in ticket_kanaal.history(limit=5):
                if message.author == bot.user:
                    has_view = True
                    break
            if not has_view:
                await ticket_kanaal.send("**Ondersteuning & Tickets**\nKlik op de knop om een ticket te openen.", view=TicketView())
    except Exception as e:
        print(f"Ticket kanaal fout: {e}")

    if not check_tiktok_live.is_running():
        check_tiktok_live.start()

    print("✅ Bot is volledig operationeel en gereed!")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if isinstance(message.channel, discord.DMChannel):
        user_id = message.author.id

        # Stap 1: Gebruiker stuurt een screenshot (Afbeelding)
        if message.attachments:
            if user_id not in pending_partner_submissions:
                pending_partner_submissions[user_id] = message.attachments[0].url
                await message.channel.send("📸 **Foto ontvangen!** Stuur nu je partner bericht in deze DM:")

        # Stap 2: Gebruiker stuurt het partner bericht (Tekst)
        elif message.content:
            if user_id in pending_partner_submissions and user_id not in pending_partner_messages:
                pending_partner_messages[user_id] = message.content

                guild = bot.guilds[0] if bot.guilds else None
                aanvraag_kanaal = await get_guild_channel_safe(guild, CHANNEL_AANVRAAG) if guild else None

                if aanvraag_kanaal:
                    image_url = pending_partner_submissions.get(user_id)
                    embed = discord.Embed(
                        title="🤝 Nieuwe Partner Aanvraag",
                        description=f"**Gebruiker:** {message.author.mention}\n\n{message.content}",
                        color=discord.Color.blue()
                    )
                    if image_url:
                        embed.set_image(url=image_url)

                    await aanvraag_kanaal.send(embed=embed, view=PartnerReviewView(message.author))
                    await message.channel.send("✅ **Bedankt! Je partneraanvraag is succesvol ingediend bij ons beheerteam.**")
                else:
                    await message.channel.send("❌ Er is iets misgegaan met het vinden van het aanvraagkanaal.")

    await bot.process_commands(message)


# --- /DEVOPDRACHT COMMANDO ---
@bot.tree.command(name="devopdracht", description="Plaats het paneel voor developer opdrachten.")
async def devopdracht_panel(interaction: discord.Interaction):
    await safe_defer(interaction)

    if interaction.user.id not in OWNER_IDS:
        user_roles = [r.id for r in interaction.user.roles] if interaction.guild else []
        if not any(rid in user_roles for rid in ROLE_DEV_PANEL_ALLOW):
            await interaction.followup.send("❌ Jij hebt geen toestemming om dit paneel te plaatsen.", ephemeral=True)
            return

    embed = discord.Embed(
        title="💼 AVJ Developer Opdrachten",
        description=(
            "Ben jij een gedreven ontwikkelaar en wil je graag opdrachten uitvoeren voor **AVJ Online Winkel**?\n\n"
            "Via ons automatische opdrachtsysteem kun je direct een uitdagend project toegewezen krijgen en je vraagprijs indienen bij ons beheer team.\n\n"
            "✨ **Hoe werkt het?**\n"
            "1️⃣ Klik op de knop hieronder om je aanvraag in te starten via privébericht (DM).\n"
            "2️⃣ Bekijk de toegewezen opdracht of kies éénmalig voor een alternatieve opdracht.\n"
            "3️⃣ Geef je gewenste vergoeding op.\n"
            "4️⃣ Na goedkeuring door onze staf ontvang je direct toegang en kun je aan de slag!\n\n"
            "Klik op de knop hieronder om jouw opdracht te starten!"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="AVJ Development Management", icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None)

    await interaction.channel.send(embed=embed, view=DevStartView())
    await interaction.followup.send("✅ Developer opdrachten paneel succesvol geplaatst!", ephemeral=True)


# --- /RESETPARTNER COMMANDO ---
@bot.tree.command(name="resetpartner", description="Reset de partner cooldown van een gebruiker.")
@app_commands.describe(gebruiker="De gebruiker wiens cooldown gereset moet worden")
async def resetpartner(interaction: discord.Interaction, gebruiker: discord.User):
    await safe_defer(interaction)

    if interaction.user.id not in OWNER_IDS:
        user_roles = [r.id for r in interaction.user.roles] if interaction.guild else []
        if ROLE_ACCEPTEREN_BEHEER not in user_roles and not any(rid in user_roles for rid in ROLE_PARTNER_ALLOW_EXTRA) and ROLE_PARTNER_BEHEER not in user_roles:
            await interaction.followup.send("❌ Jij hebt geen toestemming om cooldowns te resetten.", ephemeral=True)
            return

    if gebruiker.id in partner_cooldowns:
        partner_cooldowns.pop(gebruiker.id, None)
        await interaction.followup.send(f"✅ Partner cooldown voor {gebruiker.mention} is succesvol gereset!", ephemeral=True)
    else:
        await interaction.followup.send(f"ℹ️ {gebruiker.mention} had geen actieve partner cooldown.", ephemeral=True)


# --- /REVIEW COMMANDO ---
@bot.tree.command(name="review", description="Geef een review over iemand.")
@app_commands.describe(naam="Naam", sterren="Sterren 1-5", tips_of_uitleg="Uitleg")
@app_commands.choices(sterren=[
    app_commands.Choice(name="⭐ 1 Ster", value=1),
    app_commands.Choice(name="⭐⭐ 2 Sterren", value=2),
    app_commands.Choice(name="⭐⭐⭐ 3 Sterren", value=3),
    app_commands.Choice(name="⭐⭐⭐⭐ 4 Sterren", value=4),
    app_commands.Choice(name="⭐⭐⭐⭐⭐ 5 Sterren", value=5)
])
async def review_command(interaction: discord.Interaction, naam: str, sterren: int, tips_of_uitleg: str):
    await safe_defer(interaction)
    guild = interaction.guild
    review_kanaal = await get_guild_channel_safe(guild, CHANNEL_REVIEW) if guild else None
    if not review_kanaal:
        await interaction.followup.send("Review kanaal niet gevonden.", ephemeral=True)
        return

    embed = discord.Embed(title="🌟 Nieuwe Review", color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Service", value=naam, inline=False)
    embed.add_field(name="Beoordeling", value="⭐" * sterren, inline=False)
    embed.add_field(name="Uitleg", value=tips_of_uitleg, inline=False)
    await review_kanaal.send(embed=embed)
    await interaction.followup.send("Review geplaatst!", ephemeral=True)


# --- /SAY COMMANDO ---
@bot.tree.command(name="say", description="Laat de bot een bericht sturen.")
@app_commands.describe(bericht="Bericht", afbeelding="Optionele afbeelding")
async def say_command(interaction: discord.Interaction, bericht: str, afbeelding: discord.Attachment = None):
    await safe_defer(interaction)

    if interaction.user.id not in OWNER_IDS:
        user_roles = [r.id for r in interaction.user.roles] if interaction.guild else []
        if not any(r in SAY_ROLE_IDS for r in user_roles):
            await interaction.followup.send("Geen toestemming.", ephemeral=True)
            return

    file = await afbeelding.to_file() if afbeelding else None
    await interaction.channel.send(content=bericht, file=file)
    await interaction.followup.send("Verzonden!", ephemeral=True)


# --- /PARTNERPANEL COMMANDO ---
@bot.tree.command(name="partnerpanel", description="Plaats het korte partner paneel.")
async def partnerpanel(interaction: discord.Interaction):
    await safe_defer(interaction)

    if interaction.user.id not in OWNER_IDS:
        user_roles = [r.id for r in interaction.user.roles] if interaction.guild else []
        if not any(r == ROLE_ACCEPTEREN_BEHEER or r in ROLE_PARTNER_ALLOW_EXTRA or r == ROLE_PARTNER_BEHEER for r in user_roles):
            await interaction.followup.send("Geen toestemming.", ephemeral=True)
            return

    target = await get_guild_channel_safe(interaction.guild, CHANNEL_PARTNER_PANEL)
    if not target:
        await interaction.followup.send("Partner panel kanaal niet gevonden.", ephemeral=True)
        return

    try:
        await target.purge(limit=20)
    except Exception as e:
        print(f"Kon kanaal niet leegmaken via purge, handmatig proberen: {e}")
        try:
            async for msg in target.history(limit=20):
                await msg.delete()
        except Exception as ex:
            print(f"Fout bij handmatig verwijderen: {ex}")

    embed = discord.Embed(
        title="🤝 Partner Worden",
        description="Klik op de knop om partner te worden!",
        color=discord.Color.blurple()
    )

    await target.send(embed=embed, view=PartnerStartView())
    await interaction.followup.send("✅ Partner panel geplaatst en kanaal opgeschoond!", ephemeral=True)


bot.run(TOKEN)
