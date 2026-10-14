import os
import random

DEFAULT_DELAY_MS = 1000
MAX_SUBMISSIONS = 10000
REQUEST_TIMEOUT = 30
PLAYWRIGHT_HEADLESS = True

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]

COMMON_EMAIL_DOMAINS = [
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "protonmail.com", "icloud.com", "mail.com", "aol.com",
    "zoho.com", "yandex.com",
]

# Google Forms field type integer mapping from FB_PUBLIC_LOAD_DATA_
GFORM_TYPE_MAP = {
    0: "short_text",
    1: "paragraph",
    2: "radio",
    3: "dropdown",
    4: "checkbox",
    5: "linear_scale",
    7: "grid_radio",
    8: "grid_checkbox",
    9: "date",
    10: "time",
    13: "file_upload",
}


def random_user_agent():
    return random.choice(USER_AGENTS)


# Auth state persistence
AUTH_STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'auth_states')
GOOGLE_AUTH_STATE_FILE = os.path.join(AUTH_STATE_DIR, 'google_auth_state.json')
