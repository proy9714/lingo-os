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
