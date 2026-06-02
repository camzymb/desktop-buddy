"""A realistic sample content plan, kept out of the planner's core module.

This is the free, no-API fixture the Weekly Content Planner returns in `--mock`
mode so the desktop panel and the Notion writer can be checked without spending
anything. It mirrors EXACTLY the shape the live model returns (same keys, same
nesting), so anything that renders a real plan renders this one identically.

The content here is deliberately GENERIC sample text — a believable creator's
week, not anyone's real kit, niche, or personal story. Keep it that way: this
file is public, so it must never carry real personal detail (specific gear,
identifying projects, or an autobiographical script).
"""

# === SAMPLE PLAN ===

def sample_plan(week_of: str) -> dict:
    """Return the sample plan dict, stamped with the given `week_of` label.

    The caller passes the week label (the only value that depends on today's
    date) so this fixture stays a pure, import-free data builder — everything
    else is fixed sample text.
    """
    return {
        "week_of": week_of,
        "intro": (
            "Here's a gentle plan for your week — three pieces, all "
            "ready to go. No rush. 🤍"
        ),
        "disclaimer": (
            "This is my suggestion based on what's trending this week — feel free "
            "to edit or change anything. You know your audience best. 🤍"
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
                    "slides": [
                        "You don't need a bigger budget. You need these 5 tools. 🤍",
                        "Claude — paste your messy voice notes and get captions that "
                        "actually sound like you. No more blank-box dread.",
                        "Canva — set up one brand kit, and every graphic comes out "
                        "on-brand in minutes instead of hours.",
                        "CapCut — cut your reels fast with auto-captions, so a post is "
                        "done before your coffee's even cold.",
                        "Higgsfield — turn your raw clips into one clean, cinematic edit "
                        "without learning complicated software.",
                        "Nano Banana — generate on-brand images and thumbnails for the "
                        "days you don't have a photo ready.",
                        "Save this for your next content day 🤍 Then tell me which one "
                        "you're trying first.",
                    ],
                    "caption": (
                        "The AI tools quietly doing my small-business marketing for me "
                        "(so I can have my weekends back) 👇\n\n"
                        "You don't need a bigger budget or a marketing degree — you just "
                        "need a few tools that do the heavy lifting. These are the 5 AI "
                        "tools I actually use every week to plan, write, design, and edit "
                        "my content:\n\n"
                        "→ Claude for captions that sound like me\n"
                        "→ Canva for on-brand graphics\n"
                        "→ CapCut for fast reels\n"
                        "→ Higgsfield for a cinematic edit\n"
                        "→ Nano Banana for quick on-brand images\n\n"
                        "Save this for your next content day, and tell me which one "
                        "you're trying first 🤍\n\n"
                        "#smallbusinessmarketing #aitools #contentcreation #marketingtips"
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
                "sources": [
                    {
                        "title": "(sample) r/smallbusiness — 'AI tools you actually use' thread",
                        "url": "https://example.com/sample-source",
                    },
                ],
            },
            {
                "day": "Wednesday",
                "platform": "Instagram + TikTok",
                "format": "Video / Reel",
                "topic": "My simple weekly content workflow",
                "idea": "Behind the scenes: how I batch a whole week of content in one sitting",
                "why": (
                    "'Batch with me' process content builds trust and rides the rising "
                    "interest in practical, calm content workflows for busy creators."
                ),
                "inspo": (
                    "Quiet 'batch with me' process clips are resonating — calm, real, "
                    "and a little satisfying, with the finished week as the payoff."
                ),
                "tool": "CapCut",
                "copy": {
                    "hook": "I batch a whole week of content in one afternoon. Here's my setup.",
                    "outline": [
                        "Beat 1 (0–3s): Hook on camera — 'I batch a whole week of content in one afternoon.'",
                        "Beat 2 (3–8s): Quick peek at the simple plan, kept friendly and uncluttered.",
                        "Beat 3 (8–15s): One honest line about why batching gives you your evenings back.",
                        "Beat 4 (15–20s): The finished posts lined up, ready to schedule.",
                        "Beat 5 (end): Soft call to follow for more gentle content systems.",
                    ],
                    "caption": (
                        "A little behind-the-scenes of how I batch my content so the week "
                        "feels calm instead of frantic. 🌸 You don't need a complicated system "
                        "to start — promise. Follow along for more gentle workflows."
                    ),
                },
                "platforms": (
                    "Reel for Instagram and TikTok; a longer cut for YouTube; a written "
                    "walk-through as a LinkedIn post and a Substack issue."
                ),
                "geo_seo": (
                    "Say 'weekly content workflow' out loud in the hook (captions are "
                    "indexed) and use it in the on-screen title and upload name."
                ),
                "sources": [
                    {
                        "title": "(sample) Trending LinkedIn post — 'batch with me' content",
                        "url": "https://example.com/sample-source",
                    },
                ],
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
                "sources": [
                    {
                        "title": "(sample) Later.com blog — text-post trends this month",
                        "url": "https://example.com/sample-source",
                    },
                ],
            },
        ],
        "video_strategy": {
            "summary": (
                "This week leans into video. 🌸 Short-form 'batch/learn with me' "
                "clips are getting strong reach right now, and long-form explainers are "
                "doing well on YouTube as people search for practical content help. So: two "
                "videos — one fast short-form for TikTok that also fits Instagram (for "
                "reach and saves), and one calm 10–15 min long-form for YouTube (for trust "
                "and search/AI-answer discovery). The short-form rides the trend for a "
                "traffic spike; the long-form keeps working for months."
            ),
            "sources": [
                {
                    "title": "(sample) TikTok Creative Center — trending formats this week",
                    "url": "https://example.com/sample-source",
                },
            ],
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
                                "camera": "Mirrorless camera, handheld, 35mm, eye-level, quick push-in toward her face; bright window light.",
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
                                "camera": "Cut to a top-down of the camera on the desk; four fingers held over it.",
                                "action": "'Four — a good little camera. Decent light plus a 50mm and your content instantly looks more pro.'",
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
                            "Top-down hero shot of the camera on the desk, lens cap coming off.",
                            "2-second before/after: blank caption box vs. finished post on the phone screen.",
                        ],
                        "captions": [
                            "POV: your marketing runs itself 👀",
                            "1. Claude → captions that sound like YOU",
                            "2. Canva → on-brand in minutes",
                            "3. CapCut → reels before your coffee's cold ☕",
                            "4. A mirrorless camera → instant 'pro' look",
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
                    "title": "How I plan a whole month of content in one afternoon",
                    "platform": "YouTube",
                    "format": "long-form",
                    "length": "~12 min",
                    "why": (
                        "'Plan with me' long-form is rising as creators search for practical "
                        "content systems. Evergreen: keeps pulling search and AI-answer "
                        "traffic long after this week."
                    ),
                    "script": {
                        "hook": (
                            "Cold open, seated, 50mm, soft window light, shallow background. "
                            "Exact words, calm and warm: 'I plan a whole month of content in one "
                            "quiet afternoon — no burnout, no blank-page panic. Let me walk you "
                            "through the exact workflow.'"
                        ),
                        "shots": [
                            {
                                "camera": "Shot 1 (cold open) — mirrorless camera on tripod, 50mm, eye-level, seated, shallow background, soft window light.",
                                "action": "Exact words: 'I plan a whole month of content in one quiet afternoon — no burnout, no blank-page panic.' Beat. 'Let me walk you through the exact workflow.'",
                            },
                            {
                                "camera": "Shot 2 (the promise) — slight reframe slightly wider, warm tone.",
                                "action": "'By the end you'll know how I find ideas, batch them, and schedule a whole month — and how you could copy it. Stick around for the live plan at the end.'",
                            },
                            {
                                "camera": "Shot 3 (title card) — cut to a clean desk wide shot, gentle music up.",
                                "action": "Title-card overlay holds 2–3s: 'How I plan a month of content in an afternoon.'",
                            },
                            {
                                "camera": "Shot 4 (Ch.1: the problem) — back to seated 50mm.",
                                "action": "'Every week I'd lose hours staring at a blank content calendar. So I built one calm afternoon routine that fills the whole month.'",
                            },
                            {
                                "camera": "Shot 5 (Ch.1 b-roll over voice) — cutaway: hand flipping a blank paper planner; clock on the wall.",
                                "action": "Voiceover: 'It's not about doing more — it's about deciding once.'",
                            },
                            {
                                "camera": "Shot 6 (Ch.2: gather ideas) — screen-share, full-frame, cursor visible.",
                                "action": "Plain words: 'First I collect every idea in one place — saved posts, questions people ask me, things I learned this week.' Be honest about the messy first list.",
                            },
                            {
                                "camera": "Shot 7 (Ch.2: the tools) — picture-in-picture: seated cam small in the corner, screen full.",
                                "action": "'The only tools: a notes app, Claude to shape the ideas, and Canva to design. That's genuinely it — everything's linked below.'",
                            },
                            {
                                "camera": "Shot 8 (Ch.3: batching, part 1) — screen-share zoomed into the relevant area.",
                                "action": "Narrate slowly while sorting ideas into weeks: 'Watch — I just group the ideas by theme, one theme per week, and the month basically plans itself.'",
                            },
                            {
                                "camera": "Shot 9 (Ch.3 b-roll) — close-up of hands on the keyboard; slow pan across the desk.",
                                "action": "Voiceover bridge: 'I draft the captions in a batch while I'm in the zone — and it's okay if some are rough first.'",
                            },
                            {
                                "camera": "Shot 10 (Ch.4: why it matters) — cut to seated 50mm, gentle push-in.",
                                "action": "Reflective: 'Here's what surprised me — planning ahead didn't make it rigid. It made me less anxious, because the blank page was gone.'",
                            },
                            {
                                "camera": "Shot 11 (Ch.5: live demo) — screen-share, full frame, real time; don't cut away while it works.",
                                "action": "Build one week live: 'Okay — let's actually fill a week together… and there it is.' Let it breathe.",
                            },
                            {
                                "camera": "Shot 12 (recap) — back to seated 50mm, slightly wider, warm.",
                                "action": "'Quick recap: one, collect ideas all week. Two, batch by theme. Three, let the first draft be messy. That's the whole secret.'",
                            },
                            {
                                "camera": "Shot 13 (outro/CTA) — final seated shot, gentle push-in, soft smile, music up.",
                                "action": "Deliver the CTA (below), hold for a beat, then end card.",
                            },
                        ],
                        "b_roll": [
                            "Wide shot of the desk with the key light on and plants in frame (for the title card).",
                            "Cutaway: a blank paper planner flipped open; a clock on the wall.",
                            "Close-ups of hands typing in natural window light, for cutaways over narration.",
                            "Slow 3-second pan across the workspace (camera, coffee, notebook).",
                            "Screen-recording clips of the ideas list and calendar for picture-in-picture cutaways.",
                            "The finished month laid out on the screen, and the schedule open on a phone.",
                        ],
                        "captions": [
                            "How I plan a month of content in an afternoon",
                            "Chapter 1 — the problem",
                            "Chapter 2 — gather the ideas",
                            "Chapter 3 — batch by theme (live)",
                            "tip: it's okay for the first draft to be messy 🤍",
                            "Chapter 4 — why it actually matters",
                            "Chapter 5 — the live demo",
                            "everything's linked in the description ↓",
                        ],
                        "cta": (
                            "Exact wording: 'If this made content planning feel a little less "
                            "heavy, hit subscribe — I share one gentle little system like this "
                            "every week. The full steps and every link are in the description. "
                            "I'll see you in the next one.'"
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
            "source": {
                "title": "(sample) TechCrunch — this week's AI launch",
                "url": "https://example.com/sample-source",
            },
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
