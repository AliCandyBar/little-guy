from datetime import datetime, timezone
import pytest
from cogs.hackathon import HackathonStore, channel_name, parse_time_range, valid_team_name


def test_ids_are_isolated_by_server(tmp_path):
    store = HackathonStore(str(tmp_path / "h.db"))
    start, end = parse_time_range("2027-01-01 09:00 to 2027-01-02 17:00")
    assert store.create(1, 9, "A", "D", "P", start, end) == 1
    assert store.create(1, 9, "B", "D", "P", start, end) == 2
    assert store.create(2, 9, "Test", "D", "P", start, end) == 1
    assert store.get(3, 1) is None


def test_main_and_test_can_use_separate_database_files(tmp_path):
    main = HackathonStore(str(tmp_path / "main.db"))
    test = HackathonStore(str(tmp_path / "test.db"))
    start, end = parse_time_range("2027-01-01 09:00 to 2027-01-02 17:00")
    main.create(1, 9, "Production", "D", "P", start, end)
    test.create(2, 9, "Test", "D", "P", start, end)

    assert main.get(1, 1).name == "Production"
    assert main.get(2, 1) is None
    assert test.get(2, 1).name == "Test"
    assert test.get(1, 1) is None


def test_time_is_pacific_and_converted_to_utc():
    start, end = parse_time_range("2027-01-01 09:00 to 2027-01-01 17:00")
    assert start == datetime(2027, 1, 1, 17, tzinfo=timezone.utc)
    assert end == datetime(2027, 1, 2, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", ["bad", "2027-01-02 10:00 to 2027-01-01 10:00"])
def test_invalid_times(value):
    with pytest.raises(ValueError):
        parse_time_range(value)


def test_team_names_and_channel_slug():
    assert valid_team_name("Team 42_alpha-beta")
    assert not valid_team_name("**Team**")
    assert not valid_team_name("Winners 🏆")
    assert channel_name("My Fancy Hackathon!", 3) == "my-fancy-hackathon"


def test_only_owner_deletes_team(tmp_path):
    store = HackathonStore(str(tmp_path / "h.db"))
    start, end = parse_time_range("2027-01-01 09:00 to 2027-01-02 17:00")
    store.create(1, 9, "A", "D", "P", start, end)
    store.create_team(1, 1, "Alpha", 10)
    assert not store.delete_team(1, 1, "Alpha", 11)
    assert store.delete_team(1, 1, "Alpha", 10)


def test_uploaded_image_is_stored_with_hackathon(tmp_path):
    store = HackathonStore(str(tmp_path / "h.db"))
    start, end = parse_time_range("2027-01-01 09:00 to 2027-01-02 17:00")
    store.create(1, 9, "A", "D", "P", start, end, "banner.png", b"image-bytes")
    item = store.get(1, 1)
    assert item.image_name == "banner.png"
    assert item.image_data == b"image-bytes"
