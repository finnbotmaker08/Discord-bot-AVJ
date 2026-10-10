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
ROLE_KORTING_BEHEER = 1475901447404126340

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
CHANNEL_BETAAL_AANVRAAG = 1555919409162494012
CHANNEL_BETAAL_LOGS = 1558561264295485470

# --- TIKTOK LIVE CONFIGURATIE (Meerdere kanalen) ---
TIKTOK_HANDLES = ["faab9999_", "jcd_18"]
NOTIFICATION_CHANNEL_ID = 1555933500274642965

is_live_notified = {handle: False for handle in TIKTOK_HANDLES}

pending_partner_submissions = {}  # user_id -> image_url
pending_partner_messages = {}     # user_id -> partner bericht tekst
partner_cooldowns = {}            # user_id -> datetime van laatste aanvraag

# Geheugen voor kortingscodes
actieve_kortingscodes = {}        # code -> kortingspercentage

# Geheugen voor betaaltickets
pending_betaal_product = {}       # user_id -> product tekst
pending_betaal_image = {}         # user_id -> image_url
pending_betaal_link = {}          # user_id -> betaallink ingevoerd door staff

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


# --- BETAAL TICKET / PANEL VIEWS & MODALS ---

class BetaalStaffModal(discord.ui.Modal, title="Bestelling Afhandelen (Product & Bestand)"):
    bericht_inhoud = discord.ui.TextInput(
        label="Bericht naar klant",
        style=discord.TextStyle.paragraph,
        placeholder="Typ hier het succesbericht voor de klant...",
        required=True
    )
    download_links = discord.ui.TextInput(
        label="Download Link(s) / Product URL",
        style=discord.TextStyle.paragraph,
        placeholder="Plak hier de downloadlinks of instructies...",
        required=True
    )

    def __init__(self, member: discord.Member, original_message: discord.Message):
        super().__init__()
        self.member = member
        self.original_message = original_message

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            await self.member.send(
                f"✅ **Jouw betaling is goedgekeurd en afgehandeld!**\n\n"
                f"**Bericht:**\n{self.bericht_inhoud.value}\n\n"
                f"**Downloads / Producten:**\n{self.download_links.value}"
            )
        except discord.Forbidden:
            pass

        await interaction.followup.send("Je hebt de bestelling succesvol afgerond en doorgestuurd naar de klant via het template!", ephemeral=True)
        try:
            await self.original_message.edit(content="✅ **Bestelling goedgekeurd en afgehandeld.**", view=None)
        except Exception:
            pass


class BetaalStaffDenyModal(discord.ui.Modal, title="Betaling Afkeuren"):
    reden = discord.ui.TextInput(
        label="Reden van afkeuring",
        style=discord.TextStyle.paragraph,
        placeholder="Geef de reden op waarom de betaling is afgekeurd...",
        required=True
    )

    def __init__(self, member: discord.Member, original_message: discord.Message):
        super().__init__()
        self.member = member
        self.original_message = original_message

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.member.send(f"❌ Jouw betaling is **afgekeurd**.\n**Reden:** {self.reden.value}")
        except discord.Forbidden:
            pass

        await interaction.followup.send(f"Betaling afgekeurd met reden: {self.reden.value}", ephemeral=True)
        try:
            await self.original_message.edit(content=f"❌ **Bestelling afgekeurd.**\nReden: {self.reden.value}", view=None)
        except Exception:
            pass


class BetaalStaffLogReviewView(discord.ui.View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)
        self.member = member

    @discord.ui.button(label="Download / Product", style=discord.ButtonStyle.green, emoji="📂", custom_id="betaal_log_accept")
    async def accept_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BetaalStaffModal(self.member, interaction.message))

    @discord.ui.button(label="Afkeuren", style=discord.ButtonStyle.red, custom_id="betaal_log_deny")
    async def deny_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BetaalStaffDenyModal(self.member, interaction.message))


class BetaalStaffReviewView(discord.ui.View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)
        self.member = member

    @discord.ui.button(label="Accepteren (Betaallink invoeren)", style=discord.ButtonStyle.green, custom_id="betaal_accept_btn")
    async def accept_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BetaalLinkModal(self.member, interaction.message, self))

    @discord.ui.button(label="Afkeuren", style=discord.ButtonStyle.red, custom_id="betaal_deny_btn")
    async def deny_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DenyReasonModal(self.member, interaction.message, self))


