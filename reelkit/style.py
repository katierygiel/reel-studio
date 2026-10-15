"""Your saved editing style: fonts per purpose, caption look, pacing, effect levels, export settings."""
import shutil
from pathlib import Path

from .util import CODE_DIR, STYLE_DIR, ReelError, load_json, say

DEFAULT = CODE_DIR / "style" / "default-style.json"
ROLES = ("caption", "emphasis", "hook", "heading", "typewriter", "label", "funny")

STYLE_MD = """# My editing style

Plain-English rules Claude follows on every edit. Claude adds to this when you give feedback
("zooms are too frequent", "never put captions in all caps"). Edit it any time.

## Overall vibe
- (describe it: e.g. bright, playful, clean; feels hand-edited in CapCut, never like a template)

## Rules
- Effects are selective: only where they add something.
- Never change the meaning of what I say. Never invent dialogue.

## Reference reels I love
- (file name or link + what I like about it: pacing, captions, sounds...)
"""


def ensure_style_dir():
    """First run: create ~/Movies/Reels/_my-style with a copy of the defaults."""
    STYLE_DIR.mkdir(parents=True, exist_ok=True)
    for sub in ("fonts", "sfx", "references"):
        (STYLE_DIR / sub).mkdir(exist_ok=True)
    if not (STYLE_DIR / "style.json").exists():
        shutil.copy(DEFAULT, STYLE_DIR / "style.json")
        say(f"Created your style file: {STYLE_DIR / 'style.json'}")
    if not (STYLE_DIR / "style.md").exists():
        (STYLE_DIR / "style.md").write_text(STYLE_MD)
    if not (STYLE_DIR / "feedback.md").exists():
        (STYLE_DIR / "feedback.md").write_text("# Feedback log\n\nWhat you said about each edit, newest last. Claude reads this before every edit.\n")


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_style(project_dir=None):
    """Defaults <- your style.json <- this project's style-overrides.json (if any)."""
    style = load_json(DEFAULT)
    if (STYLE_DIR / "style.json").exists():
        style = _merge(style, load_json(STYLE_DIR / "style.json"))
    if project_dir and (Path(project_dir) / "style-overrides.json").exists():
        style = _merge(style, load_json(Path(project_dir) / "style-overrides.json"))
    for role in ROLES:
        if role not in style["fonts"]:
            raise ReelError(f"style.json is missing a font for '{role}'")
    return style


def font_files(style):
    """Font files to hand to the caption renderer, plus honest warnings about anything missing."""
    files, warnings = [], []
    for role, f in style["fonts"].items():
        if role.startswith("_"):
            continue
        if f.get("file"):
            p = Path(f["file"]).expanduser()
            if not p.is_absolute():
                p = STYLE_DIR / "fonts" / p
            if p.exists():
                files.append(p)
            else:
                warnings.append(f"Font file for '{role}' not found ({p.name}). Text will NOT look right until it's in {STYLE_DIR / 'fonts'}.")
    return files, warnings
