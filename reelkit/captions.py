"""Captions and on-screen text, written as an .ass subtitle file (a format that supports fonts, colours,
outlines, boxes and animation) which FFmpeg burns into the video."""
import re

from .timeline import norm
from .util import hex_to_ass

W, H = 1080, 1920
DEFAULT_POS = {"hook": (0.5, 0.2), "heading": (0.5, 0.28), "typewriter": (0.5, 0.3), "label": (0.5, 0.4),
               "funny": (0.5, 0.42), "caption": (0.5, 0.7), "emphasis": (0.5, 0.5)}
POP = r"\fscx40\fscy40\t(0,110,\fscx112\fscy112)\t(110,190,\fscx100\fscy100)"
BOUNCE = r"\fscx20\fscy20\t(0,140,\fscx125\fscy125)\t(140,230,\fscx92\fscy92)\t(230,300,\fscx100\fscy100)"
CAPTION_POP = r"\fscx78\fscy78\t(0,90,\fscx106\fscy106)\t(90,150,\fscx100\fscy100)"


def ts(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def esc(text):
    return text.replace("\\", "⧵").replace("{", "(").replace("}", ")").replace("\n", r"\N")


def style_line(name, f, safe):
    box = f.get("box")
    outline = box or f.get("outline", "#000000")
    return ("Style: {n},{font},{size},{pc},{pc},{oc},{bc},{b},0,0,0,100,100,{sp},0,{bs},{ow},{sh},5,{ml},{mr},0,1".format(
        n=name, font=f["family"], size=f["size"], pc=hex_to_ass(f.get("color", "#FFFFFF")), oc=hex_to_ass(outline),
        bc=hex_to_ass("#000000", 0x80), b=-1 if f.get("bold") else 0, sp=f.get("spacing", 0), bs=3 if box else 1,
        ow=f.get("box_padding", 14) if box else f.get("outline_width", 4), sh=f.get("shadow", 0),
        ml=int(safe["left"] * W), mr=int(safe["right"] * W)))


class Ass:
    def __init__(self, style):
        self.style = style
        self.events = []
        self.sfx = []        # automatic sound effects that go with text animations: (time, name, dur or None)

    def add(self, start, end, sty, text, layer=0):
        if end - start > 0.02:
            self.events.append(f"Dialogue: {layer},{ts(start)},{ts(end)},{sty},,0,0,0,,{text}")

    def emph_color(self):
        return hex_to_ass(self.style["captions"]["highlight_color"])

    # -- spoken captions -------------------------------------------------------------------------
    def captions(self, words, cfg, hide):
        c = self.style["captions"] | (cfg or {})
        mode = c.get("mode", "highlight")
        if mode == "none" or not words:
            return
        emph = {norm(x) for x in c.get("emphasis", [])}
        emph_at = [float(x) for x in c.get("emphasis_at", [])]
        upper = c.get("uppercase")
        words = [w for w in words if not any(a <= w["s"] < b for a, b in hide)]
        phrases, cur = [], []
        for w in words:
            if cur and (len(cur) >= c["max_words"] or w["s"] - cur[-1]["e"] > 0.35 or w["seg"] != cur[-1]["seg"]
                        or re.search(r"[.?!,]$", cur[-1]["w"])):
                phrases.append(cur)
                cur = []
            cur.append(w)
        if cur:
            phrases.append(cur)
        anim = c.get("anim", "pop")
        for i, ph in enumerate(phrases):
            nxt = phrases[i + 1][0]["s"] if i + 1 < len(phrases) else ph[-1]["e"] + 0.6
            end = nxt if nxt - ph[-1]["e"] < 0.3 else ph[-1]["e"] + 0.25
            y = int((ph[0].get("y") or c["y"]) * H)
            pos = rf"\an5\pos({W // 2},{y})"

            def word_txt(w, lit=False):
                t = esc(w["w"].upper() if upper else w["w"])
                t = re.sub(r"[,]$", "", t) if mode in ("word",) else t
                if norm(w["w"]) in emph or any(abs(w["s"] - a) < 0.08 for a in emph_at):
                    return r"{\rEmphasis}" + t + r"{\rCaption}"
                if lit:
                    return r"{\c" + self.emph_color() + r"&}" + t + r"{\rCaption}"
                return t
            intro = CAPTION_POP if anim == "pop" else r"\fad(80,0)" if anim == "fade" else ""
            if mode == "phrase":
                self.add(ph[0]["s"], end, "Caption", "{" + pos + intro + "}" + " ".join(word_txt(w) for w in ph))
            elif mode == "word":
                for j, w in enumerate(ph):
                    e = ph[j + 1]["s"] if j + 1 < len(ph) else end
                    self.add(w["s"], e, "Caption", "{" + pos + intro + "}" + word_txt(w))
            else:   # highlight / build: one event per spoken word so the current word can change
                for j, w in enumerate(ph):
                    s = ph[0]["s"] if j == 0 else w["s"]
                    e = ph[j + 1]["s"] if j + 1 < len(ph) else end
                    if mode == "build":
                        txt = " ".join(word_txt(x) for x in ph[:j + 1])
                        rest = " ".join(word_txt(x) for x in ph[j + 1:])
                        txt += (r" {\alpha&HFF&}" + rest) if rest else ""
                        self.add(s, e, "Caption", "{" + pos + (intro if j == 0 else "") + "}" + txt)
                    else:
                        txt = " ".join(word_txt(x, lit=(k == j)) for k, x in enumerate(ph))
                        self.add(s, e, "Caption", "{" + pos + (intro if j == 0 else "") + "}" + txt)

    # -- titles, hooks, labels, typewriter -------------------------------------------------------
    def text(self, item, start):
        role = item.get("role", "heading")
        if role not in self.style["fonts"]:
            role = "heading"
        dur = float(item.get("dur", 2.5))
        end = start + dur
        x, y = item.get("pos") or DEFAULT_POS.get(role, (0.5, 0.3))
        px, py = int(x * W), int(y * H)
        anim = item.get("anim") or ("typewriter" if role == "typewriter" else "pop")
        out = item.get("anim_out", "fade")
        raw = item["text"].upper() if item.get("uppercase") else item["text"]
        emph = {norm(e) for e in item.get("emphasis", [])}
        rot = rf"\frz{item['angle']}" if item.get("angle") else ""
        sty = role.capitalize()

        def styled(t):
            parts = re.split(r"(\s+)", t)
            return "".join(r"{\c" + self.emph_color() + "&}" + esc(p) + r"{\r" + sty + "}" if norm(p) and norm(p) in emph else esc(p)
                           for p in parts)
        fout = r"\fad(0,160)" if out == "fade" else ""
        tail = ""
        if out == "pop":
            ms = int(dur * 1000)
            tail = rf"\t({ms - 140},{ms},\fscx0\fscy0)"
        auto = item.get("sfx", True)
        if anim == "typewriter":
            cps = float(item.get("cps", self.style["effects"]["typewriter_cps"]))
            n = len(raw)
            type_dur = n / cps
            for k in range(1, n + 1):
                if raw[k - 1] == " " and k < n:
                    continue
                s = start + (k - 1) / cps
                e = start + k / cps if k < n else end
                shown, hidden = raw[:k], raw[k:]
                txt = styled(shown) + (r"{\alpha&HFF&}" + esc(hidden) if hidden else "")
                self.add(s, e, sty, "{" + rf"\an5\pos({px},{py}){rot}" + (fout if k == n else "") + "}" + txt, layer=2)
            if auto:
                self.sfx.append((start, auto if isinstance(auto, str) else "typing", type_dur))
            return
        moves = {"slide-up": (0, 120), "slide-down": (0, -120), "slide-left": (220, 0), "slide-right": (-220, 0)}
        if anim in moves:
            dx, dy = moves[anim]
            head = rf"\an5\move({px + dx},{py + dy},{px},{py},0,220)\fad(140,0)"
        else:
            head = rf"\an5\pos({px},{py})" + {"pop": POP, "bounce": BOUNCE, "fade": r"\fad(200,0)"}.get(anim, "")
        self.add(start, end, sty, "{" + head + rot + fout + tail + "}" + styled(raw), layer=2)
        if auto:
            name = auto if isinstance(auto, str) else {"pop": "pop", "bounce": "pop"}.get(anim, "swish" if anim in moves else None)
            if name:
                self.sfx.append((start, name, None))

    def write(self, path):
        safe = self.style["safe_area"]
        head = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0",
                "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "", "[V4+ Styles]",
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
                "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"]
        for role, f in self.style["fonts"].items():
            if not role.startswith("_"):
                head.append(style_line(role.capitalize(), f, safe))
        head += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
        path.write_text("\n".join(head + self.events) + "\n", encoding="utf-8")
