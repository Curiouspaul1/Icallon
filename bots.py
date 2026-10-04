"""Computer-controlled players for solo matches.

A bot is just a roster entry whose name starts with BOT_PREFIX. It has no
socket; events.py plays its turns for it. Everything in here is pure
logic (names, word choice, timing) so it can be tested without a server.
"""

import random

import utils

# Real users can't register a name starting with this (see connect()).
BOT_PREFIX = "🤖 "
BOT_NAMES = ["Ada", "Tunde", "Zara", "Kofi", "Mina", "Leo", "Ife", "Remy"]

# think: seconds a bot spends on each category (min, max).
# blank: chance it "can't think of" an answer for a category.
# When it's a bot's own turn, finishing forces everyone to submit, so
# "think" is also how much time the human gets on those rounds.
DIFFICULTY = {
    "easy": {"think": (6.0, 9.0), "blank": 0.35},
    "medium": {"think": (4.0, 6.5), "blank": 0.18},
    "hard": {"think": (3.0, 4.5), "blank": 0.06},
}
DEFAULT_DIFFICULTY = "medium"

# Letters with plenty of answers in every classic category. Solo games
# draw their rounds from these so nobody gets stuck on X or Q.
SOLO_LETTERS = "ABCDEFGHIJKLMNOPRSTW"

PLACES = {
    "a": ["Abuja", "Accra", "Athens", "Austria", "Argentina", "Amsterdam"],
    "b": ["Benin", "Brazil", "Berlin", "Bangkok", "Belgium", "Boston"],
    "c": ["Cairo", "Canada", "Chile", "Chicago", "Calabar", "Cuba"],
    "d": ["Dakar", "Denmark", "Dubai", "Dublin", "Delhi", "Durban"],
    "e": ["Egypt", "Enugu", "Ecuador", "Estonia", "Edinburgh", "Ethiopia"],
    "f": ["France", "Finland", "Fiji", "Florence", "Frankfurt", "Freetown"],
    "g": ["Ghana", "Germany", "Greece", "Geneva", "Gabon", "Glasgow"],
    "h": ["Havana", "Hungary", "Hamburg", "Helsinki", "Houston", "Haiti"],
    "i": ["Ibadan", "India", "Italy", "Ireland", "Istanbul", "Iceland"],
    "j": ["Japan", "Jamaica", "Jos", "Jordan", "Jakarta", "Johannesburg"],
    "k": ["Kenya", "Kano", "Kigali", "Kampala", "Kuwait", "Kyoto"],
    "l": ["Lagos", "London", "Lisbon", "Lima", "Libya", "Lome"],
    "m": ["Mali", "Mexico", "Madrid", "Mombasa", "Morocco", "Milan"],
    "n": ["Nigeria", "Nairobi", "Norway", "Nepal", "Niger", "Naples"],
    "o": ["Oslo", "Oman", "Ottawa", "Osaka", "Owerri", "Oxford"],
    "p": ["Paris", "Peru", "Poland", "Portugal", "Prague", "Pretoria"],
    "q": ["Qatar", "Quito", "Quebec"],
    "r": ["Rome", "Russia", "Rwanda", "Rabat", "Romania", "Riga"],
    "s": ["Spain", "Sweden", "Senegal", "Sokoto", "Sydney", "Seoul"],
    "t": ["Togo", "Tokyo", "Tunisia", "Turkey", "Toronto", "Tanzania"],
    "u": ["Uganda", "Ukraine", "Uruguay", "Uyo", "Utah"],
    "v": ["Vienna", "Venice", "Vietnam", "Venezuela", "Vancouver"],
    "w": ["Warri", "Wales", "Warsaw", "Windhoek", "Washington"],
    "x": ["Xiamen"],
    "y": ["Yemen", "Yola", "Yaounde", "York"],
    "z": ["Zambia", "Zaria", "Zimbabwe", "Zurich", "Zanzibar"],
}

