"""Turn an edit plan (plan.json) into an exact timeline: which source seconds play when, where every spoken word
lands in the finished video, and where each overlay / text / sound effect starts."""
import re
from pathlib import Path

from .analyze import load_words
from .util import FPS, ReelError, probe

PAD_AFTER, PAD_BEFORE = 0.12, 0.08    # breathing room kept around words when a pause is shortened
MIN_PIECE = 0.15


def norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


def tighten(words, a, b, max_pause, fillers):
    """Inside [a, b]: drop filler words and shorten long pauses. Returns kept (start, end) pieces of the source."""
    inside = [w for w in words if w["s"] >= a - 0.05 and w["e"] <= b + 0.05]
    keep = [w for w in inside if norm(w["w"]) not in fillers] if fillers else inside
    if not keep:
        return [(a, b)]
    pieces, start = [], max(a, keep[0]["s"] - 0.15)
    for cur, nxt in zip(keep, keep[1:]):
        filler_between = any(cur["e"] <= w["s"] and w["e"] <= nxt["s"] + 0.01 for w in inside if w not in keep)
        if nxt["s"] - cur["e"] > max_pause or (filler_between and nxt["s"] - cur["e"] > PAD_AFTER + PAD_BEFORE):
            cut_a, cut_b = cur["e"] + PAD_AFTER, nxt["s"] - PAD_BEFORE
            if cut_b - cut_a > 0.06:
                pieces.append((start, cut_a))
                start = cut_b
    pieces.append((start, min(b, keep[-1]["e"] + 0.3)))
    merged = []
    for p in pieces:                 # very short leftovers sound choppy: join them to the previous piece
        if merged and p[1] - p[0] < MIN_PIECE:
            merged[-1] = (merged[-1][0], p[1])
        else:
            merged.append(p)
    return [(round(x, 3), round(y, 3)) for x, y in merged if y - x > 0.04]


class Timeline:
    def __init__(self, proj, meta, plan, style):
        self.proj, self.meta, self.plan, self.style = Path(proj), meta, plan, style
        self.segs, self.words, self.problems = [], [], []
        self._build()

    # -- segments --------------------------------------------------------------------------------
    def _build(self):
        segs = self.plan.get("segments") or []
        if not segs:
            raise ReelError("The plan has no segments yet.")
        pacing = self.style["pacing"]
        fillers = set(pacing["fillers"]) if pacing.get("remove_fillers") else set()
        corrections = (self.plan.get("captions") or {}).get("corrections") or {}
        t, ids = 0.0, set()
        for i, s in enumerate(segs):
            sid = s.get("id") or f"s{i + 1}"
            if sid in ids:
                raise ReelError(f"Two segments are called '{sid}'. Each needs its own id.")
            ids.add(sid)
            clip = s.get("clip")
            if clip not in self.meta["clips"]:
                raise ReelError(f"Segment {sid} uses clip '{clip}', which isn't in this project.")
            c = self.meta["clips"][clip]
            if c["kind"] == "photo":
                dur = float(s.get("dur", 2.5))
                pieces, words = [(0.0, dur)], []
            else:
                length = probe(c["file"])["duration"]
                a, b = float(s.get("in", 0)), float(s.get("out", length))
                b = min(b, length)
                if b - a < 0.2:
                    raise ReelError(f"Segment {sid}: 'out' ({b}) must be after 'in' ({a}) and inside the clip ({length:.1f}s long).")
                words = load_words(self.proj, clip)
                pieces = tighten(words, a, b, pacing["max_pause"], fillers) if s.get("tighten") else [(a, b)]
            # snap every piece to whole video frames so sound and picture stay in sync across many cuts
            pieces = [(x, round(x + max(1, round((y - x) * FPS)) / FPS, 4)) for x, y in pieces]
            dur = sum(y - x for x, y in pieces)
            tr = s.get("transition") if i > 0 else None
            if isinstance(tr, str):
                tr = {"type": tr}
            if tr:
                tr = {"type": tr.get("type", "fade"), "dur": float(tr.get("dur", self.style["effects"]["transition_dur"]))}
                tr["dur"] = min(tr["dur"], dur / 2, self.segs[-1]["dur"] / 2)
                t -= tr["dur"]
            seg = {"id": sid, "clip": clip, "kind": c["kind"], "src": c["file"], "pieces": pieces, "start": round(t, 3),
                   "dur": round(dur, 3), "transition": tr, "raw": s}
            self.segs.append(seg)
            # where each kept word lands in the output
            if c["kind"] == "video" and s.get("captions", True):
                off = 0.0
                for x, y in pieces:
                    for w in words:
                        if w["s"] >= x - 0.02 and w["e"] <= y + 0.05 and norm(w["w"]) not in fillers | {""}:
                            text = corrections.get(f"{clip}@{w['s']:.2f}", w["w"])
                            self.words.append({"w": text, "s": round(t + off + w["s"] - x, 3),
                                               "e": round(t + off + min(w["e"], y) - x, 3), "seg": sid, "clip": clip, "src": w["s"],
                                               "y": s.get("caption_y")})
                    off += y - x
            t += dur
        self.total = round(t, 3)

    def seg(self, sid):
        for s in self.segs:
            if s["id"] == sid:
                return s
        raise ReelError(f"There's no segment called '{sid}'. Segments: {', '.join(s['id'] for s in self.segs)}")

    # -- anchors ---------------------------------------------------------------------------------
    def at(self, spec, what="item"):
        """Time in the finished video. Accepts 4.2 | {"seg":"s3"} | {"seg":"s3","t":1.5} | {"seg":"s3","word":"wheel","n":1,"offset":0.1}"""
        if isinstance(spec, (int, float)):
            return float(spec)
        if not isinstance(spec, dict) or "seg" not in spec:
            raise ReelError(f"{what}: 'at' should be seconds or like {{\"seg\": \"s2\", \"word\": \"wheel\"}}")
        seg = self.seg(spec["seg"])
        base = seg["start"]
        if "word" in spec:
            target = [norm(x) for x in str(spec["word"]).split()]
            ws = [w for w in self.words if w["seg"] == seg["id"]]
            hits = [i for i in range(len(ws)) if [norm(w["w"]) for w in ws[i:i + len(target)]] == target]
            if not hits:
                self.problems.append(f"{what}: couldn't find the word '{spec['word']}' in {seg['id']}; placed at the segment start")
            else:
                n = min(int(spec.get("n", 1)), len(hits)) - 1
                base = ws[hits[n]]["s"]
        elif "src" in spec:      # a moment in the source clip, e.g. when the wheel stops at 14.2s
            src_t, off = float(spec["src"]), 0.0
            for x, y in seg["pieces"]:
                if x <= src_t <= y:
                    base = seg["start"] + off + src_t - x
                    break
                off += y - x
            else:
                self.problems.append(f"{what}: source time {src_t}s was cut out of {seg['id']}; placed at the segment start")
        else:
            base += float(spec.get("t", 0))
        return round(base + float(spec.get("offset", 0)), 3)

    def seg_at(self, t):
        for s in reversed(self.segs):
            if s["start"] <= t:
                return s
        return self.segs[0]
