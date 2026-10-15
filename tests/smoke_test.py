#!/usr/bin/env python3
"""Self-test: builds made-up clips (never your footage) in a temporary folder, runs the whole pipeline and checks
the result. On a Mac it also makes a real spoken clip with the built-in `say` voice to test speech-to-text.
Usage: python3 tests/smoke_test.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="reel-selftest-"))
ENV = dict(os.environ, REELS_HOME=str(TMP / "Reels"), REELS_STYLE=str(TMP / "Reels" / "_my-style"))
MEDIA = TMP / "media"


def sh(*cmd, cwd=None):
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, env=ENV, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit(f"FAILED: {' '.join(map(str, cmd[:3]))}")
    return r.stdout


def ff(*args):
    sh("ffmpeg", "-v", "error", "-y", *args)


def make_media():
    (MEDIA / "clips").mkdir(parents=True)
    (MEDIA / "assets").mkdir()
    c, a = MEDIA / "clips", MEDIA / "assets"
    speech = ("0.3*sin(2*PI*220*t)*(between(t,0.5,2.4)+between(t,2.6,3.0)+between(t,4.6,7.0)+between(t,7.2,10.5))")
    ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=12", "-f", "lavfi", "-i", f"aevalsrc='{speech}':d=12",
       "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-metadata", "creation_time=2026-10-10T10:00:00Z", c / "talking.mov")
    ff("-f", "lavfi", "-i", "color=white:s=800x800:r=30:d=6", "-f", "lavfi", "-i", "sine=f=500:d=6", "-filter_complex",
       "[0:v]geq=r='128+127*cos(atan2(Y-400,X-400)*6)':g='128+127*sin(atan2(Y-400,X-400)*6)':b='200',rotate='t*3':c=white[v]",
       "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
       "-metadata", "creation_time=2026-10-10T10:05:00Z", c / "wheel.mp4")
    ff("-f", "lavfi", "-i", "mandelbrot=s=1920x1080:r=30", "-f", "lavfi", "-i", "anoisesrc=d=8:a=0.05", "-t", "8",
       "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-metadata", "creation_time=2026-10-10T10:10:00Z", c / "place.mp4")
    ff("-f", "lavfi", "-i", "smptehdbars=s=1080x1920:r=30:d=4", "-c:v", "libx264", "-preset", "ultrafast",
       "-pix_fmt", "yuv420p10le", "-color_trc", "arib-std-b67", "-color_primaries", "bt2020", "-colorspace", "bt2020nc",
       "-an", "-metadata", "creation_time=2026-10-10T10:15:00Z", c / "hdr.mov")
    ff("-f", "lavfi", "-i", "testsrc=s=1200x900:d=1", "-frames:v", "1", c / "photo.jpg")
    ff("-f", "lavfi", "-i", "color=hotpink:s=600x300", "-vf",
       "format=rgba,geq=r='255':g='if(between(X,120,480)*between(Y,110,190),255,105)':b='if(between(X,120,480)*between(Y,110,190),255,180)'"
       ":a='if(between(X,40,560)*between(Y,40,260),255,0)'", "-frames:v", "1", a / "logo.png")
    ff("-f", "lavfi", "-i", "color=white:s=500x500", "-vf", "drawbox=x=100:y=100:w=300:h=300:color=orange:t=fill",
       "-frames:v", "1", a / "sticker-white-bg.jpg")
    ff("-f", "lavfi", "-i", "aevalsrc='0.2*sin(2*PI*330*t)*(0.5+0.5*sin(2*PI*2*t))+0.15*sin(2*PI*495*t)':d=30", a / "song.mp3")


WORDS = [("So", .5, .7), ("today", .75, 1.1), ("I", 1.15, 1.25), ("finally", 1.3, 1.75), ("spun", 1.8, 2.05), ("the", 2.08, 2.15),
         ("wheel.", 2.18, 2.4), ("um", 2.6, 3.0), ("And", 4.6, 4.8), ("this", 4.85, 5.05), ("is", 5.1, 5.2), ("the", 5.25, 5.35),
         ("part", 5.4, 5.65), ("I", 5.7, 5.8), ("was", 5.85, 6.0), ("most", 6.05, 6.35), ("excited", 6.4, 6.95), ("about.", 7.2, 7.5),
         ("Look", 8.0, 8.3), ("at", 8.35, 8.45), ("this", 8.5, 8.8), ("place!", 9.0, 9.6), ("Honestly", 9.7, 10.1), ("amazing.", 10.1, 10.5)]

PLAN = json.loads((CODE / "tests" / "smoke_plan.json").read_text())


def check(label, ok):
    print(("  ✅ " if ok else "  ❌ ") + label)
    return ok


def main():
    reel = [sys.executable, CODE / "reel.py"]
    print(f"Self-test in {TMP} (deleted afterwards)")
    make_media()
    sh(*reel, "new", "Self test", MEDIA / "clips")
    proj = next((TMP / "Reels").glob("*-self-test"))
    for f in (MEDIA / "assets").iterdir():
        shutil.copy(f, proj / "2-assets")
    sh(*reel, "analyze", proj)
    (proj / "3-analysis" / "words" / "C01.json").write_text(json.dumps([{"w": w, "s": s, "e": e} for w, s, e in WORDS]))
    sh(*reel, "analyze", proj)
    (proj / "4-working" / "plan.json").write_text(json.dumps(PLAN))
    sh(*reel, "preview", proj)
    out = proj / "5-previews" / "preview-v1.mp4"
    good = check("preview rendered", out.exists())
    if out.exists():
        dur = float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out))
        good &= check(f"length {dur:.2f}s (expected about 14.1s)", abs(dur - 14.13) < 0.15)
        loud = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
        lufs = float(loud.rsplit("I:", 1)[1].split("LUFS")[0])
        good &= check(f"loudness {lufs} LUFS (target -14)", abs(lufs + 14) < 1.5)
    tl = (proj / "4-working" / "timeline.md").read_text()
    good &= check("filler + long pause removed", "1 pause/filler cuts" in tl)
    good &= check("chosen sound not doubled by an automatic one", tl.count("0:08.83  sound") == 1)

    if sys.platform == "darwin" and shutil.which("say") and shutil.which("whisper-cli"):
        print("Speech-to-text test (Mac voice)...")
        line = "So today I finally spun the wheel. This is the part I was most excited about."
        sh("say", "-o", MEDIA / "voice.aiff", line)
        ff("-f", "lavfi", "-i", "color=gray:s=1080x1920:r=30:d=6", "-i", MEDIA / "voice.aiff", "-shortest",
           "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", MEDIA / "spoken.mov")
        sh(*reel, "new", "Speech test", MEDIA / "spoken.mov")
        sp = next((TMP / "Reels").glob("*-speech-test"))
        sh(*reel, "analyze", sp)
        words = json.loads((sp / "3-analysis" / "words" / "C01.json").read_text())
        heard = " ".join(w["w"] for w in words).lower()
        good &= check(f"heard: \"{heard[:70]}...\"", "wheel" in heard and "excited" in heard)
    else:
        print("  ➖ speech-to-text test skipped (needs a Mac with whisper-cli installed)")
    shutil.rmtree(TMP, ignore_errors=True)
    print("ALL GOOD" if good else "SOMETHING FAILED (see ❌ above)")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
