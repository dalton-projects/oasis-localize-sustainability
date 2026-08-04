"""
Configuration resolution.

Thresholds, politeness settings and cost-model assumptions are config, not code.
They should be arguable, tunable per region and per client, and visible in the
report so a reader can disagree with them. What they must never be is invisible.

Resolution order, later wins:

  1. `defaults.json` shipped inside the package
  2. `./oasis-sustain.json` in the working directory, if present
  3. an explicit path from `--config`, or $OASIS_SUSTAIN_CONFIG

Merging is per top-level section, so a user file that sets one threshold does
not silently drop the rest of that section's defaults.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:                                  # stdlib since 3.9
    from importlib.resources import files as _resource_files
except ImportError:                   # pragma: no cover
    _resource_files = None

LOCAL_NAME = "oasis-sustain.json"
ENV_VAR = "OASIS_SUSTAIN_CONFIG"

_override: Path | None = None
_cache: dict | None = None


def set_override(path: str | os.PathLike | None) -> None:
    """Point at an explicit config file (the CLI's --config). Clears the cache."""
    global _override, _cache
    _override = Path(path) if path else None
    _cache = None


def _packaged() -> dict:
    if _resource_files is not None:
        try:
            raw = (_resource_files("oasis_sustain") / "defaults.json").read_text(
                encoding="utf-8")
            return json.loads(raw)
        except Exception:
            pass
    # Fallback for a source checkout without package metadata.
    p = Path(__file__).with_name("defaults.json")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def load(refresh: bool = False) -> dict:
    global _cache
    if _cache is not None and not refresh:
        return _cache
    cfg = _packaged()
    local = Path.cwd() / LOCAL_NAME
    if local.is_file():
        cfg = _merge(cfg, _read(local))
    explicit = _override or (Path(os.environ[ENV_VAR])
                             if os.environ.get(ENV_VAR) else None)
    if explicit and explicit.is_file():
        cfg = _merge(cfg, _read(explicit))
    _cache = cfg
    return cfg


def section(name: str) -> dict:
    return load().get(name, {}) or {}


def sources() -> list[str]:
    """Which files actually contributed, for the report footer. An assumption
    the reader cannot trace back to a file is not a stated assumption."""
    out = ["packaged defaults.json"]
    if (Path.cwd() / LOCAL_NAME).is_file():
        out.append(str(Path.cwd() / LOCAL_NAME))
    explicit = _override or (Path(os.environ[ENV_VAR])
                             if os.environ.get(ENV_VAR) else None)
    if explicit and explicit.is_file():
        out.append(str(explicit))
    return out
