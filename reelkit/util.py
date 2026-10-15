"""Small helpers shared by every part of Reel Studio. Standard library only."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
REELS_HOME = Path(os.environ.get("REELS_HOME", "~/Movies/Reels")).expanduser()
STYLE_DIR = Path(os.environ.get("REELS_STYLE", REELS_HOME / "_my-style")).expanduser()
MODELS_DIR = CODE_DIR / "models"

VIDEO_EXT = {".mov", ".mp4", ".m4v", ".mkv", ".avi", ".mts", ".3gp", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".aif", ".aiff", ".flac", ".ogg"}

# Homebrew's plain "ffmpeg" has no caption support (libass); "ffmpeg-full" does but isn't on the PATH by default.
for _d in ("/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin"):
    if os.path.isdir(_d) and _d not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _d + os.pathsep + os.environ.get("PATH", "")

FPS = 30
FULL = (1080, 1920)
PREVIEW = (540, 960)


class ReelError(Exception):
    """A problem we can explain in plain English."""


def say(msg=""):
    print(msg, flush=True)


def run(cmd, cwd=None, quiet=True):
    """Run a command (a list, never a shell string). Raise ReelError with the tail of its output on failure."""
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-12:])
        raise ReelError(f"{Path(str(cmd[0])).name} failed:\n{tail}")
    return r


def ffmpeg_major():
    out = run(["ffmpeg", "-version"]).stdout
    m = re.search(r"ffmpeg version n?(\d+)", out)
    return int(m.group(1)) if m else 6


def probe(path):
    """Duration, size, fps, audio and alpha info for one media file."""
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration:format_tags=creation_time:stream=codec_type,width,height,avg_frame_rate,pix_fmt,color_transfer:"
             "stream_tags=rotate:stream_side_data=rotation", "-of", "json", path])
    j = json.loads(r.stdout)
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), None)
    a = any(s.get("codec_type") == "audio" for s in j.get("streams", []))
    info = {"duration": float(j.get("format", {}).get("duration") or 0), "audio": a,
            "created": (j.get("format", {}).get("tags") or {}).get("creation_time")}
    if v:
        w, h = v.get("width", 0), v.get("height", 0)
        rot = abs(int(float((v.get("tags") or {}).get("rotate", 0) or 0)))
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = abs(int(float(sd["rotation"])))
        if rot in (90, 270):
            w, h = h, w
        num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
        info.update(width=w, height=h, fps=round(float(num) / float(den or 1), 2) if float(den or 1) else 0,
                    hdr=v.get("color_transfer") in ("arib-std-b67", "smpte2084"),
                    alpha=any(k in (v.get("pix_fmt") or "") for k in ("rgba", "argb", "bgra", "abgr", "yuva", "pal8", "ya")))
    return info


def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        if default is not None:
            return default
        raise ReelError(f"Missing file: {p}")
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise ReelError(f"{p.name} has a typo on line {e.lineno}: {e.msg}")


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "reel"


def free_gb(path):
    p = Path(path)
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free / 1e9


def hex_to_ass(color, alpha=0):
    """#RRGGBB -> &HAABBGGRR (ASS subtitle colour format)."""
    c = color.lstrip("#")
    if len(c) != 6:
        raise ReelError(f"Colour {color!r} should look like #FFD84D")
    return f"&H{alpha:02X}{c[4:6]}{c[2:4]}{c[0:2]}".upper()


def fmt_time(t):
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:05.2f}"


def is_mac():
    return sys.platform == "darwin"
