import os
import pathlib
import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import asyncio
import random
import feedparser

print("Script wordt geladen...")

# Probeer optioneel python-dotenv te laden (handig voor lokaal testen)
try:
    from dotenv import load_dotenv
    env_path = pathlib.Path(__file__).parent / '.env'
    load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    print("FOUT: Geen DISCORD_TOKEN gevonden!")
    exit()

# Definieer de Intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- CONFIGURATIE: ROL & KANAAL ID'S ---
ROLE_LOWER_STAFF = 1551318319892529192          # Mute, Warn
ROLE_HIGHER_STAFF = 1551313880494374962         # Superrol (heeft overal toegang toe)
ROLE_PARTNER_STAFF = 1551683186629812305        # Partnerad, Eisen
ROLE_BOTBERICHT_DM_STAFF = 1558518307949256766  # Specifieke rol voor /botbericht, /dm en /globaldm

LOG_CHANNEL_ID = 1553859972100788228            # Kanaal ID voor Giveaway Logs
TIKTOK_CHANNEL_ID = 1559164859290226788         # Kanaal ID voor TikTok Updates

# TikTok Gegevens
TIKTOK_USERNAME = "prizenetwork_official"
TIKTOK_URL = f"https://www.tiktok.com/@{TIKTOK_USERNAME}"
TIKTOK_RSS_URL = f"https://rsshub.app/tiktok/user/@{TIKTOK_USERNAME}"

laatst_geziene_tiktok_id = None
PRIZE_NETWORK_BANNER = "https://i.ibb.co/bc3100dd0fb5cc6d155b5c7907b0bae8/bc3100dd0fb5cc6d155b5c7907b0bae8.jpg"

# Sla actieve giveaways op voor /reroll
actieve_giveaways = {}
giveaway_counter = 0

# Controleer of de gebruiker de juiste rollen heeft
def check_roles(interaction: discord.Interaction, allowed_role_ids: list[int]) -> bool:
    if not interaction.guild:
        return False
        
    user_role_ids = [role.id for role in interaction.user.roles]
    if ROLE_HIGHER_STAFF in user_role_ids:
        return True
        
    return any(role_id in user_role_ids for role_id in allowed_role_ids)


# ==========================================
# AUTOMATISCHE TIKTOK UPDATES (ACHTERGROND)
# ==========================================

@tasks.loop(minutes=5)
async def tiktok_checker():
    global laatst_geziene_tiktok_id
    try:
        kanaal = bot.get_channel(TIKTOK_CHANNEL_ID)
        if not kanaal:
            return

        feed = feedparser.parse(TIKTOK_RSS_URL)
        if feed.entries:
            meest_recente = feed.entries[0]
            bericht_id = meest_recente.id if hasattr(meest_recente, 'id') else meest_recente.link

            if laatst_geziene_tiktok_id is None:
                laatst_geziene_tiktok_id = bericht_id
                return

            if bericht_id != laatst_geziene_tiktok_id:
                laatst_geziene_tiktok_id = bericht_id
                
                titel = meest_recente.title if hasattr(meest_recente, 'title') else "Nieuwe update!"
                link = meest_recente.link

                embed = discord.Embed(
                    title="🎵 **NIEUWE TIKTOK UPDATE!**",
                    description=f"**{titel}**\n\nBekijk de video/live via onderstaande link:\n{link}",
                    color=discord.Color.from_rgb(254, 44, 85),
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                embed.set_author(name="Prize Network TikTok", icon_url="https://pngimg.com/uploads/tiktok/tiktok_PNG13.png", url=TIKTOK_URL)
                embed.set_image(url=PRIZE_NETWORK_BANNER)
                embed.set_footer(text="Prize Network Socials")

                await kanaal.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none()
                )
    except Exception as e:
        print(f"Fout bij het ophalen van TikTok updates: {e}")


@bot.event
async def on_ready():
    print(f'Bot is succesvol ingelogd als {bot.user}!')
    if not tiktok_checker.is_running():
        tiktok_checker.start()
    try:
        synced = await bot.tree.sync()
        print(f"Gesynchroniseerd: {len(synced)} slash commands globaal.")
    except Exception as e:
        print(f"Fout bij synchroniseren van commands: {e}")


# ==========================================
# 1. MODERATIE COMMANDS
# ==========================================

