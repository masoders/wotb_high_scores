import discord
from discord import app_commands

from .. import config, db, utils, forum_index

class Highscore(app_commands.Group):
    def __init__(self):
        super().__init__(name="highscore", description="Highscore commands")

def register(tree: app_commands.CommandTree, bot: discord.Client, guild: discord.Object | None):
    grp = Highscore()
    tree.add_command(grp, guild=guild)

    @grp.command(name="submit", description="Submit a new highscore (commanders only)")
    @app_commands.describe(player="Player name", tank="Tank name", score="Score (1..100000)")
    async def submit(interaction: discord.Interaction, player: str, tank: str, score: int):
        member = interaction.user
        if not isinstance(member, discord.Member) or not utils.has_commander_role(member):
            await interaction.response.send_message("Nope. Only **Clan Commanders** can submit.", ephemeral=True)
            return
        tank = utils.validate_text('Tank', tank, 64)
        if not (1 <= score <= config.MAX_SCORE):
            await interaction.response.send_message(f"Score must be between 1 and {config.MAX_SCORE}.", ephemeral=True)
            return
        t = await db.get_tank(tank)
        if not t:
            await interaction.response.send_message("Unknown tank. Use an existing tank from the roster.", ephemeral=True)
            return

        player_raw = utils.validate_text('Player', player, 64)
        player_norm = utils.normalize_player(player_raw)# Store submission
await db.insert_submission(player_raw, player_norm, tank, score, interaction.user.display_name, utils.utc_now_z())

# Update bucket thread (tier/type)
_, tier, ttype = t
await forum_index.targeted_update(bot, int(tier), str(ttype))

# Announce if this is a NEW tank record
best = await db.get_best_for_tank(tank)
# best will be this submission if it's highest; but due to query ordering, it should be.
if best and best[1] == player_raw and best[2] == score:
    ch = interaction.client.get_channel(config.ANNOUNCE_CHANNEL_ID)
    if ch is None:
        try:
            ch = await interaction.client.fetch_channel(config.ANNOUNCE_CHANNEL_ID)
        except Exception:
            ch = None
    if ch is not None:
        await ch.send(f"🏆 **NEW TANK RECORD** — **{score}** by **{player_raw}** on **{tank}** (Tier {tier}, {utils.title_case_type(ttype)})")

await interaction.response.send_message("✅ Submission stored.", ephemeral=True)

    @grp.command(name="show", description="Show current champion (filters optional)")
