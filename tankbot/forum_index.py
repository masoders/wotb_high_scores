import logging
import discord

log = logging.getLogger(__name__)
from discord import ForumChannel
from discord.utils import get

from . import config, db
from .utils import title_case_type

TYPE_LABEL = {
    "light": "Light Tanks",
    "medium": "Medium Tanks",
    "heavy": "Heavy Tanks",
    "td": "Tank Destroyers",
}

async def _get_forum(bot: discord.Client) -> ForumChannel:
    ch = bot.get_channel(config.TANK_INDEX_FORUM_CHANNEL_ID)
    if ch is None:
        ch = await bot.fetch_channel(config.TANK_INDEX_FORUM_CHANNEL_ID)
    if not isinstance(ch, ForumChannel):
        raise TypeError("TANK_INDEX_FORUM_CHANNEL_ID must point to a Forum Channel")
    return ch

def _thread_title(tier: int, ttype: str) -> str:
    return f"Tier {tier} — {TYPE_LABEL.get(ttype, title_case_type(ttype))}"

def _find_tag(forum: ForumChannel, name: str):
    # Forum tags are ForumTag objects
    for t in forum.available_tags:
        if t.name == name:
            return t
    return None

async def ensure_tags(forum: ForumChannel, tier: int, ttype: str):
    # Create missing tags if possible (requires Manage Channels)
    desired = [f"Tier {tier}", title_case_type(ttype)]
    existing = {t.name for t in forum.available_tags}
    to_create = [d for d in desired if d not in existing]
    if not to_create:
        return
    # Create tags via edit (append)
    new_tags = list(forum.available_tags)
    for name in to_create:
        new_tags.append(discord.ForumTag(name=name, moderated=False))
    try:
        await forum.edit(available_tags=new_tags)
    except Exception as e:
        log.warning(f"Failed to create forum tags: {type(e).__name__}: {e}")

async def _render_bucket(tier: int, ttype: str) -> str:
    # Show best per tank in this bucket, sorted by score desc
    tanks = await db.list_tanks(tier=tier, ttype=ttype)
    lines = []
    lines.append(f"**Leaderboard — Tier {tier} / {title_case_type(ttype)}**")
    lines.append("")
    if not tanks:
        lines.append("_No tanks registered in this bucket._")
        return "\n".join(lines)

    rows = []
    for name, _, _ in tanks:
        best = await db.get_best_for_tank(name)
        if best:
            sid, player, score, created = best
            rows.append((score, sid, player, name, created))
        else:
            rows.append((None, None, None, name, None))

    # Sort: scored first (desc), then by name
    scored = [r for r in rows if r[0] is not None]
    unscored = [r for r in rows if r[0] is None]
    scored.sort(key=lambda x: (-x[0], x[1]))
    unscored.sort(key=lambda x: x[3].lower())

    # Highlight latest top: we define "top result" as first line in scored list
    if scored:
        top = scored[0]
        lines.append(f"🏆 **TOP:** **{top[0]}** — **{top[2]}** ({top[3]}) • #{top[1]} • {top[4]}Z")
        lines.append("")

    lines.append("**Records by tank**")
    for r in scored:
        score, sid, player, tank, created = r
        lines.append(f"- **{tank}**: **{score}** — {player} • #{sid} • {created}Z")
    for r in unscored:
        _, _, _, tank, _ = r
        lines.append(f"- **{tank}**: _no submissions_")

    return "\n".join(lines)


async def upsert_bucket_thread(bot: discord.Client, tier: int, ttype: str):
    forum = await _get_forum(bot)
    await ensure_tags(forum, tier, ttype)

    # resolve existing mapping
    mapping = await _get_mapping(tier, ttype)
    title = _thread_title(tier, ttype)
    content = await _render_bucket(tier, ttype)

    tag_tier = _find_tag(forum, f"Tier {tier}")
    tag_type = _find_tag(forum, title_case_type(ttype))
    tags = [t for t in [tag_tier, tag_type] if t is not None]

    if mapping is None:
        thread = await forum.create_thread(name=title, content=content, applied_tags=tags)
        await _set_mapping(tier, ttype, thread.thread.id, forum.id)
        # Pin starter message if possible
        try:
            starter = thread.message
            if starter:
                await starter.pin()
        except Exception as e:
            log.warning(f"Forum operation failed: {type(e).__name__}: {e}")
        # Lock thread (read-only)
        try:
            await thread.thread.edit(locked=True)
        except Exception as e:
            log.warning(f"Forum operation failed: {type(e).__name__}: {e}")
        return

    thread_id = mapping[0]
    thread = forum.get_thread(thread_id)
    if thread is None:
        try:
            thread = await forum.fetch_thread(thread_id)
        except Exception:
            thread = None

    if thread is None:
        # mapping stale -> recreate
        thread = await forum.create_thread(name=title, content=content, applied_tags=tags)
        await _set_mapping(tier, ttype, thread.thread.id, forum.id)
        try:
            if thread.message:
                await thread.message.pin()
        except Exception as e:
            log.warning(f"Forum operation failed: {type(e).__name__}: {e}")
        try:
            await thread.thread.edit(locked=True)
        except Exception as e:
            log.warning(f"Forum operation failed: {type(e).__name__}: {e}")
        return

    # Update title + starter content
    try:
        await thread.edit(name=title, applied_tags=tags)
    except Exception:
        pass

    try:
        # Fetch starter message and edit it
        starter = thread.starter_message
        if starter is None:
            starter = await thread.fetch_message(thread.id)
        await starter.edit(content=content)
        try:
            await starter.pin()
        except Exception as e:
            log.warning(f"Forum operation failed: {type(e).__name__}: {e}")
    except Exception:
        pass

    try:
        await thread.edit(locked=True)
    except Exception:
        pass


async def targeted_update(bot: discord.Client, tier: int, ttype: str):
    await upsert_bucket_thread(bot, tier, ttype)


async def rebuild_all(bot: discord.Client):
    # For each tier 1..10 and each type used by tanks, upsert.
    tanks = await db.list_tanks()
    types = sorted({t[2] for t in tanks})
    tiers = sorted({int(t[1]) for t in tanks})
    for ttype in types:
        for tier in tiers:
            await upsert_bucket_thread(bot, tier, ttype)

async def rebuild_missing(bot: discord.Client):
    # Only ensure mappings exist for current tiers/types. If missing mapping, create.
    tanks = await db.list_tanks()
    types = sorted({t[2] for t in tanks})
    tiers = sorted({int(t[1]) for t in tanks})
    for ttype in types:
        for tier in tiers:
            if await _get_mapping(tier, ttype) is None:
                await upsert_bucket_thread(bot, tier, ttype)

# ---- mapping helpers in DB ----
async def _get_mapping(tier: int, ttype: str):
    import aiosqlite
    async with aiosqlite.connect(config.DB_PATH) as con:
        cur = await con.execute(
            "SELECT thread_id FROM tank_index_posts WHERE tier = ? AND type = ?",
            (tier, ttype),
        )
        row = await cur.fetchone()
        return row

async def _set_mapping(tier: int, ttype: str, thread_id: int, forum_id: int):
    import aiosqlite
    async with aiosqlite.connect(config.DB_PATH) as con:
        await con.execute(
            "INSERT OR REPLACE INTO tank_index_posts (tier, type, thread_id, forum_channel_id) VALUES (?,?,?,?)",
            (tier, ttype, thread_id, forum_id),
        )
        await con.commit()
