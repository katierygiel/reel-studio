"""Build the video from the edit plan. Each segment is rendered once and cached, so changing one section
only re-renders that section. Previews are 540x960 (fast); finals are 1080x1920 H.264 MP4."""
import hashlib
import json
import shutil
import time
from pathlib import Path

from . import project as P
from . import sfx as SFX
from .captions import Ass
from .style import font_files, load_style
from .timeline import Timeline
from .util import FPS, PREVIEW, ReelError, ffmpeg_major, fmt_time, load_json, probe, run, save_json, say

TRANSITIONS = {"fade": "fade", "crossfade": "fade", "dissolve": "dissolve", "white-flash": "fadewhite", "flash": "fadewhite",
               "black": "fadeblack", "slide-left": "slideleft", "slide-right": "slideright", "slide-up": "slideup",
               "slide-down": "slidedown", "whip-left": "smoothleft", "whip-right": "smoothright", "whip-up": "smoothup",
               "zoom": "zoomin", "circle": "circleopen", "blur": "hblur", "wipe": "wipeleft"}
WHOOSHY = {"slide-left", "slide-right", "slide-up", "slide-down", "whip-left", "whip-right", "whip-up", "zoom", "wipe"}
_ZSCALE = None


def has_zscale():
    global _ZSCALE
    if _ZSCALE is None:
        _ZSCALE = " zscale " in run(["ffmpeg", "-hide_banner", "-filters"]).stdout
    return _ZSCALE


def even(x):
    return max(2, int(round(x / 2)) * 2)


def fill(W, H, fx=0.5, fy=0.5):
    return (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}:x=(iw-{W})*{fx}:y=(ih-{H})*{fy},setsar=1")


def hdr_to_sdr(info):
    """iPhones film HDR by default; convert it properly so colours don't look washed out."""
    if not info.get("hdr"):
        return ""
    if not has_zscale():
        say("  note: this clip is HDR and this FFmpeg can't convert HDR, so colours may look a little flat")
        return ""
    return "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,"


def x264(final, style):
    ex = style["export"]
    if not final:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p"]
    if ex.get("encoder") == "videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-b:v", "14M", "-profile:v", "high", "-pix_fmt", "yuv420p", "-tag:v", "avc1"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(ex.get("crf", 18)), "-profile:v", "high",
            "-pix_fmt", "yuv420p", "-tag:v", "avc1"]


# ---------- one segment ---------------------------------------------------------------------------

def render_segment(seg, W, H, cache, final):
    raw = seg["raw"]
    fx, fy = (raw.get("focus") or [0.5, 0.5])[:2]
    src = Path(seg["src"])
    st = src.stat()
    key = hashlib.sha1(json.dumps([str(src), st.st_size, int(st.st_mtime), seg["pieces"], fx, fy, raw.get("volume", 1),
                                   raw.get("mute"), raw.get("push"), W, H, final, 3]).encode()).hexdigest()[:12]
    out = cache / f"{seg['id']}-{key}.mkv"
    if out.exists():
        return out
    info = probe(src)
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14" if final else "20", "-g", str(FPS), "-pix_fmt", "yuv420p",
           "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]
    vol = 0 if raw.get("mute") else float(raw.get("volume", 1))
    parts = []
    for k, (a, b) in enumerate(seg["pieces"]):
        n = max(1, round((b - a) * FPS))
        d = n / FPS
        part = cache / f"part-{key}-{k}.mkv"
        silent = ["-f", "lavfi", "-t", f"{d:.4f}", "-i", "anullsrc=r=48000:cl=stereo"]
        if seg["kind"] == "photo":
            ins = ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.4f}", "-i", src] + silent
            if raw.get("push", True):   # slow push-in on photos (Ken Burns), rendered at 2x then scaled for smoothness
                vf = (f"{fill(W * 2, H * 2, fx, fy)},zoompan=z='1+0.07*on/{n}':x='(iw-iw/zoom)*{fx}':y='(ih-ih/zoom)*{fy}'"
                      f":d=1:s={W}x{H}:fps={FPS}")
            else:
                vf = fill(W, H, fx, fy)
            amap = "1:a"
        else:
            ins = ["-ss", f"{a:.4f}", "-t", f"{d + 0.1:.4f}", "-i", src] + (silent if not info["audio"] else [])
            vf = hdr_to_sdr(info) + fill(W, H, fx, fy)
            amap = "0:a" if info["audio"] else "1:a"
        fade = f",afade=t=in:d=0.012,afade=t=out:st={max(0, d - 0.014):.4f}:d=0.012"
        af = f"aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,volume={vol}{fade},apad,atrim=0:{d:.4f}"
        run(["ffmpeg", "-v", "error", "-y", *ins, "-map", "0:v", "-map", amap, "-vf", f"{vf},fps={FPS},format=yuv420p",
             "-af", af, "-frames:v", str(n), *enc, part])
        parts.append(part)
    lst = cache / f"list-{key}.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", out.name], cwd=cache)
    for p in parts + [lst]:
        p.unlink()
    return out


