# Desktop Buddy — Project Standards

This file encodes the permanent standards for the `desktop-buddy` project. Any Claude Code session working in this repo should read this file first and follow these standards without needing to be reminded.

---

## 1. Code Quality

- **Portfolio-grade readability.** This repo will be reviewed by recruiters. When in doubt, optimize for a stranger skimming the file on GitHub.
- **Section headers** in every `.py` file using `# === SECTION NAME ===`. Common sections: `IMPORTS`, `CONSTANTS`, `ENUMS`, `SPRITE CONFIG`, the main class(es), `ENTRY POINT`. Inside a long class, use `# --- subsection ---` to break up groups of methods.
- **Constants at the top.** All tunable values (speeds, intervals, sizes, paths) live at the top of the file with a one-or-two-line comment explaining what each one does and what changes when you tweak it. No magic numbers buried in the code.
- **Docstrings.** Every function, method, and class gets a docstring in plain English explaining its purpose. Module-level docstring at the top of every `.py` file describing what the file is for.
- **Descriptive variable names.** No `x`, `t`, `n`, `tmp`. Use `position_x`, `elapsed_ms`, `step_count`, `candidate_x`. Single-letter names are allowed *only* for trivial loop counters (`for i in range(...)`).
- **Type hints** on function signatures and non-obvious variables. Use modern Python syntax (`list[str]`, `dict[str, int]`, `tuple[float, float]`).
- **No leftover debug prints.** When debugging, wrap diagnostic output behind a `DEBUG = False` constant at the top, or remove the prints before committing. Never commit code with raw `print()` statements left in from a debugging session.
- **Comments earn their place.** Comment on *why*, not *what*. Skip comments that just restate what the code obviously does. Keep comments when they explain a non-obvious workaround, a subtle invariant, or a "why we picked this number" that a reader would otherwise have to guess.

## 2. Security & Privacy (Public Repo)

