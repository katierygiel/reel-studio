"""Look at every clip before editing: speech (with word timing), pauses, scene changes, movement, loud moments,
and a contact sheet of stills. Everything here runs on your Mac. Writes 3-analysis/report.md for Claude to read."""
import difflib
import json
import math
import re
import shutil
import tempfile
from pathlib import Path

from . import project as P
from .util import MODELS_DIR, ReelError, fmt_time, load_json, probe, run, save_json, say

SHEET_COLS = 6
MAX_STILLS = 24


# ---------- speech ----------------------------------------------------------------------------

def whisper_tools():
    cli = shutil.which("whisper-cli")
    models = sorted(MODELS_DIR.glob("ggml-*.bin")) if MODELS_DIR.exists() else []
    pref = [m for m in models if "small" in m.name] or [m for m in models if "medium" in m.name or "turbo" in m.name] or models
    return cli, (pref[0] if pref else None)


def parse_whisper(data):
    """whisper-cli JSON (one entry per word with -ml 1 -sow) -> [{"w", "s", "e"}]."""
    words = []
    for seg in data.get("transcription", []):
        text = seg.get("text", "").strip()
        if not text or re.fullmatch(r"[\[\(].*[\]\)]", text):     # [BLANK_AUDIO], (music) ...
            continue
        s, e = seg["offsets"]["from"] / 1000, seg["offsets"]["to"] / 1000
        if words and not seg.get("text", "").startswith(" "):     # piece of the previous word ("don" + "'t")
            words[-1]["w"] += text
            words[-1]["e"] = round(e, 3)
            continue
        words.append({"w": text, "s": round(s, 3), "e": round(max(e, s + 0.05), 3)})
    return words


def transcribe(src, out_json, has_audio):
    if not has_audio:
        return []
    cli, model = whisper_tools()
    if not (cli and model):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", wav])
        base = [cli, "-m", model, "-f", wav, "-ml", "1", "-sow", "-oj", "-of", Path(tmp) / "w", "-np",
                "--prompt", "Um, uh, so, like, I mean, you know. Okay."]
        if model.name.endswith(".en.bin"):
            base += ["-l", "en"]
        try:   # DTW gives tighter word timing on supported models; fall back quietly if it isn't
            name = model.stem.replace("ggml-", "")
            run(base + ["-dtw", name])
        except ReelError:
            run(base)
        words = parse_whisper(json.loads((Path(tmp) / "w.json").read_text(errors="replace")))
    save_json(out_json, words)
    return words


def sentences(words, gap=0.7):
    out, cur = [], []
    for i, w in enumerate(words):
        if cur and w["s"] - cur[-1]["e"] > gap:
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.?!]$", w["w"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


# ---------- picture and sound -----------------------------------------------------------------

def _meta_lines(path):
    t, rows = None, []
    for line in Path(path).read_text().splitlines():
        if line.startswith("frame:"):
            t = float(line.split("pts_time:")[1])
        elif "=" in line and t is not None:
            k, v = line.split("=", 1)
            rows.append((t, k, v))
    return rows


def picture(src, dur, tmp):
    """Movement per second (0 = still, 10+ = lots) and hard scene changes."""
    meta = Path(tmp) / "scd.txt"
    run(["ffmpeg", "-v", "error", "-i", src, "-an", "-vf",
         f"fps=5,scale=160:-2,scdet=threshold=12,metadata=mode=print:file={meta.name}", "-f", "null", "-"], cwd=tmp)
    per_sec, scenes = {}, []
    for t, k, v in _meta_lines(meta):
        if k == "lavfi.scd.mafd" and t > 0:
            per_sec.setdefault(int(t), []).append(float(v))
        elif k == "lavfi.scd.time":
            scenes.append(round(float(v), 1))
    motion = [round(sum(per_sec.get(s, [0])) / max(1, len(per_sec.get(s, [0]))), 1) for s in range(int(math.ceil(dur)))]
    return motion, scenes


