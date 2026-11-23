"""evolve-profile (ARCHITECTURE §7): measure the week, recalibrate with guardrails, brief the tutor, write a report.

1. Deterministic metrics per language for the window.
2. Band calibration: the i+1 band shifts toward harder content when items are finished easily with few lookups, and
   toward easier content when abandonment or lookups are high. At most ±2 points per week, ±4 in total, with reasons.
3. Optional AI pass (`profile.evolve`) or a proposal written by the agent terminal (`--apply`): a narrative, focus
   words, focus grammar, a tutor brief and style tweaks. Proposals are validated: focus words must be words you are
   learning, style changes are clamped, goals are only suggested.
4. Writes a progress report per language, a profile snapshot, a new tutor brief, and data/reports/<year>-W<week>.md.
"""

from __future__ import annotations

import json
import statistics
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, text

from app.ai.gateway import AIUnavailable, Gateway
from app.config import AppConfig
from app.db import settings_store
from app.engine.profile import get_profile
from app.services import content
from app.services.tutor import active_instructions
from app.timeutil import local_today, to_iso, utc_now

MAX_STEP, MAX_SHIFT = 0.02, 0.04
EASY_LOOKUPS, HARD_LOOKUPS = 5.0, 30.0  # lookups per 1,000 words experienced


class StyleChange(BaseModel):
    speech_rate: float | None = None
    max_sentence_words: int | None = None


class Proposal(BaseModel):
    narrative_md: str = ""
    focus_words: list[str] = Field(default_factory=list)
    focus_grammar: list[str] = Field(default_factory=list)
    tutor_instructions_md: str = ""
    style: StyleChange = Field(default_factory=StyleChange)
    suggested_goal_minutes: int | None = None


# ------------------------------------------------------------------ metrics


def _window(days: int, today: date | None = None) -> tuple[str, str, date, date]:
    end_day = today or local_today()
    start_day = end_day - timedelta(days=days - 1)
    from app.timeutil import local_midnight_utc

    return to_iso(local_midnight_utc(start_day)), to_iso(local_midnight_utc(end_day + timedelta(days=1))), start_day, end_day


