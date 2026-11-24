from __future__ import annotations

import pytest

from app import release


def test_versions_bump_and_compare() -> None:
    assert release.bump("0.1.0", "minor") == "0.2.0"
    assert release.bump("0.2.3", "patch") == "0.2.4"
    assert release.bump("0.9.4", "major") == "1.0.0"
    assert release.version_tuple("v1.10.0") > release.version_tuple("1.9.9")
    with pytest.raises(release.ReleaseError):
        release.version_tuple("1.2")


def test_only_app_changes_make_a_release() -> None:
    for path in ("backend/app/services/tts.py", "frontend/src/pages/WatchPage.tsx", "config/sources.yaml",
                 "frontend/android/app/src/main/AndroidManifest.xml", "frontend/package.json"):
        assert release.is_app_file(path), path
    for path in ("README.md", "docs/PHONE.md", "backend/tests/test_tts.py", "modes/release.md", "AGENTS.md",
                 ".github/workflows/tests.yml"):
        assert not release.is_app_file(path), path


def test_notes_get_install_instructions(tmp_path) -> None:
    notes = release.notes_with_footer(tmp_path, "## New\n- Native voices", "0.2.0")
    assert notes.startswith("## New") and "lingo-os-v0.2.0.apk" in notes and "Obtainium" in notes


def test_version_is_set_in_every_file(tmp_path, monkeypatch) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "package.json").write_text('{\n  "name": "x",\n  "version": "0.1.0"\n}\n')
    (tmp_path / "frontend" / "package.json").write_text('{\n  "version": "0.1.0",\n  "dependencies": {"a": "1.0.0"}\n}\n')
    (tmp_path / "backend" / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.0"\n\n[tool.x]\nversion = "9"\n')
    (tmp_path / "backend" / "app" / "__init__.py").write_text('__version__ = "0.1.0"\n')
    monkeypatch.setattr(release, "_run", lambda *args, **kwargs: "")  # no uv lock in a test
    release._set_versions(tmp_path, "0.2.0")
    assert release.current_version(tmp_path) == "0.2.0"
    assert '"version": "0.2.0"' in (tmp_path / "frontend" / "package.json").read_text()
    assert '"a": "1.0.0"' in (tmp_path / "frontend" / "package.json").read_text()
    pyproject = (tmp_path / "backend" / "pyproject.toml").read_text()
    assert 'version = "0.2.0"' in pyproject and 'version = "9"' in pyproject
    assert '__version__ = "0.2.0"' in (tmp_path / "backend" / "app" / "__init__.py").read_text()