# ---------- overlays ------------------------------------------------------------------------------

def rounded_mask(w, h, r, cache):
    out = cache / f"mask-{w}x{h}-{r}.png"
    if not out.exists():
        expr = (f"if(gt(abs(X-W/2),W/2-{r})*gt(abs(Y-H/2),H/2-{r}),"
                f"if(lte(hypot(abs(X-W/2)-(W/2-{r}),abs(Y-H/2)-(H/2-{r})),{r}),255,0),255)")
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=black:s={w}x{h}:d=1", "-vf",
             f"format=gray,geq=lum='{expr}'", "-frames:v", "1", out])
    return out


def overlay_chain(ov, k, at, W, H, scale, cache, add_input, style, label):
    """Filter-graph lines that turn one overlay input into an animated, positioned layer called [label].
    Returns (lines, x_expr, y_expr)."""
    info = probe(ov["path"])
    sw, sh = info.get("width") or 1, info.get("height") or 1
    dur = float(ov["dur"])
    lines, head, chain = [], f"[{k}:v]", [f"fps={FPS}", "format=rgba"]
    if ov.get("speed"):
        chain.append(f"setpts=(PTS-STARTPTS)/{float(ov['speed'])}")
    key = ov.get("remove_bg")
    if key:
        col = {"white": "0xFFFFFF", "black": "0x000000", "green": "0x00FF00", "blue": "0x0000FF"}.get(key, key.replace("#", "0x"))
        chain.append(f"chromakey={col}:0.15:0.06" if key in ("green", "blue") else f"colorkey={col}:0.14:0.08")
    if ov.get("full"):
        fx, fy = (ov.get("focus") or [0.5, 0.5])[:2]
        chain += [fill(W, H, fx, fy), "format=rgba"]
        ow, oh, cx, cy = W, H, W / 2, H / 2
    else:
        box = ov.get("box") or {}
        if "h" in box and "w" not in box:
            oh = even(box["h"] * H)
            ow = even(oh * sw / sh)
        else:
            ow = even(box.get("w", 0.5) * W)
            oh = even(ow * sh / sw)
        cx, cy = box.get("x", 0.5) * W, box.get("y", 0.4) * H
        chain.append(f"scale={ow}:{oh}")
        b = int(ov.get("border", 0) * scale)
        if b:
            chain.append(f"pad={ow + 2 * b}:{oh + 2 * b}:{b}:{b}:color={ov.get('border_color', 'white')}")
            ow, oh = ow + 2 * b, oh + 2 * b
        # videos and opaque photos get softly rounded corners by default (like CapCut picture-in-picture)
        default_r = 0 if (info.get("alpha") or key) else style["effects"].get("overlay_round", 28)
        r = int(float(ov.get("round", default_r)) * scale)
        if r:
            mk = add_input(["-loop", "1", "-framerate", FPS, "-t", f"{dur:.3f}", "-i", rounded_mask(ow, oh, r, cache)])
            lines.append(head + ",".join(chain) + f"[{label}r]")
            lines.append(f"[{mk}:v]format=gray,fps={FPS}[{label}m]")
            head, chain = f"[{label}r][{label}m]alphamerge,", []
    if ov.get("opacity") is not None:
        chain.append(f"colorchannelmixer=aa={float(ov['opacity'])}")
    a_in = ov.get("anim_in", "none" if ov.get("full") else "pop")
    a_out = ov.get("anim_out", "none" if ov.get("full") else "fade")
    if a_in == "pop" or a_out == "pop":
        grow = "if(lt(t,0.14),0.3+0.78*t/0.14,if(lt(t,0.22),1.08-0.08*(t-0.14)/0.08,1))" if a_in == "pop" else "1"
        shrink = f"if(gt(t,{dur - 0.15:.3f}),max(0.02,({dur:.3f}-t)/0.15),1)" if a_out == "pop" else "1"
        cw, ch = even(ow * 1.1), even(oh * 1.1)
        chain.append(f"scale=w='max(2,trunc({ow}*{grow}*{shrink}/2)*2)':h='max(2,trunc({oh}*{grow}*{shrink}/2)*2)':eval=frame")
        chain.append(f"pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color=black@0:eval=frame")
        ow, oh = cw, ch
    chain.append(f"setpts=PTS-STARTPTS+{at:.3f}/TB")
    if a_in == "fade":
        chain.append(f"fade=t=in:st={at:.3f}:d=0.25:alpha=1")
    if a_out == "fade":
        chain.append(f"fade=t=out:st={at + dur - 0.25:.3f}:d=0.25:alpha=1")
    lines.append(head + ",".join(chain) + f"[{label}]")
    x, y = f"{cx - ow / 2:.1f}", f"{cy - oh / 2:.1f}"
    slides = {"slide-left": ("x", W), "slide-right": ("x", -W), "slide-up": ("y", H), "slide-down": ("y", -H)}
    for anim, when in ((a_in, "in"), (a_out, "out")):
        if anim in slides:
            axis, dist = slides[anim]
            term = (f"+{dist}*pow(max(0,1-(t-{at:.3f})/0.3),3)" if when == "in"
                    else f"-{dist}*pow(min(1,max(0,(t-{at + dur - 0.3:.3f})/0.3)),3)")
            if axis == "x":
                x += term
            else:
                y += term
    return lines, x, y


