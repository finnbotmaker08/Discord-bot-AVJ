from datetime import datetime, timedelta, timezone
import os
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

ROLE_ACCEPTEREN = 1554525725657145354
ROLE_PARTNER_BEHEER = 1541819580173779026
ROLE_EXTRA_ACCEPTEREN = 1545038388091166790

# Discord ID's die ALTIJD overal toegang toe hebben
OWNER_IDS = [1328766617164972115, 1305271257901695048]

# Rollen die toegang hebben tot het /say commando
SAY_ROLE_IDS = [
    1545038155508355153,
    1545038388091166790,
    1555907057549312060,
    1475901447404126340
]

CHANNEL_AANVRAAG = 1555910106040762408
CHANNEL_TICKET = 1554523651745783940
CHANNEL_PARTNER_PUBLIC = 1476292683508089056
CHANNEL_PARTNER_PANEL = 1542844065702350878
CHANNEL_LOGS = 1555929585877524500
CHANNEL_REVIEW = 1487908079373652050

# --- TIKTOK LIVE CONFIGURATIE (Meerdere kanalen) ---
TIKTOK_HANDLES = ["faab9999_", "jcd_18"]
NOTIFICATION_CHANNEL_ID = 1555933500274642965

# Houd voor elk kanaal bij of er al een live-melding is gestuurd
is_live_notified = {handle: False for handle in TIKTOK_HANDLES}

BEHEERDER_ID = 1295590895474970705

pending_partner_submissions = {}  # user_id -> image_url
pending_partner_messages = {}     # user_id -> partner bericht tekst
partner_cooldowns = {}            # user_id -> datetime van laatste aanvraag

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
    "> 🛠️️ Wij helpen graag mensen die problemen hebben met hun Roblox studio.\n"
    "> \n"
    "> 🤑 We zijn ook nog op zoek naar medewerkers die bij ons willen werken, dus misschien ben jij wel geschikt en lijkt het je leuk.\n"
    "> \n"
    "> ● Iedereen is van harte welkom om een kijkje te nemen in onze discord server.\n\n"
    "> 📸 Video: https://media.discordapp.net/attachments/1499730647219175464/1499730650272497745/Schermopname_2026-05-01_131436.mp4\n\n"
    "> 🔗 https://discord.gg/hBeUBKUAsu"
)


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket aanmaken", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="create_ticket")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
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


class DenyReasonModal(discord.ui.Modal, title="Partner Aanvraag Afkeuren"):
    reden = discord.ui.TextInput(
        label="Reden van afkeuring",
        style=discord.TextStyle.paragraph,
        placeholder="Geef hier de reden op waarom de aanvraag wordt afgekeurd...",
        required=True
    )

    def __init__(self, member: discord.Member, original_message: discord.Message, view_instance: discord.ui.View):
        super().__init__()
        self.member = member
        self.original_message = original_message
        self.view_instance = view_instance

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        for child in self.view_instance.children:
            child.disabled = True
        try:
            await self.original_message.edit(view=self.view_instance)
        except Exception:
            pass

        try:
            await self.member.send(f"❌ Jouw partner-aanvraag is helaas **afgekeurd**.\n**Reden:** {self.reden.value}")
        except discord.Forbidden:
            pass

        user_partner_msg = pending_partner_messages.get(self.member.id, "Geen partner bericht opgegeven.")

        guild = interaction.guild or (bot.guilds[0] if bot.guilds else None)
        if guild:
            log_kanaal = guild.get_channel(CHANNEL_LOGS)
            if log_kanaal:
                embed_log = discord.Embed(
                    title="❌ Partner Aanvraag Afgekeurd Log",
                    description=(
                        f"**Aanvrager:** {self.member.mention} (`{self.member.id}`)\n"
                        f"**Afgekeurd door:** {interaction.user.mention} (`{interaction.user.id}`)\n\n"
                        f"**Ingevoerde Partner Bericht:**\n{user_partner_msg}\n\n"
                        f"**Reden van afkeuring:** {self.reden.value}"
                    ),
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                )
                try:
                    await log_kanaal.send(embed=embed_log)
                except Exception as e:
                    print(f"Fout bij versturen log (afwijzen): {e}")

        pending_partner_submissions.pop(self.member.id, None)
        pending_partner_messages.pop(self.member.id, None)

        await interaction.followup.send(f"Aanvraag van {self.member.mention} is afgekeurd met reden: {self.reden.value}", ephemeral=True)