def sound(src, tmp):
    """Quiet stretches and loud moments (laughs, cheers, music hits)."""
    r = run(["ffmpeg", "-hide_banner", "-i", src, "-vn", "-af", "silencedetect=n=-35dB:d=0.6", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    quiet = [(round(s, 1), round(e, 1)) for s, e in zip(starts, ends + [None] * (len(starts) - len(ends))) if e]
    meta = Path(tmp) / "lufs.txt"
    run(["ffmpeg", "-v", "error", "-i", src, "-vn", "-af",
         f"ebur128=metadata=1,ametadata=mode=print:key=lavfi.r128.M:file={meta.name}", "-f", "null", "-"], cwd=tmp)
    per_sec = {}
    for t, k, v in _meta_lines(meta):
        if float(v) > -70:
            per_sec.setdefault(int(t), []).append(float(v))
    loud = []
    if per_sec:
        avg = {s: sum(v) / len(v) for s, v in per_sec.items()}
        typical = sorted(avg.values())[len(avg) // 2]
        loud = [s for s, v in sorted(avg.items()) if v > typical + 7]
    return quiet, loud


def contact_sheet(src, dur, out, kind):
    """One image with up to 24 evenly spaced stills, read left-to-right, top-to-bottom."""
    if kind == "photo":
        run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", "scale=-2:480", "-q:v", "5", out])
        return 0, 1
    step = max(0.5, math.ceil(dur / MAX_STILLS * 2) / 2)
    n = min(MAX_STILLS, max(1, math.ceil(dur / step - 1e-6)))
    rows = math.ceil(n / SHEET_COLS)
    run(["ffmpeg", "-v", "error", "-y", "-i", src, "-an", "-vf",
         f"fps=1/{step}:round=down,scale=-2:240,tile={SHEET_COLS}x{rows}:padding=4:color=white",
         "-frames:v", "1", "-q:v", "6", out])
    return step, n


def frame(src, t, out, height=720):
    """A single bigger still, for a closer look at one moment."""
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", "-vf", f"scale=-2:{height}", "-q:v", "4", out])
    return out


# ---------- the whole project -----------------------------------------------------------------

def describe_motion(motion):
    if not motion:
        return ""
    lab = ["still" if m < 1.5 else "some" if m < 5 else "lots" for m in motion]
    parts, start = [], 0
    for i in range(1, len(lab) + 1):
        if i == len(lab) or lab[i] != lab[start]:
            parts.append(f"{lab[start]} {start}-{i}s")
            start = i
    return ", ".join(parts)


def analyze(proj, force=False):
    proj, meta = P.load_project(proj)
    an = P.folder(proj, "analysis")
    for sub in ("sheets", "words", "frames"):
        (an / sub).mkdir(exist_ok=True)
    cli, model = whisper_tools()
    if not (cli and model):
        say("⚠️  Speech-to-text isn't installed yet (whisper-cli + a model in models/). Skipping transcripts: run `reel doctor`.")

    cache = load_json(an / "analysis.json", {})
    results = {}
    for cid, c in meta["clips"].items():
        src = c["file"]
        stamp = f"{Path(src).stat().st_size}-{int(Path(src).stat().st_mtime)}"
        if not force and cache.get(cid, {}).get("stamp") == stamp and (cache[cid].get("words") is not None or not (cli and model)):
            results[cid] = cache[cid]
            say(f"  {cid}: already analysed")
            continue
        say(f"  {cid}: analysing {Path(c['original']).name} ...")
        info = probe(src)
        dur = info["duration"] if c["kind"] == "video" else 0
        r = {"stamp": stamp, "kind": c["kind"], "duration": round(dur, 2), "width": info.get("width"),
             "height": info.get("height"), "fps": info.get("fps"), "audio": info.get("audio", False)}
        step, n = contact_sheet(src, dur, an / "sheets" / f"{cid}.jpg", c["kind"])
        r.update(sheet_step=step, sheet_count=n)
        if c["kind"] == "video":
            with tempfile.TemporaryDirectory() as tmp:
                r["motion"], r["scenes"] = picture(src, dur, tmp)
                if r["audio"]:
                    r["quiet"], r["loud"] = sound(src, tmp)
            words = transcribe(src, an / "words" / f"{cid}.json", r["audio"])
            r["words"] = None if words is None else len(words)
        results[cid] = r
        save_json(an / "analysis.json", results | {k: v for k, v in cache.items() if k not in results and k in meta["clips"]})
    save_json(an / "analysis.json", results)
    write_report(proj, meta, results)
    say(f"Report: {an / 'report.md'}")
    return results


def load_words(proj, cid):
    p = Path(proj) / P.FOLDERS["analysis"] / "words" / f"{cid}.json"
    return load_json(p) if p.exists() else []


def repeated_takes(proj, meta):
    """Lines said more than once (retakes) across all clips."""
    lines = []
    for cid in meta["clips"]:
        for s in sentences(load_words(proj, cid)):
            text = " ".join(w["w"] for w in s)
            norm = re.sub(r"[^a-z0-9 ]", "", text.lower())
            if len(norm.split()) >= 4:
                lines.append((cid, s[0]["s"], s[-1]["e"], text, norm))
    groups, used = [], set()
    for i, a in enumerate(lines):
        if i in used:
            continue
        g = [a]
        for j in range(i + 1, len(lines)):
            if j not in used and difflib.SequenceMatcher(None, a[4], lines[j][4]).ratio() > 0.62:
                g.append(lines[j])
                used.add(j)
        if len(g) > 1:
            groups.append(g)
    return groups


def write_report(proj, meta, res):
    out = [f"# Footage report: {meta['name']}", "",
           "Clips are numbered in the order they were filmed. Contact sheets read left to right, top to bottom.",
           "Word-by-word timings are in 3-analysis/words/<clip>.json. For a closer look at one moment: `reel frame <project> <clip> <seconds>`.", ""]
    total = sum(r["duration"] for r in res.values())
    out.append(f"{len(res)} clips, {fmt_time(total)} of footage in total.\n")
    for cid, r in res.items():
        name = Path(meta["clips"][cid]["original"]).name
        if r["kind"] == "photo":
            out.append(f"## {cid} · photo · {name} · {r['width']}x{r['height']}\nsheet: 3-analysis/sheets/{cid}.jpg\n")
            continue
        w_, h_ = r["width"] or 0, r["height"] or 0
        shape = "square" if abs(w_ - h_) < 0.1 * max(w_, h_, 1) else "vertical" if h_ > w_ else "horizontal"
        out.append(f"## {cid} · {r['duration']:.1f}s · {shape} {r['width']}x{r['height']} · {name}")
        out.append(f"sheet: 3-analysis/sheets/{cid}.jpg ({r['sheet_count']} stills, every {r['sheet_step']}s from 0s)")
        out.append(f"movement: {describe_motion(r.get('motion', []))}")
        if r.get("scenes"):
            out.append(f"scene changes at: {', '.join(f'{s}s' for s in r['scenes'])}")
        if not r["audio"]:
            out.append("sound: none")
        else:
            if r.get("quiet"):
                out.append("quiet: " + ", ".join(f"{a}-{b}s" for a, b in r["quiet"]))
            if r.get("loud"):
                out.append("loud moments (laugh/cheer/hit?): " + ", ".join(f"{s}s" for s in r["loud"]))
        words = load_words(proj, cid)
        if not words and r.get("words") is None and r["audio"]:
            out.append("speech: (not transcribed yet)")
        elif not words:
            out.append("speech: none")
        else:
            first, last = words[0]["s"], words[-1]["e"]
            out.append(f"speech: {first:.1f}s to {last:.1f}s" + (f"  (⚠ {first:.1f}s before the first word)" if first > 2 else ""))
            for s in sentences(words):
                out.append(f"  [{s[0]['s']:.1f}-{s[-1]['e']:.1f}] " + " ".join(w["w"] for w in s))
        out.append("")
    takes = repeated_takes(proj, meta)
    if takes:
        out.append("## Possible repeated takes (pick the strongest)")
        for g in takes:
            out.append("- " + " | ".join(f"{c} {a:.1f}-{b:.1f}s \"{t}\"" for c, a, b, t, _ in g))
        out.append("")
    assets = P.asset_files(proj)
    if assets:
        out.append("## Extra files in 2-assets")
        for f in assets:
            try:
                i = probe(f)
            except ReelError:
                continue
            bits = [f.name]
            if i.get("width"):
                bits.append(f"{i['width']}x{i['height']}")
            if i.get("duration") and f.suffix.lower() not in {".png", ".jpg", ".jpeg", ".heic"}:
                bits.append(f"{i['duration']:.1f}s")
            if i.get("width"):
                bits.append("transparent background" if i.get("alpha") else "no transparency")
            out.append("- " + " · ".join(bits))
        out.append("")
    (Path(proj) / P.FOLDERS["analysis"] / "report.md").write_text("\n".join(out))
