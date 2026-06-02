"""Email-draft assistant — the buddy drafts replies you review and send yourself.

When asked (the "D" key, or the --draft-now / --draft-mock launch flags), the
buddy looks at today's IMPORTANT emails and drafts a short, warm, professional
reply for each one, in Camille's voice. She shows the drafts in a panel; each
gets an "Open in Gmail" button that opens a Gmail compose window in the browser,
prefilled with the draft. Camille reviews, edits if she likes, and hits send.

Hard guardrails (by construction, not just by intent):
  * READ-ONLY Gmail. This module reuses gmail_sync's existing `gmail.readonly`
    access and its existing importance filter — it never requests or uses any
    send/compose/modify scope.
  * THE BUDDY NEVER SENDS. Nothing here sends, schedules, or queues mail. It only
    drafts text and builds a Gmail compose URL; sending happens solely when
    Camille clicks send inside Gmail in her own browser.
  * APPROVED EMAILS ONLY. Drafts are made strictly for emails gmail_sync's filter
    already approved (real people, reply plausibly expected) — never for the
    skipped categories (newsletters, no-reply, promotions/social, forwards,
    rejections).

Cost: exactly ONE Anthropic API call per email drafted (a cheap Haiku call, no
web search, no tool loop), capped at gmail_sync.MAX_REPLY_DRAFTS emails per pass.
The key is bring-your-own-key, read from the gitignored `.env` (ANTHROPIC_API_KEY,
the same one the content planner uses); a missing key returns a friendly note.

Test it for free — --mock invents a couple of sample emails and drafts with NO
Anthropic call and NO Gmail access at all:

    .venv/bin/python draft_assistant.py --mock   # free: sample drafts, no calls
    .venv/bin/python draft_assistant.py          # real: read inbox + draft (paid)
"""

# === IMPORTS ===

import argparse
from dataclasses import dataclass
from urllib.parse import urlencode

# Reuse the planner's dependency-free .env loader rather than duplicating it.
from content_planner import load_env_file
from gmail_sync import (
    GmailSyncError,
    ReplyableEmail,
    fetch_important_for_reply,
)


# === CONSTANTS ===

# Bring-your-own-key: the same gitignored .env value the content planner uses.
API_KEY_VAR = "ANTHROPIC_API_KEY"

# A cheap, fast model is plenty for a short reply — and keeps cost tiny.
MODEL = "claude-haiku-4-5"

# A reply is short; a small cap keeps each call fast and cheap.
MAX_TOKENS = 400

# Gmail's "compose in the browser" URL. `view=cm` opens a compose window prefilled
# from the query string. Note: Gmail's URL scheme can't drop a reply into the
# original thread by its hidden Message-ID (that would need a send/compose scope,
# which we never use), so we address it back to the sender with a "Re:" subject —
# same recipient + "Re:" is how Gmail itself groups a conversation.
GMAIL_COMPOSE_BASE = "https://mail.google.com/mail/?"

# --- Friendly, non-crashing messages (shown in her bubble, never a crash) ---

MISSING_KEY_MESSAGE = (
    "I'd love to draft your replies, but I couldn't find your Anthropic API key. 🤍 "
    "Pop it into the .env file next to the app (ANTHROPIC_API_KEY=…) — the same key "
    "I use for your content plan — then press D again."
)

MISSING_SDK_MESSAGE = (
    "The Anthropic library isn't installed yet. 🤍 Run "
    "`.venv/bin/pip install -r requirements.txt`, then press D again."
)

NO_EMAILS_MESSAGE = "Nothing in your inbox needs a reply right now. 🤍"

GENERIC_ERROR_MESSAGE = (
    "I hit a little snag drafting your replies. 🤍 Mind checking your internet "
    "and trying again in a bit?"
)


# === DATA MODEL ===

@dataclass(frozen=True)
class DraftedReply:
    """One ready-to-review reply: who it's to, about what, and the drafted text.

    `gmail_url` opens a prefilled Gmail compose window for this reply. Held only
    in memory for the panel to show; never written to disk or logged.
    """
    sender_name: str
    subject: str
    draft_body: str
    gmail_url: str


