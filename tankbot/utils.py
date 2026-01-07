import datetime as dt
import discord
from . import config

def title_case_type(t: str) -> str:
    return {
        "light": "Light",
        "medium": "Medium",
        "heavy": "Heavy",
        "td": "Tank Destroyer",
    }.get(t.lower(), t)

def has_commander_role(member: discord.Member) -> bool:
    return any(r.name == config.COMMANDER_ROLE_NAME for r in member.roles)

def can_manage(member: discord.Member) -> bool:
    return member.guild_permissions.manage_guild or member.guild_permissions.administrator

def normalize_player(name: str) -> str:
    return name.strip().lower()

def utc_now_z() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def validate_text(label: str, value: str, max_len: int = 64) -> str:
    v = (value or "").strip()
    if not v:
        raise ValueError(f"{label} is required.")
    if len(v) > max_len:
        raise ValueError(f"{label} is too long (max {max_len} chars).")
    # Disallow newlines and control characters
    for ch in v:
        if ch in ("\n", "\r", "\t"):
            raise ValueError(f"{label} must be a single line.")
        if ord(ch) < 32:
            raise ValueError(f"{label} contains invalid control characters.")
    return v
