#!/usr/bin/env python3
"""Reel Studio: your personal AI-assisted reel editor. Claude normally runs these commands for you.

  python3 reel.py doctor                      check everything is installed
  python3 reel.py new "Pumpkin patch" <folder or files...>
  python3 reel.py analyze <project>           transcripts, contact sheets, footage report
  python3 reel.py frame <project> C03 12.5    one bigger still for a closer look
  python3 reel.py preview <project>           fast low-res preview of 4-working/plan.json
  python3 reel.py final <project>             full-quality 1080x1920 export to 6-final
  python3 reel.py sfx                         list sound effects
  python3 reel.py clean <project>             delete temporary render files
"""
import shutil
import sys

from reelkit import analyze as A
from reelkit import project as P
from reelkit import sfx as SFX
from reelkit.render import has_zscale, render
from reelkit.style import STYLE_DIR, ensure_style_dir, font_files, load_style
from reelkit.util import REELS_HOME, ReelError, ffmpeg_major, free_gb, run, say


def doctor():
    ok = True

    def line(good, text, fix=""):
        nonlocal ok
        say(("  ✅ " if good else "  ❌ ") + text + ("" if good or not fix else f"\n       fix: {fix}"))
        ok = ok and good

    say("Reel Studio check")
    line(sys.version_info >= (3, 9), f"Python {sys.version.split()[0]}", "install Apple's Command Line Tools")
    if shutil.which("ffmpeg"):
        filters = run(["ffmpeg", "-hide_banner", "-filters"]).stdout
        line(True, f"FFmpeg {ffmpeg_major()}")
        line(" ass " in filters, "FFmpeg can draw captions (libass)", "this FFmpeg build lacks libass; see SETUP.md")
        if not has_zscale():
            say("  ⚠️  FFmpeg can't convert iPhone HDR colours (zimg); HDR clips may look a little flat")
    else:
        line(False, "FFmpeg", "see SETUP.md step 3")
    cli, model = A.whisper_tools()
    line(bool(cli), "speech-to-text program (whisper-cli)", "see SETUP.md step 3")
    line(bool(model), f"speech model{f' ({model.name})' if model else ''}", "see SETUP.md step 4")
    ensure_style_dir()
    style = load_style()
    _, warnings = font_files(style)
    line(not warnings, f"your style folder: {STYLE_DIR}")
    for w in warnings:
        say(f"     ⚠️  {w}")
    gb = free_gb(REELS_HOME)
    line(gb >= 15, f"{gb:.0f} GB free disk space", "free up space: aim for 20+ GB (see SETUP.md step 1)")
    say("READY" if ok else "NOT READY YET: fix the ❌ items above.")
    return 0 if ok else 1


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        say(__doc__)
        return 0
    cmd, args = argv[1], argv[2:]
    if cmd == "doctor":
        return doctor()
    ensure_style_dir()
    if cmd == "new":
        if len(args) < 2:
            raise ReelError('Usage: reel.py new "Project name" <folder or files...>')
        P.new_project(args[0], args[1:])
    elif cmd == "analyze":
        A.analyze(args[0], force="--force" in args)
    elif cmd == "frame":
        proj, meta = P.load_project(args[0])
        clip, t = args[1], float(args[2])
        out = P.folder(proj, "analysis") / "frames" / f"{clip}_{t:.1f}s.jpg"
        out.parent.mkdir(exist_ok=True)
        say(A.frame(P.media_path(proj, meta, clip), t, out))
    elif cmd == "preview":
        render(args[0], final=False, plan_file=args[1] if len(args) > 1 else None)
    elif cmd == "final":
        render(args[0], final=True, plan_file=args[1] if len(args) > 1 else None)
    elif cmd == "sfx":
        say(SFX.describe())
    elif cmd == "clean":
        P.clean(P.resolve(args[0]))
    else:
        raise ReelError(f"Unknown command '{cmd}'. Run: python3 reel.py help")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except ReelError as e:
        say(f"\n❌ {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