@dataclass(frozen=True)
class DraftBatch:
    """The result of one drafting pass: the drafts, plus a friendly status note.

    `message` is empty on a normal success (the panel shows the drafts and the
    caller speaks its own count line); otherwise it carries a gentle note to show
    instead (missing key, nothing to reply to, offline, etc.).
    """
    drafts: list[DraftedReply]
    message: str


# === GMAIL COMPOSE URL ===

def gmail_compose_url(to_email: str, subject: str, body: str) -> str:
    """Build a Gmail compose URL prefilled with the recipient, subject, and body.

    The subject is prefixed with "Re: " (unless it already is) so Gmail groups it
    with the original conversation as closely as a URL allows. urlencode escapes
    everything — including newlines in the body — so the link is always valid.
    """
    re_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    params = urlencode(
        {"view": "cm", "fs": "1", "to": to_email, "su": re_subject, "body": body}
    )
    return GMAIL_COMPOSE_BASE + params


# === DRAFTING ===

def _system_prompt() -> str:
    """Instructions that shape every reply: short, warm, professional, her voice."""
    return (
        "You are the email assistant living inside Camille's desktop buddy. Camille "
        "is a warm, professional digital marketer. You draft a reply she will read, "
        "maybe edit, and send HERSELF. You never send anything.\n\n"
        "Write the reply in HER voice: warm, clear, courteous, and genuinely human, "
        "like a real person writing to someone they respect. Never a corporate "
        "template. Rules:\n"
        "  - Return ONLY the reply body text. No subject line, no 'Draft:' label, "
        "no commentary.\n"
        "  - NEVER use an em dash (the long '—') or an en dash (the medium '–') as "
        "punctuation. They make writing read as AI-generated. Use a period, a "
        "comma, or a joining word like 'and' or 'so' instead. (Ordinary hyphens "
        "inside words, like 'day-to-day', are fine.)\n"
        "  - Sound human and polite, never stiff or robotic. Do NOT use generic "
        "corporate filler such as 'I hope this email finds you well', 'I am writing "
        "to', or 'Please do not hesitate to'. Say things plainly and kindly.\n"
        "  - Keep it short: roughly 2 to 5 sentences. Greet the person by their "
        "first name if you can tell it, and sign off as Camille.\n"
        "  - Match the email's intent (answer a question, accept or decline gently, "
        "thank, follow up). Be genuinely responsive to what they wrote.\n"
        "  - Do NOT invent facts, dates, prices, or commitments. If a specific "
        "detail is needed that you don't have, leave a short, clearly-bracketed "
        "placeholder like [confirm the date] for Camille to fill in."
    )


def _user_prompt(email: ReplyableEmail) -> str:
    """The single user turn: the one email's sender, subject, and body to reply to."""
    body = email.body or "(no body text — draft a brief, friendly reply from the subject.)"
    return (
        f"Draft a reply to this email.\n\n"
        f"From: {email.sender_name}\n"
        f"Subject: {email.subject}\n\n"
        f"Their message:\n{body}"
    )


def _draft_one(client, email: ReplyableEmail) -> str | None:
    """Make exactly one Haiku call to draft a reply; None if that call fails.

    Returns the drafted reply text, or None so the caller can skip just this one
    email and carry on with the rest rather than failing the whole batch.
    """
    import anthropic

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_system_prompt(),
            messages=[{"role": "user", "content": _user_prompt(email)}],
        )
    except anthropic.APIError:
        return None
    text = "".join(block.text for block in response.content if block.type == "text")
    return text.strip() or None


