"""`lingo` command line. Every data command has --json so AI terminals can read it."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from app.config import load_config

app = typer.Typer(help="Lingo OS command line.", no_args_is_help=True, add_completion=False)
db_app = typer.Typer(help="Database commands.", no_args_is_help=True)
app.add_typer(db_app, name="db")
console = Console()


@app.callback()
def _main() -> None:
    # Windows consoles default to cp1252; Japanese titles need UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _emit_json(data: object) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply pending migrations to lingo.db and dictionaries.db."""
    from app.main import bootstrap

    cfg = load_config()
    from app.db import migrate

    pending_main = [p.stem for p in migrate.available("main") if p.stem not in migrate.applied(cfg.db_path)]
    pending_dict = [p.stem for p in migrate.available("dict") if p.stem not in migrate.applied(cfg.dict_db_path)]
    bootstrap(cfg)
    console.print(f"Data folder: {cfg.data_dir}")
    console.print(f"lingo.db: applied {pending_main or 'nothing (up to date)'}")
    console.print(f"dictionaries.db: applied {pending_dict or 'nothing (up to date)'}")


dict_app = typer.Typer(help="Dictionary commands.", no_args_is_help=True)
app.add_typer(dict_app, name="dict")


@dict_app.command("import")
def dict_import(
    paths: Optional[list[Path]] = typer.Argument(None, help="Yomitan zips. Default: every zip in data/dictionaries."),
    language: Optional[str] = typer.Option(None, help="Override the language from index.json."),
) -> None:
    """Import Yomitan dictionaries (re-importing replaces the old copy)."""
    import time

    from app.db.engine import make_engine
    from app.dictionary.yomitan import import_dictionary
    from app.main import bootstrap

    cfg = load_config()
    bootstrap(cfg)
    files = paths or sorted((cfg.data_dir / "dictionaries").glob("*.zip"))
    if not files:
        console.print(f"No dictionary zips found in {cfg.data_dir / 'dictionaries'}")
        raise typer.Exit(code=1)
    engine = make_engine(cfg.dict_db_path)
    for path in files:
        started = time.time()
        console.print(f"Importing {path.name} …")
        with engine.begin() as conn:
            result = import_dictionary(
                conn,
                path,
                language=language,
                progress=lambda done, total: console.print(f"  bank {done}/{total}", end="\r"),
            )
        console.print(
            f"  {result['dictionary']} ({result['language']}): {result['entries']:,} entries "
            f"({result['inflected_forms']:,} inflected forms) in {time.time() - started:.0f} s"
        )


@dict_app.command("list")
def dict_list(as_json: bool = typer.Option(False, "--json", help="Machine-readable output.")) -> None:
    """Show installed dictionaries."""
    from app.db.engine import make_engine
    from app.dictionary.yomitan import list_dictionaries
    from app.main import bootstrap

    cfg = load_config()
    bootstrap(cfg)
    with make_engine(cfg.dict_db_path).begin() as conn:
        rows = list_dictionaries(conn)
    if as_json:
        _emit_json(rows)
        return
    table = Table(title="Dictionaries")
    for column in ("Lang", "Name", "Revision", "Entries", "File"):
        table.add_column(column)
    for row in rows:
        table.add_row(row["language"], row["name"], row["revision"], f"{row['entries']:,}", row["file"])
    console.print(table)


content_app = typer.Typer(help="Library commands.", no_args_is_help=True)
app.add_typer(content_app, name="content")