def metrics(conn: Connection, lang: str, start: str, end: str) -> dict[str, Any]:
    p = {"l": lang, "s": start, "e": end}
    by_activity = {
        r[0]: round((r[1] or 0) / 60, 1)
        for r in conn.execute(
            text(
                "SELECT activity, SUM(active_seconds) FROM activity_sessions WHERE language_code = :l AND is_baseline = 0 "
                "AND started_at >= :s AND started_at < :e GROUP BY activity"
            ),
            p,
        ).all()
    }
    by_modality = {
        r[0]: round((r[1] or 0) / 60, 1)
        for r in conn.execute(
            text(
                "SELECT modality, SUM(active_seconds) FROM activity_sessions WHERE language_code = :l AND is_baseline = 0 "
                "AND started_at >= :s AND started_at < :e GROUP BY modality"
            ),
            p,
        ).all()
    }
    active_days = conn.execute(
        text(
            "SELECT COUNT(DISTINCT substr(started_at, 1, 10)) FROM activity_sessions WHERE language_code = :l "
            "AND is_baseline = 0 AND started_at >= :s AND started_at < :e"
        ),
        p,
    ).scalar() or 0
    events = {
        r[0]: r[1]
        for r in conn.execute(
            text(
                "SELECT e.event || CASE WHEN e.event = 'status_change' THEN ':' || COALESCE(e.value, '') ELSE '' END, COUNT(*) "
                "FROM word_events e JOIN lexemes x ON x.id = e.lexeme_id WHERE x.language_code = :l "
                "AND e.created_at >= :s AND e.created_at < :e GROUP BY 1"
            ),
            p,
        ).all()
    }

    # Items you spent time on, with how much of them you experienced and how many words you looked up in them.
    items = conn.execute(
        text(
            "SELECT ci.id, ci.type, ci.status, ci.progress, ci.word_count, ci.duration_sec, cs.coverage, cs.band, "
            "SUM(s.active_seconds), (SELECT COUNT(*) FROM word_events w WHERE w.content_item_id = ci.id AND w.event = 'lookup' "
            " AND w.created_at >= :s AND w.created_at < :e) FROM activity_sessions s JOIN content_items ci ON ci.id = s.content_item_id "
            "LEFT JOIN content_scores cs ON cs.content_item_id = ci.id WHERE s.language_code = :l AND s.is_baseline = 0 "
            "AND s.started_at >= :s AND s.started_at < :e GROUP BY ci.id"
        ),
        p,
    ).all()
    by_band: dict[str, dict[str, float]] = {}
    finished_coverages: list[float] = []
    started = abandoned = finished = 0
    for _id, kind, status, progress, words, duration, coverage, band, seconds, lookups in items:
        experienced = 0.0
        if words:
            if duration:
                experienced = words * min(1.0, (seconds or 0) / duration)
            else:
                experienced = words * max(progress or 0, 0.1)
        bucket = by_band.setdefault(band or "unscored", {"items": 0, "words": 0.0, "lookups": 0})
        bucket["items"] += 1
        bucket["words"] += experienced
        bucket["lookups"] += lookups or 0
        started += 1
        if status == "finished" or (progress or 0) >= 0.9:
            finished += 1
            if coverage is not None:
                finished_coverages.append(coverage)
        elif (progress or 0) < 0.3 and kind not in content.WATCH_TYPES:
            abandoned += 1
    for bucket in by_band.values():
        bucket["lookups_per_1k"] = round(bucket["lookups"] / bucket["words"] * 1000, 1) if bucket["words"] >= 200 else None
        bucket["words"] = round(bucket["words"])

    tutor = conn.execute(
        text(
            "SELECT COUNT(DISTINCT s.id), SUM(CASE WHEN m.role = 'user' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN m.corrections_json IS NOT NULL THEN json_array_length(m.corrections_json) ELSE 0 END) "
            "FROM tutor_sessions s LEFT JOIN tutor_messages m ON m.session_id = s.id WHERE s.language_code = :l "
            "AND s.started_at >= :s AND s.started_at < :e"
        ),
        p,
    ).first()
    shadow = conn.execute(
        text(
            "SELECT COUNT(*), AVG(a.text_similarity) FROM shadow_attempts a JOIN shadow_clips c ON c.id = a.clip_id "
            "WHERE c.language_code = :l AND a.created_at >= :s AND a.created_at < :e"
        ),
        p,
    ).first()
    tests = [
        {"skill": r[0], "band": json.loads(r[1] or "{}").get("band")}
        for r in conn.execute(
            text(
                "SELECT skill, result_json FROM assessments WHERE language_code = :l AND status = 'done' "
                "AND finished_at >= :s AND finished_at < :e"
            ),
            p,
        ).all()
    ]
    return {
        "minutes_total": round(sum(by_activity.values()), 1),
        "minutes_by_activity": by_activity,
        "minutes_by_modality": by_modality,
        "active_days": active_days,
        "words_saved": events.get("save", 0),
        "words_to_known": events.get("status_change:known", 0),
        "lookups": events.get("lookup", 0),
        "items_started": started,
        "items_finished": finished,
        "items_abandoned": abandoned,
        "finished_median_coverage": round(statistics.median(finished_coverages), 3) if finished_coverages else None,
        "by_band": by_band,
        "tutor": {"sessions": tutor[0] or 0, "turns": tutor[1] or 0, "corrections": tutor[2] or 0},
        "shadowing": {"attempts": shadow[0] or 0, "avg_similarity": round(shadow[1], 3) if shadow[1] is not None else None},
        "level_lab": tests,
    }


# ------------------------------------------------------------------ calibration


def band_shift(conn: Connection, lang: str) -> float:
    return float(settings_store.get(conn, f"band_shift.{lang}", 0.0) or 0.0)


def calibrate(conn: Connection, lang: str, m: dict[str, Any]) -> list[dict[str, Any]]:
    """Move the i+1 band toward harder or easier content, a little, with the reason recorded."""
    current = band_shift(conn, lang)
    target_band = m["by_band"].get("i_plus_1", {})
    rate = target_band.get("lookups_per_1k")
    step, reason = 0.0, None
    if m["items_started"] >= 2 and m["items_abandoned"] / m["items_started"] > 0.5:
        step, reason = +0.01, f"{m['items_abandoned']} of {m['items_started']} items were dropped early"
    elif rate is not None and rate > HARD_LOOKUPS:
        step, reason = +0.01, f"{rate} lookups per 1,000 words in just-right items"
    elif (
        m["items_finished"] >= 2
        and (m["finished_median_coverage"] or 0) >= 0.95
        and (rate is None or rate < EASY_LOOKUPS)
    ):
        step, reason = -0.01, f"finished {m['items_finished']} items at ≈{round(m['finished_median_coverage'] * 100)}% known with few lookups"
    if not step:
        return []
    new = max(-MAX_SHIFT, min(MAX_SHIFT, current + max(-MAX_STEP, min(MAX_STEP, step))))
    if new == current:
        return [{"what": "band", "from": current, "to": current, "reason": f"{reason}; already at the limit"}]
    settings_store.put(conn, f"band_shift.{lang}", round(new, 3))
    direction = "easier" if new > current else "harder"
    return [{"what": "band", "from": current, "to": round(new, 3), "reason": f"{reason}: picks move slightly {direction}"}]


