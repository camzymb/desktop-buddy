"""Weekly Content Planner — the buddy's content-strategist brain.

Camille's buddy doubles as a gentle content strategist. When asked, she
researches what's current — recent AI/marketing-tech launches and the hook
styles that are working right now — and drafts a one-week content plan built
around the Instagram grid:

    * Monday    → Carousel
    * Wednesday → Video / Reel
    * Friday    → Post / graphic

Each piece comes with a short topic, a trend-informed idea, a "why this, why
now" note, an inspo note, a recommended tool (only ever from her own kit),
ready-to-use drafted copy, multi-platform fit notes, and GEO/SEO tips. The plan
also includes a "what's new in AI" newsjacking section and a few hook tips.

How it works:

    * The research itself is one low-volume call to the Anthropic API using the
      model's built-in `web_search` tool, on a cheap model (Haiku).
    * The API key is **bring-your-own-key**: it is read from a gitignored
      `.env` file (`ANTHROPIC_API_KEY`) and never hard-coded or committed. If
      the key is missing, she returns a friendly note instead of crashing.
    * The finished plan is saved to a small local JSON file. The buddy's compact
      desktop panel reads it for the week's overview, and `notion_sync` writes
      the full detailed plan to Camille's Notion page.

Test it without spending anything — the `--mock` flag writes a realistic sample
plan with no API call and no Notion write:

    .venv/bin/python content_planner.py --mock   # free: sample plan, no Notion
    .venv/bin/python content_planner.py           # one real call + write to Notion
"""

# === IMPORTS ===

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent

# Where the finished plan is cached for the desktop panel to read. This holds
# Camille's own content ideas (not third-party personal data), but it is still
# kept OUT of the repo — see .gitignore — so nothing personal is ever committed.
PLAN_PATH = PROJECT_DIR / "weekly_plan.json"

# Bring-your-own-key: secrets are loaded from this gitignored file, never
# hard-coded. Only .env.example (with placeholders) is committed.
ENV_PATH = PROJECT_DIR / ".env"
API_KEY_VAR = "ANTHROPIC_API_KEY"

# A cheap, fast model is plenty for this low-volume, once-a-week research.
MODEL = "claude-haiku-4-5"

# Headroom for the full plan (table + drafted copy + news + tips). Well under
# the streaming threshold, so a plain non-streaming call is fine.
MAX_TOKENS = 8000

# The built-in web-search tool, capped so a single run can't rack up searches.
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}

# Server-side web search runs its own tool loop; if it pauses at the iteration
# limit we resume it a bounded number of times rather than looping forever.
MAX_CONTINUATIONS = 4

# The ONLY tools she may ever recommend. She must never invent others.
ALLOWED_TOOLS = (
    "Higgsfield (video / cinematic)",
    "Nano Banana",
    "Claude (scripts / captions)",
    "Canva",
    "CapCut",
    "Sony a6700 + Darktable (photography)",
)

# Friendly, non-crashing message shown when the key is missing.
MISSING_KEY_MESSAGE = (
    "I'd love to plan your week, but I couldn't find your Anthropic API key. 🤍 "
    "Pop your key into a file called .env next to the app, like this:\n\n"
    "    ANTHROPIC_API_KEY=sk-ant-your-key-here\n\n"
    "(There's a .env.example to copy.) Then ask me again — your key stays on "
    "your computer and is never shared."
)

GENERIC_ERROR_MESSAGE = (
    "I hit a little snag putting your content plan together. 🤍 "
    "Mind checking your internet and trying again in a bit?"
)


# === ENVIRONMENT (bring-your-own-key) ===

def load_env_file() -> None:
    """Load simple KEY=value lines from .env into the environment, if present.

    Best-effort and dependency-free: blank lines and `#` comments are skipped,
    surrounding quotes are stripped, and existing environment variables are
    never overwritten (so a real shell export always wins). A missing or
    unreadable .env is fine — callers handle a still-absent value gently. Shared
    by the planner (Anthropic key) and notion_sync (Notion token + page id).
    """
    try:
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# === PLAN FILE I/O ===

