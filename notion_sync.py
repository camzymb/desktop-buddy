"""Write the full weekly content plan to Camille's Notion page.

The desktop panel shows only the week at a glance; the complete, detailed plan
lives on a Notion page: a real bordered weekly table (Day · Platform · Format ·
Topic & Why · Tools · References), the ready-to-use drafted copy and repurposing
/SEO notes beneath it, and the full cinematic video scripts (laid out last, each
under its own headings). This module turns a plan dict (from content_planner)
into Notion blocks and writes them.

Bring-your-own-key, loaded from the gitignored .env (never hard-coded, never
committed):

    NOTION_TOKEN     — an internal-integration token (starts with "ntn_"/"secret_")
    NOTION_PAGE_ID   — the page to write the plan to

The page must be shared with your integration (Notion → page → ••• → Connections).
Each run ARCHIVES the week as its own dated sub-page (e.g. "Week of Jun 2–8,
2026") under that page — it never overwrites or deletes earlier weeks, so the
Content Plans page becomes a growing, dated history. Any missing setup or API
problem is returned as a friendly message — this module never raises into the
caller.
"""

# === IMPORTS ===

import os

from content_planner import load_env_file

# === CONSTANTS ===

# Bring-your-own-key: both are read from .env (see .env.example), never committed.
NOTION_TOKEN_VAR = "NOTION_TOKEN"
NOTION_PAGE_ID_VAR = "NOTION_PAGE_ID"

# Notion caps a single rich-text run at 2000 characters; our copy is short, but
# we truncate defensively so an unusually long field can never fail the write.
MAX_TEXT_LENGTH = 2000

# Notion accepts at most 100 child blocks per append call.
APPEND_CHUNK_SIZE = 100

# Friendly, non-crashing messages for the things that can go wrong.
MISSING_TOKEN_MESSAGE = (
    "I couldn't find your Notion token. 🤍 Add it to your .env file as "
    "NOTION_TOKEN=... (there's a .env.example to copy), then try again."
)
MISSING_PAGE_MESSAGE = (
    "I couldn't find your Notion page id. 🤍 Add NOTION_PAGE_ID=... to your .env "
    "file, then try again."
)
MISSING_LIBRARY_MESSAGE = (
    "The Notion library isn't installed yet. 🤍 Run "
    "`.venv/bin/pip install -r requirements.txt`, then try again."
)
ACCESS_ERROR_MESSAGE = (
    "I couldn't reach your Notion page. 🤍 Double-check your NOTION_TOKEN, and "
    "make sure you've shared the page with your integration "
    "(open the page → ••• → Connections → add it). Then try again."
)
GENERIC_ERROR_MESSAGE = (
    "I hit a snag writing to Notion. 🤍 Mind checking your internet and trying "
    "again in a bit?"
)


# === PUBLIC HELPERS ===

def page_url() -> str:
    """Return the browser URL of the configured Notion page, or "" if unset."""
    load_env_file()
    page_id = os.environ.get(NOTION_PAGE_ID_VAR, "").replace("-", "").strip()
    return f"https://www.notion.so/{page_id}" if page_id else ""


def publish_plan(plan: dict) -> str:
    """Archive this week's plan as a new dated sub-page; return "" or a message.

    Loads the token and page id from .env, then ADDS the week as its own dated
    sub-page under the Content Plans page (never overwriting or deleting earlier
    weeks). Reports any expected problem (missing setup, access/sharing issue,
    network) as a friendly string instead of raising, so the buddy never crashes
    over a publishing hiccup.
    """
    load_env_file()
    token = os.environ.get(NOTION_TOKEN_VAR, "").strip()
    page_id = os.environ.get(NOTION_PAGE_ID_VAR, "").strip()
    if not token:
        return MISSING_TOKEN_MESSAGE
    if not page_id:
        return MISSING_PAGE_MESSAGE

    # Imported lazily so the mock path and the rest of the app never need the
    # Notion library just to run.
    try:
        from notion_client import Client
        from notion_client.errors import APIResponseError, HTTPResponseError
    except ImportError:
        return MISSING_LIBRARY_MESSAGE

    client = Client(auth=token)
    title = plan.get("week_of") or "Weekly Content Plan"
    blocks = _build_blocks(plan)
    try:
        _archive_week(client, page_id, title, blocks)
    except APIResponseError:
        # 401/403/404 almost always mean a bad token or an unshared page.
        return ACCESS_ERROR_MESSAGE
    except (HTTPResponseError, OSError):
        return GENERIC_ERROR_MESSAGE
    return ""


