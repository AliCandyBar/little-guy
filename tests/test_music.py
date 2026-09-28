import io
from unittest.mock import patch

from cogs.music import (
    MusicControls,
    SpotifyRefreshTokenAuth,
    Track,
    format_time,
    is_youtube_url,
    music_join_allowed,
    progress_bar,
    youtube_info_to_tracks,
)


def test_format_time_handles_minutes_hours_and_unknown():
    assert format_time(65) == "1:05"
    assert format_time(3661) == "1:01:01"
    assert format_time(None) == "--:--"


def test_progress_bar_has_fixed_width_and_tracks_position():
    start = progress_bar(0, 100)
    middle = progress_bar(50, 100)
    end = progress_bar(100, 100)

    assert len(start) == len(middle) == len(end) == 16
    assert start.startswith("🔘")
    assert middle.count("🔘") == 1
    assert end.endswith("🔘")


def test_track_query_uses_title_artist_unless_overridden():
    track = Track(title="Song", artists="Artist", duration=120)
    assert track.query == "Song Artist audio"
    custom = Track(title="Song", artists="Artist", duration=120, search_query="custom")
    assert custom.query == "custom"


def test_music_controls_fit_discords_five_button_row_limit():
    controls = MusicControls(object())

    assert [item.row for item in controls.children] == [0, 0, 0, 0, 0, 1, 1]


def test_spotify_user_token_is_refreshed_and_cached():
    response = io.BytesIO(b'{"access_token":"new-token","expires_in":3600}')
    response.__enter__ = lambda value: value
    response.__exit__ = lambda *args: None
    auth = SpotifyRefreshTokenAuth("client", "secret", "refresh")

    with patch("urllib.request.urlopen", return_value=response) as request:
        assert auth.get_access_token() == "new-token"
        assert auth.get_access_token() == "new-token"

    assert request.call_count == 1


def test_youtube_url_validation_accepts_supported_video_and_playlist_hosts():
    assert is_youtube_url("https://www.youtube.com/watch?v=abc123")
    assert is_youtube_url("https://youtube.com/playlist?list=PL123")
    assert is_youtube_url("https://music.youtube.com/playlist?list=PL123")
    assert is_youtube_url("https://youtu.be/abc123")


def test_youtube_url_validation_rejects_lookalike_and_non_http_urls():
    assert not is_youtube_url("https://youtube.com.example.org/watch?v=abc123")
    assert not is_youtube_url("ftp://youtube.com/playlist?list=PL123")
    assert not is_youtube_url("not a URL")


def test_development_guild_can_join_from_any_channel():
    assert music_join_allowed(100, 200, 200, 999)


def test_non_development_guild_still_requires_commands_channel():
    assert music_join_allowed(100, 200, 300, 100)
    assert not music_join_allowed(100, 200, 300, 999)


def test_youtube_playlist_preserves_order_and_skips_private_videos():
    playlist = {
        "entries": [
            {
                "id": "first",
                "title": "First song",
                "channel": "Channel One",
                "duration": 120,
                "url": "https://www.youtube.com/watch?v=first",
            },
            {"id": "private", "title": "[Private video]"},
            {
                "id": "second",
                "title": "Second song",
                "uploader": "Channel Two",
                "duration": 180,
                "url": "second",
            },
        ]
    }

    tracks = youtube_info_to_tracks(playlist, "Requester", 100)

    assert [track.title for track in tracks] == ["First song", "Second song"]
    assert [track.artists for track in tracks] == ["Channel One", "Channel Two"]
    assert tracks[1].query == "https://www.youtube.com/watch?v=second"
