# Setting up Reel Studio on your Mac

About 30 minutes, mostly waiting. Do one step at a time; Claude walks you through each one.
Every command is explained before you run it. To run a command: open **Terminal** (Cmd + Space, type Terminal,
press Return), paste the command, press Return, and wait until the line ending in `%` comes back.

## Step 1: free up disk space (no Terminal needed)
Video editing needs room. Aim for **40 GB free** (at least 20).
- Apple menu → System Settings → General → **Storage**. Look at the recommendations and the biggest categories.
- Empty the **Trash**. Check **Downloads** for big old files (sort by size).
- Photos: if you use iCloud Photos, turn on **Optimize Mac Storage** (Photos → Settings → iCloud).
- Old iPhone backups and Messages attachments are often huge (both appear in the Storage screen).

## Step 2: Apple's Command Line Tools
Gives your Mac `python3` and `git`, which Reel Studio needs. Made by Apple.
```
xcode-select --install
```
A window from Apple appears: click **Install**. It may ask for your Mac password: that's macOS installing Apple
software, the same as any App Store install. If it says it's already installed, great, skip ahead.

Homebrew only has ready-made packages for **macOS 15 or newer**. On an older macOS, update first
(System Settings → General → Software Update), or Homebrew will try to build everything from scratch for hours.

## Step 3: Homebrew, then the video and speech tools
Homebrew is the standard, free installer for developer tools on Macs (https://brew.sh). Its installer asks for your
Mac password **once**, because it creates a folder in a system location (`/opt/homebrew`). Your password goes to
macOS only. After that, nothing else in this guide needs your password.
```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
When it finishes, it shows **Next steps** with 2-3 lines starting with `echo` or `eval`. Copy those lines from your own
Terminal and run them (they let Terminal find Homebrew). Then:
```
brew install ffmpeg-full whisper-cpp
```
- **ffmpeg-full**: does all the cutting, captions, sound mixing and exporting. (The plain `ffmpeg` package can't draw captions.)
- **whisper-cpp**: turns speech into text, entirely on your Mac.

## Step 4: get Reel Studio
(Claude will tell you the exact command for your GitHub repository.) The code goes in a folder called
`reel-studio` in your home folder. Your videos live separately in `Movies/Reels`.

## Step 5: the speech model (about 470 MB)
The "brain" whisper-cpp uses to recognise English speech. Downloaded once from the official whisper.cpp model page.
```
curl -L --fail -o ~/reel-studio/models/ggml-small.en.bin --create-dirs https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin
```

## Step 6: check everything
```
cd ~/reel-studio && python3 reel.py doctor && python3 tests/smoke_test.py
```
The first checks the tools; the second edits some made-up test clips (not your footage) and checks the result.
You want to see **READY** and **ALL GOOD**.

## Step 7: start editing
In the Claude desktop app, open the **Code** tab, choose the `reel-studio` folder, and say something like:
> Edit the clips in my Desktop folder "pumpkin patch" into a reel

## Removing everything later
- Reel Studio: delete the `reel-studio` folder (your videos in Movies/Reels stay).
- The tools: `brew uninstall ffmpeg-full whisper-cpp`. Homebrew itself has an uninstall script on https://brew.sh.
