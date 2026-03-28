"""
Realistic fake data generation for Google Form fields.

Uses embedded name/city/country lists — no external Faker dependency.
Label-based heuristics detect what kind of data a text field expects.
"""

import random
import string
from datetime import datetime, timedelta
from .config import COMMON_EMAIL_DOMAINS

# --- Name Data ---
FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Christopher", "Karen", "Charles", "Lisa", "Daniel", "Nancy",
    "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
    "Steven", "Dorothy", "Andrew", "Kimberly", "Paul", "Emily", "Joshua", "Donna",
    "Kenneth", "Michelle", "Kevin", "Carol", "Brian", "Amanda", "George", "Melissa",
    "Timothy", "Deborah", "Ronald", "Stephanie", "Edward", "Rebecca", "Jason", "Sharon",
    "Jeffrey", "Laura", "Ryan", "Cynthia", "Jacob", "Kathleen", "Gary", "Amy",
    "Nicholas", "Angela", "Eric", "Shirley", "Jonathan", "Anna", "Stephen", "Brenda",
    "Larry", "Pamela", "Justin", "Emma", "Scott", "Nicole", "Brandon", "Helen",
    "Benjamin", "Samantha", "Samuel", "Katherine", "Raymond", "Christine", "Gregory", "Debra",
    "Frank", "Rachel", "Alexander", "Carolyn", "Patrick", "Janet", "Jack", "Catherine",
    "Dennis", "Maria", "Jerry", "Heather", "Tyler", "Diane", "Aaron", "Ruth",
    "Jose", "Julie", "Adam", "Olivia", "Nathan", "Joyce", "Henry", "Virginia",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill",
    "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell",
    "Mitchell", "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
    "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales",
    "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson",
    "Bailey", "Reed", "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward",
    "Richardson", "Watson", "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray",
    "Mendoza", "Ruiz", "Hughes", "Price", "Alvarez", "Castillo", "Sanders", "Patel",
    "Myers", "Long", "Ross", "Foster", "Jimenez", "Powell",
]

CITIES = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia",
    "San Antonio", "San Diego", "Dallas", "San Jose", "Austin", "Jacksonville",
    "Fort Worth", "Columbus", "Charlotte", "Indianapolis", "San Francisco", "Seattle",
    "Denver", "Nashville", "Oklahoma City", "Washington", "El Paso", "Boston",
    "Portland", "Las Vegas", "Memphis", "Louisville", "Baltimore", "Milwaukee",
    "Albuquerque", "Tucson", "Fresno", "Sacramento", "Mesa", "Atlanta", "Omaha",
    "Miami", "Tulsa", "Tampa", "Minneapolis", "Cleveland", "Detroit", "Pittsburgh",
    "Orlando", "St. Louis", "Cincinnati", "Honolulu", "Toronto", "London",
]

COUNTRIES = [
    "United States", "Canada", "United Kingdom", "Australia", "Germany", "France",
    "Japan", "South Korea", "Brazil", "India", "Mexico", "Italy", "Spain", "Netherlands",
    "Sweden", "Norway", "Denmark", "Switzerland", "Singapore", "New Zealand",
    "Ireland", "Portugal", "Belgium", "Austria", "Finland", "Poland", "Thailand",
    "Malaysia", "Indonesia", "Philippines",
]

LOREM_WORDS = [
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "it",
    "for", "not", "on", "with", "he", "as", "you", "do", "at", "this",
    "but", "his", "by", "from", "they", "we", "say", "her", "she", "or",
    "an", "will", "my", "one", "all", "would", "there", "their", "what",
    "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
    "when", "make", "can", "like", "time", "just", "know", "take", "people",
    "into", "year", "your", "good", "some", "could", "them", "see", "other",
    "than", "then", "now", "look", "only", "come", "its", "over", "think",
    "also", "back", "after", "use", "two", "how", "our", "work", "first",
    "well", "way", "even", "new", "want", "because", "any", "these", "give",
    "day", "most", "us", "great", "important", "project", "team", "support",
    "system", "service", "experience", "quality", "process", "information",
]