class BetaalLinkModal(discord.ui.Modal, title="Betaallink Invoeren"):
    betaallink = discord.ui.TextInput(
        label="Betaallink",
        style=discord.TextStyle.short,
        placeholder="Plak hier de betaallink voor de klant...",
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

        pending_betaal_link[self.member.id] = self.betaallink.value

        try:
            await self.member.send(
                f"💳 **Betaallink Ontvangen!**\n\n"
                f"Hier is je betaallink om door te gaan: {self.betaallink.value}\n\n"
                f"⚠️ **Professionele Uitleg:** Om verder te gaan met je bestelling en de volgende stappen te doorlopen, dien je deze link te openen en te betalen.\n"
                f"Zodra je de betaling hebt voltooid, typ je het woord **'betaald'** hier in deze chat!"
            )
        except discord.Forbidden:
            pass

        await interaction.followup.send(f"Betaallink succesvol verzonden naar {self.member.mention}!", ephemeral=True)


class BetaalImageSubmitView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(label="Afbeelding verstuurd", style=discord.ButtonStyle.blurple, emoji="📸", custom_id="betaal_image_sent_btn")
    async def image_sent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        if self.user_id not in pending_betaal_image:
            await interaction.followup.send("Je hebt nog geen afbeeldingen / screenshots ingestuurd in deze DM!", ephemeral=True)
            return

        try:
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)
        except Exception:
            pass

        guild = bot.guilds[0] if bot.guilds else None
        if not guild:
            await interaction.followup.send("Kan geen verbinding maken met de server.", ephemeral=True)
            return

        betaal_kanaal = guild.get_channel(CHANNEL_BETAAL_AANVRAAG)
        if not betaal_kanaal:
            await interaction.followup.send("Het betaal-aanvraagkanaal kon niet worden gevonden.", ephemeral=True)
            return

        product_tekst = pending_betaal_product.get(self.user_id, "Geen product opgegeven.")
        img_url = pending_betaal_image.get(self.user_id)

        embed = discord.Embed(
            title="🧾 Nieuwe Betaal Aanvraag",
            description=f"**Gebruiker:** {interaction.user.mention} (`{interaction.user.id}`)\n\n**Gewenst Product:**\n{product_tekst}\n\n**Ingezonden Shop Afbeelding:**",
            color=discord.Color.green()
        )
        if img_url:
            embed.set_image(url=img_url)

        try:
            await betaal_kanaal.send(embed=embed, view=BetaalStaffReviewView(interaction.user))
        except Exception as e:
            await interaction.followup.send(f"Fout bij versturen naar aanvraagkanaal: {e}", ephemeral=True)
            return

        await interaction.followup.send("Je betaalticket is definitief ingediend! De staf zal dit zo snel mogelijk bekijken.", ephemeral=True)


class BetaalProductSubmitView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(label="Bericht indienen", style=discord.ButtonStyle.green, emoji="📤", custom_id="betaal_product_done_btn")
    async def product_done(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        if self.user_id not in pending_betaal_product:
            await interaction.followup.send("Niks gezien in de chat. Type iets en klik opnieuw.", ephemeral=True)
            return

        try:
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)
        except Exception:
            pass

        try:
            await interaction.user.send(
                content="📸 **Stap 2:** Maak een afbeelding van welk product je wilt uit de shop.",
                view=BetaalImageSubmitView(self.user_id)
            )
        except discord.Forbidden:
            pass


class BetaalStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Betaalticket Aanmaken", style=discord.ButtonStyle.success, emoji="💳", custom_id="betaalticket_start_btn")
    async def start_betaalticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id

        try:
            dm = await interaction.user.create_dm()
            await dm.send(
                content="🛍 **Stap 1:** Welk product zou je willen? Typ en stuur de naam/omschrijving van het product in deze DM en klik daarna op de knop hieronder.",
                view=BetaalProductSubmitView(user_id)
            )
            await interaction.followup.send("Ik heb je een privébericht (DM) gestuurd om je betaalticket te starten!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Ik kon je geen DM sturen. Zet je privéberichten open!", ephemeral=True)