# === NOTION WRITE (archive, never overwrite) ===

def _archive_week(client, parent_page_id: str, title: str, blocks: list[dict]) -> None:
    """Create a NEW dated sub-page under the Content Plans page for this week.

    Past weeks are never touched — each run only adds. A Notion page-create
    accepts at most APPEND_CHUNK_SIZE child blocks, so the first chunk seeds the
    new page and any remainder is appended to it in further chunks.
    """
    new_page = client.pages.create(
        parent={"page_id": parent_page_id},
        properties={"title": {"title": _rich_text(title)}},
        children=blocks[:APPEND_CHUNK_SIZE],
    )
    new_page_id = new_page["id"]
    for start in range(APPEND_CHUNK_SIZE, len(blocks), APPEND_CHUNK_SIZE):
        client.blocks.children.append(
            block_id=new_page_id, children=blocks[start : start + APPEND_CHUNK_SIZE]
        )


# === BLOCK BUILDERS ===

def _rich_text(content: str) -> list[dict]:
    """Wrap a plain string as a Notion rich-text run, truncated to the API limit."""
    return [{"type": "text", "text": {"content": content[:MAX_TEXT_LENGTH]}}]


def _bold_line(content: str) -> dict:
    """A short, bold paragraph — used as a copy-paste-friendly label above content."""
    run = {"type": "text", "text": {"content": content[:MAX_TEXT_LENGTH]}, "annotations": {"bold": True}}
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [run]}}


def _callout(content: str, emoji: str = "💡") -> dict:
    """A callout block — a gently boxed note, used for the 'this is a suggestion' line."""
    return {
        "object": "block",
        "type": "callout",
        "callout": {"rich_text": _rich_text(content), "icon": {"type": "emoji", "emoji": emoji}},
    }


def _link_run(title: str, url: str) -> dict:
    """A rich-text run that links to a URL, falling back safely if the URL is unusable.

    Notion rejects an empty or non-http link, which would fail the whole page
    write, so a malformed URL is shown as plain text instead of a broken link.
    """
    content = (title or url or "").strip()
    if url and url.startswith(("http://", "https://")):
        return {"type": "text", "text": {"content": content[:MAX_TEXT_LENGTH], "link": {"url": url}}}
    if url:
        content = f"{content} ({url})"
    return {"type": "text", "text": {"content": content[:MAX_TEXT_LENGTH]}}


def _source_blocks(sources) -> list[dict]:
    """Render a 'Sources' label and one linked bullet per cited source, or nothing."""
    valid = [s for s in (sources or []) if isinstance(s, dict) and (s.get("title") or s.get("url"))]
    if not valid:
        return []
    blocks: list[dict] = [_bold_line("🔗 Sources:")]
    for source in valid:
        run = _link_run(source.get("title", ""), source.get("url", ""))
        blocks.append(
            {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [run]}}
        )
    return blocks


def _block(block_type: str, content: str) -> dict:
    """Build a single-line block (heading or paragraph) holding one string."""
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": _rich_text(content)},
    }


def _bullet(content: str) -> dict:
    """Build one bulleted-list item."""
    return _block("bulleted_list_item", content)


def _numbered(content: str) -> dict:
    """Build one numbered-list item (used for ordered, shot-by-shot steps)."""
    return _block("numbered_list_item", content)


def _labelled(label: str, value) -> list[dict]:
    """A single 'Label: value' paragraph, or nothing when the value is empty."""
    if not value:
        return []
    return [_block("paragraph", f"{label}: {value}")]


# === WEEKLY TABLE ===

