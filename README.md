# Form Auto-Filler

A local Django web app that reads a form, lets you choose how each field should be filled, and then submits it as many times as you set, with live progress in the browser.

It has two modes:

| Mode | Page | How it submits |
|------|------|----------------|
| **Google Forms** | `/` | Direct HTTP POST to `/formResponse` (fast). Can switch to Playwright browser automation instead. |
| **Web Forms** (any site) | `/generic/` | Playwright only: fills the fields with CSS selectors and clicks the submit button. |

> Only use this on forms you own or have permission to test. Bulk fake submissions to someone else's form can break their terms of service and spoil their data.

## Features

- **Form parsing**: Google Forms are read from the page's embedded `FB_PUBLIC_LOAD_DATA_`, with DOM parsing as a fallback. Handles multi-section forms, hidden fields (`fvv`, `pageHistory`, `fbzx`) and forms that collect email addresses.
- **Supported Google field types**: short answer, paragraph, multiple choice, dropdown, checkboxes, linear scale, multiple-choice grid, checkbox grid, date, time. File upload is detected but not filled.
- **Fill strategies per field** (see below), plus a sample-answer preview before you start.
- **Google sign-in** for forms that require it: opens a real Chrome/Edge window, you sign in by hand, and the session is saved to `auth_states/google_auth_state.json`.
- **Batch control**: up to 10,000 submissions per job, a delay between submissions, a stop button, and live progress/logs over Server-Sent Events.
- **Resilience**: rotates user agents; rotates proxies if you give it a list; after 2 failures in a row it waits longer each time (exponential backoff, up to 30 s). In HTTP mode, it switches to Playwright on a 401 error or after 3 failures in a row.

### Fill strategies

| Strategy | Field types | What it does |
|----------|-------------|--------------|
| Random | all | Text fields: guesses realistic data from the label (name, email, phone, address, …). Choice fields: picks a random option. |
| Fixed value | all | Always submits the exact value you type. |
| From list | text | Goes through your list of values in order, one per submission. |
| Template pattern | text | Builds a value from placeholders (below). Default for the email field. |
| Pick specific options | choice / scale | Random pick limited to the options you tick (checkboxes pick 1..N of them). |
| Weighted random (%) | choice / scale (Google mode only) | Radio/dropdown/scale: weighted pick. Checkboxes: each option has its own % chance. |

Template placeholders:

| Placeholder | Example output |
|-------------|----------------|
| `{first_name}` / `{last_name}` | `james` / `smith` (lowercase) |
| `{name}` | `James Smith` |
| `{email}` | random address at a common provider |
| `{chinese_surname}` | `tan`, `lim`, `chen` |
| `{initials}` | `ch`, `ws` |
| `{choice:a,b,c}` | one of `a`, `b`, `c` |
| `{number:1-99}` | integer in range |
| `{letter}` / `{letters:3}` | `k` / `qxe` |
| `{digit}` / `{digits:4}` | `7` / `0392` |

Example: `{first_name}{digits:3}@gmail.com` → `mary482@gmail.com`

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/cincaoais/googleform.git
cd googleform
```

### 2. Install Python

Install Python 3.13 from [python.org](https://www.python.org/downloads/).

If you have other projects on your local machine using a different Python version, it is recommended to use a virtual environment manager such as:

- [uv](https://docs.astral.sh/uv/) - `uv venv`, then activate it with `source .venv/bin/activate` (macOS/Linux) or `.venv\Scripts\activate` (Windows)
- [pyenv](https://github.com/pyenv/pyenv) - `pyenv install 3.13 && pyenv local 3.13`

### 3. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

Playwright needs its own browser download for parsing forms and for browser-mode submissions. Google sign-in uses your installed Chrome or Edge if it finds one, and falls back to Playwright's Chromium.

### 4. Run database migrations

```bash
python manage.py migrate
```

### 5. Start the development server

```bash
python manage.py runserver
```

The app will be available at [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Usage

1. Open `/` for Google Forms or `/generic/` for any other web form.
2. Paste the form URL and click **Analyze Form** / **Analyze Page**.
3. Choose a fill strategy for each field and check the sample preview.
4. Set the number of submissions and the delay. Optionally add proxies (`http://host:port`, one per line), tick browser simulation (Google mode), or enter a custom submit-button CSS selector (Web Forms mode).
5. If the form requires Google sign-in, click **Login to Google** and sign in in the window that opens.
6. Click **Start Submission**. Watch the progress bar and log, and click **Stop** at any time.

### Sharing over ngrok (optional)

`settings.py` already trusts `https://*.ngrok-free.dev` for CSRF, so you can run `ngrok http 8000` to share the app. Note that anyone with that URL can start jobs using your saved Google session.

## Configuration

Defaults are set in `formfiller/config.py`:

| Setting | Default | Meaning |
|---------|---------|---------|
| `DEFAULT_DELAY_MS` | `1000` | Delay between submissions if none is given |
| `MAX_SUBMISSIONS` | `10000` | Highest number of submissions allowed per job |
| `REQUEST_TIMEOUT` | `30` | HTTP timeout in seconds |
| `PLAYWRIGHT_HEADLESS` | `True` | Set to `False` to watch the browser while it parses and submits |

## API

All endpoints take and return JSON.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/parse/` | Parse a Google Form (`{"url": ...}`) |
| POST | `/api/submit/` | Start a Google Forms job, returns `job_id` |
| POST | `/api/generic/parse/` | Parse any web form |
| POST | `/api/generic/submit/` | Start a Web Forms job |
| GET | `/api/stream/<job_id>/` | SSE stream of `progress` / `success` / `error` / `complete` / `stopped` events |
| POST | `/api/stop/<job_id>/` | Stop a running job |
| POST | `/api/google/login/` | Open the Google sign-in window |
| GET | `/api/google/auth-status/` | Current sign-in status |
| POST | `/api/google/logout/` | Delete the saved Google session |

## Project Structure

```
mysite/                 Django project settings and root URLs
formfiller/
  form_parser.py        Google Forms parser (Playwright)
  generic_parser.py     Generic web form parser (Playwright)
  form_submitter.py     Job runner: HTTP/Playwright submission, Google login, SSE events
  fake_data.py          Fill strategies, templates, realistic fake data
  config.py             Defaults, user agents, field type map
  views.py, urls.py     Pages and JSON API
  templates/, static/   Bootstrap UI (index.html, generic.html, app.js, generic_app.js)
auth_states/            Saved Google session (git-ignored, created on first login)
```

## Limitations

- Jobs run in background threads and are kept in memory, so restarting the server loses running jobs.
- File upload fields are not supported.
- Weighted random is not offered in Web Forms mode.
- Web Forms mode cannot get past CAPTCHAs or login walls; the page warns you when it finds a login form.
- `DEBUG = True`, `ALLOWED_HOSTS = ['*']` and the API views skip CSRF checks. This is meant for local use only, not production.