@bot.tree.command(name="warn", description="Geef een officiële waarschuwing aan een lid.")
async def warn(interaction: discord.Interaction, lid: discord.Member, reden: str):
    if not check_roles(interaction, [ROLE_LOWER_STAFF, ROLE_HIGHER_STAFF]):
        return await interaction.response.send_message("❌ Je hebt geen rechten voor dit commando.", ephemeral=True)
    
    embed = discord.Embed(
        title="⚠️ OFFICIËLE WAARSCHUWING",
        description=f"Er is een officiële waarschuwing uitgedeeld aan {lid.mention}.",
        color=discord.Color.from_rgb(255, 170, 0),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="👤 Gebruiker", value=f"{lid.mention} (`{lid.id}`)", inline=True)
    embed.add_field(name="🛡️ Moderator", value=f"{interaction.user.mention}", inline=True)
    embed.add_field(name="📝 Reden", value=f"```\n{reden}\n```", inline=False)
    embed.set_thumbnail(url=lid.display_avatar.url)
    embed.set_footer(text="Prize Network Moderatie", icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="mute", description="Tijdelijke mute (timeout) voor een lid.")
async def mute(interaction: discord.Interaction, lid: discord.Member, minuten: int, reden: str):
    if not check_roles(interaction, [ROLE_LOWER_STAFF, ROLE_HIGHER_STAFF]):
        return await interaction.response.send_message("❌ Je hebt geen rechten voor dit commando.", ephemeral=True)
    
    duur = datetime.timedelta(minutes=minuten)
    await lid.timeout(duur, reason=reden)
    
    embed = discord.Embed(
        title="🤫 GEBRUIKER GEMUTED",
        description=f"{lid.mention} is tijdelijk stilgezet.",
        color=discord.Color.from_rgb(230, 126, 34),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="👤 Gebruiker", value=f"{lid.mention} (`{lid.id}`)", inline=True)
    embed.add_field(name="⏱️ Duur", value=f"**{minuten} minuten**", inline=True)
    embed.add_field(name="🛡️ Moderator", value=f"{interaction.user.mention}", inline=True)
    embed.add_field(name="📝 Reden", value=f"```\n{reden}\n```", inline=False)
    embed.set_thumbnail(url=lid.display_avatar.url)
    embed.set_footer(text="Prize Network Moderatie", icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="kick", description="Kick een lid uit de server.")
