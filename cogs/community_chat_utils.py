import random
import re
import sqlite3
from datetime import date, datetime
from datetime import time


EXECUTION_REQUEST = re.compile(
    r"\b(?:please\s+|(?:can|could|would|will)\s+you\s+(?:please\s+)?)"
    r"(?:actually\s+)?(?:run|execut\w*|launch|deploy|compile|eval(?:uate)?|install)\b"
    r"|\b(?:run|execut\w*|launch|deploy|compile|eval(?:uate)?|install)\b"
    r".{0,30}\b(?:this|that|my|the attached|the following)\b"
    r".{0,30}\b(?:code|script|command|program)\b",
    re.IGNORECASE | re.DOTALL,
)

SILENCE_REQUEST = re.compile(
    r"\b(?:shut\s+up|stop\s+(?:talking|speaking|replying|responding)|"
    r"be\s+quiet|go\s+away|leave\s+me\s+alone|nobody\s+asked|"
    r"bad\s+bot|you\s+suck|i\s+hate\s+(?:you|this)|"
    r"you(?:'re|\s+are)\s+(?:stupid|dumb|useless|annoying|awful|terrible)|"
    r"(?:(?:that|this|your)\s+(?:answer|response)|that|this)\s+(?:is|was)\s+"
    r"(?:stupid|dumb|useless|annoying|awful|terrible|bad|wrong)|"
    r"(?:that|this)\s+(?:didn'?t|doesn'?t)\s+help|"
    r"(?:not|wasn'?t|isn'?t)\s+(?:useful|helpful))\b",
    re.IGNORECASE,
)

GREETER_MESSAGE = re.compile(
    r"^Hey\s+<@!?(\d+)>!\s+We\s+are\s+so\s+glad\s+you\s+joined\s+"
    r"\*\*Guild\.AI\*\*!$",
    re.IGNORECASE,
)

WEB_SEARCH_REQUEST = re.compile(
    r"\b(?:search(?:\s+the)?\s+web|look\s+it\s+up|look\s+up|google|"
    r"browse|find\s+(?:online|on\s+the\s+web)|latest|current(?:ly)?|"
    r"today|recent(?:ly)?|news|verify|fact[- ]check|source(?:s)?)\b",
    re.IGNORECASE,
)

BLOCKED_SEARCH_TOPIC = re.compile(
    r"\b(?:nsfw|porn(?:ography|ographic)?|explicit\s+sexual|sexual\s+content|"
    r"nudes?|erotic(?:a)?|fetish|adult\s+content|"
    r"politics?|political|elections?|campaign(?:ing)?|partisan|"
    r"democrats?|republicans?|congress|senate|parliament|geopolitics?|"
    r"state\s+of\s+the\s+world|world\s+affairs|global\s+affairs|"
    r"international\s+conflicts?|culture\s+wars?)\b",
    re.IGNORECASE,
)


def requests_code_execution(text: str) -> bool:
    return bool(EXECUTION_REQUEST.search(text))


def requests_silence(text: str) -> bool:
    return bool(SILENCE_REQUEST.search(text))


def should_use_discord_reply(text: str) -> bool:
    return "?" in text


def requires_web_search(text: str) -> bool:
    return bool(WEB_SEARCH_REQUEST.search(text))


def is_blocked_search_topic(text: str) -> bool:
    return bool(BLOCKED_SEARCH_TOPIC.search(text))


def greeter_member_id(text: str) -> int | None:
    match = GREETER_MESSAGE.fullmatch(text.strip())
    return int(match.group(1)) if match else None


def sentence_count(text: str) -> int:
    chunks = [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]
    return len(chunks)


def random_allowed_time(rng: random.Random | None = None) -> time:
    # 04:00 through 22:59 America/New_York; 23:00 through 03:59 is excluded.
    source = rng or random.SystemRandom()
    minute = source.randrange(4 * 60, 23 * 60)
    return time(hour=minute // 60, minute=minute % 60)


def prompt_sent_on(
    database: sqlite3.Connection,
    guild_id: int,
    local_day: date,
) -> bool:
    row = database.execute(
        "SELECT 1 FROM discussion_runs WHERE guild_id = ? AND local_date = ?",
        (guild_id, local_day.isoformat()),
    ).fetchone()
    return row is not None


def record_prompt_send(
    database: sqlite3.Connection,
    guild_id: int,
    local_day: date,
    source: str,
    sent_at: datetime,
):
    database.execute(
        "INSERT INTO discussion_runs (guild_id, local_date, source, sent_at) "
        "VALUES (?, ?, ?, ?)",
        (guild_id, local_day.isoformat(), source, sent_at.isoformat()),
    )
    database.commit()
