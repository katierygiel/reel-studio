# The edit plan (`4-working/plan.json`)

One file describes the whole edit. Claude writes it; the renderer turns it into video. Times are seconds.
Clips are referred to by id (`C01`, `C02`...) from the footage report; extra files by their name in `2-assets`.

## Placing things in time (`at`)
Anything that happens at a moment (overlays, text, zooms, sounds) takes an `at`:

| `at` | meaning |
|---|---|
| `4.2` | 4.2 s into the finished video |
| `{"seg": "s3"}` | when segment s3 starts |
| `{"seg": "s3", "t": 1.5}` | 1.5 s into segment s3 |
| `{"seg": "s3", "word": "wheel"}` | the moment they say "wheel" in s3 (`"n": 2` for the 2nd time; phrases like `"the wheel"` work) |
| `{"seg": "s3", "src": 14.2}` | the moment that was at 14.2 s in the original clip (e.g. when the wheel stops) |
| add `"offset": 0.2` | nudge later (or earlier with a negative number) |

Word anchors keep working when cuts change, so prefer them for anything tied to speech.

## Fields

```jsonc
{
  "title": "Pumpkin patch day",
  "notes": "Why this structure (for the person and for future you)",

  "segments": [                       // the main sequence, in order
    { "id": "s1", "clip": "C03", "in": 4.2, "out": 9.8,
      "tighten": true,                // remove fillers + shorten pauses (talking)
      "focus": [0.5, 0.4],            // which part to keep when cropping to vertical (0-1 across, 0-1 down)
      "volume": 1, "mute": false,
      "captions": true,               // false = no captions from this segment's speech
      "caption_y": 0.7,               // move captions up/down for this segment (avoid faces)
      "transition": null,             // or "fade" or {"type": "whip-left", "dur": 0.25}  (into this segment)
      "why": "hook: best line" },
    { "id": "s5", "clip": "C07", "dur": 2.5, "push": true }   // a photo: shown for 2.5 s with a slow zoom
  ],

  "captions": {
    "mode": "highlight",              // highlight | phrase | word | build | none   (default from style)
    "max_words": 3,
    "emphasis": ["best", "finally"],  // words shown in the emphasis font/colour
    "emphasis_at": [12.4],            // or specific occurrences, by time in the finished video
    "corrections": { "C03@5.12": "Trader Joe's" },   // fix a misheard word: clip@word-start-time
    "hide": [[{"seg": "s4"}, {"seg": "s5"}]]          // no captions between two moments
  },

  "zooms": [
    { "at": {"seg": "s1", "word": "never"}, "dur": 1.2, "type": "punch", "scale": 1.15, "focus": [0.5, 0.35] }
    // type: punch (instant, CapCut-style) | push (smooth zoom-in)
  ],

  "overlays": [                      // anything layered on top: b-roll, picture-in-picture, logos, stickers
    { "src": "C05", "in": 2.0, "at": {"seg": "s2", "word": "pumpkins"}, "dur": 2.5, "full": true },   // full-screen b-roll
    { "src": "C02", "in": 0.5, "at": 3.1, "dur": 2,
      "box": {"x": 0.5, "y": 0.38, "w": 0.55},   // centre position + width (fractions of the screen); or "h"
      "border": 8, "border_color": "white", "round": 28,
      "anim_in": "pop", "anim_out": "pop",       // pop | fade | slide-left | slide-right | slide-up | slide-down | none
      "speed": 0.5,                              // slow motion (0.5) or faster (2)
      "volume": 0.4,                             // play its own sound (default: muted)
      "sfx": "ding" },                           // sound when it appears (default: automatic, false = none)
    { "src": "logo.jpg", "remove_bg": "white", "at": {"seg": "s6"}, "dur": 2, "box": {"x": 0.5, "y": 0.25, "w": 0.4} }
    // remove_bg: white | black | green | blue | "#RRGGBB"
  ],

  "texts": [
    { "text": "I SPUN\nTHE WHEEL", "role": "hook", "at": 0, "dur": 2, "anim": "pop", "emphasis": ["wheel"] },
    { "text": "the verdict:", "role": "typewriter", "at": {"seg": "s4"}, "dur": 2.5, "pos": [0.5, 0.3], "cps": 18 },
    { "text": "$4.99!!", "role": "funny", "at": 8.0, "dur": 1.5, "anim": "bounce", "angle": -6 }
    // role: hook | heading | label | typewriter | funny | caption | emphasis  (fonts come from your style)
    // anim: pop | bounce | fade | slide-up | slide-down | slide-left | slide-right | typewriter | none
    // anim_out: fade (default) | pop | none     pos: [x, y] fractions     uppercase: true     sfx: name | false
  ],

  "sfx": [ { "name": "ding", "at": {"seg": "s3", "src": 14.2}, "vol": 0.8 } ],

  "music": { "src": "song.mp3", "start": 12.0, "vol_db": -20 }     // your own music file; ducks under speech
}
```

Transitions: fade, dissolve, white-flash, black, slide-left/right/up/down, whip-left/right/up, zoom, circle, blur, wipe.