# ---------- the whole video -----------------------------------------------------------------------

def render(proj, final=False, plan_file=None):
    t0 = time.time()
    proj, meta = P.load_project(proj)
    style = load_style(proj)
    work = P.folder(proj, "working")
    plan_path = Path(plan_file) if plan_file else work / "plan.json"
    plan = load_json(plan_path)
    W, H = (style["export"]["width"], style["export"]["height"]) if final else PREVIEW
    scale = W / 1080
    cache = work / "cache" / ("final" if final else "preview")
    cache.mkdir(parents=True, exist_ok=True)
    tl = Timeline(proj, meta, plan, style)
    say(f"Building a {fmt_time(tl.total)} {'final' if final else 'preview'} from {len(tl.segs)} segments...")

    inputs = []

    def add_input(args):
        inputs.append([str(a) for a in args])
        return len(inputs) - 1

    g = []   # filter graph lines
    # 1. segments -> one continuous base video, with transitions
    for i, seg in enumerate(tl.segs):
        f = render_segment(seg, W, H, cache, final)
        k = add_input(["-i", f])
        g.append(f"[{k}:v]settb=AVTB,setpts=PTS-STARTPTS[v{i}];[{k}:a]asetpts=PTS-STARTPTS[a{i}]")
    cv, ca = "v0", "a0"
    sfx_events = []
    for i, seg in enumerate(tl.segs[1:], 1):
        tr = seg["transition"]
        if tr:
            kind = TRANSITIONS.get(tr["type"])
            if not kind:
                raise ReelError(f"Unknown transition '{tr['type']}'. Choose from: {', '.join(TRANSITIONS)}")
            g.append(f"[{cv}][v{i}]xfade=transition={kind}:duration={tr['dur']:.3f}:offset={seg['start']:.3f}[xv{i}]")
            g.append(f"[{ca}][a{i}]acrossfade=d={tr['dur']:.3f}[xa{i}]")
            if tr["type"] in WHOOSHY and style["effects"]["auto_sfx"] and tr.get("sfx", True):
                sfx_events.append((seg["start"] - 0.1, "whoosh", None, 0.8, True))
        else:
            g.append(f"[{cv}][v{i}]concat=n=2:v=1:a=0[xv{i}];[{ca}][a{i}]concat=n=2:v=0:a=1[xa{i}]")
        cv, ca = f"xv{i}", f"xa{i}"

    # 2. punch-in zooms (applied to the base footage, so text and overlays stay put)
    zooms = plan.get("zooms") or []
    if zooms:
        zs, xs, ys = [], [], []
        for z in zooms:
            a = tl.at(z["at"], "zoom")
            d = float(z.get("dur", 1.5))
            s = float(z.get("scale", style["effects"]["zoom_scale"])) - 1
            fx, fy = (z.get("focus") or [0.5, 0.4])[:2]
            ramp = "1" if z.get("type", "punch") == "punch" else f"min(1,(it-{a:.3f})/0.45)"
            zs.append(f"between(it,{a:.3f},{a + d:.3f})*{s:.3f}*{ramp}")
            xs.append((a, a + d, fx))
            ys.append((a, a + d, fy))

        def pick(vals, default):
            e = str(default)
            for a, b, v in reversed(vals):
                e = f"if(between(it,{a:.3f},{b:.3f}),{v},{e})"
            return e
        g.append(f"[{cv}]zoompan=z='1+{'+'.join(zs)}':x='(iw-iw/zoom)*{pick(xs, 0.5)}':y='(ih-ih/zoom)*{pick(ys, 0.4)}'"
                 f":d=1:s={W}x{H}:fps={FPS}[zv]")
        cv = "zv"
    g.append(f"[{cv}]format=rgba[base]")
    cv = "base"

    # 3. overlays: b-roll, picture-in-picture, logos, photos, stickers
    ov_audio = []
    for n, ov in enumerate(plan.get("overlays") or []):
        ov = dict(ov)
        what = f"overlay {n + 1} ({ov.get('src')})"
        ov["path"] = P.media_path(proj, meta, ov["src"])
        at = tl.at(ov.get("at", 0), what)
        info = probe(ov["path"])
        is_still = not info.get("duration") or ov["path"].suffix.lower() in {".png", ".jpg", ".jpeg"}
        if "dur" not in ov:
            ov["dur"] = 2.5 if is_still else max(0.5, info["duration"] - float(ov.get("in", 0)))
        dur = float(ov["dur"])
        need = dur * float(ov.get("speed", 1))
        if is_still:
            k = add_input(["-loop", "1", "-framerate", FPS, "-t", f"{dur:.3f}", "-i", ov["path"]])
        else:
            if float(ov.get("in", 0)) + need > info["duration"] + 0.05:
                tl.problems.append(f"{what}: asks for {need:.1f}s from {ov.get('in', 0)}s but the clip is only {info['duration']:.1f}s; it will end early")
            k = add_input(["-ss", f"{float(ov.get('in', 0)):.3f}", "-t", f"{need:.3f}", "-i", ov["path"]])
        lines, x, y = overlay_chain(ov, k, at, W, H, scale, cache, add_input, style, f"o{n}")
        g += lines
        g.append(f"[{cv}][o{n}]overlay=x='{x}':y='{y}':eval=frame:eof_action=pass:"
                 f"enable='between(t,{at:.3f},{at + dur:.3f})'[ov{n}]")
        cv = f"ov{n}"
        if ov.get("volume") and info.get("audio") and not is_still:
            ov_audio.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={float(ov['volume'])},"
                            f"afade=t=out:st={max(0, need - 0.2):.3f}:d=0.2,adelay={int(at * 1000)}:all=1[oa{n}]")
        auto = ov.get("sfx", True)
        if auto and style["effects"]["auto_sfx"] and not ov.get("full"):
            name = auto if isinstance(auto, str) else {"pop": "pop", "slide-left": "swish", "slide-right": "swish",
                                                       "slide-up": "swish", "slide-down": "swish"}.get(ov.get("anim_in", "pop"))
            if name:
                sfx_events.append((at, name, None, 1.0, True))
        elif isinstance(auto, str):
            sfx_events.append((at, auto, None, 1.0, False))

    # 4. captions + text
    ass = Ass(style)
    hide = [(tl.at(a, "caption hide"), tl.at(b, "caption hide")) for a, b in (plan.get("captions") or {}).get("hide", [])]
    ass.captions(tl.words, plan.get("captions"), hide)
    for i, item in enumerate(plan.get("texts") or []):
        ass.text(item, tl.at(item.get("at", 0), f"text {i + 1}"))
    for a, name, d in ass.sfx:
        if style["effects"]["auto_sfx"]:
            sfx_events.append((a, name, d, 0.6 if name == "typing" else 1.0, True))
    ass.write(work / "captions.ass")
    fonts = work / "fonts"
    shutil.rmtree(fonts, ignore_errors=True)
    fonts.mkdir()
    ffiles, warnings = font_files(style)
    for ff in ffiles:
        shutil.copy(ff, fonts / ff.name)
    g.append(f"[{cv}]ass=filename=captions.ass:fontsdir=fonts,format=yuv420p[vout]")

    # 5. sound: voice clean-up, overlay audio, sound effects, music, loudness
    sv = float(style["effects"]["sfx_volume"])
    for e in plan.get("sfx") or []:
        sfx_events.append((tl.at(e["at"], f"sound effect {e.get('name')}"), e["name"], e.get("dur"), float(e.get("vol", 1)), False))
    sfx_events.sort(key=lambda e: (e[4], e[0]))
    kept = []
    for e in sfx_events:   # automatic effects never pile up on top of each other or on a chosen one
        if e[4] and any(abs(e[0] - k[0]) < 0.2 for k in kept):
            continue
        kept.append(e)
    kept.sort(key=lambda e: e[0])
    a_chain = "highpass=f=80,afftdn=nf=-25,acompressor=threshold=-20dB:ratio=2.5:attack=5:release=80" \
        if style["audio"]["clean_voice"] else "anull"
    g.append(f"[{ca}]{a_chain}[voice]")
    mix = ["voice"]
    for n, line in enumerate(ov_audio):
        g.append(line)
        mix.append(line.rsplit("[", 1)[1].rstrip("]"))
    for n, (a, name, d, vol, _) in enumerate(kept):
        if a >= tl.total:
            continue
        k = add_input(["-i", SFX.find(name)])
        trim = f"atrim=0:{float(d):.3f},afade=t=out:st={max(0, float(d) - 0.05):.3f}:d=0.05," if d else ""
        g.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,{trim}volume={sv * vol:.3f},"
                 f"adelay={int(max(0, a) * 1000)}:all=1[sx{n}]")
        mix.append(f"sx{n}")
    music = plan.get("music")
    if music and music.get("src"):
        mpath = P.media_path(proj, meta, music["src"])
        k = add_input(["-stream_loop", "-1", "-ss", f"{float(music.get('start', 0)):.3f}", "-i", mpath])
        db = float(music.get("vol_db", style["audio"]["music_db"]))
        g.append("[voice]asplit[voicem][key]")
        mix[0] = "voicem"
        g.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{tl.total:.3f},volume={db}dB,"
                 f"afade=t=in:d=0.6,afade=t=out:st={max(0, tl.total - 1.2):.3f}:d=1.2[mus]")
        g.append("[mus][key]sidechaincompress=threshold=0.03:ratio=5:attack=20:release=400[duck]")
        mix.append("duck")
    lufs = style["audio"]["loudness_lufs"]
    g.append("".join(f"[{m}]" for m in mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0,"
             f"loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=48000,apad,atrim=0:{tl.total:.3f}[aout]")

    graph = work / "graph.txt"
    graph.write_text(";\n".join(g))
    gflag = ["-/filter_complex", graph.name] if ffmpeg_major() >= 7 else ["-filter_complex_script", graph.name]

    version = P.next_version(proj, meta)
    hist = work / "history"
    hist.mkdir(exist_ok=True)
    save_json(hist / f"plan-v{version}.json", plan)
    if final:
        out_dir = P.folder(proj, "final")
        name = f"{meta['name']} - FINAL.mp4"
        old = out_dir / name
        if old.exists():
            (out_dir / "older").mkdir(exist_ok=True)
            old.rename(out_dir / "older" / f"{meta['name']} - replaced {time.strftime('%Y-%m-%d %H%M')}.mp4")
        out = out_dir / name
    else:
        out = P.folder(proj, "previews") / f"preview-v{version}.mp4"
    say("Rendering..." if not final else "Rendering the full-quality final (this takes a few minutes)...")
    cmd = ["ffmpeg", "-v", "error", "-y"] + [a for i in inputs for a in i] + gflag + [
        "-map", "[vout]", "-map", "[aout]", "-r", str(FPS), "-t", f"{tl.total:.3f}", *x264(final, style),
        "-c:a", "aac", "-b:a", "192k" if final else "128k", "-movflags", "+faststart", str(out)]
    run(cmd, cwd=work)
    write_timeline(proj, tl, plan, kept, out, version)
    for w in warnings + tl.problems:
        say(f"⚠️  {w}")
    say(f"Done in {time.time() - t0:.0f}s: {out}")
    return out


def write_timeline(proj, tl, plan, sfx_events, out, version):
    """A readable map of the finished video, so feedback like 'at 0:12 the zoom is too much' is easy to act on."""
    L = [f"# Timeline for {out.name} (v{version}, {fmt_time(tl.total)})", "", "## Segments"]
    for s in tl.segs:
        tr = f" · {s['transition']['type']} in" if s["transition"] else ""
        cuts = f" · {len(s['pieces']) - 1} pause/filler cuts" if len(s["pieces"]) > 1 else ""
        L.append(f"- {fmt_time(s['start'])}–{fmt_time(s['start'] + s['dur'])}  {s['id']}  {s['clip']} "
                 f"{s['pieces'][0][0]:.1f}–{s['pieces'][-1][1]:.1f}s{cuts}{tr}  {s['raw'].get('why', '')}")
    L += ["", "## What's said (caption timing)"]
    line, start = [], None
    for w in tl.words:
        if start is None:
            start = w["s"]
        line.append(w["w"])
        if len(line) >= 10 or w["w"].endswith((".", "?", "!")):
            L.append(f"- {fmt_time(start)}  {' '.join(line)}")
            line, start = [], None
    if line:
        L.append(f"- {fmt_time(start)}  {' '.join(line)}")
    L += ["", "## Overlays, text, zooms, sounds"]
    for o in plan.get("overlays") or []:
        L.append(f"- {fmt_time(tl.at(o.get('at', 0)))}  overlay {o['src']} {'(full screen)' if o.get('full') else ''} {o.get('why', '')}")
    for t in plan.get("texts") or []:
        L.append(f"- {fmt_time(tl.at(t.get('at', 0)))}  text [{t.get('role', 'heading')}] \"{t['text'].replace(chr(10), ' / ')}\"")
    for z in plan.get("zooms") or []:
        L.append(f"- {fmt_time(tl.at(z['at']))}  zoom {z.get('type', 'punch')}")
    for a, name, *_ in sfx_events:
        L.append(f"- {fmt_time(a)}  sound: {name}")
    (Path(proj) / P.FOLDERS["working"] / "timeline.md").write_text("\n".join(L) + "\n")