class PartnerReviewView(discord.ui.View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)
        self.member = member

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in OWNER_IDS:
            return True
        role_ids = [role.id for role in interaction.user.roles]
        if ROLE_ACCEPTEREN not in role_ids and ROLE_EXTRA_ACCEPTEREN not in role_ids:
            await interaction.response.send_message("Jij hebt geen toestemming om dit te beoordelen.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Accepteren", style=discord.ButtonStyle.green, custom_id="partner_accept_btn")
    async def accept_partner(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild or (bot.guilds[0] if bot.guilds else None)

        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        try:
            await self.member.send("✅ Jouw partner-aanvraag is **geaccepteerd**!")
        except discord.Forbidden:
            pass

        partner_kanaal = guild.get_channel(CHANNEL_PARTNER_PUBLIC)
        if not partner_kanaal:
            await interaction.followup.send(f"❌ Fout: Partner kanaal met ID `{CHANNEL_PARTNER_PUBLIC}` niet gevonden!", ephemeral=True)
            return

        user_partner_msg = pending_partner_messages.get(self.member.id, "Geen partner bericht opgegeven.")
        
        try:
            await partner_kanaal.send(content=user_partner_msg)
        except Exception as e:
            await interaction.followup.send(f"❌ Kon geen bericht plaatsen in het partnerkanaal: {e}", ephemeral=True)
            return

        log_kanaal = guild.get_channel(CHANNEL_LOGS)
        if log_kanaal:
            embed_log = discord.Embed(
                title="✅ Partner Aanvraag Geaccepteerd Log",
                description=(
                    f"**Aanvrager:** {self.member.mention} (`{self.member.id}`)\n"
                    f"**Geaccepteerd door:** {interaction.user.mention} (`{interaction.user.id}`)\n\n"
                    f"**Geplaatst Partner Bericht:**\n{user_partner_msg}"
                ),
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            try:
                await log_kanaal.send(embed=embed_log)
            except Exception as e:
                print(f"Fout bij versturen log (accepteren): {e}")
        
        pending_partner_submissions.pop(self.member.id, None)
        pending_partner_messages.pop(self.member.id, None)

        await interaction.followup.send(f"Aanvraag van {self.member.mention} is succesvol geaccepteerd en geplaatst in het partnerkanaal!", ephemeral=True)

    @discord.ui.button(label="Afkeuren", style=discord.ButtonStyle.red, custom_id="partner_deny_btn")
    async def deny_partner(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DenyReasonModal(self.member, interaction.message, self))


class PartnerMsgSubmitView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(label="Partner bericht versturen", style=discord.ButtonStyle.green, emoji="📤", custom_id="partner_msg_done_btn")
    async def msg_done(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        user_partner_msg = pending_partner_messages.get(self.user_id)
        if not user_partner_msg:
            await interaction.followup.send("Je hebt nog geen partner bericht ingevoerd in deze DM! Stuur eerst de tekst van jouw partner bericht.", ephemeral=True)
            return

        guild = bot.guilds[0] if bot.guilds else None
        if not guild:
            await interaction.followup.send("Kan geen verbinding maken met de server.", ephemeral=True)
            return

        aanvraag_kanaal = guild.get_channel(CHANNEL_AANVRAAG)
        if not aanvraag_kanaal:
            await interaction.followup.send("Het aanvraagkanaal kon niet worden gevonden op de server.", ephemeral=True)
            return

        image_url = pending_partner_submissions.get(self.user_id)

        try:
            embed = discord.Embed(
                title="🤝 Nieuwe Partner Aanvraag",
                description=f"**Gebruiker:** {interaction.user.mention} (`{interaction.user.id}`)\n\n**Ingevoerde Partner Bericht van gebruiker:**\n{user_partner_msg}\n\n**Ingezonden Bewijs (Screenshot):**",
                color=discord.Color.blue()
            )
            if image_url:
                embed.set_image(url=image_url)

            await aanvraag_kanaal.send(embed=embed, view=PartnerReviewView(interaction.user))
        except Exception as e:
            await interaction.followup.send(f"Er ging iets mis bij het versturen naar het kanaal: {e}", ephemeral=True)
            return

        try:
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)
        except Exception:
            pass

        await interaction.followup.send("Uw partner-aanvraag is succesvol ingediend en wordt zo spoedig mogelijk bekeken.", ephemeral=True)


class PartnerImageView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(label="Foto verstuurd", style=discord.ButtonStyle.blurple, emoji="📸", custom_id="partner_image_sent_btn")
    async def image_sent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        if self.user_id not in pending_partner_submissions:
            await interaction.followup.send("Je hebt nog geen foto / screenshot ingestuurd in deze DM!", ephemeral=True)
            return

        try:
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)
        except Exception:
            pass

        try:
            await interaction.user.send(
                content=(
                    "⚠️ **LET OP! MAAK JE PARTNER BERICHT NIET LANGER DAN 2000 WOORDEN! ZO WEL WORD U AFGEKEURD!**\n\n"
                    "📝 **Stap 3: Geef uw partner bericht aan ons.**\n"
                    "Typ en stuur nu jouw partner bericht in deze DM en klik daarna op de knop hieronder om de aanvraag definitief te verzenden."
                ),
                view=PartnerMsgSubmitView(self.user_id)
            )
        except discord.Forbidden:
            pass


class PartnerSendMsgView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(label="Bericht verstuurd", style=discord.ButtonStyle.green, emoji="📤", custom_id="partner_msg_sent_btn")
    async def msg_sent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        try:
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)
        except Exception:
            pass

        try:
            await interaction.user.send(
                content="📸 **Stap 2: Foto indienen**\nStuur nu een screenshot (afbeelding) als bewijs dat het bericht in jouw server staat in deze DM en klik daarna op de knop hieronder.",
                view=PartnerImageView(self.user_id)
            )
        except discord.Forbidden:
            pass