# --- PARTNER & MODAL CLASSES ---

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
        await interaction.response.defer(ephemeral=True)
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

        await interaction.followup.send(f"Aanvraag afgekeurd met reden: {self.reden.value}", ephemeral=True)


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
        if partner_kanaal:
            user_partner_msg = pending_partner_messages.get(self.member.id, "Geen bericht.")
            await partner_kanaal.send(content=user_partner_msg)

        log_kanaal = guild.get_channel(CHANNEL_LOGS)
        if log_kanaal:
            embed_log = discord.Embed(
                title="✅ Partner Geaccepteerd",
                description=f"**Aanvrager:** {self.member.mention}\n**Door:** {interaction.user.mention}",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            await log_kanaal.send(embed=embed_log)

        pending_partner_submissions.pop(self.member.id, None)
        pending_partner_messages.pop(self.member.id, None)
        await interaction.followup.send("Partner succesvol geaccepteerd!", ephemeral=True)

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
            await interaction.followup.send("Geen partner bericht ingevoerd!", ephemeral=True)
            return

        guild = bot.guilds[0] if bot.guilds else None
        aanvraag_kanaal = guild.get_channel(CHANNEL_AANVRAAG) if guild else None
        if not aanvraag_kanaal:
            await interaction.followup.send("Aanvraagkanaal niet gevonden.", ephemeral=True)
            return

        image_url = pending_partner_submissions.get(self.user_id)
        embed = discord.Embed(title="🤝 Nieuwe Partner Aanvraag", description=f"**Gebruiker:** {interaction.user.mention}\n{user_partner_msg}", color=discord.Color.blue())
        if image_url:
            embed.set_image(url=image_url)

        await aanvraag_kanaal.send(embed=embed, view=PartnerReviewView(interaction.user))
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        await interaction.followup.send("Aanvraag ingediend!", ephemeral=True)


class PartnerImageView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(label="Foto verstuurd", style=discord.ButtonStyle.blurple, emoji="📸", custom_id="partner_image_sent_btn")
    async def image_sent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        await interaction.user.send(content="Stuur nu je partner bericht in deze DM:", view=PartnerMsgSubmitView(self.user_id))


class PartnerSendMsgView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(label="Bericht verstuurd", style=discord.ButtonStyle.green, emoji="📤", custom_id="partner_msg_sent_btn")
    async def msg_sent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        await interaction.user.send(content="Stuur nu een screenshot als bewijs:", view=PartnerImageView(self.user_id))


class MemberCheckView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(label="Ja, ik voldoe hieraan (15+ leden)", style=discord.ButtonStyle.green, custom_id="member_check_yes")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        await interaction.user.send(content=f"Plaats dit bericht:\n\n{EXACT_PARTNER_BERICHT}", view=PartnerSendMsgView(self.user_id))
        await interaction.followup.send("DM verzonden!", ephemeral=True)

    @discord.ui.button(label="Nee", style=discord.ButtonStyle.red, custom_id="member_check_no")
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        await interaction.followup.send("Geannuleerd.", ephemeral=True)


class PartnerStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Start Partner Aanvraag", style=discord.ButtonStyle.green, custom_id="partner_start_btn")
    async def start_partner_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        now = datetime.now(timezone.utc)

        if user_id in partner_cooldowns and now - partner_cooldowns[user_id] < timedelta(hours=12):
            await interaction.followup.send("⏳ Je kunt dit maar 1 keer per 12 uur doen.", ephemeral=True)
            return

        partner_cooldowns[user_id] = now
        try:
            dm = await interaction.user.create_dm()
            await dm.send("Voldoet jouw server aan minimaal 15 leden?", view=MemberCheckView(user_id))
            await interaction.followup.send("Check je DM!", ephemeral=True)
        except discord.Forbidden:
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
    if not check_tiktok_live.is_running():
        check_tiktok_live.start()

    try:
        synced = await bot.tree.sync()
        print(f"Gesynchroniseerd: {len(synced)} commando('s).")
    except Exception as e:
        print(f"Sync fout: {e}")

    ticket_kanaal = bot.get_channel(CHANNEL_TICKET)
    if ticket_kanaal:
        has_view = False
        async for message in ticket_kanaal.history(limit=5):
            if message.author == bot.user:
                has_view = True
                break
        if not has_view:
            await ticket_kanaal.send("**Ondersteuning & Tickets**\nKlik op de knop om een ticket te openen.", view=TicketView())


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # DM afhandeling voor Partners en Betaaltickets
    if isinstance(message.channel, discord.DMChannel):
        user_id = message.author.id

        # Afbeeldingen opvangen in DM voor gewone gebruiker
        if message.attachments:
            if user_id in pending_betaal_product and user_id not in pending_betaal_image:
                pending_betaal_image[user_id] = message.attachments[0].url
                await message.channel.send("📸 Afbeelding ontvangen! Klik op **'Afbeelding verstuurd'** in het vorige menu.")
            elif user_id not in pending_partner_submissions:
                pending_partner_submissions[user_id] = message.attachments[0].url
                await message.channel.send("📸 Partner foto ontvangen! Klik op **'Foto verstuurd'**.")

        if message.content:
            # Controleren of de persoon heeft gezegd dat hij betaald heeft
            if message.content.strip().lower() == "betaald":
                guild = bot.guilds[0] if bot.guilds else None
                log_betaal_kanaal = guild.get_channel(CHANNEL_BETAAL_LOGS) if guild else None
                if log_betaal_kanaal:
                    embed_betaald = discord.Embed(
                        title="💰 Betaling doorgegeven door Klant",
                        description=f"**Klant:** {message.author.mention} (`{message.author.id}`)\n\n**Bericht van klant:** Betaald",
                        color=discord.Color.gold()
                    )
                    await log_betaal_kanaal.send(embed=embed_betaald, view=BetaalStaffLogReviewView(message.author))
                    await message.channel.send("✅ Bedankt! Je betaling is doorgegeven aan de staf. Zij controleren dit zo spoedig mogelijk.")
            
            # Betaal product tekst opvang
            elif user_id not in pending_betaal_product and user_id not in pending_partner_messages:
                pending_betaal_product[user_id] = message.content
                await message.channel.send("📝 Product ontvangen! Klik nu op de knop **'Bericht indienen'** in je DM.")

            # Partner tekst opvang
            if user_id in pending_partner_submissions and user_id not in pending_partner_messages:
                pending_partner_messages[user_id] = message.content

    await bot.process_commands(message)


# --- /KORTINGSCODE COMMANDO'S ---

@bot.tree.command(name="createkortingscode", description="Maak een nieuwe kortingscode aan (0-90%).")
@app_commands.describe(code="De kortingscode", korting="Kortingspercentage (tussen 0 en 90)")
async def create_kortingscode(interaction: discord.Interaction, code: str, korting: int):
    if interaction.user.id not in OWNER_IDS:
        user_role_ids = [role.id for role in interaction.user.roles]
        if ROLE_KORTING_BEHEER not in user_role_ids:
            await interaction.response.send_message("❌ Jij hebt geen toestemming om dit commando te gebruiken.", ephemeral=True)
            return

    if not (0 <= korting <= 90):
        await interaction.response.send_message("❌ De korting moet tussen 0 en 90 procent zijn.", ephemeral=True)
        return

    actieve_kortingscodes[code.upper()] = korting
    await interaction.response.send_message(f"✅ Kortingscode **{code.upper()}** succesvol aangemaakt met **{korting}%** korting!", ephemeral=True)


@bot.tree.command(name="removekortingscode", description="Verwijder een bestaande kortingscode.")
@app_commands.describe(code="De te verwijderen kortingscode")
async def remove_kortingscode(interaction: discord.Interaction, code: str):
    if interaction.user.id not in OWNER_IDS:
        user_role_ids = [role.id for role in interaction.user.roles]
        if ROLE_KORTING_BEHEER not in user_role_ids:
            await interaction.response.send_message("❌ Jij hebt geen toestemming om dit commando te gebruiken.", ephemeral=True)
            return

    code_upper = code.upper()
    if code_upper in actieve_kortingscodes:
        del actieve_kortingscodes[code_upper]
        await interaction.response.send_message(f"✅ Kortingscode **{code_upper}** is succesvol verwijderd.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Kortingscode **{code_upper}** kon niet worden gevonden.", ephemeral=True)


# --- /BETAALTICKET COMMANDO ---
@bot.tree.command(name="betaalticket", description="Plaats het betaalticket paneel.")
async def betaalticket_panel(interaction: discord.Interaction):
    if interaction.user.id not in OWNER_IDS:
        user_role_ids = [role.id for role in interaction.user.roles]
        if ROLE_PARTNER_BEHEER not in user_role_ids:
            await interaction.response.send_message("Geen toestemming om dit paneel te plaatsen.", ephemeral=True)
            return

    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(
        title="💳 Betaalticket Aanmaken",
        description="Wil je een product bestellen? Klik op de knop hieronder om je betaalticket te starten via DM!",
        color=discord.Color.blue()
    )
    await interaction.channel.send(embed=embed, view=BetaalStartView())
    await interaction.followup.send("Betaalpanel geplaatst!", ephemeral=True)


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
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    review_kanaal = guild.get_channel(CHANNEL_REVIEW) if guild else None
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
    if interaction.user.id not in OWNER_IDS:
        if not any(r.id in SAY_ROLE_IDS for r in interaction.user.roles):
            await interaction.response.send_message("Geen toestemming.", ephemeral=True)
            return

    file = await afbeelding.to_file() if afbeelding else None
    await interaction.channel.send(content=bericht, file=file)
    await interaction.response.send_message("Verzonden!", ephemeral=True)


# --- /PARTNERPANEL COMMANDO ---
@bot.tree.command(name="partnerpanel", description="Plaats partner paneel.")
async def partnerpanel(interaction: discord.Interaction):
    if interaction.user.id not in OWNER_IDS:
        if not any(r.id == ROLE_PARTNER_BEHEER for r in interaction.user.roles):
            await interaction.response.send_message("Geen toestemming.", ephemeral=True)
            return

    await interaction.response.defer(ephemeral=True)
    target = interaction.guild.get_channel(CHANNEL_PARTNER_PANEL)
    if not target:
        await interaction.followup.send("Partner panel kanaal niet gevonden.", ephemeral=True)
        return

    embed = discord.Embed(title="🤝 Partner Worden", description="Klik op de knop om partner te worden!", color=discord.Color.blurple())
    await target.send(embed=embed, view=PartnerStartView())
    await interaction.followup.send("Partner panel geplaatst!", ephemeral=True)


bot.run(TOKEN)
