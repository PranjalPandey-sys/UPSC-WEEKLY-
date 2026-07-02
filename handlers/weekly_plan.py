"""
handlers/weekly_plan.py — Weekly Plan & Long-Term Roadmap
===========================================================
Three views built from the plan JSON (no AI, fully offline):

1. 📅 This Week     — Day-by-day table for the current 7 days
2. 🗺️ Roadmap       — Phase timeline with subject overview per phase
3. 📆 Browse Weeks  — Paginated week-by-week schedule (any week in plan)

Navigation: weeks are passed in callback_data so browsing is stateless.
All content is rendered from pre-loaded plan JSON — instant display.
"""
import logging
from datetime import date, timedelta

from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup as Markup
from telegram.ext import CallbackQueryHandler, ContextTypes

import keyboards as kb
from media import show_section
from services import plan_loader
from storage.database import get_user, log_event
from utils.helpers import (
    compact_bar, days_remaining_label, esc, level_emoji,
    phase_display, progress_bar,
)

logger = logging.getLogger(__name__)
HTML  = "HTML"

DAY_TYPE_ICON = {
    "STUDY":          "📘",
    "REVISION":       "🔄",
    "MOCK_TEST":      "🧪",
    "MONTHLY_REVIEW": "📊",
}


# ── Keyboard builders ──────────────────────────────────────────────────────────

def kb_weekly_home() -> Markup:
    return Markup([
        [Btn("📅 This Week",    callback_data="week:this"),
         Btn("📆 Browse Weeks", callback_data="week:browse:1")],
        [Btn("🗺️ Roadmap",     callback_data="week:roadmap"),
         Btn("📋 Full Journey", callback_data="week:journey")],
        [Btn("🏠 Home",         callback_data="nav:home")],
    ])


def kb_browse_week(current_week: int, total_weeks: int) -> Markup:
    rows = []
    nav = []
    if current_week > 1:
        nav.append(Btn("◀ Prev Week", callback_data=f"week:browse:{current_week - 1}"))
    if current_week < total_weeks:
        nav.append(Btn("Next Week ▶", callback_data=f"week:browse:{current_week + 1}"))
    if nav:
        rows.append(nav)
    rows.append([
        Btn("📅 This Week", callback_data="week:this"),
        Btn("🗺️ Roadmap",   callback_data="week:roadmap"),
    ])
    rows.append([Btn("🏠 Home", callback_data="nav:home")])
    return Markup(rows)


def kb_roadmap() -> Markup:
    return Markup([
        [Btn("📅 This Week",    callback_data="week:this"),
         Btn("📆 Browse Weeks", callback_data="week:browse:1")],
        [Btn("📋 Full Journey", callback_data="week:journey"),
         Btn("🏠 Home",         callback_data="nav:home")],
    ])


# ── Helper: build plan_id from user ───────────────────────────────────────────

def _pid(user: dict) -> str:
    return f"{user['level']}_{user['timeline_months']}months_{int(user['hours_per_day'])}hours"


# ── View 1: This Week ─────────────────────────────────────────────────────────