THINGS = {
    "a": ["anchor", "apron", "arrow", "axe", "anvil", "album"],
    "b": ["basket", "bottle", "broom", "bucket", "button", "bell"],
    "c": ["candle", "chair", "clock", "comb", "cup", "curtain"],
    "d": ["desk", "drum", "door", "dish", "diary", "dice"],
    "e": ["envelope", "eraser", "engine", "easel", "earring"],
    "f": ["fan", "fork", "flute", "funnel", "flag", "fence"],
    "g": ["guitar", "glove", "gate", "glass", "globe", "glue"],
    "h": ["hammer", "hat", "helmet", "hook", "hose", "harp"],
    "i": ["iron", "ink", "inkwell", "ivory", "icebox"],
    "j": ["jar", "jacket", "jug", "jewel", "javelin"],
    "k": ["kettle", "key", "kite", "knife", "knob", "keg"],
    "l": ["ladder", "lamp", "lock", "lantern", "lens", "ladle"],
    "m": ["mirror", "map", "mat", "mug", "magnet", "mask"],
    "n": ["needle", "net", "napkin", "nail", "necklace", "notebook"],
    "o": ["oven", "oar", "organ", "ornament", "overcoat"],
    "p": ["pen", "pillow", "plate", "pot", "pencil", "purse"],
    "q": ["quilt", "quill", "quiver"],
    "r": ["radio", "rope", "ring", "ruler", "rug", "razor"],
    "s": ["spoon", "shoe", "soap", "saw", "scarf", "stool"],
    "t": ["table", "towel", "tray", "trumpet", "tent", "torch"],
    "u": ["umbrella", "urn", "utensil", "uniform"],
    "v": ["vase", "violin", "vest", "van", "veil"],
    "w": ["wallet", "watch", "wheel", "whistle", "wig", "wrench"],
    "x": ["xylophone"],
    "y": ["yarn", "yacht", "yoke"],
    "z": ["zipper", "zither"],
}


def _by_letter(words):
    index = {}
    for w in words:
        w = w.strip()
        if w and w[0].isalpha():
            index.setdefault(w[0].lower(), []).append(w)
    return index


# Names and animals come from the same sets the game validates against,
# so a bot's answer in those categories is always accepted.
_NAMES = _by_letter(sorted(n.title() for n in utils.name_set))
_ANIMALS = _by_letter(sorted(a.title() for a in utils.animal_set))
_SOURCES = {"Name": _NAMES, "Animal": _ANIMALS, "Place": PLACES, "Thing": THINGS}

# Bot places are known-good. Mark them valid up front so a bot's answer
# never costs a call to the online geocoder.
for _places in PLACES.values():
    for _p in _places:
        utils._place_cache[_p.strip().lower()] = True


def is_bot(name):
    return isinstance(name, str) and name.startswith(BOT_PREFIX.strip())


def make_bot_names(count):
    return [BOT_PREFIX + n for n in random.sample(BOT_NAMES, count)]


def pick_solo_letters(rounds):
    """One letter per round. Uses the friendly letters first and only
    reaches for the awkward ones if the game is long enough to need them."""
    rounds = max(1, min(26, rounds))
    pool = list(SOLO_LETTERS)
    random.shuffle(pool)
    if rounds > len(pool):
        rest = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in SOLO_LETTERS]
        random.shuffle(rest)
        pool += rest
    return "".join(sorted(pool[:rounds]))


def plan_answers(categories, letter, difficulty):
    """Decide a bot's whole round up front: for each category, what it
    will write and how many seconds into the round it finishes writing it.
    Returns [(category, word, ready_at_seconds), ...] in category order."""
    level = DIFFICULTY.get(difficulty, DIFFICULTY[DEFAULT_DIFFICULTY])
    key = letter.lower()
    plan = []
    clock = 0.0
    for category in categories:
        clock += random.uniform(*level["think"])
        options = _SOURCES.get(category, {}).get(key, [])
        # Unknown (custom) category, or nothing for this letter: leave blank.
        word = ""
        if options and random.random() >= level["blank"]:
            word = random.choice(options)
        plan.append((category, word, clock))
    return plan


def answers_ready(plan, elapsed):
    """What the bot has written down `elapsed` seconds into the round.
    Categories it hasn't reached yet are blank, exactly as for a human
    who gets cut off."""
    return {cat: (word if ready_at <= elapsed else "") for cat, word, ready_at in plan}
