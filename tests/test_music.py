import io
from unittest.mock import patch

from cogs.music import (
    MusicControls,
    SpotifyRefreshTokenAuth,
    Track,
    format_time,
    progress_bar,
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