def write_plan(plan: dict) -> None:
    """Save the plan (or a friendly error payload) for the desktop panel to read.

    Best-effort: if the file can't be written, the panel simply won't update —
    no exception is raised into the caller (the buddy app must stay alive).
    """
    try:
        PLAN_PATH.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_plan_payload() -> dict:
    """Return the last saved plan for the desktop panel, or a friendly message.

    A missing or unreadable file just means "no plan yet", which the panel shows
    as a gentle prompt rather than an error.
    """
    try:
        return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"error": "No plan yet — ask your buddy to plan your week. 🌸"}


# === PROMPTS ===

def _week_label(today: datetime) -> str:
    """A gentle label for the week the plan covers, e.g. 'Week of Mon, Jun 1'."""
    monday = today - timedelta(days=today.weekday())
    return "Week of " + monday.strftime("%a, %b %-d")


def _system_prompt() -> str:
    """Build the content-strategist instructions, including the exact output shape."""
    tool_lines = "\n".join(f"  - {tool}" for tool in ALLOWED_TOOLS)
    return f"""\
You are the content strategist living inside Camille's desktop buddy. Camille is \
a digital marketer. Your job is to plan one week of social content for her, in a \
warm, gentle, kind-friend tone throughout — encouraging, never hustle-y or \
corporate.

HER NICHE (keep every idea relevant to this):
  - Digital marketing and content creation
  - Her own projects and behind-the-scenes
  - Automation and building-with-Claude-Code skills
  - Explaining new AI tools and tech in plain language for marketers and small businesses

THE WEEKLY SHAPE (fixed — built around the Instagram grid, video in the middle):
  - Monday    → Carousel
  - Wednesday → Video / Reel
  - Friday    → Post / graphic

For EACH of the three pieces give:
  - a short topic title (a few words),
  - a trend-informed idea,
  - a "why this, why now" note (why it's worth posting this week),
  - a short reference/inspo note (a style or format that's working — described in \
general terms, NOT scraped from a specific creator or platform),
  - one recommended tool,
  - drafted copy she can use as-is:
      * Carousel: a strong, punchy hook plus slide-by-slide text.
      * Video / Reel: a punchy hook line plus a brief shot/beat outline.
      * Post / graphic: a caption.
  - multi-platform fit notes: how to adapt the SAME idea across Instagram, \
TikTok, LinkedIn, and YouTube (repurposing HER own content — never scraping or \
reposting others'),
  - GEO/SEO optimization notes: the keywords/phrases to include and how to be \
found in both search engines and AI answer engines (GEO).

Keep hooks punchy and human.

TOOLS — you may ONLY ever recommend from this exact list, and must NEVER invent \
or suggest any other tool:
{tool_lines}

ALSO INCLUDE:
  - A "what's new in AI / marketing tech this week" section: use web search to \
find a genuinely recent AI tool or model launch relevant to marketers or small \
businesses, explain it in plain, layman's terms, and suggest a carousel idea \
that explains it simply (the newsjacking angle).
  - A few brief hook/structure tips drawn from your web research on what hook \
styles are working right now — phrased as gentle tips, not scraped from any \
specific account.

RESEARCH: use the web_search tool to ground the ideas, the AI news, and the hook \
tips in what's current. Do NOT attempt to pull or scrape viral videos from \
TikTok, Instagram, YouTube, or LinkedIn — that's out of scope. All copy is plain \
text for Camille to use manually.

OUTPUT — return ONLY a single JSON object (no prose before or after, no code \
fences) with exactly this shape:

{{
  "week_of": "<short week label>",
  "intro": "<one warm sentence introducing the week>",
  "pieces": [
    {{
      "day": "Monday",
      "format": "Carousel",
      "topic": "<short topic title>",
      "idea": "<trend-informed idea>",
      "why": "<why this topic, why now>",
      "inspo": "<short reference / inspo note>",
      "tool": "<one tool from the allowed list>",
      "copy": {{
        "hook": "<punchy hook>",
        "slides": ["<slide 1 text>", "<slide 2 text>", "..."],
        "caption": "<caption>"
      }},
      "platforms": "<how to adapt this idea across Instagram / TikTok / LinkedIn / YouTube>",
      "geo_seo": "<keywords to include and GEO/SEO tips to be found in search and AI answers>"
    }},
    {{
      "day": "Wednesday",
      "format": "Video / Reel",
      "topic": "...",
      "idea": "...",
      "why": "...",
      "inspo": "...",
      "tool": "<one tool from the allowed list>",
      "copy": {{
        "hook": "<punchy hook line>",
        "outline": ["<beat 1>", "<beat 2>", "..."],
        "caption": "<caption>"
      }},
      "platforms": "...",
      "geo_seo": "..."
    }},
    {{
      "day": "Friday",
      "format": "Post / graphic",
      "topic": "...",
      "idea": "...",
      "why": "...",
      "inspo": "...",
      "tool": "<one tool from the allowed list>",
      "copy": {{
        "caption": "<caption>"
      }},
      "platforms": "...",
      "geo_seo": "..."
    }}
  ],
  "ai_news": {{
    "headline": "<the recent launch>",
    "in_plain_terms": "<what it is, in everyday language>",
    "why_it_matters": "<why marketers / small businesses should care>",
    "carousel_idea": "<a simple carousel idea explaining it>"
  }},
  "hook_tips": ["<tip>", "<tip>", "<tip>"],
  "closing_note": "<a gentle, encouraging sign-off>"
}}
"""