async def kick(interaction: discord.Interaction, lid: discord.Member, reden: str = "Geen reden opgegeven"):
    if not check_roles(interaction, [ROLE_HIGHER_STAFF]):
        return await interaction.response.send_message("❌ Je hebt geen rechten voor dit commando.", ephemeral=True)
    
    await lid.kick(reason=reden)
    
    embed = discord.Embed(
        title="👢 GEBRUIKER GEKICKT",
        description=f"{lid.mention} is verwijderd uit de server.",
        color=discord.Color.from_rgb(231, 76, 60),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="👤 Gebruiker", value=f"**{lid.display_name}** (`{lid.id}`)", inline=True)
    embed.add_field(name="🛡️ Moderator", value=f"{interaction.user.mention}", inline=True)
    embed.add_field(name="📝 Reden", value=f"```\n{reden}\n```", inline=False)
    embed.set_footer(text="Prize Network Moderatie", icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ban", description="Ban een lid uit de server.")
async def ban(interaction: discord.Interaction, lid: discord.Member, reden: str = "Geen reden opgegeven"):
    if not check_roles(interaction, [ROLE_HIGHER_STAFF]):
        return await interaction.response.send_message("❌ Je hebt geen rechten voor dit commando.", ephemeral=True)
    
    await lid.ban(reason=reden)
    
    embed = discord.Embed(
        title="🔨 GEBRUIKER VERBANNEN",
        description=f"**{lid.display_name}** is permanent verbannen uit de server.",
        color=discord.Color.from_rgb(155, 89, 182),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="👤 Gebruiker", value=f"**{lid.display_name}** (`{lid.id}`)", inline=True)
    embed.add_field(name="🛡️ Moderator", value=f"{interaction.user.mention}", inline=True)
    embed.add_field(name="📝 Reden", value=f"```\n{reden}\n```", inline=False)
    embed.set_footer(text="Prize Network Moderatie", icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None)

    await interaction.response.send_message(embed=embed)


# ==========================================
# 2. BOTBERICHT, DM & GLOBALDM COMMANDS
# ==========================================

@bot.tree.command(name="botbericht", description="Stuur een gewoon bericht namens de bot.")
async def botbericht(interaction: discord.Interaction, bericht: str, afbeelding: discord.Attachment = None):
    if not check_roles(interaction, [ROLE_BOTBERICHT_DM_STAFF, ROLE_HIGHER_STAFF]):
        return await interaction.response.send_message("❌ Je hebt geen rechten voor dit commando.", ephemeral=True)
    
    if interaction.channel:
        if afbeelding:
            file = await afbeelding.to_file()
            await interaction.channel.send(content=bericht, file=file)
        else:
            await interaction.channel.send(content=bericht)
            
    await interaction.response.send_message("✨ Bericht succesvol geplaatst!", ephemeral=True)


@bot.tree.command(name="dm", description="Stuur een privébericht naar een gebruiker.")
async def dm(interaction: discord.Interaction, gebruiker: discord.User, bericht: str, afbeelding: discord.Attachment = None):
    if not check_roles(interaction, [ROLE_BOTBERICHT_DM_STAFF, ROLE_HIGHER_STAFF]):
        return await interaction.response.send_message("❌ Je hebt geen rechten voor dit commando.", ephemeral=True)
    
    try:
        embed = discord.Embed(
            title="📩 **BERICHT VAN PRIZE NETWORK**",
            description=bericht,
            color=discord.Color.from_rgb(155, 89, 182),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        if afbeelding:
            embed.set_image(url=afbeelding.url)
            
        embed.set_footer(text="Verzonden door de staff van Prize Network", icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None)

        await gebruiker.send(embed=embed)
        await interaction.response.send_message(f"✅ DM succesvol verzonden naar {gebruiker.mention}.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Kon de DM niet versturen. De gebruiker heeft hun DM's waarschijnlijk uitstaan.", ephemeral=True)


@bot.tree.command(name="globaldm", description="Stuur een privébericht naar ALLE leden in de server.")
async def globaldm(interaction: discord.Interaction, bericht: str, afbeelding: discord.Attachment = None):
    if not check_roles(interaction, [ROLE_BOTBERICHT_DM_STAFF, ROLE_HIGHER_STAFF]):
        return await interaction.response.send_message("❌ Je hebt geen rechten voor dit commando.", ephemeral=True)

    if not interaction.guild:
        return await interaction.response.send_message("❌ Dit commando kan alleen in een server gebruikt worden.", ephemeral=True)

    await interaction.response.send_message("🚀 **Global DM is op de achtergrond gestart!** Je krijgt een seintje zodra het klaar is.", ephemeral=True)

    embed = discord.Embed(
        title="📢 **MEDEDELING VAN PRIZE NETWORK**",
        description=bericht,
        color=discord.Color.from_rgb(52, 152, 219),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    if afbeelding:
        embed.set_image(url=afbeelding.url)
    else:
        embed.set_image(url=PRIZE_NETWORK_BANNER)
        
    embed.set_footer(text="Prize Network Community", icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None)

    async def verstuur_achtergrond():
        succes = 0
        mislukt = 0
        
        for member in interaction.guild.members:
            if member.bot:
                continue
            try:
                await member.send(embed=embed)
                succes += 1
                await asyncio.sleep(0.05)
            except (discord.Forbidden, discord.HTTPException):
                mislukt += 1

        if interaction.channel:
            await interaction.channel.send(
                f"✅ **Global DM Voltooid door {interaction.user.mention}!**\n"
                f"• 📤 Succesvol: **{succes}** leden\n"
                f"• ❌ Mislukt (DM's uit): **{mislukt}** leden"
            )

    asyncio.create_task(verstuur_achtergrond())


# ==========================================
# 3. LUXE GIVEAWAY SYSTEM + LOGGING & REROLL
# ==========================================

class GiveawayView(discord.ui.View):
    def __init__(self, embed: discord.Embed, participants_list: list):
        super().__init__(timeout=None)
        self.participants = participants_list
        self.embed = embed

    @discord.ui.button(label="Meedoen", style=discord.ButtonStyle.success, emoji="🎉", custom_id="giveaway_join")
    async def join_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.participants:
            self.participants.remove(interaction.user)
            await interaction.response.send_message("❌ Je bent uit de giveaway gestapt.", ephemeral=True)
        else:
            self.participants.append(interaction.user)
            await interaction.response.send_message("🎉 Je doet nu succesvol mee aan de giveaway!", ephemeral=True)

        for index, field in enumerate(self.embed.fields):
            if "Deelnemers" in field.name:
                self.embed.set_field_at(index, name="👥 Deelnemers", value=f"```\n{len(self.participants)} deelnemers\n```", inline=True)
                break
        
        if interaction.message:
            try:
                await interaction.message.edit(embed=self.embed)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Aantal Deelnemers", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="giveaway_count")
    async def count_participants(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"📊 Er doen op dit moment **{len(self.participants)}** mensen mee aan deze giveaway!", ephemeral=True)


@bot.tree.command(name="giveaway", description="Start een luxe giveaway.")
async def giveaway(
    interaction: discord.Interaction, 
    prijs: str, 
    aantal_winnaars: int, 
    duur_minuten: int, 
    tag_rol: discord.Role = None
):
    global giveaway_counter
    if not check_roles(interaction, [ROLE_HIGHER_STAFF]):
        return await interaction.response.send_message("❌ Je hebt geen rechten voor dit commando.", ephemeral=True)

    if not interaction.channel:
        return await interaction.response.send_message("❌ Dit commando werkt alleen in een kanaal.", ephemeral=True)

    giveaway_counter += 1
    giv_id = giveaway_counter

    eind_tijd = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=duur_minuten)
    timestamp = f"<t:{int(eind_tijd.timestamp())}:R>"
    exacte_tijd = f"<t:{int(eind_tijd.timestamp())}:f>"

    embed = discord.Embed(
        title=f"🎉 **GIVEAWAY: {prijs.upper()}** 🎉",
        description="Klik op de groene knop **'Meedoen 🎉'** hieronder om kans te maken!",
        color=discord.Color.from_rgb(88, 101, 242)
    )
    
    embed.set_author(name=f"Giveaway #{giv_id}")

    embed.add_field(name="🏆 Prijs", value=f"```\n{prijs}\n```", inline=True)
    embed.add_field(name="👑 Winnaar(s)", value=f"```\n{aantal_winnaars} winnaar(s)\n```", inline=True)
    embed.add_field(name="👥 Deelnemers", value="```\n0 deelnemers\n```", inline=True)
    embed.add_field(name="⏳ Resterende Tijd", value=f"Eindigt {timestamp}\n({exacte_tijd})", inline=False)
    embed.add_field(name="🎙️ Gehost door", value=interaction.user.mention, inline=False)
    
    embed.set_image(url=PRIZE_NETWORK_BANNER)
    embed.set_footer(text=f"Prize Network • ID: {giv_id} • Veel succes!", icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None)

    content = tag_rol.mention if tag_rol else None
    
    participants_list = []
    actieve_giveaways[giv_id] = {
        "prijs": prijs,
        "participants": participants_list
    }

    view = GiveawayView(embed=embed, participants_list=participants_list)

    await interaction.response.send_message(f"✅ Giveaway **#{giv_id}** succesvol gestart!", ephemeral=True)
    message = await interaction.channel.send(content=content, embed=embed, view=view)

    # --- LOG: GIVEAWAY GESTART ---
    log_kanaal = bot.get_channel(LOG_CHANNEL_ID)
    if log_kanaal:
        start_log_embed = discord.Embed(
            title=f"📋 **LOG: GIVEAWAY #{giv_id} GESTART**",
            color=discord.Color.from_rgb(52, 152, 219),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        start_log_embed.add_field(name="🏆 Prijs", value=f"**{prijs}**", inline=True)
        start_log_embed.add_field(name="👑 Winnaar(s)", value=f"**{aantal_winnaars}**", inline=True)
        start_log_embed.add_field(name="⏱️ Duur", value=f"**{duur_minuten} minuten**", inline=True)
        start_log_embed.add_field(name="🎙️ Host", value=interaction.user.mention, inline=True)
        start_log_embed.add_field(name="📍 Kanaal", value=interaction.channel.mention, inline=True)
        start_log_embed.add_field(name="🔗 Bericht Link", value=f"[Ga naar Giveaway]({message.jump_url})", inline=False)
        start_log_embed.set_footer(text=f"Prize Network Giveaway Logs • ID: {giv_id}")
        await log_kanaal.send(embed=start_log_embed)

    await asyncio.sleep(duur_minuten * 60)

    for child in view.children:
        child.disabled = True

    if not participants_list:
        eind_embed = discord.Embed(
            title=f"🛑 **GIVEAWAY #{giv_id} AFGELOPEN**",
            description=f"De giveaway voor **{prijs}** is afgelopen, maar er waren helaas geen deelnemers!",
            color=discord.Color.from_rgb(231, 76, 60)
        )
        eind_embed.set_author(name=f"Giveaway #{giv_id}")
        eind_embed.set_image(url=PRIZE_NETWORK_BANNER)
        try:
            await message.edit(embed=eind_embed, view=view)
        except discord.HTTPException:
            pass

        if log_kanaal:
            eind_log_embed = discord.Embed(
                title=f"📋 **LOG: GIVEAWAY #{giv_id} AFGELOPEN (GEEN DEELNEMERS)**",
                color=discord.Color.from_rgb(231, 76, 60),
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            eind_log_embed.add_field(name="🏆 Prijs", value=f"**{prijs}**", inline=True)
            eind_log_embed.add_field(name="🔗 Bericht Link", value=f"[Ga naar Giveaway]({message.jump_url})", inline=False)
            await log_kanaal.send(embed=eind_log_embed)
    else:
        winnaars = random.sample(participants_list, min(len(participants_list), aantal_winnaars))
        winnaars_mentions = ", ".join([w.mention for w in winnaars])
        
        eind_embed = discord.Embed(
            title=f"✨ **GIVEAWAY WINNAAR(S) (#{giv_id})** ✨",
            description=f"De giveaway voor **{prijs}** is officieel afgelopen!",
            color=discord.Color.from_rgb(255, 215, 0)
        )
        eind_embed.set_author(name=f"Giveaway #{giv_id}")
        eind_embed.add_field(name="🎁 Gewonnen Prijs", value=f"**{prijs}**", inline=False)
        eind_embed.add_field(name="🎉 Winnaar(s)", value=winnaars_mentions, inline=False)
        eind_embed.add_field(name="👥 Totaal Aantal Deelnemers", value=f"**{len(participants_list)}**", inline=False)
        eind_embed.set_image(url=PRIZE_NETWORK_BANNER)
        eind_embed.set_footer(text="Prize Network • Open een ticket om je prijs te claimen!", icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None)

        try:
            await message.edit(embed=eind_embed, view=view)
        except discord.HTTPException:
            pass
            
        await interaction.channel.send(content=f"🎊 Gefeliciteerd {winnaars_mentions}! Je hebt **{prijs}** gewonnen (Giveaway **#{giv_id}**).", embed=eind_embed)

        if log_kanaal:
            eind_log_embed = discord.Embed(
                title=f"📋 **LOG: GIVEAWAY #{giv_id} AFGELOPEN**",
                color=discord.Color.from_rgb(46, 204, 113),
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            eind_log_embed.add_field(name="🏆 Prijs", value=f"**{prijs}**", inline=True)
            eind_log_embed.add_field(name="🎉 Winnaar(s)", value=winnaars_mentions, inline=True)
            eind_log_embed.add_field(name="👥 Deelnemers", value=f"**{len(participants_list)}**", inline=True)
            eind_log_embed.add_field(name="🎙️ Host", value=interaction.user.mention, inline=True)
            eind_log_embed.add_field(name="🔗 Bericht Link", value=f"[Ga naar Giveaway]({message.jump_url})", inline=False)
            eind_log_embed.set_footer(text=f"Prize Network Giveaway Logs • ID: {giv_id}")
            await log_kanaal.send(embed=eind_log_embed)


@bot.tree.command(name="reroll", description="Kies nieuwe winnaars voor een giveaway.")
@app_commands.describe(nummer="Het giveaway nummer", hoeveel="Aantal nieuwe winnaars")
async def reroll(interaction: discord.Interaction, nummer: int, hoeveel: int):
    if not check_roles(interaction, [ROLE_HIGHER_STAFF]):
        return await interaction.response.send_message("❌ Je hebt geen rechten voor dit commando.", ephemeral=True)

    if nummer not in actieve_giveaways:
        return await interaction.response.send_message(f"❌ Kan geen actieve of opgeslagen giveaway vinden met nummer **{nummer}**.", ephemeral=True)

    giv_data = actieve_giveaways[nummer]
    participants = giv_data["participants"]
    prijs = giv_data["prijs"]

    if not participants:
        return await interaction.response.send_message(f"❌ Er waren geen deelnemers bij giveaway **{nummer}** om te rerollen.", ephemeral=True)

    nieuwe_winnaars = random.sample(participants, min(len(participants), hoeveel))
    winnaars_mentions = ", ".join([w.mention for w in nieuwe_winnaars])

    embed = discord.Embed(
        title=f"🔄 **REROLL WINNAAR(S)**",
        description=f"Er is een nieuwe winnaar gekozen voor **{prijs}**!",
        color=discord.Color.from_rgb(241, 196, 15),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.set_author(name=f"Giveaway #{nummer}")
    embed.add_field(name="🎁 Prijs", value=f"**{prijs}**", inline=False)
    embed.add_field(name="🎉 Nieuwe Winnaar(s)", value=winnaars_mentions, inline=False)

    # 1. Stuur een onzichtbare bevestiging naar de moderator
    await interaction.response.send_message("✅ Reroll succesvol uitgevoerd!", ephemeral=True)

    # 2. Stuur het schone bericht los in het kanaal (zonder bovenschrift en zonder naam in footer)
    if interaction.channel:
        await interaction.channel.send(content=f"🎊 Nieuwe winnaar(s) voor giveaway **#{nummer}**: {winnaars_mentions}!", embed=embed)


# ==========================================
# 4. PARTNER COMMANDS
# ==========================================

@bot.tree.command(name="partnerad", description="Plaats de officiële Prize Network partner advertentie.")
async def partnerad(interaction: discord.Interaction):
    if not check_roles(interaction, [ROLE_PARTNER_STAFF, ROLE_HIGHER_STAFF]):
        return await interaction.response.send_message("❌ Je hebt geen rechten voor dit commando.", ephemeral=True)

    bericht_tekst = (
        "# PRIZE NETWORK\n\n"
        "Ben jij op zoek naar een actieve en gezellige Discord-server?\n\n"
        "Welkom bij **Prize Network**!\n\n"
        " • Regelmatige giveaways • Leuke events • Mooie prijzen • Actieve community • Nieuwe partners en samenwerkingen\n\n"
        "Join Prize Network en maak kans op leuke prijzen!\n\n"
        " • https://discord.gg/pW8WmhJMtJ\n\n"
        "**PRIZE NETWORK**\n"
        "Samen groeien, samen winnen."
    )
    
    await interaction.response.send_message(bericht_tekst)


@bot.tree.command(name="eisen", description="Toon de officiële partner eisen.")
async def eisen(interaction: discord.Interaction):
    if not check_roles(interaction, [ROLE_PARTNER_STAFF, ROLE_HIGHER_STAFF]):
        return await interaction.response.send_message("❌ Je hebt geen rechten voor dit commando.", ephemeral=True)

    embed = discord.Embed(
        title="🤝 **PARTNER EISEN — PRIZE NETWORK**",
        description="Om een officiële samenwerking of partnerschap aan te gaan met **Prize Network**, dient jouw Discord-server aan de onderstaande voorwaarden te voldoen:",
        color=discord.Color.from_rgb(52, 152, 219)
    )
    
    embed.add_field(
        name="📌 Voorwaarden & Eisen",
        value=(
            "• 👥 **Minimaal 100+ leden** *(exclusief bots)*\n"
            "• 💬 **Actieve Community** & gezonde dagelijkse chat\n"
            "• 🛡️ **Veilige Omgeving** *(geen NSFW of illegale content)*\n"
            "• 📢 **Partnerkanaal** *(een net en overzichtelijk kanaal voor partner-ads)*\n"
            "• 🔔 **everyone ping** *(1 ping per partner-ad toegestaan, in overleg)*"
        ),
        inline=False
    )
    
    embed.set_image(url=PRIZE_NETWORK_BANNER)
    embed.set_footer(text="Prize Network Partnerships", icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None)

    await interaction.response.send_message(embed=embed)


# Start de bot
bot.run(TOKEN)
