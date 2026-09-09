import re


SENSITIVE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bglda_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{25,}\b"),
    re.compile(
        r"\b(?:api[_ -]?key|password|secret|token)\s*[:=]\s*"
        r"(?!(?:YOUR|REPLACE|EXAMPLE|PLACEHOLDER)[_-])\S{8,}",
        re.IGNORECASE,
    ),
)


def contains_sensitive_data(text: str) -> bool:
    return any(pattern.search(text) for pattern in SENSITIVE_PATTERNS)


def sanitize_project_name(name: str) -> str:
    safe_name = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return safe_name[:80] or "custom-guild-agent"


def normalize_agent_ts(code: str) -> str:
    normalized = code.strip()
    fenced = re.fullmatch(
        r"```(?:typescript|ts)?\s*\n(?P<code>.*)\n```",
        normalized,
        re.DOTALL | re.IGNORECASE,
    )
    if fenced:
        normalized = fenced.group("code").strip()

    if "export default" not in normalized:
        raise ValueError("Generated agent.ts has no default export.")
    if "@guildai/agents-sdk" not in normalized:
        raise ValueError("Generated agent.ts does not use the Guild SDK.")
    return normalized


def take_discord_chunk(
    text: str,
    max_utf16_units: int,
) -> tuple[str, str]:
    """Split text using Discord's UTF-16 message length accounting."""
    units = 0
    split_at = 0

    for index, character in enumerate(text):
        character_units = 2 if ord(character) > 0xFFFF else 1
        if units + character_units > max_utf16_units:
            break
        units += character_units
        split_at = index + 1

    if split_at == len(text):
        return text, ""

    newline_at = text.rfind("\n", 0, split_at)
    if newline_at >= min(500, split_at // 2):
        split_at = newline_at

    remainder = text[split_at:]
    if remainder.startswith("\n"):
        remainder = remainder[1:]
    return text[:split_at], remainder
