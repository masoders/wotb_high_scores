import io
import csv
import discord
from discord import app_commands

from .. import config, db, forum_index, utils

class Tank(app_commands.Group):
    def __init__(self):
        super().__init__(name="tank", description="Tank roster admin commands (admins only)")

def _require_admin(interaction: discord.Interaction) -> bool:
    m = interaction.user
    return isinstance(m, discord.Member) and utils.can_manage(m)

def register(tree: app_commands.CommandTree, bot: discord.Client, guild: discord.Object | None):
    grp = Tank()
    tree.add_command(grp, guild=guild)

    @grp.command(name="add", description="Add a tank (admins only)")
    async def add(interaction: discord.Interaction, name: str, tier: int, type: str):
        if not _require_admin(interaction):
            await interaction.response.send_message("Nope. You need **Manage Server**.", ephemeral=True)
            return
        name = utils.validate_text('Tank name', name, 64)
        type = type.strip().lower()
        if not (1 <= tier <= 10):
            await interaction.response.send_message("Tier must be 1..10.", ephemeral=True)
            return
        if type not in ("light", "medium", "heavy", "td"):
            await interaction.response.send_message("Type must be one of: light, medium, heavy, td.", ephemeral=True)
            return
        if await db.get_tank(name):
            await interaction.response.send_message("Tank already exists.", ephemeral=True)
            return

        await db.add_tank(name, tier, type, interaction.user.display_name, utils.utc_now_z())
        await forum_index.targeted_update(bot, tier, type)
        await interaction.response.send_message(f"✅ Added **{name}** (Tier {tier}, {utils.title_case_type(type)}).", ephemeral=True)

    @grp.command(name="edit", description="Edit a tank (admins only)")
    async def edit(interaction: discord.Interaction, name: str, tier: int, type: str):
        if not _require_admin(interaction):
            await interaction.response.send_message("Nope. You need **Manage Server**.", ephemeral=True)
            return
        name = utils.validate_text('Tank name', name, 64)
        type = type.strip().lower()
        t = await db.get_tank(name)
        if not t:
            await interaction.response.send_message("Tank not found.", ephemeral=True)
            return
        old_tier, old_type = int(t[1]), t[2]
        if not (1 <= tier <= 10):
            await interaction.response.send_message("Tier must be 1..10.", ephemeral=True)
            return
        if type not in ("light", "medium", "heavy", "td"):
            await interaction.response.send_message("Type must be one of: light, medium, heavy, td.", ephemeral=True)
            return

        await db.edit_tank(name, tier, type, interaction.user.display_name, utils.utc_now_z())
        # Update both old and new buckets
        await forum_index.targeted_update(bot, old_tier, old_type)
        await forum_index.targeted_update(bot, tier, type)
        await interaction.response.send_message(f"✅ Updated **{name}**.", ephemeral=True)

    @grp.command(name="remove", description="Remove a tank (only if no submissions)")
    async def remove(interaction: discord.Interaction, name: str):
        if not _require_admin(interaction):
            await interaction.response.send_message("Nope. You need **Manage Server**.", ephemeral=True)
            return
        name = utils.validate_text('Tank name', name, 64)
        t = await db.get_tank(name)
        if not t:
            await interaction.response.send_message("Tank not found.", ephemeral=True)
            return
        tier, ttype = int(t[1]), t[2]
        try:
            await db.remove_tank(name, interaction.user.display_name, utils.utc_now_z())
        except Exception as e:
            await interaction.response.send_message(f"❌ {type(e).__name__}: {e}", ephemeral=True)
            return
        await forum_index.targeted_update(bot, tier, ttype)
        await interaction.response.send_message(f"✅ Removed **{name}**.", ephemeral=True)

    @grp.command(name="list", description="List tanks (filters optional)")
    async def list_cmd(interaction: discord.Interaction, tier: int | None = None, type: str | None = None):
        if not _require_admin(interaction):
            await interaction.response.send_message("Nope. You need **Manage Server**.", ephemeral=True)
            return
        if type is not None:
            type = type.strip().lower()
        rows = await db.list_tanks(tier=tier, ttype=type)
        if not rows:
            await interaction.response.send_message("No tanks found.", ephemeral=True)
            return
        lines = ["**Tanks**"]
        for n, tr, tp in rows[:200]:
            lines.append(f"- **{n}** — Tier {tr}, {utils.title_case_type(tp)}")
        msg = "\n".join(lines)
        if len(msg) > 1800:
            msg = msg[:1800] + "\n…(truncated)"
        await interaction.response.send_message(msg, ephemeral=True)

    @grp.command(name="changes", description="Show tank change log")
    async def changes(interaction: discord.Interaction, limit: int = 20):
        if not _require_admin(interaction):
            await interaction.response.send_message("Nope. You need **Manage Server**.", ephemeral=True)
            return
        rows = await db.tank_changes(limit=limit)
        if not rows:
            await interaction.response.send_message("No changes logged.", ephemeral=True)
            return
        lines = ["**Tank changes**"]
        for _id, action, details, actor, created in rows:
            lines.append(f"- #{_id} **{action}** `{details}` by **{actor}** • {created}Z")
        msg = "\n".join(lines)
        if len(msg) > 1800:
            msg = msg[:1800] + "\n…(truncated)"
        await interaction.response.send_message(msg, ephemeral=True)

    @grp.command(name="export_csv", description="Export tank roster as CSV")
    async def export_csv(interaction: discord.Interaction):
        if not _require_admin(interaction):
            await interaction.response.send_message("Nope. You need **Manage Server**.", ephemeral=True)
            return
        rows = await db.list_tanks()
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["name", "tier", "type"])
        for n, tr, tp in rows:
            w.writerow([n, tr, tp])
        data = out.getvalue().encode("utf-8")
        await interaction.response.send_message("CSV export:", ephemeral=True, file=discord.File(io.BytesIO(data), filename="tanks.csv"))

    @grp.command(name="preview_import", description="Preview CSV import (no changes)")
    async def preview_import(interaction: discord.Interaction, csv_file: discord.Attachment, delete_missing: bool = False):
        if not _require_admin(interaction):
            await interaction.response.send_message("Nope. You need **Manage Server**.", ephemeral=True)
            return
        raw = (await csv_file.read()).decode("utf-8", errors="replace")
        r = csv.DictReader(io.StringIO(raw))
        incoming = {}
        for row in r:
            name = utils.validate_text('Tank name', (row.get('name') or ''), 64) if (row.get('name') or '').strip() else ''
            if not name:
                continue
            incoming[name] = (int(row.get("tier") or 0), (row.get("type") or "").strip().lower())

        existing = {n: (int(t), tp) for n, t, tp in await db.list_tanks()}

        adds = [n for n in incoming.keys() if n not in existing]
        edits = [n for n in incoming.keys() if n in existing and incoming[n] != existing[n]]
        removes = [n for n in existing.keys() if n not in incoming] if delete_missing else []

        lines = ["**Preview import**"]
        lines.append(f"- Adds: {len(adds)}")
        lines.append(f"- Edits: {len(edits)}")
        lines.append(f"- Removes: {len(removes)} (delete_missing={delete_missing})")
        if adds:
            lines.append("\n**Adds**: " + ", ".join(adds[:30]) + ("…" if len(adds)>30 else ""))
        if edits:
            lines.append("\n**Edits**: " + ", ".join(edits[:30]) + ("…" if len(edits)>30 else ""))
        if removes:
            lines.append("\n**Removes**: " + ", ".join(removes[:30]) + ("…" if len(removes)>30 else ""))
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @grp.command(name="import_csv", description="Import tank roster from CSV (applies changes)")
    async def import_csv(interaction: discord.Interaction, csv_file: discord.Attachment, delete_missing: bool = False):
        if not _require_admin(interaction):
            await interaction.response.send_message("Nope. You need **Manage Server**.", ephemeral=True)
            return
        raw = (await csv_file.read()).decode("utf-8", errors="replace")
        r = csv.DictReader(io.StringIO(raw))
        incoming = {}
        for row in r:
            name = utils.validate_text('Tank name', (row.get('name') or ''), 64) if (row.get('name') or '').strip() else ''
            if not name:
                continue
            tier = int(row.get("tier") or 0)
            ttype = (row.get("type") or "").strip().lower()
            if not (1 <= tier <= 10) or ttype not in ("light","medium","heavy","td"):
                await interaction.response.send_message(f"Invalid row for `{name}`.", ephemeral=True)
                return
            incoming[name] = (tier, ttype)

        existing_rows = await db.list_tanks()
        existing = {n: (int(t), tp) for n, t, tp in existing_rows}

        adds = [n for n in incoming.keys() if n not in existing]
        edits = [n for n in incoming.keys() if n in existing and incoming[n] != existing[n]]
        removes = [n for n in existing.keys() if n not in incoming] if delete_missing else []

        # Apply adds/edits
        for n in adds:
            tier, tp = incoming[n]
            await db.add_tank(n, tier, tp, interaction.user.display_name, utils.utc_now_z())
        for n in edits:
            tier, tp = incoming[n]
            await db.edit_tank(n, tier, tp, interaction.user.display_name, utils.utc_now_z())

        # Apply removals if allowed
        if delete_missing:
            for n in removes:
                try:
                    await db.remove_tank(n, interaction.user.display_name, utils.utc_now_z())
                except Exception:
                    # skip tanks with submissions
                    pass

        # Targeted updates: rebuild buckets for affected tiers/types (cheap + safe)
        affected = set()
        for n in adds + edits:
            tier, tp = incoming[n]
            affected.add((tier, tp))
        for n in edits:
            old_tier, old_tp = existing[n]
            affected.add((old_tier, old_tp))

        for tier, tp in affected:
            await forum_index.targeted_update(bot, tier, tp)

        await interaction.response.send_message(f"✅ Import applied. Adds={len(adds)} Edits={len(edits)} Removes={len(removes)}.", ephemeral=True)

    @grp.command(name="rebuild_index", description="Rebuild ALL forum index threads")
    async def rebuild_index(interaction: discord.Interaction):
        if not _require_admin(interaction):
            await interaction.response.send_message("Nope. You need **Manage Server**.", ephemeral=True)
            return
        await interaction.response.send_message("Rebuilding index…", ephemeral=True)
        await forum_index.rebuild_all(bot)
        await interaction.followup.send("✅ Index rebuilt.", ephemeral=True)

    @grp.command(name="rebuild_index_missing", description="Create/repair missing forum index threads")
    async def rebuild_index_missing(interaction: discord.Interaction):
        if not _require_admin(interaction):
            await interaction.response.send_message("Nope. You need **Manage Server**.", ephemeral=True)
            return
        await interaction.response.send_message("Repairing missing index threads…", ephemeral=True)
        await forum_index.rebuild_missing(bot)
        await interaction.followup.send("✅ Missing threads repaired.", ephemeral=True)