# The weekly overview is a real Notion table; these are its columns, in order.
TABLE_COLUMNS = ("Day", "Platform", "Format", "Topic & Why", "Tools", "References")


def _table_row(cells: list[str]) -> dict:
    """Build one table_row block from a list of plain-string cell values."""
    return {
        "object": "block",
        "type": "table_row",
        "table_row": {"cells": [_rich_text(value) for value in cells]},
    }


def _weekly_table(pieces: list[dict]) -> dict:
    """Build a real, bordered Notion table for the week — one row per piece.

    A Notion table block must carry all its rows as children, and every row must
    have exactly `table_width` cells, so we emit the header plus one fixed-width
    row per piece inside a single table block. The longer fields (drafted copy,
    repurposing notes, SEO) don't belong in cells — they go below the table.
    """
    rows = [_table_row(list(TABLE_COLUMNS))]
    for piece in pieces:
        topic = piece.get("topic", "")
        why = piece.get("why", "")
        topic_why = f"{topic} — {why}" if topic and why else (topic or why)
        rows.append(
            _table_row(
                [
                    piece.get("day", ""),
                    piece.get("platform", ""),
                    piece.get("format", ""),
                    topic_why,
                    piece.get("tool", ""),
                    piece.get("inspo", ""),
                ]
            )
        )
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": len(TABLE_COLUMNS),
            "has_column_header": True,
            "has_row_header": False,
            "children": rows,
        },
    }


def _build_blocks(plan: dict) -> list[dict]:
    """Turn a plan dict into the ordered list of Notion blocks for the page."""
    blocks: list[dict] = [
        _block("heading_1", f"🌸 Weekly Content Plan — {plan.get('week_of', 'This week')}"),
    ]
    if plan.get("intro"):
        blocks.append(_block("paragraph", plan["intro"]))
    # Her humble note that this is a suggestion Camille can freely edit.
    if plan.get("disclaimer"):
        blocks.append(_callout(plan["disclaimer"], "🤍"))

    # The week at a glance is a real bordered table; the ready-to-use copy and
    # notes (too long for cells) follow underneath, one block per piece.
    pieces = plan.get("pieces", [])
    if pieces:
        blocks.append(_weekly_table(pieces))
        blocks.append(_block("heading_2", "✍️ Drafted copy & notes"))
        for piece in pieces:
            blocks += _piece_detail_blocks(piece)

    news = plan.get("ai_news")
    if news:
        blocks.append(_block("heading_2", "What's new in AI / marketing tech ✨"))
        blocks += _labelled("Headline", news.get("headline"))
        blocks += _labelled("In plain terms", news.get("in_plain_terms"))
        blocks += _labelled("Why it matters", news.get("why_it_matters"))
        blocks += _labelled("Carousel idea", news.get("carousel_idea"))
        news_source = news.get("source")
        if news_source:
            blocks += _source_blocks([news_source])

    tips = plan.get("hook_tips")
    if tips:
        blocks.append(_block("heading_2", "Hook tips 🪝"))
        blocks += [_bullet(tip) for tip in tips]

    # The full cinematic scripts are long, so they go last — below the weekly
    # table and the short sections, each under its own clear headings — rather
    # than crammed into the panel or the table cells.
    strategy = plan.get("video_strategy")
    if strategy:
        blocks += _video_strategy_blocks(strategy)

    if plan.get("closing_note"):
        blocks.append(_block("paragraph", plan["closing_note"]))
    return blocks