# ------------------------------------------------------------------ proposals


def context_for(conn: Connection, lang: str) -> dict[str, Any]:
    learning = [
        r[0]
        for r in conn.execute(
            text(
                "SELECT l.lemma FROM user_words w JOIN lexemes l ON l.id = w.lexeme_id WHERE l.language_code = :l "
                "AND w.status = 'learning' ORDER BY COALESCE(w.status_changed_at, w.last_seen_at) DESC LIMIT 40"
            ),
            {"l": lang},
        ).all()
    ]
    grammar = [
        {"name": r[0], "errors": r[1], "status": r[2]}
        for r in conn.execute(
            text(
                "SELECT g.title, u.errors, u.status FROM user_grammar u JOIN grammar_points g ON g.id = u.grammar_point_id "
                "WHERE g.language_code = :l ORDER BY u.errors DESC LIMIT 10"
            ),
            {"l": lang},
        ).all()
    ]
    corrections = [
        f"{r[0]} → {r[1]}"
        for r in conn.execute(
            text(
                "SELECT e.original_text, e.corrected_text FROM grammar_evidence e JOIN grammar_points g ON g.id = e.grammar_point_id "
                "WHERE g.language_code = :l ORDER BY e.created_at DESC LIMIT 12"
            ),
            {"l": lang},
        ).all()
    ]
    instructions = active_instructions(conn, lang)
    return {"learning_words": learning, "grammar": grammar, "corrections": corrections, "style": instructions["style"]}


def validate(proposal: Proposal, ctx: dict[str, Any]) -> tuple[Proposal, list[str]]:
    """Guardrails for anything an AI proposes. Returns the cleaned proposal and what was dropped or clamped."""
    notes: list[str] = []
    learning = set(ctx["learning_words"])
    kept = [w for w in dict.fromkeys(proposal.focus_words) if w in learning][:15]
    if len(kept) < len(set(proposal.focus_words)):
        notes.append("dropped focus words that aren't on your learning list")
    proposal.focus_words = kept
    proposal.focus_grammar = [g.strip()[:80] for g in proposal.focus_grammar if g.strip()][:3]
    if len(proposal.tutor_instructions_md) > 1500:
        proposal.tutor_instructions_md = proposal.tutor_instructions_md[:1500]
        notes.append("shortened the tutor brief")
    style = ctx["style"]
    rate = proposal.style.speech_rate
    if rate is not None:
        current = float(style.get("speech_rate", 0.9))
        clamped = round(max(0.7, min(1.1, max(current - 0.1, min(current + 0.1, rate)))), 2)
        if clamped != rate:
            notes.append(f"speech rate limited to {clamped}")
        proposal.style.speech_rate = clamped
    words = proposal.style.max_sentence_words
    if words is not None:
        current_words = int(style.get("max_sentence_words") or words)
        clamped_words = max(5, min(25, max(current_words - 3, min(current_words + 3, words))))
        if clamped_words != words:
            notes.append(f"sentence length limited to {clamped_words} words")
        proposal.style.max_sentence_words = clamped_words
    if proposal.suggested_goal_minutes is not None and not 5 <= proposal.suggested_goal_minutes <= 600:
        proposal.suggested_goal_minutes = None
        notes.append("ignored an unrealistic goal")
    return proposal, notes


