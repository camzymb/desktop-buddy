<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fredoka&weight=600&size=40&duration=3500&pause=800&color=F25C9C&center=true&vCenter=true&width=720&height=90&lines=Desktop+Buddy+%F0%9F%8C%B8;a+little+companion+for+my+screen" alt="Desktop Buddy" />
</p>

<p align="center">
  <img src="assets/demo.gif" alt="Desktop Buddy walking around the screen, greeting, and showing the daily post-it" width="640" />
</p>

## 🌸 Hi there

**Desktop Buddy** is a tiny chibi-girl companion who lives on my desktop. She strolls along the bottom of the screen, waves hello, shows me what my day looks like, and gives me a gentle nudge before things start — all in a soft, kind-friend tone rather than a buzzing-notification one.

She started as a "wouldn't it be cute if…" idea and turned into a fun little playground for tinkering with desktop apps, voice, and calendar automation. 🐧

## ✨ What she does

- 🚶‍♀️ **Walks around your desktop** — a hand-illustrated character who paces along the screen and strikes friendly poses.
- 🎙️ **Talks to you** — soft spoken voice clips paired with gentle, encouraging little messages.
- 📅 **Knows your day** — reads your Google Calendar (read-only) to see what's coming up.
- 📌 **Daily post-it** — a cute planner panel that pops out of her with today's events and to-dos. You can **drag it anywhere** to keep it out of the way, and she remembers where you left it.
- 🌅 **Welcomes you back** — starts automatically when you log in and greets you with a warm hello.
- ⏰ **Gentle reminders** — gives you a heads-up about 15 minutes before each event, so nothing sneaks up on you.

## 🛠️ Built with

- **Python** + **PyQt6** — the character, animation, and transparent always-on-top overlay
- **Google Calendar API** — read-only access to today's events
- **pygame-ce** — voice and sound playback

Made for **Pop!_OS / COSMIC** on Linux (Wayland).

## 🚀 Try it

```bash
# 1. Set up a virtual environment and install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Add your own Google Calendar credentials.json (kept private, never committed)

# 3. Say hello
.venv/bin/python main.py
```

To have her greet you automatically at login, run `scripts/setup_autostart.sh`.

> Your private data stays yours: calendar credentials and tokens live only on your machine and are never committed to this repo.

## 🔤 Credits

Speech bubbles use [**Fredoka**](https://fonts.google.com/specimen/Fredoka) by Hanken Design Co., licensed under the [SIL Open Font License 1.1](https://openfontlicense.org/). The font and its license are bundled in [`assets/fonts/`](assets/fonts/).

## 👋 About

Made by [Camille](https://bycamillenicole.com) — a digital marketer who loves exploring new tech and building little tools and AI-assisted automations just for the fun of it. 🌸
