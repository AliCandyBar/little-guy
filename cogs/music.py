"""Discord voice music playback backed by Spotify metadata and YouTube audio."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import re
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, replace
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
except ImportError:  # Lets lightweight tooling import this module before install.
    spotipy = None  # type: ignore[assignment]
    SpotifyClientCredentials = None  # type: ignore[assignment,misc]


SPOTIFY_URL = re.compile(
    r"https?://open\.spotify\.com/(?:intl-[^/]+/)?(track|playlist)/([A-Za-z0-9]+)"
)
BAR_SIZE = 16


def format_time(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def progress_bar(elapsed: float, duration: float | None) -> str:
    if not duration or duration <= 0:
        return "🔘" + "▬" * (BAR_SIZE - 1)
    position = min(BAR_SIZE - 1, max(0, int((elapsed / duration) * BAR_SIZE)))
    return "▬" * position + "🔘" + "▬" * (BAR_SIZE - position - 1)


@dataclass(frozen=True, slots=True)
class Track:
    title: str
    artists: str
    duration: float | None
    artwork: str | None = None
    spotify_url: str | None = None
    requested_by: str | None = None
    search_query: str | None = None
    webpage_url: str | None = None

    @property
    def query(self) -> str:
        return self.search_query or f"{self.title} {self.artists} audio"


class SpotifyRefreshTokenAuth:
    """Small Spotipy auth manager for a pre-authorized user refresh token."""

    TOKEN_URL = "https://accounts.spotify.com/api/token"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.access_token: str | None = None
        self.expires_at = 0.0
        self.lock = threading.Lock()

    def get_access_token(self, as_dict: bool = False, **_: object) -> str | dict:
        with self.lock:
            if not self.access_token or time.monotonic() >= self.expires_at - 60:
                credentials = base64.b64encode(
                    f"{self.client_id}:{self.client_secret}".encode()
                ).decode()
                body = urllib.parse.urlencode(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": self.refresh_token,
                    }
                ).encode()
                request = urllib.request.Request(
                    self.TOKEN_URL,
                    data=body,
                    headers={
                        "Authorization": f"Basic {credentials}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    token_info = json.load(response)
                self.access_token = token_info["access_token"]
                self.expires_at = time.monotonic() + int(token_info.get("expires_in", 3600))
                self.refresh_token = token_info.get("refresh_token", self.refresh_token)

            if as_dict:
                return {
                    "access_token": self.access_token,
                    "token_type": "Bearer",
                    "expires_at": int(time.time() + max(0, self.expires_at - time.monotonic())),
                    "refresh_token": self.refresh_token,
                }
            return self.access_token


class MusicControls(discord.ui.View):
    def __init__(self, player: "GuildPlayer") -> None:
        super().__init__(timeout=None)
        self.player = player

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        error = self.player.cog.control_error(interaction, self.player)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return False
        return True

    async def run(self, interaction: discord.Interaction, action: str) -> None:
        await interaction.response.defer(ephemeral=True)
        message = await self.player.apply_action(action)
        await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.run(interaction, "stop")

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.run(interaction, "previous")

    @discord.ui.button(emoji="⏪", style=discord.ButtonStyle.secondary, row=0)
    async def restart(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.run(interaction, "restart")

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.primary, row=0)
    async def pause(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.run(interaction, "pause")

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.success, row=0)
    async def resume(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.run(interaction, "resume")

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=1)
    async def skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.run(interaction, "skip")

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.run(interaction, "shuffle")


class GuildPlayer:
    def __init__(self, cog: "Music", guild: discord.Guild) -> None:
        self.cog = cog
        self.guild = guild
        self.voice: discord.VoiceClient | None = None
        self.text_channel: discord.TextChannel | discord.Thread | None = None
        self.queue: deque[Track] = deque()
        self.history: list[Track] = []
        self.current: Track | None = None
        self.message: discord.Message | None = None
        self.started_at = 0.0
        self.paused_at: float | None = None
        self.paused_total = 0.0
        self.lock = asyncio.Lock()
        self.idle_since: float | None = None
        self.empty_since: float | None = None
        self.closed = False
        self.monitor_task = asyncio.create_task(self.monitor())

    def elapsed(self) -> float:
        if not self.current:
            return 0
        end = self.paused_at if self.paused_at is not None else time.monotonic()
        return max(0, end - self.started_at - self.paused_total)

    async def add(self, tracks: list[Track], *, start: bool = True) -> None:
        async with self.lock:
            self.queue.extend(tracks)
            self.idle_since = None
            should_start = start and self.current is None
        if should_start:
            await self.play_next()
        else:
            await self.update_card()

    async def play_next(self) -> None:
        async with self.lock:
            if self.closed or not self.voice or not self.voice.is_connected():
                return
            if not self.queue:
                self.current = None
                self.idle_since = time.monotonic()
                await self.update_card()
                return
            track = self.queue.popleft()
            self.current = track
            self.started_at = time.monotonic()
            self.paused_at = None
            self.paused_total = 0

        try:
            source_url, resolved = await self.cog.resolve_audio(track)
            self.current = resolved
            source = discord.FFmpegPCMAudio(
                source_url,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options="-vn",
            )
            source = discord.PCMVolumeTransformer(source, volume=self.cog.volume)
            loop = asyncio.get_running_loop()

            def after(error: Exception | None) -> None:
                if error:
                    print(f"Music playback error in guild {self.guild.id}: {error}")
                loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self.finished_track())
                )

            assert self.voice is not None
            self.voice.play(source, after=after)
            await self.update_card()
        except Exception as exc:
            print(f"Could not play {track.title!r}: {exc}")
            if self.text_channel:
                await self.text_channel.send(
                    f"⚠️ I couldn't play **{track.title}**; skipping it."
                )
            await self.finished_track()

    async def finished_track(self) -> None:
        if self.closed:
            return
        if self.current:
            self.history.append(self.current)
            self.history = self.history[-50:]
        self.current = None
        await self.play_next()

    async def replay(self, track: Track, *, keep_current: bool) -> None:
        if keep_current and self.current:
            self.queue.appendleft(self.current)
        self.queue.appendleft(track)
        self.current = None
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            self.voice.stop()
        else:
            await self.play_next()

    async def apply_action(self, action: str) -> str:
        voice = self.voice
        if action == "pause":
            if not voice or not voice.is_playing():
                return "Nothing is currently playing."
            voice.pause()
            self.paused_at = time.monotonic()
            await self.update_card()
            return "Paused."
        if action == "resume":
            if not voice or not voice.is_paused():
                return "Nothing is paused."
            assert self.paused_at is not None
            self.paused_total += time.monotonic() - self.paused_at
            self.paused_at = None
            voice.resume()
            await self.update_card()
            return "Resumed."
        if action == "skip":
            if not voice or not (voice.is_playing() or voice.is_paused()):
                return "Nothing is currently playing."
            voice.stop()
            return "Skipped."
        if action == "stop":
            self.queue.clear()
            self.history.clear()
            self.current = None
            if voice and (voice.is_playing() or voice.is_paused()):
                voice.stop()
            else:
                self.idle_since = time.monotonic()
                await self.update_card()
            return "Stopped playback and cleared the queue."
        if action == "restart":
            if not self.current:
                return "Nothing is currently playing."
            await self.replay(self.current, keep_current=False)
            return "Restarted the current song."
        if action == "previous":
            if not self.history:
                return "There is no previous song."
            await self.replay(self.history.pop(), keep_current=True)
            return "Playing the previous song."
        if action == "shuffle":
            items = list(self.queue)
            random.shuffle(items)
            self.queue = deque(items)
            await self.update_card()
            return f"Shuffled {len(items)} queued song(s)."
        return "Unknown music action."

    def embed(self) -> discord.Embed:
        if self.current:
            track = self.current
            elapsed = min(self.elapsed(), track.duration or self.elapsed())
            title = "Now playing" if self.paused_at is None else "Paused"
            embed = discord.Embed(
                title=f"{'🎶' if self.paused_at is None else '⏸️'} {title}",
                description=(
                    f"**[{track.title}]({track.spotify_url or track.webpage_url})**\n"
                    f"{track.artists}\n\n"
                    f"`{format_time(elapsed)}` {progress_bar(elapsed, track.duration)} "
                    f"`{format_time(track.duration)}`"
                ),
                color=discord.Color.green(),
            )
            if track.artwork:
                embed.set_thumbnail(url=track.artwork)
            if track.requested_by:
                embed.set_footer(text=f"Requested by {track.requested_by} • {len(self.queue)} queued")
        else:
            embed = discord.Embed(
                title="🎵 Music player",
                description="The queue is empty. Use `/play` or `/queue` to add music.",
                color=discord.Color.blurple(),
            )
            embed.set_footer(text="I’ll leave after 15 minutes without music.")
        if self.queue:
            preview = list(self.queue)[:5]
            lines = [f"`{index}.` {item.title} — {item.artists}" for index, item in enumerate(preview, 1)]
            if len(self.queue) > 5:
                lines.append(f"…and {len(self.queue) - 5} more")
            embed.add_field(name="Up next", value="\n".join(lines), inline=False)
        return embed

    async def update_card(self) -> None:
        if not self.text_channel:
            return
        view = MusicControls(self)
        try:
            if self.message:
                await self.message.edit(embed=self.embed(), view=view)
            else:
                self.message = await self.text_channel.send(embed=self.embed(), view=view)
        except (discord.NotFound, discord.Forbidden):
            self.message = await self.text_channel.send(embed=self.embed(), view=view)

    async def monitor(self) -> None:
        while not self.closed:
            await asyncio.sleep(10)
            if not self.voice or not self.voice.is_connected():
                continue
            humans = [member for member in self.voice.channel.members if not member.bot]
            now = time.monotonic()
            self.empty_since = None if humans else (self.empty_since or now)
            if self.current:
                await self.update_card()
            idle_expired = self.idle_since is not None and now - self.idle_since >= 15 * 60
            empty_expired = self.empty_since is not None and now - self.empty_since >= 5 * 60
            if idle_expired or empty_expired:
                reason = "15 minutes of inactivity" if idle_expired else "the voice channel being empty"
                await self.disconnect(f"Left voice after {reason}.")

    async def disconnect(self, notice: str | None = None) -> None:
        self.closed = True
        self.queue.clear()
        if self.voice and self.voice.is_connected():
            await self.voice.disconnect(force=True)
        if notice and self.text_channel:
            await self.text_channel.send(f"👋 {notice}")
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass
        self.cog.players.pop(self.guild.id, None)
        current = asyncio.current_task()
        if self.monitor_task is not current:
            self.monitor_task.cancel()


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.players: dict[int, GuildPlayer] = {}
        channel_id = os.getenv("BOT_COMMANDS_CHANNEL_ID")
        self.commands_channel_id = int(channel_id) if channel_id else None
        self.volume = min(1.0, max(0.0, float(os.getenv("MUSIC_VOLUME", "0.5"))))
        self.spotify = None
        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        refresh_token = os.getenv("SPOTIFY_REFRESH_TOKEN")
        if client_id and client_secret and spotipy and SpotifyClientCredentials:
            auth_manager = (
                SpotifyRefreshTokenAuth(client_id, client_secret, refresh_token)
                if refresh_token
                else SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
            )
            self.spotify = spotipy.Spotify(auth_manager=auth_manager)
        self.ytdl_options = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "default_search": "ytsearch1",
            "source_address": "0.0.0.0",
        }

    async def cog_unload(self) -> None:
        for player in list(self.players.values()):
            await player.disconnect()

    def player_for(self, guild: discord.Guild) -> GuildPlayer:
        player = self.players.get(guild.id)
        if not player or player.closed:
            player = GuildPlayer(self, guild)
            self.players[guild.id] = player
        return player

    def control_error(self, interaction: discord.Interaction, player: GuildPlayer | None = None) -> str | None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return "Music commands can only be used in a server."
        player = player or self.players.get(interaction.guild.id)
        if not player or not player.voice or not player.voice.is_connected():
            return "I’m not in a voice channel. Use `/join` first."
        if not interaction.user.voice or interaction.user.voice.channel != player.voice.channel:
            return "You must be in my voice channel to control the music."
        return None

    async def require_control(self, interaction: discord.Interaction) -> GuildPlayer | None:
        player = self.players.get(interaction.guild_id or 0)
        error = self.control_error(interaction, player)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return None
        return player

    async def spotify_tracks(self, url: str, requester: str) -> list[Track]:
        match = SPOTIFY_URL.search(url)
        if not match:
            raise ValueError("Please provide a valid Spotify track or playlist link.")
        if not self.spotify:
            raise RuntimeError("Spotify support is not configured. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.")

        kind, spotify_id = match.groups()
        loop = asyncio.get_running_loop()
        if kind == "track":
            raw_tracks = [await loop.run_in_executor(None, self.spotify.track, spotify_id)]
        else:
            def load_playlist() -> list[dict]:
                result = self.spotify.playlist_items(spotify_id, additional_types=("track",))
                items: list[dict] = []
                while result:
                    items.extend(item["track"] for item in result["items"] if item.get("track"))
                    result = self.spotify.next(result) if result.get("next") else None
                return items
            raw_tracks = await loop.run_in_executor(None, load_playlist)

        return [
            Track(
                title=item["name"],
                artists=", ".join(artist["name"] for artist in item["artists"]),
                duration=item.get("duration_ms", 0) / 1000 or None,
                artwork=(item.get("album", {}).get("images") or [{}])[0].get("url"),
                spotify_url=item.get("external_urls", {}).get("spotify"),
                requested_by=requester,
            )
            for item in raw_tracks
            if not item.get("is_local")
        ]

    async def resolve_audio(self, track: Track) -> tuple[str, Track]:
        def extract() -> dict:
            with yt_dlp.YoutubeDL(self.ytdl_options) as ytdl:
                info = ytdl.extract_info(track.query, download=False)
                if "entries" in info:
                    info = next((entry for entry in info["entries"] if entry), None)
                if not info or not info.get("url"):
                    raise RuntimeError("No playable source found")
                return info
        info = await asyncio.get_running_loop().run_in_executor(None, extract)
        resolved = replace(
            track,
            duration=track.duration or info.get("duration"),
            artwork=track.artwork or info.get("thumbnail"),
            webpage_url=info.get("webpage_url"),
        )
        return info["url"], resolved

    @app_commands.command(name="join", description="Summon Little Guy to your voice channel.")
    @app_commands.guild_only()
    async def join(self, interaction: discord.Interaction) -> None:
        if self.commands_channel_id and interaction.channel_id != self.commands_channel_id:
            await interaction.response.send_message(
                f"Use this command in <#{self.commands_channel_id}>.", ephemeral=True
            )
            return
        member = interaction.user
        if not isinstance(member, discord.Member) or not member.voice or not member.voice.channel:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        player = self.player_for(interaction.guild)
        if player.voice and player.voice.is_connected():
            if player.voice.channel != member.voice.channel:
                await interaction.followup.send("I’m already active in another voice channel.", ephemeral=True)
                return
        else:
            try:
                player.voice = await member.voice.channel.connect(self_deaf=True)
            except RuntimeError as exc:
                await player.disconnect()
                missing_voice_library = "library needed" in str(exc).lower()
                message = (
                    "Voice support is missing from this deployment. Rebuild the bot "
                    "with the updated requirements and try again."
                    if missing_voice_library
                    else "I couldn't initialize voice playback. Check the bot logs and try again."
                )
                await interaction.followup.send(f"⚠️ {message}", ephemeral=True)
                return
            except (discord.ClientException, discord.ConnectionClosed, asyncio.TimeoutError):
                await player.disconnect()
                await interaction.followup.send(
                    "⚠️ I couldn't connect to that voice channel. Check my Connect and Speak permissions.",
                    ephemeral=True,
                )
                return
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.followup.send("Use this in a server text channel.", ephemeral=True)
            return
        player.text_channel = interaction.channel
        player.idle_since = time.monotonic()
        player.empty_since = None
        await player.update_card()
        await interaction.followup.send(f"Joined {member.voice.channel.mention}.", ephemeral=True)

    async def add_link(self, interaction: discord.Interaction, link: str, *, start: bool) -> None:
        player = await self.require_control(interaction)
        if not player:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            tracks = await self.spotify_tracks(link, interaction.user.display_name)
        except Exception as exc:
            status = getattr(exc, "http_status", None)
            is_playlist = bool((match := SPOTIFY_URL.search(link)) and match.group(1) == "playlist")
            if is_playlist and status in {401, 403}:
                message = (
                    "Spotify now requires user authorization for playlists. Configure "
                    "`SPOTIFY_REFRESH_TOKEN` from the Spotify account that owns or collaborates "
                    "on this playlist, then restart me."
                )
            else:
                message = "I couldn't read that Spotify link. Verify the link and try again."
                print(f"Spotify lookup failed: {exc}")
            await interaction.followup.send(f"⚠️ {message}", ephemeral=True)
            return
        if not tracks:
            await interaction.followup.send("That link did not contain any playable tracks.", ephemeral=True)
            return
        await player.add(tracks, start=start)
        verb = "Added" if start else "Queued"
        await interaction.followup.send(f"{verb} {len(tracks)} song(s).", ephemeral=True)

    @app_commands.command(name="play", description="Play a Spotify link, or resume paused music.")
    @app_commands.describe(link="A Spotify song or playlist link (omit to resume)")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, link: str | None = None) -> None:
        if link:
            await self.add_link(interaction, link, start=True)
            return
        await self.action_command(interaction, "resume")

    @app_commands.command(name="queue", description="Add a Spotify song or playlist to the queue.")
    @app_commands.describe(link="A Spotify song or playlist link")
    @app_commands.guild_only()
    async def queue_command(self, interaction: discord.Interaction, link: str) -> None:
        await self.add_link(interaction, link, start=True)

    async def action_command(self, interaction: discord.Interaction, action: str) -> None:
        player = await self.require_control(interaction)
        if not player:
            return
        await interaction.response.send_message(await player.apply_action(action), ephemeral=True)

    @app_commands.command(name="stop", description="Stop playback and clear the music queue.")
    async def stop(self, interaction: discord.Interaction) -> None:
        await self.action_command(interaction, "stop")

    @app_commands.command(name="previous", description="Play the previous song.")
    async def previous(self, interaction: discord.Interaction) -> None:
        await self.action_command(interaction, "previous")

    @app_commands.command(name="restart", description="Rewind the current song to its beginning.")
    async def restart(self, interaction: discord.Interaction) -> None:
        await self.action_command(interaction, "restart")

    @app_commands.command(name="pause", description="Pause the current song.")
    async def pause(self, interaction: discord.Interaction) -> None:
        await self.action_command(interaction, "pause")

    @app_commands.command(name="resume", description="Resume the paused song.")
    async def resume(self, interaction: discord.Interaction) -> None:
        await self.action_command(interaction, "resume")

    @app_commands.command(name="skip", description="Skip the current song.")
    async def skip(self, interaction: discord.Interaction) -> None:
        await self.action_command(interaction, "skip")

    @app_commands.command(name="shuffle", description="Shuffle the songs waiting in the queue.")
    async def shuffle(self, interaction: discord.Interaction) -> None:
        await self.action_command(interaction, "shuffle")

    @app_commands.command(name="leave", description="Disconnect Little Guy and clear the music queue.")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction) -> None:
        player = await self.require_control(interaction)
        if not player:
            return
        await interaction.response.send_message("Disconnected and cleared the queue.", ephemeral=True)
        await player.disconnect()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