FEEDBACK_SENTENCES = [
    "This is a great experience overall.",
    "I found the process straightforward and easy to follow.",
    "Everything was handled efficiently and on time.",
    "I appreciate the attention to detail shown here.",
    "The service met my expectations and was professional.",
    "I have no complaints about the process.",
    "Overall I am satisfied with the experience.",
    "The team was helpful and responsive throughout.",
    "I would recommend this to others.",
    "The quality of work exceeded my expectations.",
    "There is room for improvement in communication.",
    "I think the overall approach is solid.",
    "Good work by the team on this project.",
    "I look forward to seeing future improvements.",
    "The process was smooth from start to finish.",
]

STREET_NAMES = [
    "Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine Rd", "Elm St",
    "Washington Blvd", "Park Ave", "Lake Dr", "Hill Rd", "Valley Way",
    "Sunset Blvd", "River Rd", "Forest Ave", "Spring St", "Church St",
    "Market St", "Center St", "School Rd", "Union Ave",
]

COMPANY_NAMES = [
    "Acme Corp", "Globex Inc", "Soylent Corp", "Initech", "Umbrella Corp",
    "Stark Industries", "Wayne Enterprises", "Cyberdyne Systems", "Aperture Science",
    "Massive Dynamic", "Oscorp", "LexCorp", "Tyrell Corp", "Weyland-Yutani",
    "InGen", "OCP", "Veidt Enterprises", "Gekko & Co", "Sterling Cooper",
    "Dunder Mifflin",
]


CHINESE_SURNAMES = [
    "tan", "lim", "lee", "chen", "wong", "ng", "ong", "goh", "chan", "chua",
    "teh", "yap", "koh", "low", "sim", "ho", "lau", "teo", "foo", "chong",
    "yeo", "lai", "chew", "heng", "soh", "tay", "phua", "ang", "loh", "khoo",
    "yeoh", "chia", "leong", "choo", "wee", "yong", "kwok", "pang", "seah",
    "quek", "hoe", "koo", "phang", "kok", "chai", "hung", "chin", "chng",
    "beh", "gan", "saw", "ooi", "png", "soo", "mah", "tham", "yew", "san",
    "sia", "kek", "tok", "lew", "ngo", "cheah", "chang", "tang", "choong",
    "loke", "teoh", "liow", "chung", "hew", "kam", "lye", "sew", "bong",
    "chu", "fong", "seng", "ting", "loo", "mai", "cheong", "lam", "mok",
    "chieng", "tiong", "hii", "sie", "yii", "ling", "lu", "kong", "tong",
]

CHINESE_INITIALS = [
    "ah", "bh", "ch", "ck", "cl", "cs", "cy", "dh", "dk", "dy",
    "eh", "ey", "fh", "fy", "gh", "hk", "hl", "hm", "hn", "hp",
    "hs", "hw", "hy", "hz", "jc", "jh", "jk", "jl", "jm", "jn",
    "js", "jw", "jy", "kc", "kh", "kk", "kl", "km", "kn", "ks",
    "kw", "ky", "lh", "lk", "lm", "ln", "ly", "mh", "mk", "ml",
    "mn", "ms", "my", "nh", "nk", "pk", "pl", "py", "sc", "sh",
    "sk", "sl", "sm", "sn", "sp", "ss", "sw", "sy", "tc", "th",
    "tk", "tl", "tm", "ts", "tw", "ty", "wc", "wh", "wk", "wl",
    "wm", "wn", "ws", "wy", "xh", "xy", "yc", "yh", "yk", "yl",
    "ym", "yn", "ys", "yw", "yy", "zh", "zk", "zl", "zm", "zy",
]


