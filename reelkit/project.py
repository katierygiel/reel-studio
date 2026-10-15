"""Reel projects: one folder per video under ~/Movies/Reels/. Your original footage is never modified."""
import datetime as dt
import os
import shutil
import subprocess
from pathlib import Path

from .util import (AUDIO_EXT, IMAGE_EXT, REELS_HOME, VIDEO_EXT, ReelError, free_gb, is_mac, load_json,
                   probe, run, save_json, say, slug)

FOLDERS = {
    "footage": "1-footage",     # safe copies of your clips (read-only), or nothing if they're used in place
    "assets": "2-assets",       # logos, photos, overlay videos, music, anything extra: drop files here
    "analysis": "3-analysis",   # transcripts, contact sheets, the footage report
    "working": "4-working",     # the edit plan, captions, temporary files (safe to delete)
    "previews": "5-previews",   # quick low-res previews, numbered
    "final": "6-final",         # finished exports, clearly named
}


def folder(proj, key):
    p = Path(proj) / FOLDERS[key]
    p.mkdir(exist_ok=True)
    return p


def media_in(paths):
    files = []
    for p in paths:
        p = Path(p).expanduser()
        if not p.exists():
            raise ReelError(f"Can't find {p}")
        items = sorted(p.iterdir()) if p.is_dir() else [p]
        files += [f for f in items if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in VIDEO_EXT | IMAGE_EXT]
    if not files:
        raise ReelError("No videos or photos found there. Supported: " + ", ".join(sorted(VIDEO_EXT | IMAGE_EXT)))
    return files


def _safe_copy(src, dst):
    """Make a read-only working copy without using extra disk space when possible.
    On a Mac's own drive, `cp -c` makes an APFS clone: an instant copy that shares storage with the original.
    Returns the path to use; if cloning isn't possible we use the original in place (only ever read, never written)."""
    if is_mac():
        r = subprocess.run(["cp", "-c", str(src), str(dst)], capture_output=True)
        if r.returncode == 0:
            os.chmod(dst, 0o444)
            return dst, "clone"
    return src, "in place"


def to_still(src, work):
    """HEIC and other photo formats -> JPEG copy that FFmpeg can read (original untouched)."""
    if src.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        return src
    out = work / "converted" / (src.stem + ".jpg")
    out.parent.mkdir(exist_ok=True)
    if not out.exists():
        if is_mac():
            run(["sips", "-s", "format", "jpeg", str(src), "--out", str(out)])
        else:
            run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-frames:v", "1", str(out)])
    return out


def new_project(name, sources):
    files = media_in(sources)
    proj = REELS_HOME / f"{dt.date.today():%Y-%m-%d}-{slug(name)}"
    n = 2
    while proj.exists():
        proj = REELS_HOME / f"{dt.date.today():%Y-%m-%d}-{slug(name)}-{n}"
        n += 1
    proj.mkdir(parents=True)
    for k in FOLDERS:
        folder(proj, k)
    if free_gb(proj) < 10:
        say(f"⚠️  Only {free_gb(proj):.0f} GB free on this drive. Rendering needs room: aim for 20+ GB free.")

    # Number clips in the order they were filmed (falls back to file name), not the order you picked them.
    infos = []
    for f in files:
        info = probe(f)
        when = info.get("created") or dt.datetime.fromtimestamp(f.stat().st_mtime, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        infos.append((when, f.name, f, info))
    infos.sort()

    clips, modes = {}, set()
    for i, (_, _, f, info) in enumerate(infos, 1):
        cid = f"C{i:02d}"
        kind = "photo" if f.suffix.lower() in IMAGE_EXT else "video"
        use, mode = _safe_copy(f, folder(proj, "footage") / f"{cid}_{f.name}")
        modes.add(mode)
        if kind == "photo":
            use = to_still(Path(use), folder(proj, "working"))
        clips[cid] = {"file": str(use), "original": str(f), "kind": kind, "how": mode}

    save_json(proj / "project.json", {"name": name, "created": dt.datetime.now().isoformat(timespec="seconds"),
                                      "clips": clips, "version": 0})
    say(f"New project: {proj}")
    say(f"  {len(clips)} clip(s): " + ", ".join(f"{c} = {Path(v['original']).name}" for c, v in clips.items()))
    if "in place" in modes:
        say("  Your originals are used in place (read only, never changed), so no extra disk space is used.")
    else:
        say("  Read-only copies made in 1-footage (they share storage with your originals, so no extra disk space).")
    say(f"  Put logos, overlay videos, photos or music in: {folder(proj, 'assets')}")
    return proj


def load_project(proj):
    proj = resolve(proj)
    return proj, load_json(proj / "project.json")


def resolve(proj):
    """Accept a full path, a folder name, or part of a name ('pumpkin')."""
    p = Path(proj).expanduser()
    if (p / "project.json").exists():
        return p.resolve()
    if REELS_HOME.exists():
        hits = sorted(d for d in REELS_HOME.iterdir() if d.is_dir() and proj.lower() in d.name.lower() and (d / "project.json").exists())
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ReelError(f"'{proj}' matches several projects: " + ", ".join(h.name for h in hits))
    raise ReelError(f"No project found for '{proj}'. Projects live in {REELS_HOME}")


def asset_files(proj):
    d = folder(proj, "assets")
    return sorted(f for f in d.iterdir() if f.is_file() and not f.name.startswith(".")
                  and f.suffix.lower() in VIDEO_EXT | IMAGE_EXT | AUDIO_EXT)


def media_path(proj, meta, ref):
    """A plan refers to media as a clip id ('C03') or a file in 2-assets ('logo.png' or '2-assets/logo.png')."""
    if ref in meta["clips"]:
        return Path(meta["clips"][ref]["file"])
    p = Path(proj) / ref
    if not p.exists():
        p = Path(proj) / FOLDERS["assets"] / ref
    if not p.exists():
        raise ReelError(f"The plan mentions '{ref}', but there's no clip with that id or file in 2-assets.")
    if p.suffix.lower() in {".heic", ".heif", ".webp", ".gif"}:
        p = to_still(p, folder(proj, "working"))
    return p


def next_version(proj, meta):
    meta["version"] = meta.get("version", 0) + 1
    save_json(Path(proj) / "project.json", meta)
    return meta["version"]


def clean(proj):
    """Delete temporary render files (never footage, assets, previews or finals)."""
    w = Path(proj) / FOLDERS["working"] / "cache"
    if w.exists():
        size = sum(f.stat().st_size for f in w.rglob("*") if f.is_file()) / 1e9
        shutil.rmtree(w)
        say(f"Freed {size:.1f} GB of temporary render files.")
    else:
        say("Nothing to clean.")