def _user_kickoff(today: datetime) -> str:
    """The single user turn that starts the research, grounded in today's date."""
    return (
        f"Today is {today.strftime('%A, %B %-d, %Y')}. Please research and draft my "
        f"content plan for this week ({_week_label(today)}). Return only the JSON object."
    )


# === RESPONSE PARSING ===

def _extract_json(text: str) -> dict:
    """Pull the JSON object out of the model's reply, tolerating stray wrapping.

    The prompt asks for bare JSON, but we defensively slice from the first `{`
    to the last `}` so an accidental code fence or stray sentence doesn't break
    parsing. Raises ValueError if no valid object is found.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


# === PLAN GENERATION ===

def mock_plan() -> dict:
    """A realistic sample plan for free, no-API testing of the panel and wiring.

    Mirrors exactly the shape the live model returns, so the desktop panel and
    the Notion writer can be verified without spending anything. The ideas,
    tools, and tone match the real thing; only the research is invented.
    """
    today = datetime.now()
    return {
        "week_of": _week_label(today),
        "intro": (
            "Here's a gentle plan for your week, Camille — three pieces, all "
            "ready to go. No rush. 🤍"
        ),
        "pieces": [
            {
                "day": "Monday",
                "format": "Carousel",
                "topic": "5 AI tools for small-business marketing",
                "idea": "5 AI tools quietly changing how small businesses market in 2026",
                "why": (
                    "Tool roundups are saving people money right now, and 'AI for small "
                    "business' is a rising search — you're answering a question people are "
                    "already typing."
                ),
                "inspo": (
                    "The 'helpful tool roundup' carousel is working well — framed as a "
                    "little gift to your audience, not a flex."
                ),
                "tool": "Canva",
                "copy": {
                    "hook": "You don't need a bigger budget. You need these 5 tools. 🤍",
                    "slides": [
                        "Slide 1 — Hook: You don't need a bigger budget. You need these 5 tools.",
                        "Slide 2 — Why it matters: AI can quietly do the heavy lifting so you "
                        "get your evenings back.",
                        "Slide 3 — Tool 1: A captions assistant that sounds like you, not a robot.",
                        "Slide 4 — Tool 2: A design tool for on-brand graphics in minutes.",
                        "Slide 5 — Tool 3: A quick video editor for clean, scroll-stopping reels.",
                        "Slide 6 — Save this & tell me: which one are you trying first?",
                    ],
                    "caption": (
                        "Marketing your small business shouldn't cost you your weekends. "
                        "Here are 5 gentle little tools doing the heavy lifting for me lately. "
                        "Save this one for later 🤍 Which are you trying first?"
                    ),
                },
                "platforms": (
                    "Carousel for Instagram; repost as a LinkedIn document; the same 5 points "
                    "become a short TikTok/Reel list and a quick X thread."
                ),
                "geo_seo": (
                    "Work the phrase 'AI tools for small business marketing' into slide 1 and "
                    "the caption; add alt text per slide so search and AI answer engines can read it."
                ),
            },
            {
                "day": "Wednesday",
                "format": "Video / Reel",
                "topic": "Building a tiny automation with Claude Code",
                "idea": "Behind the scenes: building a tiny desktop helper with Claude Code",
                "why": (
                    "'Build with me' process content builds trust and rides the rising "
                    "interest in practical AI and automation for non-developers."
                ),
                "inspo": (
                    "Quiet 'build with me' process clips are resonating — calm, real, "
                    "and a little nerdy, with the finished thing as the payoff."
                ),
                "tool": "CapCut",
                "copy": {
                    "hook": "I taught my computer to plan my content for me. Here's how.",
                    "outline": [
                        "Beat 1 (0–3s): Hook on camera — 'I taught my computer to plan my content.'",
                        "Beat 2 (3–8s): Screen peek of the idea, kept simple and friendly.",
                        "Beat 3 (8–15s): One honest line about why automation gives you time back.",
                        "Beat 4 (15–20s): The finished helper doing its thing.",
                        "Beat 5 (end): Soft call to follow for more gentle automation tips.",
                    ],
                    "caption": (
                        "A little behind-the-scenes of me building automations just for the "
                        "fun of it. 🌸 You don't have to be technical to start — promise. "
                        "Follow along for more soft-tech experiments."
                    ),
                },
                "platforms": (
                    "Reel for Instagram and TikTok; a longer cut for YouTube Shorts; a written "
                    "walk-through as a LinkedIn post."
                ),
                "geo_seo": (
                    "Say 'AI automation for small business' out loud in the hook (captions are "
                    "indexed) and use it in the on-screen title and upload name."
                ),
            },
            {
                "day": "Friday",
                "format": "Post / graphic",
                "topic": "Permission-slip reminder: done beats perfect",
                "idea": "A kind reminder: done and shared beats perfect and hidden",
                "why": (
                    "Warm, shareable text posts get saved and sent to friends — widening your "
                    "reach without spending on ads."
                ),
                "inspo": (
                    "Simple text-on-graphic 'permission slip' posts are doing well — "
                    "warm, screenshot-able, easy to share to stories."
                ),
                "tool": "Nano Banana",
                "copy": {
                    "caption": (
                        "Your gentle Friday reminder: the post you almost didn't make is "
                        "still allowed to help someone. 🤍 Share it anyway. I'm cheering "
                        "you on."
                    )
                },
                "platforms": (
                    "Graphic for the Instagram feed; share to Stories; the same line works as a "
                    "LinkedIn one-liner or a Pinterest pin."
                ),
                "geo_seo": (
                    "Add descriptive alt text and a searchable caption ('small business "
                    "motivation') so the graphic is findable in search and AI answers."
                ),
            },
        ],
        "ai_news": {
            "headline": "(Sample) A new AI model made plain-language marketing copy easier",
            "in_plain_terms": (
                "A fresh AI update means writing captions and scripts that actually sound "
                "like a real person just got noticeably better — fewer robotic phrases."
            ),
            "why_it_matters": (
                "For a small business, that means on-brand copy in minutes instead of an "
                "afternoon — more time for the parts only you can do."
            ),
            "carousel_idea": (
                "'What this new AI update means for your small business (in plain English)' "
                "— one calm slide per benefit, no jargon."
            ),
        },
        "hook_tips": [
            "Lead with the outcome your reader wants, not the topic ('Get your evenings back', not 'About automation').",
            "A soft number still works — '5 tools', '3 minutes' — it tells people exactly what they're getting.",
            "Try a gentle contrast hook: 'You don't need X. You need Y.'",
            "End carousels with a tiny ask ('save this', 'tell me which one') to invite replies.",
        ],
        "closing_note": (
            "That's your week, all set. 🤍 Three small pieces, made with care — "
            "you've got this, one gentle step at a time."
        ),
    }


def build_weekly_plan(use_mock: bool = False) -> dict:
    """Return this week's content plan as a dict, never raising on expected errors.

    With `use_mock` it returns the free sample plan and makes no API call. The
    live path loads the bring-your-own-key from .env, runs one research call on
    a cheap model with the built-in web-search tool, and parses the JSON plan.
    Any expected problem (missing key, network/API error, unparseable reply) is
    returned as a friendly `{"error": ...}` payload the panel can show calmly,
    rather than crashing the buddy.
    """
    if use_mock:
        return mock_plan()

    load_env_file()
    if not os.environ.get(API_KEY_VAR):
        return {"error": MISSING_KEY_MESSAGE}

    # Imported lazily so the mock path (and the rest of the app) never needs the
    # SDK installed just to run.
    try:
        import anthropic
    except ImportError:
        return {
            "error": (
                "The Anthropic library isn't installed yet. 🤍 Run "
                "`.venv/bin/pip install -r requirements.txt`, then ask me again."
            )
        }

    today = datetime.now()
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": _user_kickoff(today)}]

    try:
        for _ in range(MAX_CONTINUATIONS):
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=_system_prompt(),
                tools=[WEB_SEARCH_TOOL],
                messages=messages,
            )
            # The web-search loop can pause at its iteration cap; resume it by
            # re-sending the conversation so far until it finishes the answer.
            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                continue
            break
    except anthropic.AuthenticationError:
        return {"error": MISSING_KEY_MESSAGE}
    except anthropic.APIError:
        return {"error": GENERIC_ERROR_MESSAGE}

    reply = "".join(block.text for block in response.content if block.type == "text")
    try:
        plan = _extract_json(reply)
    except ValueError:
        return {"error": GENERIC_ERROR_MESSAGE}

    # Stamp the week label in case the model phrased it differently.
    plan.setdefault("week_of", _week_label(today))
    return plan


# === STANDALONE CLI ===

def main() -> None:
    """Generate a plan and (for a real run) write it to Notion.

    `--mock` produces the free sample plan and writes it locally only — no API
    call and no Notion write — for inspecting the data or feeding the panel.
    With no flag it makes one real research call and publishes the full plan to
    Camille's Notion page (the one real end-to-end test).
    """
    parser = argparse.ArgumentParser(description="Generate the weekly content plan.")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use a free sample plan; write locally only (no API call, no Notion).",
    )
    args = parser.parse_args()

    print("Putting your plan together…" if not args.mock else "Building a sample plan…")
    plan = build_weekly_plan(use_mock=args.mock)
    write_plan(plan)

    if "error" in plan:
        print(f"Note: {plan['error']}")
        return
    if args.mock:
        print(f"Sample plan written to {PLAN_PATH.name} (no Notion write).")
        return

    # Imported here (not at module load) so the mock path never needs the Notion
    # library, and to keep the brain independent of the publishing step.
    from notion_sync import page_url, publish_plan

    error = publish_plan(plan)
    if error:
        print(error)
    else:
        print(f"Published your full plan to Notion: {page_url()}")


if __name__ == "__main__":
    main()