async def show_this_week(query, context: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    """Day-by-day table for the 7 days surrounding the user's current day."""
    pid         = _pid(user)
    current_day = user["current_day"] or 1
    total       = plan_loader.get_plan_length(pid)
    level       = user["level"] or "beginner"

    # Show days current_day … current_day+6 (clamp to plan length)
    week_start = current_day
    week_end   = min(current_day + 6, total)

    lines = []
    for d in range(week_start, week_end + 1):
        task = plan_loader.get_day_task(pid, d)
        if not task:
            break
        icon    = DAY_TYPE_ICON.get(task.get("day_type", "STUDY"), "📘")
        subject = task.get("subject", "—").replace("_", " ")[:18]
        topic   = task.get("subtopic", "—")[:22]
        mins    = task.get("estimated_total_min", 0)
        hrs     = f"{mins//60}h{mins%60:02d}m" if mins else f"{int(user['hours_per_day'])}h"
        marker  = " ← TODAY" if d == current_day else ""
        lines.append(
            f"  <b>Day {d}</b> {icon} {esc(subject)}\n"
            f"    <i>{esc(topic)}</i>  ·  {hrs}{marker}"
        )

    pct  = round(current_day / total * 100, 1) if total else 0
    bar  = progress_bar(pct, 8)
    rem  = days_remaining_label(total - current_day)

    caption = (
        f"📅 <b>This Week — Days {week_start}–{week_end}</b>\n"
        f"{level_emoji(level)} {level.title()} Plan  ·  {bar} {pct:.0f}%\n"
        f"<i>{rem}</i>\n\n"
        + "\n\n".join(lines) +
        f"\n\n<i>Tap Browse Weeks to see any week ahead.</i>"
    )
    await show_section(query, context, "plan", caption, kb_weekly_home())
    log_event(user["user_id"], "week_this_week")


# ── View 2: Browse any week ────────────────────────────────────────────────────

async def show_browse_week(
    query, context: ContextTypes.DEFAULT_TYPE, user: dict, week_num: int
) -> None:
    """Show a specific week (1-indexed) from the plan."""
    pid   = _pid(user)
    total = plan_loader.get_plan_length(pid)
    level = user["level"] or "beginner"
    current_day = user["current_day"] or 1

    total_weeks = (total + 6) // 7  # ceiling division
    week_num    = max(1, min(week_num, total_weeks))

    day_start = (week_num - 1) * 7 + 1
    day_end   = min(day_start + 6, total)

    lines = []
    for d in range(day_start, day_end + 1):
        task = plan_loader.get_day_task(pid, d)
        if not task:
            break
        icon    = DAY_TYPE_ICON.get(task.get("day_type", "STUDY"), "📘")
        subject = task.get("subject", "—").replace("_", " ")[:18]
        topic   = task.get("subtopic", "—")[:24]
        mins    = task.get("estimated_total_min", 0)
        hrs     = f"{mins//60}h{mins%60:02d}m" if mins else f"{int(user['hours_per_day'])}h"
        is_past  = d < current_day
        is_today = d == current_day
        marker   = " ✅" if is_past else (" ← TODAY" if is_today else "")
        lines.append(
            f"  <b>Day {d}</b> {icon} {esc(subject)}\n"
            f"    <i>{esc(topic)}</i>  ·  {hrs}{marker}"
        )

    caption = (
        f"📆 <b>Week {week_num} of {total_weeks}</b>"
        f"  (Days {day_start}–{day_end})\n"
        f"{level_emoji(level)} {level.title()} Plan  ·  {total} days total\n\n"
        + "\n\n".join(lines)
    )
    await show_section(
        query, context, "plan", caption,
        kb_browse_week(week_num, total_weeks),
    )
    log_event(user["user_id"], f"week_browse_w{week_num}")


# ── View 3: Roadmap (phase timeline) ──────────────────────────────────────────

async def show_roadmap(query, context: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    """
    Phase-by-phase roadmap: start day, end day, subjects covered, progress.
    Built by scanning daily_plan for phase transitions — entirely offline.
    """
    pid         = _pid(user)
    total       = plan_loader.get_plan_length(pid)
    current_day = user["current_day"] or 1
    level       = user["level"] or "beginner"

    # Scan plan and group days by phase
    phases: dict[str, dict] = {}   # phase_name → {start, end, subjects, types}
    current_phase = None

    for d in range(1, total + 1):
        task  = plan_loader.get_day_task(pid, d)
        if not task:
            break
        phase = task.get("phase", "Foundation")
        subj  = task.get("subject", "").replace("_", " ")
        dtype = task.get("day_type", "STUDY")

        if phase not in phases:
            phases[phase] = {
                "start":    d,
                "end":      d,
                "subjects": set(),
                "types":    set(),
            }
        phases[phase]["end"] = d
        if subj:
            phases[phase]["subjects"].add(subj)
        phases[phase]["types"].add(dtype)

    if not phases:
        await query.answer("Roadmap not available for this plan.", show_alert=True)
        return

    lines = []
    for phase_name, info in phases.items():
        start   = info["start"]
        end_d   = info["end"]
        subjects= sorted(info["subjects"])[:5]
        days_in = end_d - start + 1
        is_done = current_day > end_d
        is_now  = start <= current_day <= end_d

        if is_done:
            status = "✅"
            prog   = compact_bar(100, 6)
        elif is_now:
            done_in_phase = current_day - start
            pct_phase = round(done_in_phase / days_in * 100, 0) if days_in else 0
            status = "▶️"
            prog   = compact_bar(pct_phase, 6)
        else:
            status = "⏳"
            prog   = compact_bar(0, 6)

        subj_str = ", ".join(esc(s) for s in subjects)
        if len(info["subjects"]) > 5:
            subj_str += f" +{len(info['subjects'])-5} more"

        mock_flag = " 🧪" if "MOCK_TEST" in info["types"] else ""
        rev_flag  = " 🔄" if "REVISION" in info["types"] else ""

        lines.append(
            f"{status} <b>{esc(phase_display(phase_name))}</b>{mock_flag}{rev_flag}\n"
            f"   Days {start}–{end_d} ({days_in}d)  {prog}\n"
            f"   <i>{subj_str}</i>"
        )

    total_pct = round(current_day / total * 100, 1) if total else 0
    bar       = progress_bar(total_pct, 10)

    caption = (
        f"🗺️ <b>Your UPSC Roadmap</b>\n"
        f"{level_emoji(level)} {level.title()} · {total} days\n"
        f"Overall: {bar} {total_pct:.0f}%\n\n"
        + "\n\n".join(lines) +
        "\n\n<i>✅ done  ▶️ current  ⏳ upcoming</i>"
    )
    await show_section(query, context, "plan", caption, kb_roadmap())
    log_event(user["user_id"], "week_roadmap")


# ── View 4: Full Journey (subject sequence, no day detail) ────────────────────

async def show_journey(query, context: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    """
    Bird's-eye view: every distinct subject in plan order with day ranges.
    Useful for seeing the complete curriculum at a glance.
    """
    pid   = _pid(user)
    total = plan_loader.get_plan_length(pid)
    level = user["level"] or "beginner"
    current_day = user["current_day"] or 1

    # Group consecutive days by subject (ignore day_type changes within same subject)
    subject_blocks: list[tuple[str, str, int, int]] = []  # (subject, phase, start, end)
    prev_subj  = None
    prev_phase = None
    block_start = 1

    for d in range(1, total + 1):
        task  = plan_loader.get_day_task(pid, d)
        if not task:
            break
        subj  = task.get("subject", "—").replace("_", " ")
        phase = task.get("phase", "")

        if subj != prev_subj or phase != prev_phase:
            if prev_subj is not None:
                subject_blocks.append((prev_subj, prev_phase or "", block_start, d - 1))
            prev_subj   = subj
            prev_phase  = phase
            block_start = d

    if prev_subj:
        subject_blocks.append((prev_subj, prev_phase or "", block_start, total))

    lines = []
    for subj, phase, start, end_d in subject_blocks[:25]:  # cap at 25 to fit screen
        days_in = end_d - start + 1
        done    = current_day > end_d
        active  = start <= current_day <= end_d
        icon    = "✅" if done else ("▶️" if active else "⏳")
        lines.append(
            f"{icon} <b>{esc(subj)}</b>  "
            f"<i>Days {start}–{end_d}</i>  ({days_in}d)"
        )

    if len(subject_blocks) > 25:
        lines.append(f"<i>…and {len(subject_blocks)-25} more subject blocks</i>")

    caption = (
        f"📋 <b>Complete Journey</b>\n"
        f"{level_emoji(level)} {level.title()} · {total} days · "
        f"{len(subject_blocks)} subject blocks\n\n"
        + "\n".join(lines)
    )
    await show_section(query, context, "plan", caption, kb_roadmap())
    log_event(user["user_id"], "week_journey")


# ── Main entry + callback router ──────────────────────────────────────────────

async def show_weekly_plan(query, context: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    """Landing page for the weekly plan section."""
    pid         = _pid(user)
    total       = plan_loader.get_plan_length(pid)
    current_day = user["current_day"] or 1
    level       = user["level"] or "beginner"
    total_weeks = (total + 6) // 7

    pct = round(current_day / total * 100, 1) if total else 0
    bar = progress_bar(pct, 8)

    caption = (
        f"🗓️ <b>Study Plan Overview</b>\n\n"
        f"{level_emoji(level)} {level.title()} Plan\n"
        f"Day <b>{current_day}</b> of <b>{total}</b>  ·  "
        f"{total_weeks} weeks  ·  {days_remaining_label(total - current_day)}\n"
        f"{bar} {pct:.0f}% complete\n\n"
        f"<b>Choose a view:</b>\n"
        f"  📅 <b>This Week</b> — days {current_day} to {min(current_day+6, total)}\n"
        f"  📆 <b>Browse Weeks</b> — page through all {total_weeks} weeks\n"
        f"  🗺️ <b>Roadmap</b> — phase timeline with progress\n"
        f"  📋 <b>Full Journey</b> — every subject in sequence"
    )
    await show_section(query, context, "plan", caption, kb_weekly_home())


async def weekly_callback(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route all week: callbacks."""
    query   = update.callback_query
    user_id = query.from_user.id
    parts   = query.data.split(":")   # ["week", action, ...optional arg]
    action  = parts[1] if len(parts) > 1 else "home"

    user = get_user(user_id)
    if not user or not user["setup_done"]:
        await query.answer("Please /start first.")
        return

    match action:
        case "home" | "menu":
            await show_weekly_plan(query, context, user)

        case "this":
            await show_this_week(query, context, user)

        case "browse":
            try:
                week_num = int(parts[2])
            except (IndexError, ValueError):
                week_num = 1
            await show_browse_week(query, context, user, week_num)

        case "roadmap":
            await show_roadmap(query, context, user)

        case "journey":
            await show_journey(query, context, user)

        case _:
            await query.answer()


def get_weekly_handlers() -> list:
    return [CallbackQueryHandler(weekly_callback, pattern=r"^week:")]