def _piece_detail_blocks(piece: dict) -> list[dict]:
    """Build the ready-to-use copy and notes for one piece, shown below the table.

    The at-a-glance facts (day, platform, format, topic, tool, reference) already
    live in the table above, so here we keep only the longer content that doesn't
    belong in a cell: the fuller idea, the drafted copy, repurposing notes, and
    SEO tips. Any field the plan omitted is simply skipped.
    """
    title = f"{piece.get('day', '')} · {piece.get('format', '')}".strip(" ·")
    if piece.get("topic"):
        title = f"{title} — {piece['topic']}"
    blocks: list[dict] = [_block("heading_3", title)]

    blocks += _labelled("Idea", piece.get("idea"))

    copy = piece.get("copy") or {}
    slides = copy.get("slides") or []
    outline = copy.get("outline") or []
    if slides:
        # Carousel: slide 1 is the cover/hook, so don't repeat a separate hook.
        blocks += _carousel_slide_blocks(slides)
    elif outline:
        blocks += _labelled("Hook", copy.get("hook"))
        blocks.append(_bold_line("Shot / beat outline:"))
        blocks += [_bullet(beat) for beat in outline]
    else:
        blocks += _labelled("Hook", copy.get("hook"))

    # The caption goes in its own clean block (no "Caption:" prefix) so it can be
    # pasted straight into the post box, line breaks and all.
    caption = copy.get("caption")
    if caption:
        blocks.append(_bold_line("📝 Caption — ready to paste:"))
        blocks.append(_block("paragraph", caption))

    blocks += _labelled("Multi-platform fit", piece.get("platforms"))
    blocks += _labelled("GEO/SEO", piece.get("geo_seo"))
    blocks += _source_blocks(piece.get("sources"))
    return blocks


def _carousel_slide_blocks(slides: list[str]) -> list[dict]:
    """Render carousel slides as labeled, copy-paste-ready blocks.

    Each slide is a bold "Slide N" label — the first is the cover/hook, the last
    is the CTA — followed by that slide's exact text on its own block, so Camille
    can copy a single slide straight into Canva with nothing to trim.
    """
    blocks: list[dict] = [_bold_line("🎠 Carousel slides — ready to paste:")]
    count = len(slides)
    for index, text in enumerate(slides):
        if index == 0:
            label = "Slide 1 — Hook (cover)"
        elif index == count - 1:
            label = f"Slide {count} — CTA"
        else:
            label = f"Slide {index + 1}"
        blocks.append(_bold_line(label))
        blocks.append(_block("paragraph", text))
    return blocks


# === VIDEO SCRIPTS ===

def _video_strategy_blocks(strategy: dict) -> list[dict]:
    """Build the video-scripts section: the week's strategy, then a full script each."""
    blocks: list[dict] = [_block("heading_1", "🎬 Video scripts")]
    blocks += _labelled("This week's video strategy", strategy.get("summary"))
    blocks += _source_blocks(strategy.get("sources"))
    for video in strategy.get("videos", []):
        blocks += _video_blocks(video)
    return blocks


def _video_blocks(video: dict) -> list[dict]:
    """Build the heading and full cinematic script for one suggested video.

    The script is laid out under its own sub-headings (hook, shot-by-shot,
    b-roll, captions, CTA) so each long script reads cleanly on the page; any
    field the model omitted is simply skipped.
    """
    blocks: list[dict] = [_block("heading_2", f"🎥 {video.get('title', 'Video')}")]

    # Platform / format / length on one tidy line, dropping any missing part.
    meta = " · ".join(
        part for part in (video.get("platform"), video.get("format"), video.get("length")) if part
    )
    blocks += _labelled("Format", meta)
    blocks += _labelled("Why", video.get("why"))

    script = video.get("script") or {}
    blocks += _labelled("Hook (first 3s)", script.get("hook"))

    shots = script.get("shots") or []
    if shots:
        blocks.append(_block("heading_3", "Shot-by-shot"))
        blocks += [_numbered(_format_shot(shot)) for shot in shots]

    b_roll = script.get("b_roll") or []
    if b_roll:
        blocks.append(_block("heading_3", "B-roll"))
        blocks += [_bullet(idea) for idea in b_roll]

    captions = script.get("captions") or []
    if captions:
        blocks.append(_block("heading_3", "On-screen captions"))
        blocks += [_bullet(caption) for caption in captions]

    blocks += _labelled("CTA", script.get("cta"))
    return blocks


def _format_shot(shot) -> str:
    """Render one shot as 'camera direction — action', tolerating a plain string."""
    if isinstance(shot, dict):
        camera = shot.get("camera", "").strip()
        action = shot.get("action", "").strip()
        if camera and action:
            return f"{camera} — {action}"
        return camera or action
    return str(shot)
