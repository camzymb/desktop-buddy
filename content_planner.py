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
ready-to-use drafted copy, multi-platform fit notes (LinkedIn, Substack, TikTok,
Instagram, YouTube), and GEO/SEO tips. She also decides a fresh video strategy
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
  - the primary platform for that piece (one or two words, e.g. "Instagram" or \
"Instagram + TikTok"),
  - a trend-informed idea,
  - a "why this, why now" note (why it's worth posting this week),
  - a short reference/inspo note (a style or format that's working — described in \
general terms, NOT scraped from a specific creator or platform),
  - one recommended tool,
  - drafted copy she can use as-is:
      * Carousel: a strong, punchy hook plus slide-by-slide text.
      * Video / Reel: a punchy hook line plus a brief shot/beat outline.
      * Post / graphic: a caption.
  - multi-platform fit notes: how to adapt the SAME idea across LinkedIn, \
Substack, TikTok, Instagram, and YouTube (repurposing HER own content — never \
scraping or reposting others'),
  - GEO/SEO optimization notes: the keywords/phrases to include and how to be \
found in both search engines and AI answer engines (GEO).

Keep hooks punchy and human.

TOOLS — you may ONLY ever recommend from this exact list, and must NEVER invent \
or suggest any other tool:
{tool_lines}

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
She films on a Sony a6700 and edits in Higgsfield, so write real, specific camera \
directions she can shoot to. Do NOT be thin or generic. Each script must include:
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
      "platform": "<primary platform, e.g. Instagram>",
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
      "platforms": "<how to adapt this idea across LinkedIn / Substack / TikTok / Instagram / YouTube>",
      "geo_seo": "<keywords to include and GEO/SEO tips to be found in search and AI answers>"
    }},
    {{
      "day": "Wednesday",
      "platform": "<primary platform, e.g. Instagram + TikTok>",
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
      "platform": "<primary platform, e.g. Instagram>",
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
  "video_strategy": {{
    "summary": "<this week's video plan and WHY: how many videos, which trend, which platforms, expected traction>",
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
                "platform": "Instagram",
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
                    "become a short TikTok/Reel list and a quick Substack note."
                ),
                "geo_seo": (
                    "Work the phrase 'AI tools for small business marketing' into slide 1 and "
                    "the caption; add alt text per slide so search and AI answer engines can read it."
                ),
            },
            {
                "day": "Wednesday",
                "platform": "Instagram + TikTok",
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
                    "Reel for Instagram and TikTok; a longer cut for YouTube; a written "
                    "walk-through as a LinkedIn post and a Substack issue."
                ),
                "geo_seo": (
                    "Say 'AI automation for small business' out loud in the hook (captions are "
                    "indexed) and use it in the on-screen title and upload name."
                ),
            },
            {
                "day": "Friday",
                "platform": "Instagram",
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
                    "LinkedIn one-liner or a short Substack note."
                ),
                "geo_seo": (
                    "Add descriptive alt text and a searchable caption ('small business "
                    "motivation') so the graphic is findable in search and AI answers."
                ),
            },
        ],
        "video_strategy": {
            "summary": (
                "This week leans into video, Camille. 🌸 Short-form 'build/learn with me' "
                "clips are getting strong reach right now, and long-form explainers are "
                "doing well on YouTube as people search for practical AI help. So: two "
                "videos — one fast short-form for TikTok that also fits Instagram (for "
                "reach and saves), and one calm 10–15 min long-form for YouTube (for trust "
                "and search/AI-answer discovery). The short-form rides the trend for a "
                "traffic spike; the long-form keeps working for months."
            ),
            "videos": [
                {
                    "title": "5 AI tools doing my marketing for me",
                    "platform": "TikTok (also fits Instagram Reels)",
                    "format": "short-form",
                    "length": "~45s",
                    "why": (
                        "Quick AI-tool roundups are trending and highly saveable; short-form "
                        "is where the cold-reach spike is this week. Cross-posts to Reels "
                        "with no re-edit."
                    ),
                    "script": {
                        "hook": (
                            "Handheld, 35mm, eye-level, fast 1-second push-in toward her face, "
                            "bright window light. Exact words, said quickly with NO intro: "
                            "'Stop paying for marketing you can do in 10 minutes — here are the "
                            "5 AI tools doing mine for me.'"
                        ),
                        "shots": [
                            {
                                "camera": "a6700 handheld, 35mm, eye-level, quick push-in toward her face; bright window light.",
                                "action": "Straight to camera, energetic, no preamble: 'Stop paying for marketing you can do in 10 minutes — here are the 5 AI tools doing mine for me.'",
                            },
                            {
                                "camera": "Hard cut, same handheld look, tighter (chest-up); she holds up one finger.",
                                "action": "'One — Claude for captions. I paste my messy voice notes and it writes captions that actually sound like me.'",
                            },
                            {
                                "camera": "Quick cut to over-the-shoulder of the laptop, shallow depth of field, screen in focus.",
                                "action": "Screen-recording overlay of a caption generating (~2s) while she says: 'No more staring at a blank box.'",
                            },
                            {
                                "camera": "Cut back to handheld eye-level; two fingers up.",
                                "action": "'Two — Canva. One brand kit, and every graphic is on-brand in minutes, not hours.'",
                            },
                            {
                                "camera": "Hard cut, three fingers, slight whip-pan in.",
                                "action": "'Three — CapCut to cut my reels. Auto-captions on, done before my coffee's cold.'",
                            },
                            {
                                "camera": "Cut to a top-down of the Sony a6700 on the desk; four fingers held over it.",
                                "action": "'Four — this little camera. Good light plus a 50mm and your content instantly looks more pro.'",
                            },
                            {
                                "camera": "Slow push-in, warmer; five fingers, then a small smile.",
                                "action": "'And five — the one that saves my weekends: Higgsfield, to pull it all into one cinematic edit.'",
                            },
                            {
                                "camera": "Final beat, holding eye contact, settle and soften.",
                                "action": "'Save this so you've got the list — then tell me which one you're grabbing first.'",
                            },
                        ],
                        "b_roll": [
                            "Screen recording: a caption generating in Claude (2–3s).",
                            "Close-up of hands dragging a graphic into place in Canva.",
                            "Over-shoulder of the CapCut timeline as auto-captions pop on.",
                            "Top-down hero shot of the Sony a6700 on the desk, lens cap coming off.",
                            "2-second before/after: blank caption box vs. finished post on the phone screen.",
                        ],
                        "captions": [
                            "POV: your marketing runs itself 👀",
                            "1. Claude → captions that sound like YOU",
                            "2. Canva → on-brand in minutes",
                            "3. CapCut → reels before your coffee's cold ☕",
                            "4. Sony a6700 → instant 'pro' look",
                            "5. Higgsfield → the cinematic edit ✨",
                            "save this 🤍 which one first?",
                        ],
                        "cta": (
                            "Said on camera and pinned as the first comment: 'Save this for your "
                            "next content day — then drop the tool you're trying first and I'll "
                            "reply with exactly how I use it.'"
                        ),
                    },
                },
                {
                    "title": "How I built a tiny AI helper with Claude Code (no CS degree)",
                    "platform": "YouTube",
                    "format": "long-form",
                    "length": "~12 min",
                    "why": (
                        "'Build with me' long-form is rising as non-developers search for "
                        "practical AI tutorials. Evergreen: keeps pulling search and "
                        "AI-answer traffic long after this week."
                    ),
                    "script": {
                        "hook": (
                            "Cold open, seated, 50mm, soft window light, shallow background. "
                            "Exact words, calm and warm: 'I taught my computer to plan a whole "
                            "week of my content for me — and I'm not a programmer. No CS "
                            "degree, no bootcamp. Let me show you exactly how I built it.'"
                        ),
                        "shots": [
                            {
                                "camera": "Shot 1 (cold open) — a6700 on tripod, 50mm, eye-level, seated, shallow background, soft window light.",
                                "action": "Exact words: 'I taught my computer to plan a whole week of my content for me — and I'm not a programmer.' Beat. 'No CS degree, no bootcamp. Let me show you exactly how.'",
                            },
                            {
                                "camera": "Shot 2 (the promise) — slight reframe slightly wider, warm tone.",
                                "action": "'By the end you'll know what it does, how I built it without code, and how you could make your own. Stick around for the live demo at the end.'",
                            },
                            {
                                "camera": "Shot 3 (title card) — cut to a clean desk wide shot, gentle music up.",
                                "action": "Title-card overlay holds 2–3s: 'How I built a tiny AI helper (no CS degree).'",
                            },
                            {
                                "camera": "Shot 4 (Ch.1: the problem) — back to seated 50mm.",
                                "action": "'Every Sunday I'd lose two hours staring at a blank content calendar. So I thought — what if something could draft it for me, in my voice?'",
                            },
                            {
                                "camera": "Shot 5 (Ch.1 b-roll over voice) — cutaway: hand flipping a blank paper planner; clock on the wall.",
                                "action": "Voiceover: 'I'm not technical. I just wanted my evenings back.'",
                            },
                            {
                                "camera": "Shot 6 (Ch.2: the idea) — screen-share, full-frame, cursor visible.",
                                "action": "Plain words: 'It's a little desktop helper. I ask it to plan my week, it researches what's trending, and it writes the posts.' Be honest about the messy first attempts.",
                            },
                            {
                                "camera": "Shot 7 (Ch.2: the tools) — picture-in-picture: seated cam small in the corner, screen full.",
                                "action": "'The only tools: Claude Code to build it, and one API key. That's genuinely it — everything's linked below.'",
                            },
                            {
                                "camera": "Shot 8 (Ch.3: building it, part 1) — screen-share zoomed into the relevant area.",
                                "action": "Narrate slowly while asking Claude Code to create the helper: 'Watch — I just describe what I want in plain English, and it writes the code.'",
                            },
                            {
                                "camera": "Shot 9 (Ch.3 b-roll) — close-up of hands on the keyboard; slow pan across the desk.",
                                "action": "Voiceover bridge: 'It wrote the first version in a couple of minutes. Then we fixed the bits that broke — and that part is completely normal.'",
                            },
                            {
                                "camera": "Shot 10 (Ch.3: building it, part 2) — back to screen-share for one real fix.",
                                "action": "Show one realistic bug and the calm fix: 'See? It's not magic — it's just patient back-and-forth.'",
                            },
                            {
                                "camera": "Shot 11 (Ch.4: why it matters) — cut to seated 50mm, gentle push-in.",
                                "action": "Reflective: 'Here's what surprised me — it didn't just save time. It made me want to create again, because the scary blank page was gone.'",
                            },
                            {
                                "camera": "Shot 12 (Ch.5: live demo) — screen-share, full frame, real time; don't cut away while it works.",
                                "action": "Run the finished helper live: 'Okay — let's actually run it… and there's my whole week.' Let it breathe.",
                            },
                            {
                                "camera": "Shot 13 (Ch.5 b-roll) — close-up of the finished plan panel on the desktop; phone showing the Notion page.",
                                "action": "Voiceover: 'It even writes the full scripts — like the one I'm reading from right now.'",
                            },
                            {
                                "camera": "Shot 14 (recap) — back to seated 50mm, slightly wider, warm.",
                                "action": "'Quick recap: one, you don't need to code. Two, start tiny. Three, let it be a little messy. That's the whole secret.'",
                            },
                            {
                                "camera": "Shot 15 (outro/CTA) — final seated shot, gentle push-in, soft smile, music up.",
                                "action": "Deliver the CTA (below), hold for a beat, then end card.",
                            },
                        ],
                        "b_roll": [
                            "Wide shot of the desk with the key light on and plants in frame (for the title card).",
                            "Cutaway: a blank paper planner flipped open; a clock on the wall.",
                            "Close-ups of hands typing in natural window light, for cutaways over narration.",
                            "Slow 3-second pan across the workspace (camera, coffee, notebook).",
                            "Screen-recording clips of the build for picture-in-picture cutaways.",
                            "The finished helper running on the desktop, and the Notion page open on a phone.",
                        ],
                        "captions": [
                            "How I built a tiny AI helper (no CS degree)",
                            "Chapter 1 — the problem",
                            "Chapter 2 — the idea",
                            "Chapter 3 — building it (live)",
                            "tip: it's okay for it to break 🤍",
                            "Chapter 4 — why it actually matters",
                            "Chapter 5 — the live demo",
                            "everything's linked in the description ↓",
                        ],
                        "cta": (
                            "Exact wording: 'If this made AI feel a little less scary, hit "
                            "subscribe — I build one gentle little tool like this every week and "
                            "walk you through it. The full steps and every link are in the "
                            "description. I'll see you in the next one.'"
                        ),
                    },
                },
            ],
        },
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