def _write_instructions(conn: Connection, lang: str, proposal: Proposal, ctx: dict[str, Any], report_id: int) -> int | None:
    if not (proposal.tutor_instructions_md.strip() or proposal.focus_words or proposal.focus_grammar):
        return None
    style = dict(ctx["style"])
    if proposal.style.speech_rate is not None:
        style["speech_rate"] = proposal.style.speech_rate
    if proposal.style.max_sentence_words is not None:
        style["max_sentence_words"] = proposal.style.max_sentence_words
    focus_ids = [
        r[0]
        for r in conn.execute(
            text(f"SELECT id FROM lexemes WHERE language_code = :l AND lemma IN ({','.join(':w%d' % i for i in range(len(proposal.focus_words))) or 'NULL'})"),
            {"l": lang, **{f"w{i}": w for i, w in enumerate(proposal.focus_words)}},
        ).all()
    ]
    brief = proposal.tutor_instructions_md.strip() or "No special notes."
    if proposal.focus_grammar:
        brief += "\nCreate natural chances to use: " + ", ".join(proposal.focus_grammar) + "."
    if proposal.focus_words:
        brief += "\nReuse some of these words naturally: " + ", ".join(proposal.focus_words) + "."
    conn.execute(text("UPDATE tutor_instructions SET is_active = 0 WHERE language_code = :l AND is_active = 1"), {"l": lang})
    return conn.execute(
        text(
            "INSERT INTO tutor_instructions (language_code, version, origin, instructions_md, focus_words_json, "
            "focus_grammar_json, style_json, is_active, report_id) VALUES (:l, COALESCE((SELECT MAX(version) FROM "
            "tutor_instructions WHERE language_code = :l), 0) + 1, 'evolve', :md, :fw, :fg, :st, 1, :r)"
        ),
        {
            "l": lang, "md": brief, "fw": json.dumps(focus_ids), "fg": json.dumps(proposal.focus_grammar, ensure_ascii=False),
            "st": json.dumps(style), "r": report_id,
        },
    ).lastrowid


# ------------------------------------------------------------------ the whole run


def _markdown(period: str, sections: list[dict[str, Any]]) -> str:
    lines = [f"# Weekly report · {period}", ""]
    for s in sections:
        m = s["metrics"]
        lines += [f"## {s['name']}", ""]
        lines.append(
            f"- **{m['minutes_total']:.0f} minutes** on {m['active_days']} day(s): "
            + ", ".join(f"{k} {v:.0f}" for k, v in sorted(m["minutes_by_activity"].items(), key=lambda kv: -kv[1]))
            if m["minutes_by_activity"] else "- No tracked time this week."
        )
        lines.append(f"- Words: {m['words_saved']} saved, {m['words_to_known']} marked known, {m['lookups']} lookups")
        lines.append(f"- Items: {m['items_started']} opened, {m['items_finished']} finished, {m['items_abandoned']} dropped early")
        if m["tutor"]["sessions"]:
            lines.append(f"- Tutor: {m['tutor']['sessions']} conversation(s), {m['tutor']['turns']} turns, {m['tutor']['corrections']} corrections")
        if m["shadowing"]["attempts"]:
            avg = m["shadowing"]["avg_similarity"]
            lines.append(f"- Shadowing: {m['shadowing']['attempts']} attempts" + (f", {round(avg * 100)}% recognised on average" if avg is not None else ""))
        for t in m["level_lab"]:
            lines.append(f"- Level Lab {t['skill']}: {t['band']}")
        lines.append(f"- Level estimate: {s['level']} (a range, not an exact value)")
        if s["narrative"]:
            lines += ["", s["narrative"].strip()]
        if s["adjustments"]:
            lines += ["", "**What changed**", ""] + [f"- {a['reason']}" for a in s["adjustments"]]
        if s["notes"]:
            lines += [f"- Guardrails: {'; '.join(s['notes'])}"]
        if s.get("goal"):
            lines += ["", f"Suggested daily goal: {s['goal']} minutes (change it in Settings if you agree)."]
        lines.append("")
    return "\n".join(lines)


