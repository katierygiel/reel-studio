# Reel Studio

A personal, local-first reel editor. Give Claude a folder of raw clips. It works out the story, picks the best
moments and takes, cuts the "um"s and dead air, and adds captions, overlays, sound effects, zooms and transitions in
*your* style. It previews, takes your notes, and exports a finished 1080×1920 MP4.

Setup: see **[SETUP.md](SETUP.md)**. For Claude: **[CLAUDE.md](CLAUDE.md)** (how to edit) and
**[docs/PLAN-FORMAT.md](docs/PLAN-FORMAT.md)** (the edit plan).

## How it works
1. `reel.py new` sets up a project folder and numbers your clips in filming order. Your originals are never changed.
2. `reel.py analyze` runs on your Mac and produces word-timed transcripts, pauses, scene changes, movement,
   loud moments, contact sheets of stills and possible repeated takes, all in `3-analysis/report.md`.
3. Claude reads the report and stills and writes an **edit plan** (`4-working/plan.json`): story order, trims, B-roll,
   overlays, text, zooms, sounds.
4. `reel.py preview` renders a fast 540×960 preview. You give notes, Claude changes the plan, and only the changed
   parts re-render.
5. `reel.py final` renders the full-quality 1080×1920 H.264 MP4 into `6-final`.

## Your files
```
~/Movies/Reels/
  _my-style/              your style: fonts, colours, rules, feedback, your own sounds and font files
  2026-10-15-pumpkin-patch/
    1-footage/            read-only working copies (APFS clones: no extra disk space) or nothing if used in place
    2-assets/             drop logos, overlay videos, photos, music here
    3-analysis/           transcripts, contact sheets, footage report
    4-working/            plan.json, timeline.md, captions, temporary files (reel.py clean frees space)
    5-previews/           preview-v1.mp4, preview-v2.mp4 ...
    6-final/              "<name> - FINAL.mp4" (older finals move to 6-final/older)
```

## Privacy and cost
- All analysis and rendering happens on your Mac. Nothing is uploaded by these scripts.
- Claude (in the Claude app) sees transcripts and still images in order to make editing decisions, under your Claude
  plan's terms. It never receives your video files.
- No API keys and no per-video fees: it runs on your existing Claude plan (big projects use more of your usage limit).
- Sound effects are generated from scratch (no licences needed). Music and extra sounds are files you provide.

## Status
Built and tested on Linux with made-up clips. Not yet tested on a Mac or with real speech; `tests/smoke_test.py`
covers that once it's installed.
Coming next: a local review page (reorder/trim/caption edits in your browser), face-aware caption placement,
analysis of reference reels, beat-synced music cuts.