def generate_value(field, strategy, submission_index=0):
    """
    Generate a value for a form field based on the configured strategy.

    Args:
        field: dict with field_type, label, options, etc.
        strategy: dict with strategy type and config
        submission_index: current submission number (for sequential)

    Returns:
        str for single-value fields, list[str] for checkbox fields
    """
    strat_type = strategy.get("strategy", "random")

    if strat_type == "fixed":
        return strategy.get("fixed_value", "")

    if strat_type == "from_list":
        value_list = strategy.get("value_list", [])
        if not value_list:
            return ""
        return value_list[submission_index % len(value_list)]

    if strat_type == "template":
        template = strategy.get("template", "")
        if template:
            return _render_template(template)
        return ""

    if strat_type == "pick_options":
        picked = strategy.get("picked_options", [])
        if not picked:
            return _generate_random(field)
        field_type = field.get("field_type", "")
        if field_type == "checkbox":
            count = random.randint(1, len(picked))
            return random.sample(picked, count)
        else:
            return random.choice(picked)

    # Default: random
    return _generate_random(field)


def _render_template(template):
    """
    Render a template string with placeholders.

    Supported placeholders:
        {chinese_surname}     → random Chinese surname (e.g. "tan", "lim", "chen")
        {initials}            → random 2-letter initials (e.g. "ch", "ws", "yk")
        {choice:a,b,c}        → random pick from comma-separated values
        {number:MIN-MAX}      → random integer in range (e.g. {number:1-99})
        {letter}              → single random lowercase letter
        {letters:N}           → N random lowercase letters (e.g. {letters:3})
        {digit}               → single random digit 0-9
        {digits:N}            → N random digits
        {first_name}          → random English first name (lowercase)
        {last_name}           → random English last name (lowercase)
        {name}                → "FirstName LastName"
        {email}               → random email address
    """
    import re

    def replacer(match):
        token = match.group(1)

        if token == "chinese_surname":
            return random.choice(CHINESE_SURNAMES)

        if token == "initials":
            return random.choice(CHINESE_INITIALS)

        if token.startswith("choice:"):
            options = token[7:].split(",")
            return random.choice([o.strip() for o in options if o.strip()])

        if token.startswith("number:"):
            range_str = token[7:]
            parts = range_str.split("-")
            if len(parts) == 2:
                lo, hi = int(parts[0]), int(parts[1])
                return str(random.randint(lo, hi))
            return "0"

        if token == "letter":
            return random.choice(string.ascii_lowercase)

        if token.startswith("letters:"):
            n = int(token[8:])
            return "".join(random.choices(string.ascii_lowercase, k=n))

        if token == "digit":
            return str(random.randint(0, 9))

        if token.startswith("digits:"):
            n = int(token[7:])
            return "".join(str(random.randint(0, 9)) for _ in range(n))

        if token == "first_name":
            return random.choice(FIRST_NAMES).lower()

        if token == "last_name":
            return random.choice(LAST_NAMES).lower()

        if token == "name":
            return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"

        if token == "email":
            return _generate_email()

        return match.group(0)  # leave unknown placeholders as-is

    return re.sub(r"\{([^}]+)\}", replacer, template)


def _generate_random(field):
    """Generate random data appropriate for the field type."""
    # Special handling for the synthetic email field
    if field.get("_is_email"):
        return _generate_email()

    ft = field.get("field_type", "short_text")

    if ft == "short_text":
        return _generate_text_by_label(field.get("label", ""))

    if ft == "paragraph":
        return _generate_paragraph(field.get("label", ""))

    if ft in ("radio", "dropdown"):
        options = field.get("options", [])
        if options:
            return random.choice(options)
        return ""

    if ft == "checkbox":
        options = field.get("options", [])
        if options:
            k = random.randint(1, max(1, len(options)))
            return random.sample(options, k)
        return []

    if ft == "linear_scale":
        lo = field.get("scale_min", 1)
        hi = field.get("scale_max", 5)
        return str(random.randint(lo, hi))

    if ft == "date":
        return _generate_random_date()

    if ft == "time":
        return _generate_random_time()

    if ft in ("grid_radio", "grid_checkbox"):
        options = field.get("options", [])
        if options:
            if ft == "grid_checkbox":
                k = random.randint(1, max(1, len(options)))
                return random.sample(options, k)
            return random.choice(options)
        return ""

    # Fallback
    return _generate_lorem(3, 8)


