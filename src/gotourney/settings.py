"""Changing tournament.toml from a form, keeping its comments and layout (tomlkit).

``save_settings`` gets the managed sections as a dictionary in the structure of the file, checks
the result with the normal settings validation and writes only the changed values.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import tomlkit

from .config import CONFIG_FILE, Config, ConfigError, parse_config
from .rounds import round_file
from .workflow import Problem

LIST_OF_TABLES = {("pairing", "rules"), ("awards", "prizes")}


def settings_version(directory: Path) -> str:
    """Changes when tournament.toml changes (detects edits made elsewhere meanwhile)."""
    st = (Path(directory) / CONFIG_FILE).stat()
    return f"{st.st_mtime_ns}-{st.st_size}"


def read_settings(directory: Path) -> tuple[Config, str]:
    path = Path(directory) / CONFIG_FILE
    try:
        cfg = parse_config(tomllib.loads(path.read_text(encoding="utf-8")))
    except (ConfigError, tomllib.TOMLDecodeError) as e:
        raise Problem("invalid", f"{CONFIG_FILE}: {e}") from None
    return cfg, settings_version(directory)


def _merge(base: dict, changes: dict) -> dict:
    merged = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for section, values in changes.items():
        target = dict(merged.get(section, {}))
        for key, value in values.items():
            if value is None:
                target.pop(key, None)
            else:
                target[key] = value
        merged[section] = target
    return merged


def save_settings(directory: Path, changes: dict, version: str) -> Config:
    """Apply changes ({section: {key: value}}, value None = remove the key) to tournament.toml."""
    path = Path(directory) / CONFIG_FILE
    if settings_version(directory) != version:
        raise Problem("changed", f"{CONFIG_FILE} was changed elsewhere in the meantime. Reload the page; your "
                      f"changes were not saved.")
    text = path.read_text(encoding="utf-8")
    base = tomllib.loads(text)
    if "rules" in changes.get("pairing", {}):
        changes["pairing"].setdefault("club_penalty", None)          # replaced by the rules
    merged = _merge(base, changes)
    try:
        cfg = parse_config(merged)
    except ConfigError as e:
        raise Problem("invalid", str(e)) from None
    paired = max((r for r in range(1, 100) if round_file(directory, r).exists()), default=0)
    if cfg.tournament.rounds < paired:
        raise Problem("invalid", f"round {paired} is already paired; the tournament needs at least {paired} rounds")

    doc = tomlkit.parse(text)
    for section, values in changes.items():
        if section not in doc:
            doc[section] = tomlkit.table()
        table = doc[section]
        for key, value in values.items():
            if value is None:
                if key in table:
                    del table[key]
            elif (section, key) in LIST_OF_TABLES:
                aot = tomlkit.aot()
                for entry in value:
                    t = tomlkit.table()
                    for k, v in entry.items():
                        t[k] = v
                    aot.append(t)
                table[key] = aot
            elif isinstance(value, dict):
                t = tomlkit.table()
                for k, v in value.items():
                    t[k] = v
                table[key] = t
            elif key not in table or table[key] != value:
                table[key] = value
    # a blank line before every table header, as in the template
    new_text = re.sub(r"(?m)([^\n])\n(\[)", r"\1\n\n\2", tomlkit.dumps(doc))
    # final check of what will be written
    try:
        parse_config(tomllib.loads(new_text))
    except (ConfigError, tomllib.TOMLDecodeError) as e:
        raise Problem("invalid", f"internal error while writing {CONFIG_FILE}: {e}") from None
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(path)
    return cfg
