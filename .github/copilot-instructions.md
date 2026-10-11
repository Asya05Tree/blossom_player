# Copilot instructions for Blossom Player

Short, actionable guidance to help AI coding agents be productive in this repo.

## Quick start
- Install core Python dependencies (PyQt6 UI, audio, and tag parsing) and external tools:

  ```bash
  pip install PyQt6 mutagen yt-dlp spotdl
  # ffmpeg is required by yt-dlp/spotdl - install via system package manager
  # fpcalc (Chromaprint) is required for duplicate detection by audio fingerprint -
  # download from https://github.com/acoustid/chromaprint/releases and place at
  # tools/fpcalc/fpcalc.exe (or put fpcalc on PATH). See core/fingerprint_util.py.
  # shazamio needs a special install order on new Python versions - see the
  # comment block at the bottom of requirements.txt (core/shazam_util.py).
  ```

- Run the app locally:

  ```bash
  python main.py
  ```

- Populate a development DB entry (edit the MP3 path first):

  ```bash
  # Open seed.py and set a valid local MP3 path, then:
  python seed.py
  ```

## High-level architecture (what to read first)
- UI: `ui/index.html`, `ui/script.js`, `ui/style.css` — the application uses a lightweight HTML/JS front-end rendered inside a PyQt6 `QWebEngineView` (see `main.py`).
- Bridge: `core/bridge.py` is the canonical Python ⇄ JS interface. It registers the `pyBridge` object with `QWebChannel` and exposes slots/signals used by the front-end.
- Playback: `core/player.py` encapsulates playback using `PyQt6.QtMultimedia.QMediaPlayer` + `QAudioOutput` and manages queue/loop/shuffle logic.
- Persistence: `core/database.py` provides a small SQLite CRUD layer (DB file: `blossom.db`). Models are in `core/models.py`.
- Downloads & conversion: `core/downloader.py` uses `yt-dlp` and the `spotdl` CLI; downloads go to `assets/downloads` and are post-processed to MP3 (FFmpeg required).
- Covers: `core/covers.py` handles saving and resizing album art used throughout the UI and seed flow.

Read these files in order: `main.py` → `core/bridge.py` → `core/player.py` → `core/database.py` to get a compact understanding of control flow.

## Data & flow notes (concrete patterns)
- The front-end asks Python for state via the `pyBridge` object; when the page loads the bridge calls `_update_ui_state()` to emit `songChanged` and other signals.
- Database initialization: `db.init_db()` is called from `BlossomBridge.__init__` — modules assume the DB exists after bridge construction.
- Song representation: `core/models.py` defines `Song` objects; `core/database.py` stores file paths as strings (absolute or relative). Many parts of the app expect `filepath` to reference a real local file.
- Cover handling: code uses `file:///` URLs for local cover images (see `core/bridge.py` converting Windows paths) — be careful with backslash↔slash transforms on Windows.

## Conventions & project-specific patterns
- Visual/text style: many user-visible strings are decorated with special Unicode characters (see `core/bridge.py` and `seed.py` where titles/artists are formatted with ✧ and ❀). Preserve this style when adding UI-visible text.
- DB access: use `core.database` helper functions (`add_song`, `get_all_songs`, etc.) rather than touching SQLite directly.
- Downloads: `core/downloader.py` expects `yt-dlp` Python package and the `spotdl` CLI; errors are printed to stdout. If adding features around downloads, follow the same approach (return a dict with `title`, `artist`, `filepath`).
- Plugins: there is a `plugins/` directory organized by capability. No single automatic loader was found while scanning code — treat these folders as organizational, inspect existing plugin modules and adapt to their local usage patterns before assuming runtime auto-discovery.

## Common developer workflows (how contributors run and debug)
- Start UI-driven debugging: run `python main.py` and watch stdout for print-debugging lines — bridge functions print errors and flow-related messages.
- Recreate DB state: edit `seed.py` to point to a valid MP3, then `python seed.py` to add a test record.
- Add a song from the UI: use the built-in file dialog exposed in `core/bridge.py` (`add_new_song_dialog`) — it will extract ID3 tags via `mutagen.easyid3` when present and persist via `core.database`.

## Important files to reference when changing behavior
- `main.py` — app entry, PyQt app and QWebEngineView wiring.
- `core/bridge.py` — all JS ⇄ Python interactions; update signal signatures carefully (front-end expects exact parameter order).
- `core/player.py` — playback semantics (loop modes: `sequence`, `repeat_one`, `repeat_all`) and shuffle handling.
- `core/database.py` & `core/models.py` — DB schema and model shapes used across the app.
- `core/downloader.py` — uses `yt-dlp` and `spotdl`; follow its return shape when adding new sources.

## Safety/caveats discovered in the codebase
- `seed.py` contains an absolute path placeholder — update it in your environment before running.
- `core/downloader.py` launches `spotdl` via `subprocess.run` — ensure `spotdl` is installed and on PATH. `yt-dlp` is used programmatically and needs `ffmpeg` available for conversion.
- The app assumes local files exist for playback; adding remote streaming will require changes to `core/player.py` and possibly to how `filepath` is stored.

## When in doubt (guidance for PR authors)
- Preserve the `pyBridge` API shape: the JS side calls slots with specific arg order — changing arg order or types requires front-end updates in `ui/script.js`.
- Prefer `core.database` helpers for persistence and `core/covers.py` for cover generation to keep behavior consistent.

---
If anything here is unclear or you want more examples (small code snippets for common changes), tell me which area to expand.