class MemberCheckView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(label="Ja, ik voldoe hieraan (15+ leden)", style=discord.ButtonStyle.green, custom_id="member_check_yes")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        try:
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)
        except Exception:
            pass

        try:
            await interaction.user.send(
                content=f"**Stap 1: Partner Bericht Plaatsen**\nDien uw partner bericht nu in, als u dat gedaan heeft klik dan op de knop: Bericht verstuurd\n\n{EXACT_PARTNER_BERICHT}",
                view=PartnerSendMsgView(self.user_id)
            )
            await interaction.followup.send("Ik heb je een privébericht (DM) gestuurd met verdere instructies!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Ik kon je geen DM sturen. Zorg ervoor dat je privéberichten open staan!", ephemeral=True)

    @discord.ui.button(label="Nee", style=discord.ButtonStyle.red, custom_id="member_check_no")
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)
        except Exception:
            pass
        partner_cooldowns.pop(self.user_id, None)
        await interaction.followup.send("❌ Je voldoet niet aan de eis van 15+ leden. Het proces is geannuleerd.", ephemeral=True)


class PartnerStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Start Partner Aanvraag", style=discord.ButtonStyle.green, custom_id="partner_start_btn")
    async def start_partner_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        now = datetime.now(timezone.utc)

        if user_id in partner_cooldowns:
            laatste_tijd = partner_cooldowns[user_id]
            verschil = now - laatste_tijd
            if verschil < timedelta(hours=12):
                overgebleven = timedelta(hours=12) - verschil
                uren = int(overgebleven.total_seconds() // 3600)
                minuten = int((overgebleven.total_seconds() % 3600) // 60)
                await interaction.followup.send(
                    f"⏳ Je kunt dit maximaal 1 keer per 12 uur doen. Probeer het over **{uren} uur en {minuten} minuten** opnieuw.",
                    ephemeral=True
                )
                return

        partner_cooldowns[user_id] = now

        try:
            dm_channel = await interaction.user.create_dm()
            await dm_channel.send(
                content="Voldoet jouw server aan de eis van **minimaal 15 leden**?",
                view=MemberCheckView(user_id)
            )
            await interaction.followup.send("Ik heb je een privébericht (DM) gestuurd om de controle te starten!", ephemeral=True)
        except discord.Forbidden:
            partner_cooldowns.pop(user_id, None)
            await interaction.followup.send("❌ Ik kon je geen DM sturen. Zorg ervoor dat je **privéberichten (DM's)** open staan voor leden van deze server!", ephemeral=True)


# --- TIKTOK LIVE BACKGROUND CHECK (Meerdere kanalen) ---
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
                    await channel.send(
                        f"Deze persoon is live! Kom snel kijken.\n"
                        f"https://www.tiktok.com/@{handle}/live"
                    )
            elif not is_live:
                is_live_notified[handle] = False
        except Exception as e:
            print(f"Fout bij controleren TikTok status voor {handle}: {e}")

@check_tiktok_live.before_loop
async def before_check_tiktok_live():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Ingelogd als {bot.user.name} (ID: {bot.user.id})")
    
    if not check_tiktok_live.is_running():
        check_tiktok_live.start()

    try:
        synced = await bot.tree.sync()
        print(f"Succesvol {len(synced)} slash commando('s) gesynchroniseerd.")
    except Exception as e:
        print(f"Fout bij synchroniseren: {e}")

    ticket_kanaal = bot.get_channel(CHANNEL_TICKET)
    if ticket_kanaal:
        async for message in ticket_kanaal.history(limit=5):
            if message.author == bot.user:
                return
        
        await ticket_kanaal.send(
            "**Ondersteuning & Tickets**\nKlik op de knop hieronder om een privéticket te openen met het team.",
            view=TicketView()
        )


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if isinstance(message.channel, discord.DMChannel):
        user_id = message.author.id
        
        if message.attachments:
            pending_partner_submissions[user_id] = message.attachments[0].url
            await message.channel.send("📸 Foto succesvol ontvangen! Klik nu op de knop **'Foto verstuurd'** in het vorige bericht om door te gaan naar Stap 3.")
        
        elif message.content and user_id in pending_partner_submissions and user_id not in pending_partner_messages:
            pending_partner_messages[user_id] = message.content
            await message.channel.send("📝 Partner bericht succesvol ontvangen! Klik nu op de knop **'Partner bericht versturen'** om de aanvraag definitief in te dienen.")

    await bot.process_commands(message)


# --- /REVIEW COMMANDO ---
@bot.tree.command(name="review", description="Geef een review over iemand.")
@app_commands.describe(
    naam="De naam van degene die je reviewt",
    sterren="Aantal sterren van 1 tot 5",
    tips_of_uitleg="Jouw tips of uitleg over de ervaring"
)
@app_commands.choices(sterren=[
    app_commands.Choice(name="⭐ 1 Ster", value=1),
    app_commands.Choice(name="⭐⭐ 2 Sterren", value=2),
    app_commands.Choice(name="⭐⭐⭐ 3 Sterren", value=3),
    app_commands.Choice(name="⭐⭐⭐⭐ 4 Sterren", value=4),
    app_commands.Choice(name="⭐⭐⭐⭐⭐ 5 Sterren", value=5)
])
async def review_command(interaction: discord.Interaction, naam: str, sterren: int, tips_of_uitleg: str):
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    review_kanaal = guild.get_channel(CHANNEL_REVIEW) if guild else None

    if not review_kanaal:
        await interaction.followup.send("❌ Fout: Het review-kanaal kon niet worden gevonden.", ephemeral=True)
        return

    sterren_tekst = "⭐" * sterren

    embed = discord.Embed(
        title="🌟 Nieuwe Review Ontvangen",
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Gereviewde Persoon / Service", value=naam, inline=False)
    embed.add_field(name="Beoordeling", value=f"{sterren_tekst} ({sterren}/5 sterren)", inline=False)
    embed.add_field(name="Tips / Uitleg", value=tips_of_uitleg, inline=False)
    embed.set_footer(text=f"Review geschreven door {interaction.user.name}", icon_url=interaction.user.display_avatar.url)

    try:
        await review_kanaal.send(embed=embed)
        await interaction.followup.send("✅ Je review is succesvol geplaatst in het review-kanaal!", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Er ging iets mis bij het plaatsen van de review: {e}", ephemeral=True)


# --- /SAY COMMANDO ---
@bot.tree.command(name="say", description="Laat de bot een bericht (optioneel met afbeelding) sturen in het huidige kanaal.")
@app_commands.describe(
    bericht="Het tekstbericht dat de bot moet sturen",
    afbeelding="Optioneel: upload hier een afbeelding om mee te sturen"
)
async def say_command(interaction: discord.Interaction, bericht: str, afbeelding: discord.Attachment = None):
    if interaction.user.id not in OWNER_IDS:
        user_role_ids = [role.id for role in interaction.user.roles]
        has_allowed_role = any(role_id in user_role_ids for role_id in SAY_ROLE_IDS)

        if not has_allowed_role:
            await interaction.response.send_message("❌ Jij hebt geen toestemming om dit commando te gebruiken.", ephemeral=True)
            return

    file_to_send = None
    if afbeelding:
        file_to_send = await afbeelding.to_file()

    await interaction.channel.send(content=bericht, file=file_to_send)
    await interaction.response.send_message("Je bericht is verzonden!", ephemeral=True)


# --- /PARTNERPANEL COMMANDO ---
@bot.tree.command(name="partnerpanel", description="Plaats het partner paneel in het kanaal.")
async def partnerpanel(interaction: discord.Interaction):
    if interaction.user.id not in OWNER_IDS:
        user_role_ids = [role.id for role in interaction.user.roles]
        if ROLE_PARTNER_BEHEER not in user_role_ids:
            await interaction.response.send_message("Jij hebt geen toestemming om dit commando te gebruiken.", ephemeral=True)
            return

    await interaction.response.defer(ephemeral=True)
    
    target_kanaal = interaction.guild.get_channel(CHANNEL_PARTNER_PANEL)
    if not target_kanaal:
        await interaction.followup.send("Het opgegeven partner panel kanaal is niet gevonden.", ephemeral=True)
        return

    embed_panel = discord.Embed(
        title="🤝 Partner Worden",
        description="Wil je een partnerschap aangaan met **AVJ Online Winkel**?\nKlik op de knop hieronder om het proces via DM te starten!",
        color=discord.Color.blurple()
    )

    await target_kanaal.send(
        embed=embed_panel,
        view=PartnerStartView()
    )
    
    await interaction.followup.send("Het partner panel is succesvol geplaatst in het kanaal!", ephemeral=True)


bot.run(TOKEN)