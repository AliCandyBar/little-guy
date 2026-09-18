from cogs.music import Track, format_time, progress_bar


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
