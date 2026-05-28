# Desktop Buddy — Project Standards

Engineering standards and conventions for the `desktop-buddy` project. This file is the
source of truth for code quality, security, and structure; read it before contributing.

## Overview

Desktop Buddy is a desktop companion for Linux (Pop!_OS / COSMIC, Wayland): an illustrated
character that walks along the screen, surfaces gentle reminders in speech bubbles with voice
playback, and presents a daily summary of calendar events. It runs as a transparent,
always-on-top overlay.

**Tech stack:** Python 3, PyQt6 (overlay & rendering), pygame-ce (audio), Google Calendar API
(read-only). A small HTML/CSS/JS module renders the daily-summary card. Planned: Claude API for
dynamic messages and further context-aware reminders.

## Code Quality

- **Section headers** in every `.py` file (`# === SECTION NAME ===`); group related methods
  with `# --- subsection ---`.
- **Tunable constants at the top** of the file, each with a short comment — no magic numbers
  buried in code.
- **Docstrings** on every module, class, and function, in plain English.
- **Type hints** on signatures and non-obvious variables; modern syntax (`list[str]`,
  `tuple[float, float]`).
- **Descriptive names** — no single-letter identifiers except trivial loop counters.
- **No leftover debug prints** — gate diagnostics behind a `DEBUG` flag or remove them.
- **Comments explain *why*, not *what*** — reserve them for non-obvious decisions.
- Favor readability: one well-organized module over premature abstraction; split a file into
  focused modules once it grows unwieldy.

## Security & Privacy

This is a public repository. Source code is public; private data never is.

- **Never commit** secrets or personal data: API keys, OAuth tokens, client secrets, passwords,
  credential files (`credentials.json`, `token.json`, `client_secret*.json`), `.env` files, or
  any fetched personal data (calendar, email, etc.).
- **Load secrets from environment variables or a local `.env`** — never hard-code them. Commit
  only `.env.example` with placeholder values.
- **Keep all credential and token files gitignored**; verify nothing sensitive is staged before
  each commit.
- **Least privilege** — request read-only scopes for external APIs (e.g. Google Calendar
  `calendar.readonly`).
- **Keep personal data local** — fetched data is shown only to the user (e.g. served on
  localhost) and is never written into the repo or exposed on the network.
- **Never log full secrets** to the console.

## Project Structure

- **Entry point:** `main.py` launches the buddy.
- **Modules:** focused, single-responsibility files (e.g. `calendar_sync.py`,
  `speech_bubble.py`, `audio.py`, `quotes.py`).
- **Assets:** sprites in `sprites/`, sounds in `sounds/`, bundled fonts in `assets/fonts/`
  (with their licenses).
- **Daily-summary UI:** `callout/` (standalone HTML/CSS/JS), served locally by
  `callout_server.py`.
- **Secrets (gitignored):** `credentials.json`, `token.json`, `.env`.
- **Environment:** a project-local virtualenv (`.venv/`); dependencies pinned in
  `requirements.txt`.

## Conventions

- Plan non-trivial changes before implementing; verify behavior by running the app, not just by
  inspecting code.
- Write clear, descriptive commit messages.
- Create new commits rather than amending published history; confirm before any destructive or
  irreversible git operation.
