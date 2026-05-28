"""The buddy's warm, gentle messages.

Kept separate from the app logic so the messages are easy to read and edit
without touching code. The tone is intentionally soft and caring — a kind
friend checking in, never aggressive "hustle/grind" positivity and never
nagging or bossy. Each line is short enough to sit comfortably inside a small
speech bubble.

Messages are grouped by kind for readability, then combined into the single
MOTIVATIONAL_QUOTES tuple the app picks from at random — so she mixes
emotional support and practical self-care freely.
"""

# === MOTIVATIONAL QUOTES ===

# Emotional support: reassurance, encouragement, permission to go easy.
EMOTIONAL_SUPPORT_QUOTES: tuple[str, ...] = (
    "You're doing better than you think. 🤍",
    "One small thing at a time, okay?",
    "Proud of you for showing up today.",
    "Take a breath. You've got this.",
    "It's okay to rest. You've earned it.",
    "Hey — you're allowed to go slow today.",
    "Whatever you finished today counts. Really.",
    "You don't have to do it all at once.",
    "Be a little gentle with yourself, okay?",
    "I believe in you — quietly, but a lot. 🤍",
    "Small steps are still steps forward.",
    "You're not behind. You're right on time.",
    "Maybe some water? For me? 🤍",
    "It's okay if today was just okay.",
    "You're carrying a lot. I see you.",
    "Rest isn't lazy — it's part of the work.",
    "One thing done is enough to be proud of.",
    "You showed up, and that matters.",
    "Go easy on yourself today.",
    "Progress, not perfect. Always.",
    "You're safe to take your time here.",
    "Stretch a little? You've been so focused.",
    "Tiny wins count too. Promise. 🤍",
    "However today goes, I'm glad you're here.",
    "You've made it through every hard day so far.",
)

# Practical self-care: gentle nudges to drink, stretch, blink, eat, breathe.
PRACTICAL_SELF_CARE_QUOTES: tuple[str, ...] = (
    "Hey, have you had some water lately? 🤍",
    "Time for a little stretch — your body will thank you!",
    "Maybe look away from the screen for a sec? Rest your eyes. 👀",
    "Stand up and wiggle around for a minute, okay?",
    "Don't forget to drink some water 💧",
    "Roll your shoulders back — you've been hunched a while 🤍",
    "Take a deep breath. In... and out.",
    "How about a quick walk to the kitchen and back?",
    "Blink a few times — give your eyes a little break.",
    "Snack check! Have you eaten something today?",
    "Unclench your jaw and drop your shoulders 🤍",
    "A little screen break sounds nice right about now.",
    "Posture check — sit up tall, gently. 🤍",
    "Maybe refill your water before it runs out? 💧",
    "Wiggle your fingers and give your wrists a rest.",
    "If you're cold, go grab a cozy layer. 🤍",
)

# Combined pool the app draws from at random.
MOTIVATIONAL_QUOTES: tuple[str, ...] = (
    EMOTIONAL_SUPPORT_QUOTES + PRACTICAL_SELF_CARE_QUOTES
)
