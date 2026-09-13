"""Locate bundled assets and seed writable data without copying user state.

Release bundles contain only explicit ``defaults/`` seeds and ``res/`` assets.
Source checkouts retain their existing ``user_data`` directory. No path depends
on the shell's working directory, and existing user files are never replaced.
"""

import json
import logging
import math
import os
from pathlib import Path
import shutil
import sys


APP_NAME = "MorseWriter"
BOOTSTRAP_MARKER = ".bootstrap-complete"
_SOURCE_ROOT = Path(__file__).resolve().parent
_SOURCE_SEEDS = {
    "layouts.json": "user_data/layouts.json",
}


def source_resource(*parts):
    """Return an absolute bundled/source asset path, independent of cwd."""
    root = Path(getattr(sys, "_MEIPASS", _SOURCE_ROOT)) if getattr(sys, "frozen", False) else _SOURCE_ROOT
    return root.joinpath(*parts).resolve()


def user_data_dir(app_name=APP_NAME):
    """Return the writable application data directory without creating it."""
    if not getattr(sys, "frozen", False):
        return _SOURCE_ROOT / "user_data"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / app_name / "user_data"


def _legacy_user_data_dir(app_name=APP_NAME):
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return None
    public = Path(os.environ.get("PUBLIC") or "C:/Users/Public")
    return public / "Documents" / "Ace Centre" / app_name / "user_data"


def _seed_resource(name, resource_dir=None):
    root = Path(resource_dir) if resource_dir is not None else source_resource()
    release_seed = root / "defaults" / name
    return release_seed if release_seed.is_file() else root / _SOURCE_SEEDS[name]


def layouts_seed_path():
    """The current unified layout shipped with this version."""
    return _seed_resource('layouts.json')


def _copy_missing(source, target):
    """Create only this file; never overwrite even if another instance won."""
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    # Open the source first, so a missing bundle cannot leave an empty target.
    with Path(source).open("rb") as reader:
        try:
            writer = target.open("xb")
        except FileExistsError:
            return False
        try:
            with writer:
                shutil.copyfileobj(reader, writer)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return True


def _write_missing(target, text):
    try:
        writer = target.open("x", encoding="utf-8")
    except FileExistsError:
        return False
    try:
        with writer:
            writer.write(text)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return True


def _legacy_preferences(directory, defaults):
    if directory is None:
        return None
    path = directory / "config.json"
    try:
        if path.stat().st_size > 64 * 1024:
            return None
        values = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(values, dict):
            return None
        allowed = set(defaults) | {"fastMorseMode"}
        result = {}
        for key, value in values.items():
            if key not in allowed or not isinstance(value, (str, int, float, bool, type(None))):
                continue
            if isinstance(value, float) and not math.isfinite(value):
                continue
            result[key] = value
        return result or None
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, ValueError):
        logging.warning("无法读取旧版设置，将使用默认设置：%s", path)
        return None


def bootstrap_assets(default_config, *, data_dir=None, resource_dir=None, legacy_dir=None):
    """Seed missing assets and return the writable data directory.

    Legacy migration is attempted only once, when the new config is absent.
    Only bounded scalar preferences migrate; old layouts, abbreviation files,
    databases, logs and arbitrary extra files do not migrate.
    """
    directory = Path(data_dir) if data_dir is not None else user_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    config_path = directory / "config.json"
    marker_path = directory / BOOTSTRAP_MARKER
    first_run = not config_path.exists() and not marker_path.exists()
    legacy = Path(legacy_dir) if legacy_dir is not None else _legacy_user_data_dir()
    migrated = _legacy_preferences(legacy, default_config) if first_run else None

    # Ensure all mandatory data before publishing a first-run config/marker.
    _copy_missing(_seed_resource("layouts.json", resource_dir), directory / "layouts.json")

    # Keep legacy omissions (e.g. keyer_mode) intact for ConfigManager's existing
    # version conversion. Fresh installs use the explicit release defaults.
    settings = migrated if migrated is not None else dict(default_config)
    _write_missing(config_path, json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
    _write_missing(marker_path, "1\n")
    return directory.resolve()