def _generate_text_by_label(label):
    """Use label heuristics to generate appropriate text data."""
    label_lower = label.lower()

    if any(kw in label_lower for kw in ["full name", "your name", "nama", "name"]):
        return _generate_name()

    if any(kw in label_lower for kw in ["email", "e-mail", "emel"]):
        return _generate_email()

    if any(kw in label_lower for kw in ["phone", "tel", "mobile", "contact number", "nombor"]):
        return _generate_phone()

    if any(kw in label_lower for kw in ["age", "umur"]):
        return str(random.randint(18, 65))

    if any(kw in label_lower for kw in ["address", "alamat", "street"]):
        return _generate_address()

    if any(kw in label_lower for kw in ["city", "town", "bandar"]):
        return random.choice(CITIES)

    if any(kw in label_lower for kw in ["country", "negara", "nation"]):
        return random.choice(COUNTRIES)

    if any(kw in label_lower for kw in ["company", "organization", "organisation", "syarikat"]):
        return random.choice(COMPANY_NAMES)

    if any(kw in label_lower for kw in ["date", "tarikh", "birthday", "dob"]):
        return _generate_random_date()

    if any(kw in label_lower for kw in ["website", "url", "link"]):
        first = random.choice(FIRST_NAMES).lower()
        return f"https://www.{first}{random.randint(1, 999)}.com"

    if any(kw in label_lower for kw in ["comment", "feedback", "message", "suggestion",
                                         "reason", "explain", "describe", "maklum balas"]):
        return random.choice(FEEDBACK_SENTENCES)

    if any(kw in label_lower for kw in ["number", "quantity", "amount", "nombor", "bilangan"]):
        return str(random.randint(1, 100))

    # Default: generate a short phrase
    return _generate_lorem(2, 5)


def _generate_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _generate_email():
    first = random.choice(FIRST_NAMES).lower()
    last = random.choice(LAST_NAMES).lower()
    num = random.randint(1, 999)
    domain = random.choice(COMMON_EMAIL_DOMAINS)
    separator = random.choice([".", "_", ""])
    return f"{first}{separator}{last}{num}@{domain}"


def _generate_phone():
    area = random.randint(200, 999)
    mid = random.randint(100, 999)
    end = random.randint(1000, 9999)
    return f"({area}) {mid}-{end}"


def _generate_address():
    num = random.randint(1, 9999)
    street = random.choice(STREET_NAMES)
    city = random.choice(CITIES)
    return f"{num} {street}, {city}"


def _generate_paragraph(label):
    """Generate 2-4 sentences."""
    label_lower = label.lower()
    if any(kw in label_lower for kw in ["feedback", "comment", "suggestion", "maklum balas"]):
        sentences = random.sample(FEEDBACK_SENTENCES, min(3, len(FEEDBACK_SENTENCES)))
        return " ".join(sentences)

    count = random.randint(2, 4)
    sentences = []
    for _ in range(count):
        sentences.append(_generate_lorem(5, 15).capitalize() + ".")
    return " ".join(sentences)


def _generate_lorem(min_words, max_words):
    """Generate a random sentence from lorem-ish words."""
    count = random.randint(min_words, max_words)
    words = [random.choice(LOREM_WORDS) for _ in range(count)]
    words[0] = words[0].capitalize()
    return " ".join(words)


def _generate_random_date():
    """Generate a random date in the past 2 years. Format: YYYY-MM-DD."""
    days_back = random.randint(0, 730)
    date = datetime.now() - timedelta(days=days_back)
    return date.strftime("%Y-%m-%d")


def _generate_random_time():
    """Generate a random time. Format: HH:MM."""
    hour = random.randint(0, 23)
    minute = random.choice([0, 15, 30, 45])
    return f"{hour:02d}:{minute:02d}"
