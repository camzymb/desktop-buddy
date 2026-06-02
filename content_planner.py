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
ready-to-paste drafted copy (for a carousel, the full slide-by-slide text plus a
platform-optimized caption), multi-platform fit notes (LinkedIn, Substack,
TikTok, Instagram, YouTube), and GEO/SEO tips. She also decides a fresh video strategy
each week from the trends (how many videos, which platforms, why) and writes a
full, camera-ready cinematic script for each — hook, shot-by-shot breakdown,
b-roll, on-screen captions, and CTA. The plan also includes a "what's new in AI"
newsjacking section and a few hook tips.

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

from sample_plan import sample_plan


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

# Headroom for the full plan (table + drafted copy + news + tips) PLUS the full
# cinematic video scripts, which are long (a long-form shot-by-shot can run
# pages). Still fast on Haiku and well under the non-streaming timeout, so a
# plain non-streaming call remains fine.
MAX_TOKENS = 16000

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
    "Mirrorless camera + Darktable (photography)",
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
    """A dated label for the week the plan covers, e.g. 'Week of Jun 2–8, 2026'.

    Spans Monday to Sunday. Used as the heading, the panel label, and the title
    of each week's archived sub-page in Notion, so it carries the full range and
    year (and stays readable across month or year boundaries).
    """
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    if monday.year != sunday.year:
        return f"Week of {monday.strftime('%b %-d, %Y')} – {sunday.strftime('%b %-d, %Y')}"
    if monday.month == sunday.month:
        return f"Week of {monday.strftime('%b %-d')}–{sunday.day}, {sunday.year}"
    return f"Week of {monday.strftime('%b %-d')} – {sunday.strftime('%b %-d')}, {sunday.year}"


