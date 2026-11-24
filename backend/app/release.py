"""Publishing a release: `lingo release check` and `lingo release publish` (the `/lingo release` mode drives them).

check    finds the last GitHub release, lists the commits and app files changed since, and suggests a version.
         Changes only to docs, tests or the AI-terminal playbooks don't make a release.
publish  runs the tests, sets the version everywhere, builds and signs the Android APK with the release key, then
         commits "Release vX.Y.Z", tags it, pushes, and creates the GitHub release with the APK attached. A failed
         build leaves nothing behind: the version files are put back.

One version for everything lives in the root package.json; Gradle derives the APK's versionCode from it.
The signing key stays on this computer (~/.lingo, see docs/RELEASING.md), so every release is signed with the same
key and phones (and Obtainium) accept updates.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_URL_FALLBACK = "https://github.com/proy9714/lingo-os"
APK_NAME = "lingo-os-v{version}.apk"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

# What counts as a change to the app itself (anything users would get by updating).
APP_PATHS = (
    "backend/app/", "backend/pyproject.toml", "config/", "frontend/src/", "frontend/public/", "frontend/index.html",
    "frontend/package.json", "frontend/capacitor.config.ts", "frontend/vite.config.ts", "frontend/android/app/src/",
    "frontend/android/app/build.gradle", "frontend/android/build.gradle", "frontend/android/variables.gradle",
)
# Files whose version is set by publish.
VERSION_FILES = ("package.json", "frontend/package.json", "backend/pyproject.toml", "backend/app/__init__.py", "backend/uv.lock")


class ReleaseError(RuntimeError):
    pass


# ------------------------------------------------------------------ helpers


def _run(args: list[str], cwd: Path, *, env: dict[str, str] | None = None, check: bool = True, timeout: int = 1800) -> str:
    exe = shutil.which(args[0]) or args[0]
    result = subprocess.run(
        [exe, *args[1:]], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
    )
    if check and result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-15:]
        raise ReleaseError(f"`{' '.join(args[:3])}` failed:\n" + "\n".join(tail))
    return result.stdout


def _git(root: Path, *args: str, check: bool = True) -> str:
    return _run(["git", *args], root, check=check).strip()


def version_tuple(version: str) -> tuple[int, int, int]:
    match = SEMVER.match(version.removeprefix("v"))
    if not match:
        raise ReleaseError(f"'{version}' is not a version like 1.2.3")
    return int(match[1]), int(match[2]), int(match[3])


def bump(version: str, part: str) -> str:
    major, minor, patch = version_tuple(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def current_version(root: Path) -> str:
    return json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]


def repo_url(root: Path) -> str:
    url = _git(root, "remote", "get-url", "origin", check=False)
    match = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
    return f"https://github.com/{match[1]}" if match else REPO_URL_FALLBACK


def is_app_file(path: str) -> bool:
    return path.startswith(APP_PATHS)


# ------------------------------------------------------------------ check


def last_release(root: Path) -> dict[str, Any] | None:
    """The latest published GitHub release, or None before the first one."""
    out = subprocess.run(
        [shutil.which("gh") or "gh", "release", "view", "--json", "tagName,name,publishedAt,url"],
        cwd=root, capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        if "not found" in (out.stderr or "").lower():
            return None
        raise ReleaseError(f"GitHub CLI: {(out.stderr or out.stdout).strip()[:300]}")
    return json.loads(out.stdout)


def check(root: Path) -> dict[str, Any]:
    _git(root, "fetch", "--tags", "--quiet", "origin", check=False)
    last = last_release(root)
    tag = last["tagName"] if last else None
    if tag and not _git(root, "tag", "--list", tag):
        raise ReleaseError(f"The last release's tag {tag} isn't in this clone; run `git fetch --tags`.")
    span = f"{tag}..HEAD" if tag else "HEAD"
    raw = _git(root, "log", span, "--no-merges", "--format=%h%x1f%s%x1f%b%x1e")
    commits = []
    for entry in raw.split("\x1e"):
        if entry.strip():
            sha, subject, body = (entry.strip("\n").split("\x1f") + ["", ""])[:3]
            commits.append({"sha": sha, "subject": subject, "body": body.strip()})
    if tag:
        changed = [line.split("\t") for line in _git(root, "diff", "--name-status", tag, "HEAD").splitlines() if line]
    else:
        changed = [["A", path] for path in _git(root, "ls-files").splitlines()]
    files = [{"status": parts[0][0], "path": parts[-1]} for parts in changed]
    app_files = [f for f in files if is_app_file(f["path"])]
    dirty = [line for line in _git(root, "status", "--porcelain", "--untracked-files=no").splitlines() if line]
    version = current_version(root)
    base = last["tagName"].removeprefix("v") if last else version
    added_app_files = any(f["status"] == "A" for f in app_files)
    featureish = any(re.search(r"\b(add|adds|added|new|support|feature)\b", c["subject"], re.I) for c in commits)
    part = "minor" if (added_app_files or featureish or not last) else "patch"
    suggested = bump(base, part)
    if version_tuple(suggested) <= version_tuple(version) and not last:
        suggested = bump(version, part)
    return {
        "last_release": last,
        "current_version": version,
        "commits": commits,
        "files_changed": len(files),
        "app_files_changed": [f["path"] for f in app_files],
        "should_release": bool(app_files),
        "reason": "app code changed since the last release" if app_files else (
            "no changes since the last release" if not files else "only docs, tests or playbooks changed"
        ),
        "suggested_bump": part,
        "suggested_version": suggested,
        "uncommitted_changes": dirty,
        "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "unpushed_commits": int(_git(root, "rev-list", "--count", "@{u}..HEAD", check=False) or 0),
    }


# ------------------------------------------------------------------ toolchain


@dataclass
class Toolchain:
    env: dict[str, str]
    build_tools: Path
    keystore_properties: Path


def keystore_properties_path() -> Path:
    return Path(os.environ.get("LINGO_KEYSTORE_PROPERTIES") or Path.home() / ".lingo" / "release-keystore.properties")


def _read_properties(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
    return out


def toolchain() -> Toolchain:
    env = dict(os.environ)
    java = env.get("JAVA_HOME")
    if not java or not re.search(r"(1[7-9]|2\d)", Path(java).name):
        candidates = sorted(glob.glob(r"C:\Program Files\Microsoft\jdk-2*")) + sorted(glob.glob(r"C:\Program Files\Eclipse Adoptium\jdk-2*"))
        if candidates:
            java = candidates[-1]
    if not java or not Path(java, "bin").is_dir():
        raise ReleaseError("JDK 21 not found: install it and set JAVA_HOME (see docs/RELEASING.md).")
    sdk = env.get("ANDROID_HOME") or env.get("ANDROID_SDK_ROOT") or str(Path(env.get("LOCALAPPDATA", "")) / "Android" / "Sdk")
    tools = sorted(Path(sdk, "build-tools").glob("*")) if Path(sdk, "build-tools").is_dir() else []
    if not tools:
        raise ReleaseError("Android SDK not found: install it and set ANDROID_HOME (see docs/RELEASING.md).")
    env.update(JAVA_HOME=java, ANDROID_HOME=sdk)
    props = keystore_properties_path()
    if not props.exists():
        raise ReleaseError(f"No release signing key at {props} (see docs/RELEASING.md).")
    return Toolchain(env=env, build_tools=tools[-1], keystore_properties=props)


# ------------------------------------------------------------------ publish


def _set_versions(root: Path, version: str) -> None:
    for name in ("package.json", "frontend/package.json"):
        path = root / name
        text = path.read_text(encoding="utf-8")
        path.write_text(re.sub(r'("version":\s*")[^"]+(")', rf"\g<1>{version}\g<2>", text, count=1), encoding="utf-8")
    path = root / "backend/pyproject.toml"
    path.write_text(re.sub(r'(?m)^version = "[^"]+"', f'version = "{version}"', path.read_text(encoding="utf-8"), count=1), encoding="utf-8")
    path = root / "backend/app/__init__.py"
    path.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', path.read_text(encoding="utf-8")), encoding="utf-8")
    _run(["uv", "lock", "--project", "backend"], root)


def _restore_versions(root: Path) -> None:
    _git(root, "checkout", "--", *VERSION_FILES, check=False)


def build_apk(root: Path, version: str, tools: Toolchain) -> tuple[Path, str]:
    """Build the web app, copy it into Android, build and sign the release APK. Returns (apk, cert sha-256)."""
    frontend = root / "frontend"
    _run(["npm", "run", "build"], frontend, env=tools.env)
    _run(["npx", "cap", "sync", "android"], frontend, env=tools.env)
    android = frontend / "android"
    gradlew = str(android / ("gradlew.bat" if os.name == "nt" else "gradlew"))
    _run([gradlew, "assembleRelease", "--no-daemon", "-q"], android, env=tools.env, timeout=3600)
    built = android / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
    if not built.exists():
        raise ReleaseError("The build finished without a signed APK (is the signing key file readable?).")
    signer = tools.build_tools / ("apksigner.bat" if os.name == "nt" else "apksigner")
    certs = _run([str(signer), "verify", "--print-certs", str(built)], root, env=tools.env)
    match = re.search(r"certificate SHA-256 digest: ([0-9a-f]+)", certs)
    if not match:
        raise ReleaseError("The APK isn't signed.")
    digest = match[1]
    expected = _read_properties(tools.keystore_properties).get("certSha256", "").replace(":", "").lower()
    if expected and digest != expected:
        raise ReleaseError("The APK was signed with a different key than the release key: phones would refuse the update.")
    out_dir = root / "release"
    out_dir.mkdir(exist_ok=True)
    apk = out_dir / APK_NAME.format(version=version)
    shutil.copyfile(built, apk)
    return apk, digest


def notes_with_footer(root: Path, notes: str, version: str) -> str:
    url = repo_url(root)
    return (
        notes.strip()
        + "\n\n---\n"
        + f"**Android:** download `{APK_NAME.format(version=version)}` below, or add `{url}` to "
        + "[Obtainium](https://github.com/ImranR98/Obtainium) to get every update automatically.\n"
        + f"**Laptop:** `git pull` (or download the source below), then `npm run setup` and `npm run start`.\n"
    )


def publish(
    root: Path, version: str, notes_file: Path, *, dry_run: bool = False, skip_tests: bool = False,
    say: Any = lambda message: None,
) -> dict[str, Any]:
    version = version.removeprefix("v")
    version_tuple(version)
    notes = notes_file.read_text(encoding="utf-8").strip()
    if len(notes) < 20:
        raise ReleaseError("The release notes are empty.")
    state = check(root)
    if state["branch"] != "main":
        raise ReleaseError(f"Releases are made from main (this is {state['branch']}).")
    if state["uncommitted_changes"]:
        raise ReleaseError("There are uncommitted changes; commit or stash them first.")
    last = state["last_release"]
    if last and version_tuple(version) <= version_tuple(last["tagName"]):
        raise ReleaseError(f"v{version} isn't newer than the last release {last['tagName']}.")
    if _git(root, "tag", "--list", f"v{version}"):
        raise ReleaseError(f"The tag v{version} already exists.")
    if not dry_run and not state["should_release"]:
        raise ReleaseError(f"Nothing to release: {state['reason']}.")
    tools = toolchain()

    if not skip_tests:
        say("running the tests")
        _run(["uv", "run", "--project", "backend", "pytest", "-q", "backend/tests"], root, timeout=3600)
        _run(["npm", "--prefix", "frontend", "run", "typecheck"], root)

    say(f"building v{version}")
    _set_versions(root, version)
    try:
        apk, digest = build_apk(root, version, tools)
    except Exception:
        _restore_versions(root)
        raise
    full_notes = notes_with_footer(root, notes, version)
    if dry_run:
        _restore_versions(root)
        return {"dry_run": True, "version": version, "apk": str(apk), "apk_bytes": apk.stat().st_size, "cert_sha256": digest,
                "notes": full_notes}

    say("committing, tagging and pushing")
    _git(root, "add", *VERSION_FILES)
    message = root / "release" / f"notes-v{version}.md"
    message.write_text(f"Release v{version}\n\n{notes}\n", encoding="utf-8")
    _git(root, "commit", "-q", "-F", str(message))
    _git(root, "tag", "-a", f"v{version}", "-F", str(message))
    try:
        _git(root, "push", "origin", "main")
        _git(root, "push", "origin", f"v{version}")
        message.write_text(full_notes, encoding="utf-8")
        say("creating the GitHub release")
        _run(
            ["gh", "release", "create", f"v{version}", str(apk), "--title", f"Lingo OS v{version}", "--notes-file", str(message),
             "--verify-tag", "--latest"],
            root,
        )
    except ReleaseError as exc:
        raise ReleaseError(
            f"{exc}\n\nThe release commit and tag v{version} exist locally. Once the problem is fixed: "
            f"`git push origin main v{version}`, then `gh release create v{version} {apk} --notes-file {message}`."
        ) from exc
    url = _run(["gh", "release", "view", f"v{version}", "--json", "url", "--jq", ".url"], root).strip()
    return {"dry_run": False, "version": version, "url": url, "apk": str(apk), "cert_sha256": digest}