def evolve(
    engine: Engine,
    cfg: AppConfig,
    gateway: Gateway | None,
    *,
    days: int = 7,
    use_llm: bool = True,
    proposals: dict[str, dict[str, Any]] | None = None,
    dry_run: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    start, end, start_day, end_day = _window(days, today)
    iso_year, iso_week, _ = end_day.isocalendar()
    period = f"{iso_year}-W{iso_week:02d}"
    period_label = f"{period} ({start_day.isoformat()} to {end_day.isoformat()})"
    sections: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"period": period, "start": start_day.isoformat(), "end": end_day.isoformat(), "languages": {}}

    for lang in cfg.language_codes:
        with engine.connect() as conn:
            m = metrics(conn, lang, start, end)
            ctx = context_for(conn, lang)
            profile = get_profile(conn, lang) or {}
            name = conn.execute(text("SELECT name FROM languages WHERE code = :c"), {"c": lang}).scalar() or lang
        level = profile.get("level_alt") if lang == "ja" and profile.get("level_alt") else profile.get("level") or "?"
        entry: dict[str, Any] = {"metrics": m, "context": ctx}
        if dry_run:
            summary["languages"][lang] = entry
            continue

        proposal, notes, model = None, [], None
        raw = (proposals or {}).get(lang)
        if raw is not None:
            proposal, model = Proposal.model_validate(raw), "agent terminal"
        elif use_llm and gateway is not None and m["minutes_total"] > 0:
            variables = {
                "language": name, "period": period_label, "level": level, "metrics": json.dumps(m, ensure_ascii=False),
                "learning_words": ", ".join(ctx["learning_words"]) or "none",
                "grammar": json.dumps(ctx["grammar"], ensure_ascii=False), "corrections": "; ".join(ctx["corrections"]) or "none",
                "style": json.dumps(ctx["style"]),
            }
            try:
                proposal, meta = gateway.structured("profile.evolve", "evolve", variables, Proposal, cache=False)
                model = f"{meta['provider']}/{meta['model']}"
            except AIUnavailable as exc:
                notes.append(f"no AI review this week ({exc})")
        if proposal is not None:
            proposal, more = validate(proposal, ctx)
            notes += more

        with engine.begin() as conn:
            adjustments = calibrate(conn, lang, m)
            report_id = conn.execute(
                text(
                    "INSERT INTO progress_reports (language_code, period_start, period_end, metrics_json, narrative_md, "
                    "adjustments_json, llm_model) VALUES (:l, :s, :e, :m, :n, :a, :model)"
                ),
                {
                    "l": lang, "s": start_day.isoformat(), "e": end_day.isoformat(), "m": json.dumps(m, ensure_ascii=False),
                    "n": proposal.narrative_md if proposal else None,
                    "a": json.dumps({"changes": adjustments, "notes": notes, "goal": proposal.suggested_goal_minutes if proposal else None}, ensure_ascii=False),
                    "model": model,
                },
            ).lastrowid
            instructions_id = _write_instructions(conn, lang, proposal, ctx, report_id) if proposal else None
            version = (conn.execute(text("SELECT MAX(profile_version) FROM profile_snapshots WHERE language_code = :l"), {"l": lang}).scalar() or 0) + 1
            conn.execute(
                text(
                    "INSERT INTO profile_snapshots (language_code, profile_version, reason, profile_json, report_id) "
                    "VALUES (:l, :v, 'weekly_evolve', :p, :r)"
                ),
                {"l": lang, "v": version, "p": json.dumps({**profile, "band_shift": band_shift(conn, lang)}, default=str), "r": report_id},
            )
            if adjustments and adjustments[0]["from"] != adjustments[0]["to"]:
                content.rescore_language(conn, lang)
        sections.append(
            {"name": name, "metrics": m, "level": level, "narrative": proposal.narrative_md if proposal else "",
             "adjustments": adjustments, "notes": notes, "goal": proposal.suggested_goal_minutes if proposal else None}
        )
        summary["languages"][lang] = {
            "report_id": report_id, "minutes": m["minutes_total"], "adjustments": adjustments, "notes": notes,
            "tutor_brief_updated": instructions_id is not None, "model": model,
        }

    if not dry_run and sections:
        folder = cfg.data_dir / "reports"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{period}.md"
        path.write_text(_markdown(period_label, sections), encoding="utf-8")
        rel = path.relative_to(cfg.data_dir).as_posix()
        with engine.begin() as conn:
            ids = [v["report_id"] for v in summary["languages"].values()]
            conn.execute(
                text(f"UPDATE progress_reports SET markdown_path = :p WHERE id IN ({','.join(str(int(i)) for i in ids)})"), {"p": rel}
            )
        summary["markdown"] = rel
    summary["finished_at"] = to_iso(utc_now())
    return summary


def reports(conn: Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT markdown_path, MIN(period_start), MAX(period_end), MAX(created_at), GROUP_CONCAT(language_code), "
            "SUM(json_extract(metrics_json, '$.minutes_total')) FROM progress_reports WHERE markdown_path IS NOT NULL "
            "GROUP BY markdown_path ORDER BY MAX(created_at) DESC LIMIT :n"
        ),
        {"n": limit},
    ).all()
    return [
        {"path": r[0], "start": r[1], "end": r[2], "created_at": r[3], "languages": (r[4] or "").split(","), "minutes": round(r[5] or 0)}
        for r in rows
    ]
