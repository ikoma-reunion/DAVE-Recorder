# DAVE Recorder

DAVE Recorder hooks a local Discord client (voice/renderer processes) using Frida and saves received Opus audio and H.264 video streams to files. This repository provides both a GUI (PySide6) and a CLI.

Quick Start :
1. Run your Discord

2. Install and run DAVE-Recorder
```powershell
uv sync

# Run GUI
uv run dave-recorder

# Or CLI
uv run dave-recorder-cli
```

3. Change the settings as needed.

Important: Obtain explicit consent from call participants before recording. Use is at your own risk.


## What this project can do

- Discover and attach to Discord voice/renderer processes using Frida.
- Receive Opus audio packets and write **raw** Ogg/Opus files **per user** (split/append modes supported).
- Receive H.264 frames and save **raw** .h264 streams (waits for keyframes before recording).
- Provide a GUI (PySide6) and a CLI; includes a simple local audio mixer for immediate playback.

## Limitations / What this project does not do

- This is not designed to break Discord E2EE. It hooks native modules used by the client and may break with client updates.(However, it is somewhat robust due to automatic function resolution.)
- It does not replace legal consent. Recording without required consent may be illegal — you are responsible for compliance.
- Not guaranteed to run on all platforms; primarily developed with Windows in mind.
- Frida attach may be blocked by security/anticheat software; SeDebugPrivilege or specific Frida versions may be required.
- This program saves files only in OPUS and H.264. Some software may not be able to play these files directly. You will need to use Audacity or FFmpeg to convert them to MP3 or MP4.

## Requirements

- Python 3.14+ (uv is recommended)

## Usage

Start Discord and set up the call. Then run the GUI or CLI as shown in the Quick Start above.

Configuration is stored in `dave_recorder_settings.json` in the working directory. Recordings are saved to the directory configured in settings (default `recordings/`). Cache is stored in `.cache/`.

## Settings (examples)

- save_directory: directory for recordings
- filename_format: e.g. `{username}_{date}_{time}.opus`
- recording_mode: `split` or `append`
- record_video: enable H.264 saving
- log_level: logging level

## Output files

- Audio: Ogg/Opus (.opus) written by `core.ogg_writer.OggOpusWriter`.
- Video: raw H.264 (.h264); recording starts after a keyframe is observed.

Files are created with `_ongoing.opus` / `_ongoing.h264` suffixes and are renamed with timestamps when segments end.

## Security, Legal and Ethical Notes

- This software is provided for educational/research purposes. Recording without appropriate consent may be illegal or violate agreements. Obtain explicit consent from participants.
- The authors and maintainers accept no liability for consequences from using this software. Use at your own risk.

## Developer notes

- Source is under `src/` with primary packages `core`, `gui`, and `cli`.
- Entry points (see `pyproject.toml`):
  - `dave-recorder = "gui.main:main"`
  - `dave-recorder-cli = "cli.main:main"`
- Tests: use pytest:

```powershell
pytest -q
```

Static analysis / formatting: ruff, pyright (see `pyproject.toml`).

## Troubleshooting

- Frida cannot attach: try running with admin privileges, check antivirus/security software, verify Frida versions.
- Dependency build failures (av, sounddevice): ensure system libraries (FFmpeg, PortAudio) are installed.
- Short or truncated recordings: may indicate hook failure or client changes — increase log verbosity to debug.


---

Last reminder: this tool is for educational/research purposes. Always follow applicable laws, contracts and ethical guidelines when recording.

