"""Background job: get a language ready (download its word-splitting model and dictionary), then add it."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable

import httpx

from app.jobs.runner import JobContext, register

CHUNK = 1 << 16


def download(url: str, target: Path, say: Callable[[float], None]) -> Path:
    """Stream a file to `target` (via a .part file), reporting the share done."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        done = 0
        with partial.open("wb") as out:
            for chunk in response.iter_bytes(CHUNK):
                out.write(chunk)
                done += len(chunk)
                if total:
                    say(done / total)
    partial.replace(target)
    return target


def extract_model(wheel: Path, target: Path) -> None:
    """A spaCy model wheel holds <name>/<name>-<version>/config.cfg …: keep just that folder."""
    staging = target.with_name(target.name + ".new")
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(wheel) as archive:
        config = next((n for n in archive.namelist() if n.endswith("/config.cfg") and n.count("/") == 2), None)
        if not config:
            raise RuntimeError(f"{wheel.name} doesn't look like a spaCy model")
        prefix = config.rsplit("/", 1)[0] + "/"
        for name in archive.namelist():
            if name.startswith(prefix) and not name.endswith("/"):
                dest = staging / name[len(prefix):]
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
    shutil.rmtree(target, ignore_errors=True)
    staging.replace(target)


@register("install_language")
def install_language(ctx: JobContext) -> dict[str, Any]:
    from app.config import forget_added_languages
    from app.db.engine import make_engine
    from app.dictionary.yomitan import import_dictionary
    from app.languages import forget_pack, registry
    from app.services import languages

    code = ctx.payload["code"]
    variant = ctx.payload.get("variant")
    spec = registry.spec(code)
    result: dict[str, Any] = {"code": code, "model": None, "dictionary": None}

    # 1. The word-splitting model (0-60% of the progress bar).
    if spec.model and not languages.model_ready(ctx.cfg, code):
        cache = ctx.cfg.data_dir / "cache" / "downloads"
        wheel = cache / spec.model.url.rsplit("/", 1)[-1]
        ctx.progress(0.02, f"downloading the {spec.name} language model ({spec.model.size_mb} MB)")
        download(spec.model.url, wheel, lambda f: ctx.progress(0.02 + 0.5 * f, f"downloading the {spec.name} language model"))
        ctx.progress(0.55, "unpacking the language model")
        extract_model(wheel, languages.model_dir(ctx.cfg, spec.model.name))
        wheel.unlink(missing_ok=True)
        forget_pack(code)
        result["model"] = spec.model.name

    # The language works from here on: add it now, the dictionary follows.
    with ctx.engine.begin() as conn:
        languages.finish_install(conn, ctx.cfg, code, variant)
    forget_added_languages()

    # 2. The dictionary (60-100%). Failing here leaves the language usable (lookups then show "no entry").
    dict_engine = make_engine(ctx.cfg.dict_db_path)
    with dict_engine.connect() as conn:
        have = languages.dictionaries_of(conn, code)
    if not have:
        target = ctx.cfg.data_dir / "dictionaries" / spec.dictionary.file
        try:
            if not target.exists():
                ctx.progress(0.6, f"downloading the {spec.name} dictionary ({spec.dictionary.size_mb} MB)")
                download(spec.dictionary.url, target, lambda f: ctx.progress(0.6 + 0.2 * f, f"downloading the {spec.name} dictionary"))
            ctx.progress(0.82, f"importing the {spec.name} dictionary")
            with dict_engine.begin() as conn:
                imported = import_dictionary(
                    conn, target, language=code,
                    progress=lambda done, total: ctx.progress(0.82 + 0.17 * done / max(total, 1), f"importing the dictionary ({done}/{total})"),
                )
            result["dictionary"] = imported["dictionary"]
        except Exception as exc:  # noqa: BLE001 - network or a changed file: the language still works
            result["dictionary_error"] = f"{type(exc).__name__}: {exc}"[:300]
    dict_engine.dispose()

    # 3. Start looking for things to watch and read in it.
    try:
        from app.services import topup

        with ctx.engine.begin() as conn:
            topup.maybe_top_up(conn, code)
    except Exception:  # noqa: BLE001 - suggestions will be looked for on the next page visit anyway
        pass
    ctx.progress(1.0, f"{spec.name} is ready")
    return result


@register("rescore")
def rescore(ctx: JobContext) -> dict[str, Any]:
    """Your starting estimate changed: score everything in the language again, then re-rank."""
    from app.services import content, recommend

    lang = ctx.payload["lang"]
    ctx.progress(0.05, "re-scoring your content")
    with ctx.engine.begin() as conn:
        count = content.rescore_language(conn, lang)
    recommend.invalidate()
    return {"language": lang, "rescored": count}
