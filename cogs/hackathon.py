import io
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

PACIFIC = ZoneInfo("America/Los_Angeles")
TIME_FORMAT = "%Y-%m-%d %H:%M"
TEAM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,49}$")


def parse_time_range(value, now=None):
    parts = re.split(r"\s+to\s+", value.strip(), maxsplit=1, flags=re.I)
    if len(parts) != 2:
        raise ValueError("Use `YYYY-MM-DD HH:MM to YYYY-MM-DD HH:MM` (Pacific time).")
    try:
        start, end = (datetime.strptime(x, TIME_FORMAT).replace(tzinfo=PACIFIC) for x in parts)
    except ValueError as exc:
        raise ValueError("Use `YYYY-MM-DD HH:MM to YYYY-MM-DD HH:MM` (Pacific time).") from exc
    if end <= start:
        raise ValueError("The end time must be after the start time.")
    if now and end.astimezone(timezone.utc) <= now.astimezone(timezone.utc):
        raise ValueError("The end time must be in the future.")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def valid_team_name(name):
    return bool(TEAM_NAME.fullmatch(name.strip()))


def channel_name(name, hackathon_id):
    value = re.sub(r"[^a-z0-9-]+", "-", name.lower().replace("_", " ")).strip("-")
    return re.sub(r"-+", "-", value)[:80].rstrip("-") or f"hackathon-{hackathon_id}"


@dataclass(frozen=True)
class Hackathon:
    guild_id: int
    hackathon_id: int
    name: str
    description: str
    prizes: str
    start_at: datetime
    end_at: datetime
    status: str
    announcement_channel_id: int | None
    announcement_message_id: int | None
    event_channel_id: int | None
    image_name: str | None
    image_data: bytes | None


class HackathonStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS hackathon_counters(guild_id INTEGER PRIMARY KEY,last_id INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hackathons(
          guild_id INTEGER NOT NULL,hackathon_id INTEGER NOT NULL,name TEXT NOT NULL,
          description TEXT NOT NULL,prizes TEXT NOT NULL,start_at TEXT NOT NULL,end_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft',announcement_channel_id INTEGER,
          announcement_message_id INTEGER,event_channel_id INTEGER,created_by INTEGER NOT NULL,
          PRIMARY KEY(guild_id,hackathon_id));
        CREATE TABLE IF NOT EXISTS hackathon_teams(
          guild_id INTEGER NOT NULL,hackathon_id INTEGER NOT NULL,name TEXT NOT NULL COLLATE NOCASE,
          owner_id INTEGER NOT NULL,PRIMARY KEY(guild_id,hackathon_id,name),
          FOREIGN KEY(guild_id,hackathon_id) REFERENCES hackathons(guild_id,hackathon_id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS hackathon_team_members(
          guild_id INTEGER NOT NULL,hackathon_id INTEGER NOT NULL,team_name TEXT NOT NULL COLLATE NOCASE,
          user_id INTEGER NOT NULL,PRIMARY KEY(guild_id,hackathon_id,user_id),
          FOREIGN KEY(guild_id,hackathon_id,team_name)
          REFERENCES hackathon_teams(guild_id,hackathon_id,name) ON DELETE CASCADE);
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(hackathons)")}
        if "image_name" not in columns:
            self.db.execute("ALTER TABLE hackathons ADD COLUMN image_name TEXT")
        if "image_data" not in columns:
            self.db.execute("ALTER TABLE hackathons ADD COLUMN image_data BLOB")
        self.db.commit()

    def create(self, guild, creator, name, description, prizes, start, end,
               image_name=None, image_data=None):
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT last_id FROM hackathon_counters WHERE guild_id=?", (guild,)).fetchone()
            number = (row[0] if row else 0) + 1
            self.db.execute("INSERT INTO hackathon_counters VALUES(?,?) ON CONFLICT(guild_id) DO UPDATE SET last_id=excluded.last_id", (guild, number))
            self.db.execute("INSERT INTO hackathons(guild_id,hackathon_id,name,description,prizes,start_at,end_at,created_by,image_name,image_data) VALUES(?,?,?,?,?,?,?,?,?,?)", (guild, number, name, description, prizes, start.isoformat(), end.isoformat(), creator, image_name, image_data))
            self.db.commit()
            return number
        except Exception:
            self.db.rollback()
            raise

    def get(self, guild, number):
        r = self.db.execute("SELECT * FROM hackathons WHERE guild_id=? AND hackathon_id=?", (guild, number)).fetchone()
        if not r:
            return None
        return Hackathon(r["guild_id"], r["hackathon_id"], r["name"], r["description"], r["prizes"], datetime.fromisoformat(r["start_at"]), datetime.fromisoformat(r["end_at"]), r["status"], r["announcement_channel_id"], r["announcement_message_id"], r["event_channel_id"], r["image_name"], r["image_data"])

    def update(self, guild, number, field, value, start=None, end=None):
        if field == "time":
            self.db.execute("UPDATE hackathons SET start_at=?,end_at=? WHERE guild_id=? AND hackathon_id=?", (start.isoformat(), end.isoformat(), guild, number))
        else:
            if field not in {"name", "description", "prizes"}:
                raise ValueError("Invalid field")
            self.db.execute(f"UPDATE hackathons SET {field}=? WHERE guild_id=? AND hackathon_id=?", (value, guild, number))
        self.db.commit()

    def start(self, guild, number, channel, message, event_channel):
        self.db.execute("UPDATE hackathons SET status='active',announcement_channel_id=?,announcement_message_id=?,event_channel_id=? WHERE guild_id=? AND hackathon_id=?", (channel, message, event_channel, guild, number))
        self.db.commit()

    def set_preview(self, guild, number, channel, message):
        self.db.execute("UPDATE hackathons SET announcement_channel_id=?,announcement_message_id=? WHERE guild_id=? AND hackathon_id=?", (channel, message, guild, number))
        self.db.commit()

    def set_image(self, guild, number, image_name, image_data):
        self.db.execute("UPDATE hackathons SET image_name=?,image_data=? WHERE guild_id=? AND hackathon_id=?", (image_name, image_data, guild, number))
        self.db.commit()

    def end(self, guild, number):
        c = self.db.execute("UPDATE hackathons SET status='ended' WHERE guild_id=? AND hackathon_id=? AND status='active'", (guild, number))
        self.db.commit()
        return c.rowcount > 0

    def due(self, now):
        rows = self.db.execute("SELECT guild_id,hackathon_id FROM hackathons WHERE status='active' AND end_at<=?", (now.isoformat(),)).fetchall()
        return [self.get(*row) for row in rows]

    def teams(self, guild, number):
        rows = self.db.execute("SELECT t.name,m.user_id FROM hackathon_teams t LEFT JOIN hackathon_team_members m ON m.guild_id=t.guild_id AND m.hackathon_id=t.hackathon_id AND m.team_name=t.name WHERE t.guild_id=? AND t.hackathon_id=? ORDER BY t.name,m.user_id", (guild, number)).fetchall()
        result = {}
        for name, user in rows:
            result.setdefault(name, [])
            if user is not None:
                result[name].append(user)
        return list(result.items())

    def create_team(self, guild, number, name, owner):
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("INSERT INTO hackathon_teams VALUES(?,?,?,?)", (guild, number, name, owner))
            self.db.execute("INSERT INTO hackathon_team_members VALUES(?,?,?,?)", (guild, number, name, owner))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def join_team(self, guild, number, name, user):
        self.db.execute("INSERT INTO hackathon_team_members VALUES(?,?,?,?)", (guild, number, name, user))
        self.db.commit()

    def delete_team(self, guild, number, name, owner):
        c = self.db.execute("DELETE FROM hackathon_teams WHERE guild_id=? AND hackathon_id=? AND name=? AND owner_id=?", (guild, number, name, owner))
        self.db.commit()
        return c.rowcount > 0


class CreateModal(discord.ui.Modal, title="Create hackathon"):
    name = discord.ui.TextInput(label="Hackathon name", max_length=100)
    description = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=1000)
    prizes = discord.ui.TextInput(label="Prizes", style=discord.TextStyle.paragraph, max_length=1000)
    time_range = discord.ui.TextInput(label="Time frame (Pacific)", placeholder="2026-11-01 09:00 to 2026-11-03 17:00", max_length=50)

    def __init__(self, cog, image_name=None, image_data=None):
        super().__init__()
        self.cog = cog
        self.image_name = image_name
        self.image_data = image_data

    async def on_submit(self, interaction):
        try:
            start, end = parse_time_range(str(self.time_range), datetime.now(timezone.utc))
            number = self.cog.store_for(interaction.guild_id).create(interaction.guild_id, interaction.user.id, str(self.name).strip(), str(self.description).strip(), str(self.prizes).strip(), start, end, self.image_name, self.image_data)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.send_message(f"Hackathon **#{number} — {self.name}** was saved as a draft.", ephemeral=True)


class EditModal(discord.ui.Modal):
    def __init__(self, cog, item, field):
        super().__init__(title=f"Edit #{item.hackathon_id}: {field}")
        self.cog, self.item, self.field = cog, item, field
        defaults = {"name": item.name, "description": item.description, "prizes": item.prizes, "time": f"{item.start_at.astimezone(PACIFIC):{TIME_FORMAT}} to {item.end_at.astimezone(PACIFIC):{TIME_FORMAT}}"}
        style = discord.TextStyle.paragraph if field in {"description", "prizes"} else discord.TextStyle.short
        self.value = discord.ui.TextInput(label=field.title(), default=defaults[field], style=style, max_length=1000 if field in {"description", "prizes"} else 100)
        self.add_item(self.value)

    async def on_submit(self, interaction):
        try:
            if self.field == "time":
                start, end = parse_time_range(str(self.value), datetime.now(timezone.utc))
                self.cog.store_for(interaction.guild_id).update(interaction.guild_id, self.item.hackathon_id, self.field, "", start, end)
            else:
                self.cog.store_for(interaction.guild_id).update(interaction.guild_id, self.item.hackathon_id, self.field, str(self.value).strip())
            await self.cog.refresh(interaction.guild_id, self.item.hackathon_id)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.send_message("Hackathon updated.", ephemeral=True)


class Hackathons(commands.GroupCog, group_name="hackathon", group_description="Hackathon commands"):
    team = app_commands.Group(name="team", description="Hackathon team commands")

    def __init__(self, bot):
        self.bot = bot
        self.staff = self.required("STAFF_ROLE_ID")
        self.verified = self.required("VERIFIED_ROLE_ID")
        main_guild = self.required("HACKATHON_MAIN_GUILD_ID")
        test_guild = self.required("HACKATHON_TEST_GUILD_ID")
        self.categories = {main_guild: self.required("HACKATHON_MAIN_CATEGORY_ID"), test_guild: self.required("HACKATHON_TEST_CATEGORY_ID")}
        if len(self.categories) != 2:
            raise RuntimeError("Main and test hackathon guild IDs must differ.")
        main_database = os.getenv("HACKATHON_MAIN_DATABASE", "data/hackathons_main.db")
        test_database = os.getenv("HACKATHON_TEST_DATABASE", "data/hackathons_test.db")
        if os.path.abspath(main_database) == os.path.abspath(test_database):
            raise RuntimeError("Main and test hackathon databases must use different files.")
        self.stores = {
            main_guild: HackathonStore(main_database),
            test_guild: HackathonStore(test_database),
        }
        self.expiry.start()

    @staticmethod
    def required(name):
        value = os.getenv(name)
        if not value or not value.isdigit():
            raise RuntimeError(f"{name} must contain a Discord ID.")
        return int(value)

    def cog_unload(self):
        self.expiry.cancel()
        for store in self.stores.values():
            store.db.close()

    def store_for(self, guild_id):
        """Return only the database assigned to this configured Discord server."""
        return self.stores[guild_id]

    async def allowed(self, interaction, staff=False):
        if not interaction.guild or interaction.guild_id not in self.categories:
            await interaction.response.send_message("Hackathon commands are not configured for this server.", ephemeral=True)
            return False
        if staff and (not isinstance(interaction.user, discord.Member) or self.staff not in {r.id for r in interaction.user.roles}):
            await interaction.response.send_message("This command is only available to staff.", ephemeral=True)
            return False
        return True

    async def item(self, interaction, number, staff=False):
        if not await self.allowed(interaction, staff):
            return None
        item = self.store_for(interaction.guild_id).get(interaction.guild_id, number)
        if not item:
            await interaction.response.send_message(f"Hackathon #{number} does not exist in this server.", ephemeral=True)
        return item

    def make_embed(self, item):
        embed = discord.Embed(title=item.name, description=item.description, color={"draft": discord.Color.gold(), "active": discord.Color.green(), "ended": discord.Color.red()}[item.status])
        start, end = int(item.start_at.timestamp()), int(item.end_at.timestamp())
        ps, pe = item.start_at.astimezone(PACIFIC), item.end_at.astimezone(PACIFIC)
        embed.add_field(name="Prizes", value=item.prizes, inline=False)
        embed.add_field(name="Schedule", value=f"Pacific: {ps:%b %d, %Y at %I:%M %p %Z} — {pe:%b %d, %Y at %I:%M %p %Z}\nYour time: <t:{start}:F> — <t:{end}:F>\nCountdown: <t:{end}:R>", inline=False)
        teams = self.store_for(item.guild_id).teams(item.guild_id, item.hackathon_id)
        text = "\n".join(f"• {n} ({len(m)} member{'s' if len(m) != 1 else ''})" for n, m in teams) or "No teams have registered yet."
        embed.add_field(name="Teams", value=text[:1024], inline=False)
        embed.add_field(name="Register", value=f"Use `/hackathon team create` or `/hackathon team join` with ID `{item.hackathon_id}`. Team names may only contain letters, numbers, spaces, hyphens, and underscores—no formatting or fancy characters.", inline=False)
        embed.set_footer(text=f"Status: {item.status.title()} • ID {item.hackathon_id}")
        if item.image_data:
            embed.set_image(url=f"attachment://{item.image_name}")
        return embed

    @staticmethod
    async def read_image(image):
        if not image.content_type or not image.content_type.startswith("image/"):
            raise ValueError("The uploaded file must be an image.")
        if image.size > 8 * 1024 * 1024:
            raise ValueError("The image must be 8 MB or smaller.")
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", image.filename)
        return safe_name or "hackathon-image.png", await image.read()

    @staticmethod
    def image_file(item):
        if not item.image_data:
            return None
        return discord.File(io.BytesIO(item.image_data), filename=item.image_name)

    async def refresh(self, guild_id, number):
        item = self.store_for(guild_id).get(guild_id, number)
        if not item or not item.announcement_channel_id or not item.announcement_message_id:
            return
        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(item.announcement_channel_id) if guild else None
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(item.announcement_message_id)
                file = self.image_file(item)
                await message.edit(embed=self.make_embed(item), attachments=[file] if file else [])
            except (discord.NotFound, discord.Forbidden):
                pass

    @app_commands.command(name="create", description="Create a hackathon draft (staff only)")
    async def create(self, interaction: discord.Interaction, image: discord.Attachment | None = None):
        if not await self.allowed(interaction, True):
            return
        try:
            image_name, image_data = await self.read_image(image) if image else (None, None)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.send_modal(CreateModal(self, image_name, image_data))

    @app_commands.command(name="edit", description="Edit a hackathon field (staff only)")
    @app_commands.choices(field=[app_commands.Choice(name=x.title(), value=x) for x in ("name", "description", "prizes", "time")])
    async def edit(self, interaction: discord.Interaction, hackathon_id: int, field: app_commands.Choice[str]):
        item = await self.item(interaction, hackathon_id, True)
        if item:
            await interaction.response.send_modal(EditModal(self, item, field.value))

    @app_commands.command(name="embed", description="Post a preview without starting (staff only)")
    async def embed(self, interaction: discord.Interaction, hackathon_id: int):
        item = await self.item(interaction, hackathon_id, True)
        if item:
            await interaction.response.send_message(embed=self.make_embed(item), file=self.image_file(item))
            message = await interaction.original_response()
            self.store_for(item.guild_id).set_preview(item.guild_id, item.hackathon_id, interaction.channel_id, message.id)

    @app_commands.command(name="image", description="Add or replace a hackathon image (staff only)")
    async def image(self, interaction: discord.Interaction, hackathon_id: int, image: discord.Attachment):
        item = await self.item(interaction, hackathon_id, True)
        if not item:
            return
        try:
            image_name, image_data = await self.read_image(image)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        self.store_for(item.guild_id).set_image(item.guild_id, item.hackathon_id, image_name, image_data)
        await self.refresh(item.guild_id, item.hackathon_id)
        await interaction.response.send_message("Hackathon image updated.", ephemeral=True)

    @app_commands.command(name="start", description="Start a hackathon (staff only)")
    async def start(self, interaction: discord.Interaction, hackathon_id: int):
        item = await self.item(interaction, hackathon_id, True)
        if not item:
            return
        if item.status != "draft":
            return await interaction.response.send_message("Only a draft can be started.", ephemeral=True)
        category = interaction.guild.get_channel(self.categories[interaction.guild_id])
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message("The configured hackathon category was not found.", ephemeral=True)
        await interaction.response.defer()
        event = await interaction.guild.create_text_channel(channel_name(item.name, item.hackathon_id), category=category, topic=f"Hackathon #{item.hackathon_id}: {item.name}")
        role = interaction.guild.get_role(self.verified)
        message = await interaction.followup.send(content=role.mention if role else None, embed=self.make_embed(item), file=self.image_file(item), allowed_mentions=discord.AllowedMentions(roles=True), wait=True)
        self.store_for(item.guild_id).start(item.guild_id, item.hackathon_id, interaction.channel_id, message.id, event.id)
        await message.edit(embed=self.make_embed(self.store_for(item.guild_id).get(item.guild_id, item.hackathon_id)))
        await event.send(f"Hackathon **{item.name}** has started. Submit your work here when ready.")

    async def finish(self, guild, item):
        if not self.store_for(item.guild_id).end(item.guild_id, item.hackathon_id):
            return False
        await self.refresh(item.guild_id, item.hackathon_id)
        channel = guild.get_channel(item.event_channel_id) if item.event_channel_id else None
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=discord.Embed(title=f"The {item.name} hackathon has ended!", description="Submit your entries in this channel for the judges to review.", color=discord.Color.red()))
        return True

    @app_commands.command(name="end", description="End a hackathon now (staff only)")
    async def end(self, interaction: discord.Interaction, hackathon_id: int):
        item = await self.item(interaction, hackathon_id, True)
        if item:
            result = await self.finish(interaction.guild, item)
            await interaction.response.send_message("Hackathon ended." if result else "That hackathon is not active.", ephemeral=True)

    @app_commands.command(name="winners", description="Announce the three winning teams (staff only)")
    async def winners(self, interaction: discord.Interaction, hackathon_id: int, first_place: str, second_place: str, third_place: str):
        item = await self.item(interaction, hackathon_id, True)
        if not item:
            return
        teams = {n.casefold(): (n, m) for n, m in self.store_for(item.guild_id).teams(item.guild_id, item.hackathon_id)}
        requested = [first_place, second_place, third_place]
        missing = [n for n in requested if n.casefold() not in teams]
        if missing:
            return await interaction.response.send_message("No registered team was found for: " + ", ".join(missing), ephemeral=True)
        if len({n.casefold() for n in requested}) != 3:
            return await interaction.response.send_message("Each placement must use a different team.", ephemeral=True)
        lines = []
        for place, entered in zip(("1st", "2nd", "3rd"), requested):
            name, members = teams[entered.casefold()]
            lines.append(f"**{place} place — {name}**\n" + " ".join(f"<@{u}>" for u in members))
        embed = discord.Embed(title=f"{item.name} winners", description="\n\n".join(lines) + "\n\nWinners, please create a ticket to claim your prize(s).", color=discord.Color.gold())
        role = interaction.guild.get_role(self.verified)
        await interaction.response.send_message(content=role.mention if role else None, embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=True))

    @team.command(name="create", description="Create a team for an active hackathon")
    async def team_create(self, interaction: discord.Interaction, name: str, hackathon_id: int):
        item = await self.item(interaction, hackathon_id)
        if not item:
            return
        if item.status != "active":
            return await interaction.response.send_message("Teams can only be created for an active hackathon.", ephemeral=True)
        if not valid_team_name(name):
            return await interaction.response.send_message("Use 1–50 letters, numbers, spaces, hyphens, or underscores only.", ephemeral=True)
        try:
            self.store_for(item.guild_id).create_team(item.guild_id, item.hackathon_id, name.strip(), interaction.user.id)
        except sqlite3.IntegrityError:
            return await interaction.response.send_message("That name exists, or you are already on a team.", ephemeral=True)
        await self.refresh(item.guild_id, item.hackathon_id)
        await interaction.response.send_message(f"Team **{name.strip()}** created.", ephemeral=True)

    @team.command(name="join", description="Join a team for an active hackathon")
    async def team_join(self, interaction: discord.Interaction, name: str, hackathon_id: int):
        item = await self.item(interaction, hackathon_id)
        if not item:
            return
        if item.status != "active":
            return await interaction.response.send_message("Teams can only be joined during an active hackathon.", ephemeral=True)
        try:
            self.store_for(item.guild_id).join_team(item.guild_id, item.hackathon_id, name.strip(), interaction.user.id)
        except sqlite3.IntegrityError:
            return await interaction.response.send_message("That team does not exist, or you are already on a team.", ephemeral=True)
        await self.refresh(item.guild_id, item.hackathon_id)
        await interaction.response.send_message(f"You joined **{name.strip()}**.", ephemeral=True)

    @team.command(name="delete", description="Delete a team you created")
    async def team_delete(self, interaction: discord.Interaction, name: str, hackathon_id: int):
        item = await self.item(interaction, hackathon_id)
        if not item:
            return
        if not self.store_for(item.guild_id).delete_team(item.guild_id, item.hackathon_id, name.strip(), interaction.user.id):
            return await interaction.response.send_message("That team does not exist, or you are not its creator.", ephemeral=True)
        await self.refresh(item.guild_id, item.hackathon_id)
        await interaction.response.send_message(f"Team **{name.strip()}** deleted.", ephemeral=True)

    @tasks.loop(minutes=1)
    async def expiry(self):
        for store in self.stores.values():
            for item in store.due(datetime.now(timezone.utc)):
                guild = self.bot.get_guild(item.guild_id)
                if guild:
                    try:
                        await self.finish(guild, item)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

    @expiry.before_loop
    async def before_expiry(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Hackathons(bot))
