"""Built-in sound effects, synthesised from scratch with FFmpeg: no downloads, no licences.
Your own sounds win: drop e.g. ding.wav or ding.mp3 into ~/Movies/Reels/_my-style/sfx/ and it replaces the built-in 'ding'.
Any other file you put there becomes a new effect named after the file."""
from pathlib import Path

from .util import AUDIO_EXT, CODE_DIR, STYLE_DIR, ReelError, run

BUILTIN_DIR = CODE_DIR / "build" / "sfx"

# name: (generator, filters, what it's for)
SYNTH = {
    "pop":     ("sine=f=640:d=0.12", "vibrato=f=12:d=0.4,afade=t=out:st=0.02:d=0.10", "text or a sticker popping on"),
    "ding":    ("aevalsrc='0.55*sin(2*PI*1568*t)*exp(-3.5*t)+0.35*sin(2*PI*2352*t)*exp(-5*t)+0.15*sin(2*PI*3136*t)*exp(-7*t)':d=1.3",
                "afade=t=in:d=0.004", "a positive reveal, something exciting"),
    "sparkle": ("aevalsrc='0.5*sin(2*PI*(2600+900*sin(2*PI*9*t))*t)*exp(-4*t)':d=0.9", "aecho=0.6:0.5:40:0.4,afade=t=in:d=0.01", "something pretty or magical"),
    "whoosh":  ("anoisesrc=d=0.5:c=pink:a=0.6", "highpass=f=500,lowpass=f=6000,afade=t=in:d=0.28:curve=exp,afade=t=out:st=0.28:d=0.22", "an intentional transition"),
    "swish":   ("anoisesrc=d=0.25:c=pink:a=0.5", "highpass=f=900,lowpass=f=7000,afade=t=in:d=0.12:curve=exp,afade=t=out:st=0.12:d=0.13", "text sliding in"),
    "click":   ("anoisesrc=d=0.03:c=white:a=0.9", "highpass=f=2500,afade=t=out:st=0.004:d=0.025", "a tap, a button, a list item"),
    "typing":  ("aevalsrc='0.8*random(0)*lt(mod(t\\,0.075)\\,0.006)':d=8", "highpass=f=1500,lowpass=f=8000", "typewriter text (trimmed to the text's length)"),
    "shutter": ("aevalsrc='random(0)*(lt(t\\,0.025)+between(t\\,0.09\\,0.12))':d=0.2", "highpass=f=1200,lowpass=f=9000", "camera / photo moment"),
    "notify":  ("aevalsrc='0.5*sin(2*PI*988*t)*lt(t\\,0.12)*exp(-10*t)+0.5*sin(2*PI*1319*t)*gte(t\\,0.12)*exp(-8*(t-0.12))':d=0.7", "afade=t=in:d=0.004", "a notification-style callout"),
    "boing":   ("aevalsrc='0.7*sin(2*PI*(160*t+5*sin(2*PI*11*t)))*exp(-3*t)':d=0.9", "afade=t=in:d=0.004", "a comedic moment"),
    "rise":    ("aevalsrc='0.4*sin(2*PI*(220*t+700*t*t))':d=0.8", "afade=t=in:d=0.5:curve=exp,afade=t=out:st=0.7:d=0.1", "build-up before a reveal"),
    "boom":    ("aevalsrc='0.9*sin(2*PI*(70*t-12*t*t))*exp(-2.5*t)':d=1.2", "lowpass=f=400,afade=t=in:d=0.005", "a dramatic, big moment"),
}


def build_builtin(force=False):
    BUILTIN_DIR.mkdir(parents=True, exist_ok=True)
    for name, (src, af, _) in SYNTH.items():
        out = BUILTIN_DIR / f"{name}.wav"
        if out.exists() and not force:
            continue
        # synthesise, then bring every effect to the same peak level (-3 dB) so volumes are predictable
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-af", f"{af},aformat=channel_layouts=stereo",
             "-ar", "48000", str(out) + ".tmp.wav"])
        peak = run(["ffmpeg", "-hide_banner", "-i", str(out) + ".tmp.wav", "-af", "volumedetect", "-f", "null", "-"]).stderr
        mx = float(peak.split("max_volume:")[1].split("dB")[0]) if "max_volume:" in peak else 0.0
        run(["ffmpeg", "-v", "error", "-y", "-i", str(out) + ".tmp.wav", "-af", f"volume={-3 - mx:.2f}dB", str(out)])
        Path(str(out) + ".tmp.wav").unlink()


def library():
    """{name: path}. Your files in _my-style/sfx override the built-ins."""
    build_builtin()
    lib = {p.stem: p for p in BUILTIN_DIR.glob("*.wav")}
    if (STYLE_DIR / "sfx").exists():
        for p in (STYLE_DIR / "sfx").iterdir():
            if p.suffix.lower() in AUDIO_EXT:
                lib[p.stem.lower()] = p
    return lib


def find(name):
    lib = library()
    if name not in lib:
        raise ReelError(f"No sound effect called '{name}'. Available: {', '.join(sorted(lib))}")
    return lib[name]


def describe():
    lib = library()
    lines = []
    for name in sorted(lib):
        what = SYNTH[name][2] if name in SYNTH and lib[name].parent == BUILTIN_DIR else "your own sound"
        lines.append(f"- {name}: {what}")
    return "\n".join(lines)
