"""
Is `public.conversations` safe to archive? (SPEC-098)

**Read-only.** This script never writes. Run it against staging and then
production, read the output, and only then merge the migration.

The question is not "are the row counts equal" — they are not supposed to be.
Three states produce very different numbers and two of them are expected:

* `purge_user_data` deletes a user's `messages` and `chat_settings` rows and has
  never touched `conversations`, so a deleted account leaves old history with no
  new history. That is the end state working correctly.
* `conversations.item_id` cascades on item delete, so deleting a listing has been
  quietly removing whole conversation rows since before the cutover.
* People kept talking after SPEC-043, so a live user should have *more* rows in
  `messages` than their old array ever held.

What actually matters is whether anyone's history exists ONLY in the old table.
`user_profiles` is what separates "purged" from "live user we would be putting
away", which is why it is part of the query rather than inferred from counts.

    mise run db:verify:conversations          # staging
    mise run db:verify:conversations:prod     # production

Exit code is 1 if anything needs a human, 0 if nothing does.
"""

import asyncio
import os
from dataclasses import dataclass, field

OK = "ok"
PURGED = "purged"
NEEDS_REVIEW = "needs review"

# One row per user: how much history the old table holds for them, how much the
# new one does, and whether the account still exists.
SNAPSHOT_SQL = """
select
    c.user_id::text as user_id,
    sum(
        case when jsonb_typeof(c.messages) = 'array'
             then jsonb_array_length(c.messages) else 0 end
    )::bigint as old_count,
    coalesce(max(m.cnt), 0)::bigint as new_count,
    bool_or(p.id is not null) as has_profile
from public.conversations c
left join lateral (
    select count(*) as cnt from public.messages mm where mm.user_id = c.user_id
) m on true
left join public.user_profiles p on p.id = c.user_id
where c.user_id is not null
group by c.user_id
order by 1;
"""


@dataclass
class Report:
    verdicts: dict[str, str] = field(default_factory=dict)
    needs_review: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    total_users: int = 0
    total_old_messages: int = 0
    total_new_messages: int = 0


def classify(old_count: int, new_count: int, has_profile: bool) -> str:
    """One user's verdict.

    Order matters: a missing profile means the rows went on purpose, whatever
    the counts say, so it is checked before the shortfall comparison.
    """
    if old_count == 0:
        return OK
    if not has_profile:
        return PURGED
    if new_count == 0:
        # A live account whose entire history is only in the old table.
        return NEEDS_REVIEW
    if new_count < old_count:
        # Present in both, but shorter than the snapshot — a partial backfill.
        return NEEDS_REVIEW
    return OK


def assess(snapshot: list[dict]) -> Report:
    """Turn the per-user snapshot into a verdict a person can act on."""
    report = Report(counts={OK: 0, PURGED: 0, NEEDS_REVIEW: 0})
    for entry in snapshot:
        user_id = entry["user_id"]
        old_count = int(entry["old_count"] or 0)
        new_count = int(entry["new_count"] or 0)
        verdict = classify(old_count, new_count, bool(entry["has_profile"]))

        report.verdicts[user_id] = verdict
        report.counts[verdict] += 1
        report.total_users += 1
        report.total_old_messages += old_count
        report.total_new_messages += new_count
        if verdict == NEEDS_REVIEW:
            report.needs_review.append(user_id)
    return report


def exit_code(report: Report) -> int:
    return 1 if report.needs_review else 0


def render(report: Report, snapshot: list[dict]) -> str:
    by_user = {e["user_id"]: e for e in snapshot}
    lines = [
        "",
        "public.conversations — retirement readiness (SPEC-098)",
        "=" * 58,
        f"  users with a conversations row : {report.total_users}",
        f"  messages held in old arrays    : {report.total_old_messages}",
        f"  rows now in public.messages    : {report.total_new_messages}",
        "",
        f"  {OK:<13}: {report.counts[OK]:>5}   migrated, or never had history",
        f"  {PURGED:<13}: {report.counts[PURGED]:>5}   account deleted; leftovers are expected",
        f"  {NEEDS_REVIEW:<13}: {report.counts[NEEDS_REVIEW]:>5}   history may exist ONLY in the old table",
        "",
    ]

    if report.needs_review:
        lines.append("  Needs a human before this is archived:")
        for user_id in report.needs_review[:25]:
            e = by_user[user_id]
            lines.append(f"    {user_id}  old={e['old_count']:<6} new={e['new_count']:<6} profile=yes")
        if len(report.needs_review) > 25:
            lines.append(f"    … and {len(report.needs_review) - 25} more")
        lines += [
            "",
            "  These accounts still exist and their transcript is shorter in",
            "  public.messages than the snapshot the old table holds. The",
            "  migration will refuse to run; that is the guard doing its job.",
            "",
        ]
    else:
        lines += [
            "  ✅ Nothing needs review. Every remaining row belongs to a deleted",
            "     account or is already represented in public.messages.",
            "",
            "  The migration is still a SCHEMA MOVE, not a drop — reverse it with:",
            "     alter table archive.conversations set schema public;",
            "",
        ]
    return "\n".join(lines)


async def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL is not set. Run through Infisical (see mise.toml).")
        return 2

    import asyncpg

    safe_target = db_url.split("@")[-1] if "@" in db_url else db_url
    print(f"🔎 Read-only check against: {safe_target}")

    conn = await asyncpg.connect(db_url, ssl="require")
    try:
        exists = await conn.fetchval(
            "select 1 from information_schema.tables "
            "where table_schema = 'public' and table_name = 'conversations';"
        )
        if not exists:
            print("\n✅ public.conversations does not exist here — already retired, or never created.")
            return 0

        snapshot = [dict(r) for r in await conn.fetch(SNAPSHOT_SQL)]
    finally:
        await conn.close()

    report = assess(snapshot)
    print(render(report, snapshot))
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