@content_app.command("fetch-history")
def content_fetch_history(
    lang: Optional[str] = typer.Option(None, "--lang", help="de, es or ja. Default: all."),
    limit: Optional[int] = typer.Option(None, help="Stop after this many videos."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Fetch YouTube captions for videos you've watched, analyse them, refresh your starting estimate."""
    from app.engine.evidence import content_evidence
    from app.jobs.history import fetch_history_captions, pending_videos
    from app.jobs.runner import JobContext
    from app.main import bootstrap

    cfg = load_config()
    engine = bootstrap(cfg)
    with engine.begin() as conn:
        todo = len(pending_videos(conn, lang, limit))
    if not as_json:
        console.print(f"{todo} videos to fetch (about {todo * 4 // 60 + 1} min; pauses between requests are deliberate).")
    ctx = JobContext(
        engine, cfg, None, {"lang": lang, "limit": limit},
        on_progress=None if as_json else (lambda f, m: console.print(f"  {round(f * 100):3d}%  {m}"[:110])),
    )
    result = fetch_history_captions(ctx)
    with engine.begin() as conn:
        evidence = {code: content_evidence(conn, code) for code in cfg.language_codes if lang in (None, code)}
    if as_json:
        _emit_json({"result": result, "evidence": evidence})
        return
    console.print(result)
    for code, ev in evidence.items():
        console.print(
            f"{code.upper()}: {ev['videos_analysed']}/{ev['videos_watched']} videos analysed · "
            f"{ev['content_words_heard']:,} content words heard · {ev['lemmas_heard_10_plus']:,} words heard 10+ times · "
            f"typical video needs ~{ev['vocabulary_for_90_percent']} words for 90% coverage"
        )


@content_app.command("rescore")
def content_rescore(
    lang: Optional[str] = typer.Option(None, "--lang", help="de, es or ja. Default: all."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Refresh the starting estimate and re-score every analysed item against your current profile."""
    from app.engine.evidence import content_evidence
    from app.engine.profile import get_profile, sync_baselines
    from app.main import bootstrap
    from app.services.content import rescore_language

    cfg = load_config()
    out = {}
    with bootstrap(cfg).begin() as conn:
        sync_baselines(conn, cfg)
        for code in cfg.language_codes:
            if lang not in (None, code):
                continue
            profile = get_profile(conn, code) or {}
            out[code] = {
                "rescored": rescore_language(conn, code),
                "vocabulary_for_90_percent": content_evidence(conn, code)["vocabulary_for_90_percent"],
                "profile_words": round(profile.get("vocab_size") or 0),
                "level": profile.get("level"),
                "measured": bool(profile.get("measured")),
            }
    if as_json:
        _emit_json(out)
        return
    for code, row in out.items():
        console.print(
            f"{code.upper()}: {row['rescored']} items re-scored · typical item needs ~{row['vocabulary_for_90_percent']} words "
            f"for 90% · estimate ≈ {row['profile_words']:,} words, {row['level']} "
            f"({'measured' if row['measured'] else 'starting estimate'})"
        )


@content_app.command("scan")
def content_scan() -> None:
    """Register media files in data/library/media/<lang>/ (same-named .srt/.vtt become transcripts)."""
    from app.main import bootstrap
    from app.services.content import scan_media

    cfg = load_config()
    with bootstrap(cfg).begin() as conn:
        console.print(scan_media(conn, cfg))


@app.command("update-content")
def update_content_cmd(
    lang: Optional[str] = typer.Option(None, "--lang", help="de, es or ja. Default: all."),
    limit: Optional[int] = typer.Option(None, "--limit", help="New videos to check per language (default from config/sources.yaml)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="List what would be checked; write nothing."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Find new videos and articles near your level (YouTube, RSS feeds, Comprehensible Input Wiki sources)."""
    from app.main import bootstrap
    from app.services.discover import update_content

    cfg = load_config()
    engine = bootstrap(cfg)
    result = update_content(
        engine, cfg, lang, per_run=limit, dry_run=dry_run,
        progress=None if as_json else (lambda fraction, message: console.print(f"  {round(fraction * 100):3d}%  {message}"[:110])),
    )
    if as_json:
        _emit_json(result)
        return
    for code, row in result.items():
        wiki = row.get("wiki") or {}
        console.print(
            f"{code.upper()}: {row.get('catalogued', 0)} new videos in the catalogue · {row['checked']} measured · "
            f"{row['added']} videos and {row['articles_added']} articles kept · {row['off_level']} off-level · "
            f"{row['no_captions']} without captions"
            + (" · stopped early (YouTube refused)" if row["stopped_early"] else "")
        )
        if wiki.get("skipped") or wiki.get("error"):
            console.print(f"    wiki: {wiki.get('skipped') or wiki.get('error')}")
        elif wiki:
            console.print(f"    wiki: {wiki.get('resources', 0)} resources, {wiki.get('added', 0)} new")
        for title in row["added_titles"][:8]:
            console.print(f"    + {title[:90]}")
        for error in row["errors"][:3]:
            console.print(f"    ! {error[:100]}")


sources_app = typer.Typer(help="Content sources (Comprehensible Input Wiki and config/sources.yaml).", no_args_is_help=True)
app.add_typer(sources_app, name="sources")


@sources_app.command("list")
def sources_list(
    lang: str = typer.Option(..., "--lang", help="de, es or ja."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Sources known for a language, with level labels and whether they are fetched."""
    from app.main import bootstrap
    from app.services.discover import list_sources

    cfg = load_config()
    with bootstrap(cfg).begin() as conn:
        rows = list_sources(conn, lang)
    if as_json:
        _emit_json(rows)
        return
    table = Table(title=f"Sources ({lang}) · {len(rows)}")
    for column in ("Name", "Kind", "Level", "Fetched", "Flags"):
        table.add_column(column)
    for row in rows:
        table.add_row(row["name"][:40], row["kind"], row["level_label"] or "", "yes" if row["enabled"] else "link only",
                      ", ".join(row["config"].get("flags", [])))
    console.print(table)


@sources_app.command("sync-wiki")
def sources_sync_wiki(lang: Optional[str] = typer.Option(None, "--lang", help="de, es or ja. Default: all.")) -> None:
    """Read the language pages of comprehensibleinputwiki.org (at most once a week, as robots.txt allows)."""
    from app.ingest.ci_wiki import WikiError
    from app.main import bootstrap
    from app.services.discover import sync_wiki

    cfg = load_config()
    engine = bootstrap(cfg)
    for code in cfg.language_codes:
        if lang not in (None, code):
            continue
        try:
            console.print(sync_wiki(engine, cfg, code))
        except WikiError as exc:
            console.print(f"{code}: {exc}")


@app.command("evolve-profile")
def evolve_profile_cmd(
    days: int = typer.Option(7, "--days", min=1, max=31, help="Length of the window."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Metrics and deterministic adjustments only."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print metrics and context; write nothing."),
    apply: Optional[Path] = typer.Option(None, "--apply", help="A proposal JSON written by the agent terminal."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Weekly review: metrics, band calibration with guardrails, tutor brief and report (data/reports/)."""
    import json as json_lib

    from app.ai.config import load_ai_config
    from app.ai.gateway import Gateway
    from app.main import bootstrap
    from app.services.evolve import evolve

    cfg = load_config()
    engine = bootstrap(cfg)
    proposals = None
    if apply is not None:
        data = json_lib.loads(apply.read_text(encoding="utf-8"))
        proposals = data.get("languages", data)
    gateway = None if no_llm or apply else Gateway(load_ai_config(cfg.root), engine)
    result = evolve(engine, cfg, gateway, days=days, use_llm=not no_llm, proposals=proposals, dry_run=dry_run)
    if as_json:
        _emit_json(result)
        return
    console.print(f"Week {result['period']} ({result['start']} to {result['end']})")
    for code, row in result["languages"].items():
        if dry_run:
            console.print(f"  {code.upper()}: {row['metrics']['minutes_total']:.0f} min")
            continue
        changes = "; ".join(a["reason"] for a in row["adjustments"]) or "no band change"
        console.print(f"  {code.upper()}: {row['minutes']:.0f} min · {changes}" + (" · tutor brief updated" if row["tutor_brief_updated"] else ""))
        for note in row["notes"]:
            console.print(f"     {note}")
    if result.get("markdown"):
        console.print(f"Report: data/{result['markdown']}")


brief_app = typer.Typer(help="The tutor's weekly brief.", no_args_is_help=True)
app.add_typer(brief_app, name="tutor-brief")


@brief_app.command("show")
def tutor_brief_show(
    lang: str = typer.Option(..., "--lang", help="de, es or ja."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """The active brief the tutor follows."""
    from app.main import bootstrap
    from app.services.tutor import active_instructions

    cfg = load_config()
    with bootstrap(cfg).begin() as conn:
        brief = active_instructions(conn, lang)
    if as_json:
        _emit_json(brief)
        return
    console.print(brief["instructions_md"])
    console.print(f"style: {brief['style']}")


@brief_app.command("set")
def tutor_brief_set(
    lang: str = typer.Option(..., "--lang", help="de, es or ja."),
    file: Path = typer.Option(..., "--file", help="JSON: {tutor_instructions_md, focus_words, focus_grammar, style}."),
) -> None:
    """Replace the brief from a proposal file (validated with the same guardrails as the weekly review)."""
    import json as json_lib

    from app.main import bootstrap
    from app.services.evolve import Proposal, _write_instructions, context_for, validate

    cfg = load_config()
    proposal = Proposal.model_validate(json_lib.loads(file.read_text(encoding="utf-8")))
    with bootstrap(cfg).begin() as conn:
        ctx = context_for(conn, lang)
        proposal, notes = validate(proposal, ctx)
        new_id = _write_instructions(conn, lang, proposal, ctx, None)
    console.print(f"Brief {'saved' if new_id else 'unchanged (empty proposal)'}." + (f" Guardrails: {'; '.join(notes)}" if notes else ""))


manga_app = typer.Typer(help="Manga library.", no_args_is_help=True)
app.add_typer(manga_app, name="manga")


@manga_app.command("scan")
def manga_scan(as_json: bool = typer.Option(False, "--json", help="Machine-readable output.")) -> None:
    """Import volumes dropped into data/inbox/manga/ (.mokuro + images, image folders, .zip/.cbz)."""
    from app.main import bootstrap
    from app.services.manga import scan_inbox

    cfg = load_config()
    with bootstrap(cfg).begin() as conn:
        result = scan_inbox(conn, cfg)
    if as_json:
        _emit_json(result)
        return
    console.print(f"Inbox: {result['folder']}")
    for row in result["results"]:
        console.print(f"  {row['title']}: {row['status']}")
    if not result["results"]:
        console.print("  Nothing new.")


data_app = typer.Typer(help="Back up all your data to one file, or restore it.", no_args_is_help=True)
app.add_typer(data_app, name="data")


@data_app.command("export")
def data_export(
    path: Optional[Path] = typer.Argument(None, help="Where to write the backup (default: data/backups/)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Write everything (database, library, recordings, reports) to one .lingo file."""
    from app.main import bootstrap
    from app.services import backup

    cfg = load_config()
    bootstrap(cfg)
    target = backup.export(cfg, path)
    if as_json:
        _emit_json({"path": str(target), **backup.inspect(target)})
        return
    console.print(f"Backup written: {target} ({target.stat().st_size // 1024 // 1024} MB)")


@data_app.command("import")
def data_import(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, help="A .lingo backup file."),
    yes: bool = typer.Option(False, "--yes", help="Don't ask for confirmation."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Replace this computer's data with a backup (the current data is saved in data/backups first)."""
    from app.main import bootstrap
    from app.services import backup

    cfg = load_config()
    try:
        manifest = backup.inspect(path)
    except backup.BackupError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    if not yes and not typer.confirm(
        f"Replace this computer's data with the backup from {manifest['created_at'][:10]} "
        f"({', '.join(manifest.get('languages') or []) or 'no languages'})?"
    ):
        raise typer.Exit(1)
    result = backup.restore(cfg, bootstrap(cfg), path)
    if as_json:
        _emit_json(result)
        return
    console.print(f"Restored. Your previous data was saved as {result['previous_data']}.")
    if result["downloading"]:
        console.print("Dictionaries and language models download again when the app runs: " + ", ".join(result["downloading"]))


ai_app = typer.Typer(help="AI gateway (config/llm.yaml).", no_args_is_help=True)
app.add_typer(ai_app, name="ai")


def _gateway():
    from app.ai.config import load_ai_config
    from app.ai.gateway import Gateway
    from app.main import bootstrap

    cfg = load_config()
    return Gateway(load_ai_config(cfg.root), bootstrap(cfg))


@ai_app.command("status")
def ai_status(as_json: bool = typer.Option(False, "--json", help="Machine-readable output.")) -> None:
    """Which provider and model each task would use, or why AI is off."""
    gateway = _gateway()
    out = {task: gateway.status(task) for task in gateway.cfg.tasks}
    out["usage_30_days"] = gateway.usage(30)
    if as_json:
        _emit_json(out)
        return
    for task, row in out.items():
        if task == "usage_30_days":
            continue
        console.print(f"{task:24} " + (f"{row['provider']} / {row['model']}" if row["enabled"] else f"off: {row['reason']}"))
    usage = out["usage_30_days"]
    console.print(f"Last 30 days: {usage['calls']} calls, {usage['cache_hits']} answered from cache.")


@ai_app.command("test")
def ai_test() -> None:
    """Make one tiny call to check the key and model."""
    from pydantic import BaseModel

    from app.ai.gateway import AIUnavailable

    class Ping(BaseModel):
        ok: bool

    try:
        result, meta = _gateway().structured("lookup.context_gloss", "ping", {"word": "Hallo"}, Ping, cache=False)
    except AIUnavailable as exc:
        console.print(f"[red]AI is off:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]OK[/green] {meta['provider']} / {meta['model']} answered: {result.ok}")


@ai_app.command("models")
def ai_models() -> None:
    """List the models each key can use (Gemini, Claude, ChatGPT), to pick in Settings or config/llm.yaml."""
    from app.ai.providers import ProviderError

    gateway = _gateway()
    for name in gateway.cfg.choosable:
        label = gateway.cfg.providers[name].label
        reason = gateway.cfg.providers[name].unavailable_reason()
        if reason:
            console.print(f"{label}: {reason}")
            continue
        try:
            models = gateway.providers[name].list_models()
        except ProviderError as exc:
            console.print(f"{label}: {exc}")
            continue
        console.print(f"{label}: " + ", ".join(sorted(models)))


@app.command()
def serve(
    host: Optional[str] = typer.Option(None, help="Defaults to config/app.yaml (127.0.0.1)."),
    port: Optional[int] = typer.Option(None, help="Defaults to config/app.yaml (8787)."),
    reload: bool = typer.Option(False, help="Reload on code changes (development)."),
) -> None:
    """Run the app: API plus the built frontend at http://127.0.0.1:8787."""
    import uvicorn

    cfg = load_config()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=host or cfg.host,
        port=port or cfg.port,
        reload=reload,
        reload_dirs=[str(cfg.root / "backend" / "app")] if reload else None,
    )


@app.command()
def doctor(as_json: bool = typer.Option(False, "--json", help="Machine-readable output.")) -> None:
    """Check the environment: Python, data folder, databases, build, ffmpeg, API keys."""
    from app.main import bootstrap
    from app.services.doctor import run_checks

    cfg = load_config()
    bootstrap(cfg)
    report = run_checks(cfg)
    if as_json:
        _emit_json(report)
        return
    table = Table(title=f"Lingo OS {report['version']} - doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for check in report["checks"]:
        status = "[green]ok[/]" if check["ok"] else ("[red]FAIL[/]" if check["required"] else "[yellow]later[/]")
        table.add_row(check["name"], status, check["detail"])
    console.print(table)
    if not report["ok"]:
        raise typer.Exit(code=1)


@app.command()
def status(
    lang: Optional[str] = typer.Option(None, "--lang", help="de, es or ja. Default: all."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Hours, sessions and the starting level estimate per language."""
    from app.main import bootstrap
    from app.services import stats

    cfg = load_config()
    engine = bootstrap(cfg)
    with engine.begin() as conn:
        data = stats.overview(conn, cfg)
        today = {code: stats.today_stats(conn, cfg, code) for code in cfg.language_codes}
    languages = [entry for entry in data["languages"] if lang is None or entry["language"] == lang]
    if lang and not languages:
        console.print(f"[red]Unknown language '{lang}'. Use one of: {', '.join(cfg.language_codes)}[/]")
        raise typer.Exit(code=2)
    for entry in languages:
        entry["today"] = today[entry["language"]]
    if as_json:
        _emit_json({"languages": languages})
        return
    table = Table(title="Lingo OS - status")
    for column in ("Lang", "Total h", "Before tracking", "Tracked", "Sessions", "Last session", "Today", "Level (hours only)"):
        table.add_column(column)
    for entry in languages:
        est = entry["estimate"]
        today_entry = entry["today"]
        table.add_row(
            entry["language"].upper(),
            f"{entry['total_hours']:.1f}",
            f"{entry['baseline_hours']:.1f}",
            f"{entry['tracked_hours']:.1f}",
            str(entry["sessions"]),
            entry["last_session_date"] or "-",
            f"{today_entry['today_minutes']}/{today_entry['goal_minutes']} min",
            f"{est['level']} of {est['max_level']} (~{est['words_prior']} words, low confidence)",
        )
    console.print(table)


@app.command()
def recommend(
    lang: Optional[str] = typer.Option(None, "--lang", help="de, es or ja. Default: the active language."),
    n: int = typer.Option(12, min=1, max=50, help="How many picks."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Up Next: picks matched to your level, with the reasons for each."""
    from app.db import settings_store
    from app.main import bootstrap
    from app.services.recommend import up_next

    cfg = load_config()
    with bootstrap(cfg).begin() as conn:
        code = lang or settings_store.get(conn, "active_language") or cfg.language_codes[0]
        result = up_next(conn, code, n)
    keep = ("id", "kind", "type", "title", "creator", "duration_sec", "word_count", "coverage", "band", "expected_unknown", "reasons")
    result["picks"] = [{k: pick[k] for k in keep} for pick in result["picks"]]
    if as_json:
        _emit_json(result)
        return
    table = Table(title=f"Up next ({code}) · {len(result['picks'])} of {result['available']} analysed")
    for column in ("#", "Title", "Channel / author", "Fit", "Why"):
        table.add_column(column)
    for i, pick in enumerate(result["picks"], 1):
        table.add_row(str(i), pick["title"][:60], pick["creator"] or "", pick["band"] or "", "; ".join(pick["reasons"]))
    console.print(table)


@app.command("import-tracker")
def import_tracker(
    path: Optional[Path] = typer.Option(None, help="Folder with immersion_log_*.csv. Default: config/app.local.yaml or config/app.yaml."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Import or re-sync your Immersion Tracker CSVs (safe to run repeatedly)."""
    from app.ingest import immersion_tracker as tracker
    from app.main import bootstrap

    cfg = load_config()
    folder = path or cfg.tracker_path
    if folder is None:
        console.print("[red]No folder given and none configured (immersion_tracker.path in config/app.local.yaml)[/]")
        raise typer.Exit(code=2)
    engine = bootstrap(cfg)
    with engine.begin() as conn:
        summary = tracker.import_tracker_folder(conn, cfg.data_dir, folder, cfg.language_codes)
        flags = tracker.pending_flags(conn)
    summary["pending_flags"] = flags
    if as_json:
        _emit_json(summary)
        return
    table = Table(title=f"Immersion Tracker import - {folder}")
    for column in ("Lang", "Status", "Rows", "New", "Already there", "Flagged", "Errors"):
        table.add_column(column)
    for item in summary["files"]:
        table.add_row(
            item["language"].upper(),
            item["status"],
            str(item["rows"]),
            str(item["imported"]),
            str(item["already_present"]),
            str(len(item["duplicates"])),
            str(len(item["errors"])),
        )
    console.print(table)
    if summary["goals_imported"]:
        console.print(f"Daily goals copied from the tracker: {summary['goals_imported']}")
    for flag in flags:
        console.print(
            f"[yellow]Not counted (probable double-log):[/] {flag['language'].upper()} {flag['date']} "
            f"'{flag['title']}' - {flag['reason']}. Count it from Settings if it was a real rewatch."
        )


# ------------------------------------------------------------------ releases

release_app = typer.Typer(help="Publish a release to GitHub (with the Android APK).", no_args_is_help=True)
app.add_typer(release_app, name="release")


@release_app.command("check")
def release_check(as_json: bool = typer.Option(False, "--json", help="Machine-readable output.")) -> None:
    """What changed since the last GitHub release, and whether it's worth a new one."""
    from app.release import ReleaseError, check

    try:
        state = check(load_config().root)
    except ReleaseError as exc:
        if as_json:
            _emit_json({"error": str(exc)})
        else:
            console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if as_json:
        _emit_json(state)
        return
    last = state["last_release"]
    console.print(f"Last release: {last['tagName'] + ' (' + last['publishedAt'][:10] + ')' if last else 'none yet'}")
    console.print(f"Commits since: {len(state['commits'])} · app files changed: {len(state['app_files_changed'])}")
    for commit in state["commits"][:20]:
        console.print(f"  {commit['sha']} {commit['subject']}")
    verdict = "[green]worth a release[/]" if state["should_release"] else "[yellow]nothing to release[/]"
    console.print(f"{verdict}: {state['reason']}. Suggested version: v{state['suggested_version']} ({state['suggested_bump']})")


@release_app.command("publish")
def release_publish(
    version: str = typer.Option(..., "--version", help="The new version, e.g. 0.3.0."),
    notes: Path = typer.Option(..., "--notes", exists=True, dir_okay=False, help="Markdown file with the release notes."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Test and build the signed APK, but commit and publish nothing."),
    skip_tests: bool = typer.Option(False, "--skip-tests", help="Don't run the test suite first."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Test, set the version, build and sign the APK, commit, tag, push and create the GitHub release."""
    from app.release import ReleaseError, publish

    say = (lambda message: None) if as_json else (lambda message: console.print(f"[dim]… {message}[/]"))
    try:
        result = publish(load_config().root, version, notes, dry_run=dry_run, skip_tests=skip_tests, say=say)
    except ReleaseError as exc:
        if as_json:
            _emit_json({"error": str(exc)})
        else:
            console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if as_json:
        _emit_json(result)
    elif result["dry_run"]:
        console.print(f"[green]Dry run OK[/]: signed {result['apk']} ({result['apk_bytes'] // 1024} KB). Nothing was committed or published.")
    else:
        console.print(f"[green]Published v{result['version']}[/]: {result['url']}")


if __name__ == "__main__":
    app()