This is a **public** GitHub repository. The *code* is meant to be public (it showcases Camille's work); **none of Camille's private personal data may ever be committed or pushed.** These rules are permanent and apply to every chunk.

**Never commit or push:**
- Real Google Calendar events or any calendar data
- Gmail messages, email content, or email addresses
- Notion content
- API keys, OAuth tokens, client secrets, or passwords
- Credential files: `credentials.json`, `token.json`, `client_secret.json`, etc.
- Any `.env` file
- Any file containing Camille's personal information

**Rules:**
- **Load secrets from a local `.env` file or environment variables — never hard-code them** in any committed file.
- **`.env` and all credential/token files must always be listed in `.gitignore`** and never committed.
- **Never log or print full secrets** to the terminal or console.
- **Personal data stays local.** When we build the Google Calendar / Gmail / Notion integrations, all OAuth tokens and fetched personal data live only on Camille's machine — never pushed to the repo.
- **Only these things go public:** source code, non-sensitive assets (`sprites/`, `sounds/`), the README, and config *templates* with placeholder values.
- **Example configs use fake placeholders** (e.g. `YOUR_API_KEY_HERE`) in a file named `.env.example` — never put real values in any committed file.
- **Before any commit or push, verify nothing sensitive is staged** (no secrets, credentials, tokens, or personal data).

## 3. Project Structure

- **`main.py` is the entry point.** Running `python main.py` (from the activated venv) always launches the buddy.
- **Split files when they earn it.** If `main.py` grows past ~400-500 lines and the sections start to feel crowded, split into logical modules — typical candidates: `buddy_window.py` (the overlay + sprite class), `movement.py` (walking and destination logic), `animation.py` (frame swapping), `constants.py` (the tunable knobs). Don't split prematurely; one well-sectioned file beats four files of indirection.
- **Assets:** sprites live in `sprites/` (PNGs with transparent backgrounds), sounds live in `sounds/` (MP3s).
- **Virtual environment:** `.venv/` at the project root, already in `.gitignore`. All Python work happens inside it. `requirements.txt` is kept up to date via `pip freeze`.
- **Secrets & private data:** governed by the Security & Privacy section above — `.env`, credential files, and tokens are always gitignored, and never commit anything that looks like an API key or personal data.

## 4. Workflow

- **Plan before significant code changes.** Before touching code on any non-trivial change (new feature, refactor, debugging a behavior issue), describe the plan in plain language and wait for approval. Small tweaks (bumping a constant, fixing a typo) don't need this.
- **Run after implementing.** After making changes, launch the script so Camille can verify the behavior visually. Don't claim a feature works without seeing it work.
- **Commit messages follow the pattern `Chunk X: brief description`** (e.g., `Chunk B: floor-walking with distance-synced animation`). Use a single short subject line; a paragraph body is fine when it adds context.
- **Don't push until visual confirmation.** Local commits are fine; `git push` only after Camille has confirmed the change works on screen.
- **Risky actions need confirmation.** Force-push, destructive resets, dropping branches, pushing directly to `main` — pause and confirm even if the action seems obvious.

## 5. Project Context

- **What this is:** A desktop AI companion. A chibi-style girl character who eventually nudges the user about meetings, emails, and other reminders, with personality powered by Claude.
- **Environment:** Pop!_OS 24.04 LTS, COSMIC desktop (Wayland-based). Code should not rely on X11-only behaviors. **Notable constraints learned the hard way:**
  - Wayland compositors refuse client-side window repositioning, which is why the buddy lives on a fullscreen transparent overlay with `setMask()` for click-through (the sprite is repositioned *inside* the overlay).
  - The `Qt.WindowType.Tool` flag is required to get true always-on-top + hidden-from-taskbar behavior, but the compositor decides the overlay's actual size and may give us a smaller rect than we asked for. **Coordinate math must use `self.width()` / `self.height()` at runtime, not the screen size,** so the buddy stays inside whatever overlay we actually got.
- **Tech stack (current):** Python 3, PyQt6.
- **Tech stack (planned):** `pygame` or similar for sound playback, the Anthropic Claude API for dynamic messages, Google Calendar API and Gmail API for context-aware reminders, autostart-on-login integration with COSMIC.
- **Who Camille is:** A digital marketer, not a professional programmer. She is learning AI-assisted development by building this project. **Explain technical decisions in plain language.** She reviews code by *running it and watching what it does*, not by reading it line by line — so behavior over claims, always.

## 6. Character Behavior (Current Model)

- **Floor physics:** The buddy walks along the bottom of the screen, treated as a floor. Her feet are anchored to a fixed `ground_y` line; only X position changes during a walk.
- **Distance-synced animation:** Leg-swap frames are triggered by distance traveled (`STRIDE_PX`), not by an elapsed-time timer. This keeps her gait visually anchored to motion — no "ice-skating" effect.
- **Wandering pattern:** Pick a random X far enough away to be a real trip (`MIN_TRIP_DISTANCE_PX`), walk to it at `SPEED_PX` per movement tick, pause for 2-3 seconds in the idle pose, then pick the next destination.
- **Spawn:** Bottom-right corner on launch.
- **Direction sprites:** Four-frame walk cycles for LEFT and RIGHT only (no vertical movement at the moment). Uses the clean side-profile frames in order `walk_*_2 → _3 → _5 → _6.png`, advanced one frame per `STRIDE_PX` traveled. Frames `_1` and `_4` exist in `sprites/` but are intentionally skipped — they are high-knee poses with the head turned backward, which reads as a direction flip. Idle pose is `idle_front.png`.
- **Always-on-top transparent overlay** that does not block clicks on other windows (input mask sized to the sprite rect).
- **Escape closes** the app (requires the overlay to have keyboard focus — clicking the buddy gives it focus).

## 7. Coming Chunks (Roadmap)

- **Chunk C:** Speech bubbles (rendered above the buddy's head).
- **Chunk D:** Sound effects (`sounds/voice_*.mp3` and `sounds/pop.mp3`), triggered by events.
- **Chunk E:** Claude API integration — dynamic personalized messages.
- **Chunk F:** Google Calendar integration — meeting reminders.
- **Chunk G:** Gmail integration — new-email nudges.
- **Chunk H:** Autostart-on-login for COSMIC / GNOME.

Each chunk follows the standard workflow in Section 4: plan → approve → implement → run → confirm → commit → (eventually) push.
