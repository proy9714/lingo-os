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
    """List the Gemini models your key can use (to pin one in config/llm.yaml)."""
    from app.ai.providers import GeminiProvider, ProviderError

    gateway = _gateway()
    for name, provider in gateway.providers.items():
        if isinstance(provider, GeminiProvider):
            try:
                models = provider.list_models()
            except ProviderError as exc:
                console.print(f"{name}: {exc}")
                continue
            console.print(f"{name}: " + ", ".join(sorted(models)))


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
    path: Optional[Path] = typer.Option(None, help="Folder with immersion_log_*.csv. Default: config/app.yaml."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Import or re-sync your Immersion Tracker CSVs (safe to run repeatedly)."""
    from app.ingest import immersion_tracker as tracker
    from app.main import bootstrap

    cfg = load_config()
    folder = path or cfg.tracker_path
    if folder is None:
        console.print("[red]No folder given and none configured in config/app.yaml[/]")
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


if __name__ == "__main__":
    app()
