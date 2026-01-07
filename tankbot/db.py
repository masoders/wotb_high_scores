import aiosqlite
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tanks (
    name TEXT PRIMARY KEY,
    tier INTEGER NOT NULL,
    type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_name_raw TEXT NOT NULL,
    player_name_norm TEXT NOT NULL,
    tank_name TEXT NOT NULL,
    score INTEGER NOT NULL,
    submitted_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tank_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    details TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tank_index_posts (
    tier INTEGER NOT NULL,
    type TEXT NOT NULL,
    thread_id INTEGER NOT NULL,
    forum_channel_id INTEGER NOT NULL,
    PRIMARY KEY (tier, type)
);
"""

async def init_db():
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()

async def get_tank(name: str):
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute("SELECT name, tier, type FROM tanks WHERE name = ?", (name,))
        return await cur.fetchone()

async def list_tanks(tier: int | None = None, ttype: str | None = None):
    q = "SELECT name, tier, type FROM tanks"
    args = []
    wh = []
    if tier is not None:
        wh.append("tier = ?")
        args.append(tier)
    if ttype is not None:
        wh.append("type = ?")
        args.append(ttype)
    if wh:
        q += " WHERE " + " AND ".join(wh)
    q += " ORDER BY tier DESC, type, name"
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute(q, tuple(args))
        return await cur.fetchall()

async def insert_submission(player_raw: str, player_norm: str, tank_name: str, score: int, submitted_by: str, created_at: str):
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "INSERT INTO submissions (player_name_raw, player_name_norm, tank_name, score, submitted_by, created_at) VALUES (?,?,?,?,?,?)",
            (player_raw, player_norm, tank_name, score, submitted_by, created_at),
        )
        await db.commit()

async def get_best_for_tank(tank_name: str):
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute("""
        SELECT id, player_name_raw, score, created_at
        FROM submissions
        WHERE tank_name = ?
        ORDER BY score DESC, id ASC
        LIMIT 1;
        """, (tank_name,))
        return await cur.fetchone()

async def get_champion():
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute("""
        SELECT s.id, s.player_name_raw, s.tank_name, s.score,
               s.submitted_by, s.created_at, t.tier, t.type
        FROM submissions s
        JOIN tanks t ON t.name = s.tank_name
        ORDER BY s.score DESC, s.id ASC
        LIMIT 1;
        """)
        return await cur.fetchone()

async def get_recent(limit: int):
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute("""
        SELECT s.id, s.player_name_raw, s.tank_name, s.score,
               s.submitted_by, s.created_at, t.tier, t.type
        FROM submissions s
        JOIN tanks t ON t.name = s.tank_name
        ORDER BY s.id DESC
        LIMIT ?;
        """, (limit,))
        return await cur.fetchall()

async def top_holders_by_tank(limit: int = 10):
    limit = max(1, min(limit, 25))
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute("""
        WITH ranked AS (
            SELECT
                s.player_name_raw,
                s.player_name_norm,
                s.tank_name,
                s.score,
                s.id,
                ROW_NUMBER() OVER (
                    PARTITION BY s.tank_name
                    ORDER BY s.score DESC, s.id ASC
                ) AS rn
            FROM submissions s
        )
        SELECT player_name_raw, COUNT(*) AS tops
        FROM ranked
        WHERE rn = 1
        GROUP BY player_name_norm
        ORDER BY tops DESC, MIN(id) ASC
        LIMIT ?;
        """, (limit,))
        return await cur.fetchall()

async def top_holders_by_tier_type(limit: int = 10):
    limit = max(1, min(limit, 25))
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute("""
        WITH ranked AS (
            SELECT
                s.player_name_raw,
                s.player_name_norm,
                t.tier,
                t.type,
                s.score,
                s.id,
                ROW_NUMBER() OVER (
                    PARTITION BY t.tier, t.type
                    ORDER BY s.score DESC, s.id ASC
                ) AS rn
            FROM submissions s
            JOIN tanks t ON t.name = s.tank_name
        )
        SELECT player_name_raw, COUNT(*) AS tops
        FROM ranked
        WHERE rn = 1
        GROUP BY player_name_norm
        ORDER BY tops DESC, MIN(id) ASC
        LIMIT ?;
        """, (limit,))
        return await cur.fetchall()

async def counts():
    async with aiosqlite.connect(config.DB_PATH) as db:
        c1 = await (await db.execute("SELECT COUNT(*) FROM tanks")).fetchone()
        c2 = await (await db.execute("SELECT COUNT(*) FROM submissions")).fetchone()
        c3 = await (await db.execute("SELECT COUNT(*) FROM tank_index_posts")).fetchone()
        return int(c1[0]), int(c2[0]), int(c3[0])

async def log_tank_change(action: str, details: str, actor: str, created_at: str):
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "INSERT INTO tank_changes (action, details, actor, created_at) VALUES (?,?,?,?)",
            (action, details, actor, created_at),
        )
        await db.commit()

async def add_tank(name: str, tier: int, ttype: str, actor: str, created_at: str):
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "INSERT INTO tanks (name, tier, type, created_at) VALUES (?,?,?,?)",
            (name, tier, ttype, created_at),
        )
        await db.commit()
    await log_tank_change("add", f"{name}|tier={tier}|type={ttype}", actor, created_at)

async def edit_tank(name: str, tier: int, ttype: str, actor: str, created_at: str):
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "UPDATE tanks SET tier = ?, type = ? WHERE name = ?",
            (tier, ttype, name),
        )
        await db.commit()
    await log_tank_change("edit", f"{name}|tier={tier}|type={ttype}", actor, created_at)

async def tank_has_submissions(name: str) -> bool:
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM submissions WHERE tank_name = ? LIMIT 1", (name,))
        return (await cur.fetchone()) is not None

async def remove_tank(name: str, actor: str, created_at: str):
    if await tank_has_submissions(name):
        raise ValueError("Tank has submissions and cannot be removed.")
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM tanks WHERE name = ?", (name,))
        await db.commit()
    await log_tank_change("remove", f"{name}", actor, created_at)

async def tank_changes(limit: int = 25):
    limit = max(1, min(limit, 50))
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, action, details, actor, created_at FROM tank_changes ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return await cur.fetchall()

async def get_champion_filtered(tier: int | None = None, ttype: str | None = None):
    # If no filters, return global champion (same as get_champion)
    q = """
    SELECT s.id, s.player_name_raw, s.tank_name, s.score,
           s.submitted_by, s.created_at, t.tier, t.type
    FROM submissions s
    JOIN tanks t ON t.name = s.tank_name
    """
    args = []
    wh = []
    if tier is not None:
        wh.append("t.tier = ?")
        args.append(tier)
    if ttype is not None:
        wh.append("t.type = ?")
        args.append(ttype)
    if wh:
        q += " WHERE " + " AND ".join(wh)
    q += " ORDER BY s.score DESC, s.id ASC LIMIT 1;"
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute(q, tuple(args))
        return await cur.fetchone()