def draft_replies(use_mock: bool = False) -> DraftBatch:
    """Read today's important emails and draft a reply for each — never raising.

    With `use_mock` it returns sample drafts and makes NO Anthropic call and NO
    Gmail access. The live path reuses gmail_sync's read-only fetch + importance
    filter, then makes exactly one cheap Haiku call per approved email. Any
    expected problem (missing key, offline, an email whose draft call fails) is
    handled gently — a friendly `message`, or simply skipping that one email —
    so this can never crash the buddy.
    """
    if use_mock:
        return mock_batch()

    load_env_file()
    import os

    if not os.environ.get(API_KEY_VAR):
        return DraftBatch(drafts=[], message=MISSING_KEY_MESSAGE)

    # Imported lazily so the mock path never needs the SDK installed.
    try:
        import anthropic
    except ImportError:
        return DraftBatch(drafts=[], message=MISSING_SDK_MESSAGE)

    try:
        emails = fetch_important_for_reply()
    except GmailSyncError as error:
        return DraftBatch(drafts=[], message=str(error))

    if not emails:
        return DraftBatch(drafts=[], message=NO_EMAILS_MESSAGE)

    client = anthropic.Anthropic()
    drafts: list[DraftedReply] = []
    for email in emails:
        draft_body = _draft_one(client, email)  # exactly one API call per email
        if draft_body is None:
            continue  # skip just this one; keep the rest of the batch
        drafts.append(
            DraftedReply(
                sender_name=email.sender_name,
                subject=email.subject,
                draft_body=draft_body,
                gmail_url=gmail_compose_url(email.sender_email, email.subject, draft_body),
            )
        )

    if not drafts:
        # Emails were found but every draft call fell over — show a gentle note.
        return DraftBatch(drafts=[], message=GENERIC_ERROR_MESSAGE)
    return DraftBatch(drafts=drafts, message="")


# === MOCK (free, no API, no Gmail) ===

def mock_batch() -> DraftBatch:
    """Two realistic sample drafts for free testing of the panel and the wording.

    Mirrors exactly the shape the live path returns, so the panel and the Gmail
    button can be verified end-to-end without any Anthropic call or Gmail access.
    The senders, subjects, and Gmail addresses are invented.
    """
    samples = [
        (
            "Maya Lindqvist",
            "Coffee next week?",
            "maya.example@example.com",
            "Hi Maya! It really has been ages, and I'd love that. 🤍 Next week works "
            "well for me. Would [Tuesday or Thursday] afternoon suit you? And yes, the "
            "desktop buddy has been such a fun little rabbit hole, so I'll happily tell "
            "you all about it over coffee. Let me know what's good for you!\n\nWarmly,"
            "\nCamille",
        ),
        (
            "Jordan Reyes",
            "Quick question about your content workflow",
            "jordan.example@example.com",
            "Hi Jordan, thank you so much, that means a lot! 🤍 For planning my week I "
            "lean on a simple rhythm: a carousel on Monday, a video midweek, and a "
            "lighter post on Friday, all mapped out in one sitting so I'm not deciding "
            "day-to-day. Happy to share more if it would help. Consistency really is "
            "the whole game.\n\nWarmly,\nCamille",
        ),
    ]
    drafts = [
        DraftedReply(
            sender_name=name,
            subject=subject,
            draft_body=draft,
            gmail_url=gmail_compose_url(address, subject, draft),
        )
        for name, subject, address, draft in samples
    ]
    return DraftBatch(
        drafts=drafts,
        message="",
    )


# === STANDALONE CLI ===

def main() -> None:
    """Draft replies and print them — a quick, GUI-free way to check the wording.

    `--mock` uses free sample emails and makes NO Anthropic call and NO Gmail
    access. With no flag it reads today's important inbox emails (read-only) and
    makes one real Haiku call per email (the paid path). Nothing is ever sent.
    """
    parser = argparse.ArgumentParser(description="Draft replies to important emails.")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use free sample emails/drafts — no Anthropic call, no Gmail access.",
    )
    args = parser.parse_args()

    print("Drafting sample replies…" if args.mock else "Reading your inbox and drafting…")
    batch = draft_replies(use_mock=args.mock)

    if not batch.drafts:
        print(batch.message)
        return

    print(f"\nDrafted {len(batch.drafts)} repl{'y' if len(batch.drafts) == 1 else 'ies'} "
          f"(review and send each yourself):\n")
    for index, draft in enumerate(batch.drafts, start=1):
        print(f"── Draft {index} — to {draft.sender_name} · Re: {draft.subject} ──")
        print(draft.draft_body)
        print(f"\n[Open in Gmail] {draft.gmail_url}\n")


if __name__ == "__main__":
    main()