def _system_prompt() -> str:
    """Build the content-strategist instructions, including the exact output shape."""
    tool_lines = "\n".join(f"  - {tool}" for tool in ALLOWED_TOOLS)
    return f"""\
You are the content strategist living inside Camille's desktop buddy. Camille is \
a digital marketer. Your job is to plan one week of social content for her, in a \
warm, gentle, kind-friend tone throughout — encouraging, never hustle-y or \
corporate.

HOW YOU WORK (these rules apply to EVERYTHING you produce):
  - DO THE RESEARCH YOURSELF. Use the web_search tool to find what's current — \
trends, SEO and GEO keywords, what's popular right now, new AI and marketing \
tools, and platform/social-media updates — so Camille never has to browse. \
Ground every idea in that research.
  - COPY-PASTE / USE READY. Everything must be usable as-is: carousel slides \
ready to drop into Canva, captions ready for the post box, video scripts she can \
film straight from. Be complete and detailed by default.
  - NAME REAL THINGS. No vague placeholders — never "a design tool" or "a \
captions assistant"; name the actual, real, currently-relevant tool, product, or \
format. Never invent fake tools, fake products, or fake sources — everything must \
be web-researched and real.
  - CITE YOUR SOURCES. For each trend or idea, say where you found it (e.g. a \
Reddit thread, a trending LinkedIn or Instagram post, an article) and include the \
ACTUAL link, so Camille can verify it herself.
  - DECIDE THE ANGLE YOURSELF. Choose the trending angle autonomously — Camille \
shouldn't have to. Because these are your suggestions, include a gentle, humble \
disclaimer on the plan (e.g. "This is my suggestion — feel free to edit or change \
it 🤍").
  - AUTONOMOUS FALLBACK. If you genuinely cannot fully produce something yourself \
(e.g. it needs an image or live data you can't generate), do NOT hand back a \
vague placeholder. Instead write a ready-to-paste PROMPT Camille can drop \
straight into Claude to generate it, and clearly label it by beginning that text \
with "📋 PROMPT FOR CLAUDE:". Use this only when truly needed — it's your \
judgment call.

HER NICHE (keep every idea relevant to this):
  - Digital marketing and content creation
  - Behind-the-scenes of a creative workflow
  - Practical AI tools and automation for everyday creators and small businesses
  - Explaining new AI tools and tech in plain language for marketers and small businesses

THE WEEKLY SHAPE (fixed — built around the Instagram grid, video in the middle):
  - Monday    → Carousel
  - Wednesday → Video / Reel
  - Friday    → Post / graphic

For EACH of the three pieces give:
  - a short topic title (a few words),
  - the primary platform for that piece (one or two words, e.g. "Instagram" or \
"Instagram + TikTok"),
  - a trend-informed idea,
  - a "why this, why now" note (why it's worth posting this week),
  - a short reference/inspo note (a style or format that's working — described in \
general terms, NOT scraped from a specific creator or platform),
  - the tool from her OWN kit she'd use to MAKE this piece (e.g. Canva for a \
carousel, CapCut for a reel) — this fills the table's Tools column,
  - at least one SOURCE for the idea/trend: where you found it, with the ACTUAL link,
  - drafted copy she can use as-is, in her gentle, authentic voice (never hypey):
      * Carousel: the COMPLETE, ready-to-paste slide-by-slide text. Slide 1 is \
the cover/hook that stops the scroll; each middle slide makes exactly ONE clear \
point (for a "5 tools" carousel, that's roughly one tool per slide); the final \
slide is the CTA. Write each slide as clean text she can drop straight into \
Canva, and do NOT prefix slides with "Slide 1" etc. (the app adds those labels). \
PLUS a full post caption: a strong first line, then the value, then a call to \
action — optimized for the platform and GEO/SEO-aware (work the key phrase in \
naturally; do NOT hashtag-stuff, a few natural tags at most).
      * Video / Reel: a punchy hook line, a brief shot/beat outline, and a caption.
      * Post / graphic: a caption (plus a hook line if it helps).
  - multi-platform fit notes: how to adapt the SAME idea across LinkedIn, \
Substack, TikTok, Instagram, and YouTube (repurposing HER own content — never \
scraping or reposting others'),
  - GEO/SEO optimization notes: the keywords/phrases to include and how to be \
found in both search engines and AI answer engines (GEO).

Keep hooks punchy and human.

TOOL RECOMMENDATIONS (research everything; never invent a tool):
  - ROUNDUP / "best tools" content (e.g. "5 AI tools for small-business \
marketing"): research and name the REAL, currently-trending WIDER-MARKET tools — \
NOT just Camille's own kit. Name each actual product, with a concrete one-line \
reason it helps small-business marketing, and include a few BONUS tools in the \
caption. Keep it relatable, trustworthy, and current. A "5 tools" carousel must \
name 5 real tools, not 3 and not vague ones.
  - CAMILLE'S OWN-PROCESS content (e.g. "how I built my desktop buddy", \
behind-the-scenes): authentically feature the tools she ACTUALLY uses:
{tool_lines}
  - The per-piece "tool" field (the table's Tools column) is the tool from \
Camille's OWN kit above that she'd open to MAKE that piece — always from her kit.

VIDEO STRATEGY (decide it fresh each week from what's trending — do NOT use a \
fixed number):
  - Based on your web research, decide how many videos are worth making this \
week (typically 1–3) and which platforms they target. Lead with a short \
strategy note that explains your call: which trend you're riding, which \
platform(s) each video is for, and the traction you'd expect.
  - Length follows platform and trend: short-form ~30–60s for TikTok/Instagram \
(and an optional short cut for LinkedIn); long-form ~10–15 min for YouTube. \
Pick the mix that fits what's working right now — e.g. one short-form for TikTok \
that also fits Instagram, plus one long-form for YouTube.

FOR EACH VIDEO you suggest, write a FULL, CAMERA-READY CINEMATIC SCRIPT — \
detailed enough that Camille could film straight from it with no extra thinking. \
She films on a mirrorless camera and edits in Higgsfield, so write real, specific \
camera directions she can shoot to. Do NOT be thin or generic. Each script must include:
  - Hook: the EXACT words she says in the first 3 seconds (write them out in \
quotes), plus how it's framed — scroll-stopping.
  - A shot-by-shot breakdown that covers the WHOLE video, shot by shot. For \
every shot give BOTH: (a) the camera direction — angle, movement, framing, lens \
feel — and (b) the EXACT words she says (in quotes) or the precise action she \
performs. Number enough shots to actually fill the runtime: a short-form video \
wants roughly 6–10 tight shots; a long-form video must be genuinely long — break \
it into clear sections/chapters with many shots (12+), not a short summary.
  - B-roll ideas: specific, shootable cutaways (not "some b-roll" — say exactly \
what to film).
  - On-screen captions/text: the ACTUAL words that appear on screen, written out \
as they'd be typed.
  - CTA: the EXACT wording of the call to action.
Match the tone to the format: punchy and energetic for short-form, thoughtful \
and considered for long-form — always authentic, never hypey.

ALSO INCLUDE:
  - A "what's new in AI / marketing tech this week" section: use web search to \
find a genuinely recent AI tool or model launch relevant to marketers or small \
businesses, explain it in plain, layman's terms, and suggest a carousel idea \
that explains it simply (the newsjacking angle).
  - A few brief hook/structure tips drawn from your web research on what hook \
styles are working right now — phrased as gentle tips, not scraped from any \
specific account.

RESEARCH SCOPE: ground the ideas, the tool roundups, the AI news, the hook tips, \
and the trending angle in real web research, and cite each with an actual link \
(see HOW YOU WORK). Do NOT scrape or repost anyone else's actual posts or videos \
— describe styles and formats in general terms. All copy is plain text for \
Camille to use manually.

OUTPUT — return ONLY a single JSON object (no prose before or after, no code \
fences) with exactly this shape:

{{
  "week_of": "<short week label>",
  "intro": "<one warm sentence introducing the week>",
  "disclaimer": "<a gentle, humble note that this is your suggestion she can freely edit or change>",
  "pieces": [
    {{
      "day": "Monday",
      "platform": "<primary platform, e.g. Instagram>",
      "format": "Carousel",
      "topic": "<short topic title>",
      "idea": "<trend-informed idea>",
      "why": "<why this topic, why now>",
      "inspo": "<short reference / inspo note>",
      "tool": "<the tool from her own kit she'd use to MAKE this piece>",
      "copy": {{
        "slides": ["<slide 1: the cover/hook>", "<slide 2: one clear point — name the real tool/thing>", "<...one point per slide...>", "<final slide: the CTA>"],
        "caption": "<full caption: strong first line + value + call to action, platform- and GEO/SEO-aware, natural (not hashtag-stuffed); for a roundup, add a few bonus tools here>"
      }},
      "platforms": "<how to adapt this idea across LinkedIn / Substack / TikTok / Instagram / YouTube>",
      "geo_seo": "<keywords to include and GEO/SEO tips to be found in search and AI answers>",
      "sources": [{{"title": "<where you found this trend/idea>", "url": "<actual link>"}}]
    }},
    {{
      "day": "Wednesday",
      "platform": "<primary platform, e.g. Instagram + TikTok>",
      "format": "Video / Reel",
      "topic": "...",
      "idea": "...",
      "why": "...",
      "inspo": "...",
      "tool": "<the tool from her own kit she'd use to MAKE this piece>",
      "copy": {{
        "hook": "<punchy hook line>",
        "outline": ["<beat 1>", "<beat 2>", "..."],
        "caption": "<caption>"
      }},
      "platforms": "...",
      "geo_seo": "...",
      "sources": [{{"title": "<where you found this trend/idea>", "url": "<actual link>"}}]
    }},
    {{
      "day": "Friday",
      "platform": "<primary platform, e.g. Instagram>",
      "format": "Post / graphic",
      "topic": "...",
      "idea": "...",
      "why": "...",
      "inspo": "...",
      "tool": "<the tool from her own kit she'd use to MAKE this piece>",
      "copy": {{
        "caption": "<caption>"
      }},
      "platforms": "...",
      "geo_seo": "...",
      "sources": [{{"title": "<where you found this trend/idea>", "url": "<actual link>"}}]
    }}
  ],
  "video_strategy": {{
    "summary": "<this week's video plan and WHY: how many videos, which trend, which platforms, expected traction>",
    "sources": [{{"title": "<where you found the video trend>", "url": "<actual link>"}}],
    "videos": [
      {{
        "title": "<short video title>",
        "platform": "<primary platform, noting any cross-post, e.g. 'TikTok (also fits Instagram)'>",
        "format": "<short-form | long-form>",
        "length": "<e.g. ~30–60s or ~10–15 min>",
        "why": "<which trend, which platform, the traction you'd expect>",
        "script": {{
          "hook": "<scroll-stopping first 3 seconds>",
          "shots": [
            {{"camera": "<camera direction: angle / movement / framing>", "action": "<what she says or does in this shot>"}}
          ],
          "b_roll": ["<b-roll / cutaway idea>"],
          "captions": ["<on-screen text>"],
          "cta": "<call to action>"
        }}
      }}
    ]
  }},
  "ai_news": {{
    "headline": "<the recent launch>",
    "in_plain_terms": "<what it is, in everyday language>",
    "why_it_matters": "<why marketers / small businesses should care>",
    "carousel_idea": "<a simple carousel idea explaining it>",
    "source": {{"title": "<where you found this news>", "url": "<actual link>"}}
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
    the Notion writer can be verified without spending anything. The sample
    content lives in sample_plan.py (a generic, public-safe fixture); here we
    just stamp it with this week's label, the one value that depends on today.
    """
    return sample_plan(_week_label(datetime.now()))


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
    """Generate a plan and (unless it's a local-only mock) write it to Notion.

    `--mock` produces the free sample plan with NO API call. On its own it writes
    locally only — for inspecting the data or feeding the panel. Add `--to-notion`
    to also publish that sample to Notion: still free (a Notion write costs
    nothing; only the research call costs credit), so it's the way to preview the
    full layout — including the video scripts — at zero cost. With no flag it
    makes one real research call and publishes the real plan (the paid run).
    """
    parser = argparse.ArgumentParser(description="Generate the weekly content plan.")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use a free sample plan, no API call (writes locally unless --to-notion).",
    )
    parser.add_argument(
        "--to-notion",
        action="store_true",
        help="Publish to Notion. With --mock this previews the layout for free; it "
        "REPLACES the page's current contents.",
    )
    args = parser.parse_args()

    # A real run always publishes; a mock publishes only when explicitly asked.
    write_to_notion = (not args.mock) or args.to_notion

    print("Building a sample plan…" if args.mock else "Putting your plan together…")
    plan = build_weekly_plan(use_mock=args.mock)
    write_plan(plan)

    if "error" in plan:
        print(f"Note: {plan['error']}")
        return
    if not write_to_notion:
        print(f"Sample plan written to {PLAN_PATH.name} (no Notion write).")
        return

    # Imported here (not at module load) so the local-only path never needs the
    # Notion library, and to keep the brain independent of the publishing step.
    from notion_sync import page_url, publish_plan

    label = "sample plan" if args.mock else "full plan"
    error = publish_plan(plan)
    if error:
        print(error)
    else:
        print(f"Published your {label} to Notion: {page_url()}")


if __name__ == "__main__":
    main()