@app_commands.describe(tier="Filter by tier (1..10)", type="Filter by type (light/medium/heavy/td)")
async def show(interaction: discord.Interaction, tier: int | None = None, type: str | None = None):
    if tier is not None and not (1 <= tier <= 10):
        await interaction.response.send_message("Tier must be 1..10.", ephemeral=True)
        return
    if type is not None:
        type = type.strip().lower()
        if type not in ("light","medium","heavy","td"):
            await interaction.response.send_message("Type must be one of: light, medium, heavy, td.", ephemeral=True)
            return

    champ = await db.get_champion_filtered(tier=tier, ttype=type)
    if not champ:
        await interaction.response.send_message("No submissions found for that filter.", ephemeral=True)
        return

    cid, player, tank, score, submitted_by, created, ctier, ctype = champ
    label = "Global champion" if tier is None and type is None else "Champion"
    await interaction.response.send_message(
        f"🏆 **{label}**
**{score}** — **{player}** ({tank}) • Tier {ctier} {utils.title_case_type(ctype)} • #{cid} • {created}Z",
        ephemeral=True
    )
            return
        cid, player, tank, score, submitted_by, created, ctier, ctype = champ
        await interaction.response.send_message(
            f"🏆 **Global champion**\n**{score}** — **{player}** ({tank}) • #{cid} • {created}Z",
            ephemeral=True
        )

    @grp.command(name="qualify", description="Check if a score would qualify as a new tank record (no submission)")
    @app_commands.describe(player="Player name (optional)", tank="Tank name", score="Score to compare")
    async def qualify(interaction: discord.Interaction, tank: str, score: int, player: str | None = None):
        tank = utils.validate_text('Tank', tank, 64)
        if not (1 <= score <= config.MAX_SCORE):
            await interaction.response.send_message(f"Score must be between 1 and {config.MAX_SCORE}.", ephemeral=True)
            return
        t = await db.get_tank(tank)
        if not t:
            await interaction.response.send_message("Unknown tank. Pick an existing tank from the roster.", ephemeral=True)
            return

        if player is None or not player.strip():
            player = interaction.user.display_name
        player = utils.validate_text('Player', player, 64)

        tier, ttype = t[1], t[2]
        best = await db.get_best_for_tank(tank)
        champ = await db.get_champion()

        lines = []
        lines.append("**Qualification check**")
        lines.append(f"- Player: **{player}**")
        lines.append(f"- Tank: **{tank}** (Tier **{tier}**, **{utils.title_case_type(ttype)}**)")
        lines.append(f"- Your score: **{score}**")

        if best is None:
            lines.append("✅ No record exists for this tank. You would become **#1** if submitted.")
        else:
            bid, bplayer, bscore, bcreated = best
            if score > bscore:
                lines.append(f"✅ Current record: **{bscore}** by **{bplayer}** (#{bid}, {bcreated}Z).")
                lines.append(f"✅ You would be **NEW #1** by **+{score-bscore}**.")
            else:
                lines.append(f"❌ Current record: **{bscore}** by **{bplayer}** (#{bid}, {bcreated}Z).")
                if score == bscore:
                    lines.append("❌ Ties do not qualify (earlier wins). You need **+1**.")
                else:
                    lines.append(f"❌ Short by **{bscore-score}**.")

        if champ:
            _, cplayer, ctank, cscore, *_ = champ
            if score > cscore:
                lines.append("")
                lines.append(f"🏆 Would also beat global champion (**{cscore}**, {ctank} by {cplayer}).")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @grp.command(name="history", description="Show recent submissions (grouped) + stats")
    @app_commands.describe(limit="How many recent entries (1-25)")
    async def history(interaction: discord.Interaction, limit: int = 10):
        limit = max(1, min(limit, 25))
        rows = await db.get_recent(limit)
        if not rows:
            await interaction.response.send_message("No submissions yet.", ephemeral=True)
            return

        champ = await db.get_champion()
        champ_id = champ[0] if champ else None

        grouped: dict[str, dict[int, list[tuple]]] = {}
        for r in rows:
            _id, player, tank_name, score, submitted_by, created_at, tier, ttype = r
            grouped.setdefault(ttype, {}).setdefault(int(tier), []).append(r)

        type_order = ["heavy", "medium", "light", "td"]
        types_sorted = [t for t in type_order if t in grouped] + [t for t in grouped.keys() if t not in type_order]

        lines: list[str] = []
        for ttype in types_sorted:
            lines.append(f"## {utils.title_case_type(ttype)}")
            for tier in sorted(grouped[ttype].keys(), reverse=True):
                lines.append(f"**Tier {tier}**")
                for (_id, player, tank_name, score, submitted_by, created_at, _tier, _ttype) in grouped[ttype][tier]:
                    badge = "🏆 **TOP** " if champ_id is not None and _id == champ_id else ""
                    lines.append(f"{badge}**#{_id}** — **{score}** — **{player}** ({tank_name}) • {created_at}Z")
                lines.append("")

        tops_tanks = await db.top_holders_by_tank(limit=5)
        tops_buckets = await db.top_holders_by_tier_type(limit=5)

        lines.append("---")
        lines.append("### 📊 Stats (current #1 holders)")
        lines.append("**Most #1 tanks:**")
        for i, (p, cnt) in enumerate(tops_tanks, start=1):
            lines.append(f"{i}. **{p}** — {cnt} tank tops")
        lines.append("")
        lines.append("**Most #1 Tier×Type buckets:**")
        for i, (p, cnt) in enumerate(tops_buckets, start=1):
            lines.append(f"{i}. **{p}** — {cnt} bucket tops")

        msg = "\n".join(lines).strip()
        if len(msg) > 1800:
            msg = msg[:1800] + "\n…(truncated)"
        await interaction.response.send_message(msg, ephemeral=True)
