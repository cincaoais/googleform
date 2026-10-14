"""
Google Form submission engine.

Primary: direct HTTP POST to /formResponse (fast, for bulk submissions).
Fallback: Playwright browser automation (slower, for complex forms).
Supports proxy rotation, user-agent rotation, and rate-limit backoff.
"""

import os
import json
import uuid
import time
import queue
import random
import threading
import requests
from urllib.parse import urlencode

from .config import (
    DEFAULT_DELAY_MS, MAX_SUBMISSIONS, REQUEST_TIMEOUT,
    PLAYWRIGHT_HEADLESS, random_user_agent,
    AUTH_STATE_DIR, GOOGLE_AUTH_STATE_FILE,
)
from .fake_data import generate_value


class FormSubmitter:
    """Manages form submission jobs in background threads."""

    def __init__(self):
        self._jobs = {}          # job_id -> job_state dict
        self._stop_events = {}   # job_id -> threading.Event
        self._subscribers = {}   # job_id -> list[queue.Queue]
        self._lock = threading.Lock()
        self._login_status = "idle"
        self._login_error = ""
        if os.path.exists(GOOGLE_AUTH_STATE_FILE):
            self._login_status = "authenticated"

    # ============ GOOGLE LOGIN ============

    def start_google_login(self):
        """Start Google login flow in a background thread."""
        if self._login_status == "logging_in":
            return False
        self._login_status = "logging_in"
        self._login_error = ""
        thread = threading.Thread(target=self._do_google_login, daemon=True)
        thread.start()
        return True

    def get_login_status(self):
        """Return current Google login status."""
        return {
            "status": self._login_status,
            "error": self._login_error,
        }

    def clear_google_auth(self):
        """Remove saved Google auth state."""
        if os.path.exists(GOOGLE_AUTH_STATE_FILE):
            os.remove(GOOGLE_AUTH_STATE_FILE)
        self._login_status = "idle"

    def _do_google_login(self):
        """Open a visible browser for the user to sign in to Google."""
        try:
            from playwright.sync_api import sync_playwright

            os.makedirs(AUTH_STATE_DIR, exist_ok=True)

            with sync_playwright() as p:
                # Use system Chrome/Edge to avoid Google's automation detection
                browser = None
                for channel in ["chrome", "msedge", None]:
                    try:
                        launch_opts = {
                            "headless": False,
                            "args": ["--disable-blink-features=AutomationControlled"],
                        }
                        if channel:
                            launch_opts["channel"] = channel
                        browser = p.chromium.launch(**launch_opts)
                        break
                    except Exception:
                        if channel is None:
                            raise
                        continue

                context = browser.new_context()
                # Hide automation signals from Google
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                page = context.new_page()

                page.goto("https://accounts.google.com/")

                # Poll until user signs in or closes the browser
                signed_in = False
                auth_cookie_names = {'SID', 'SSID', 'HSID', 'APISID', 'SAPISID'}

                for _ in range(150):  # 5 minutes max
                    time.sleep(2)
                    try:
                        if page.is_closed():
                            break
                        cookies = context.cookies()
                        google_auth = [c for c in cookies
                                       if c['domain'].endswith('.google.com')
                                       and c['name'] in auth_cookie_names]
                        if len(google_auth) >= 2:
                            time.sleep(2)  # Let all cookies settle
                            signed_in = True
                            break
                    except Exception:
                        break

                if signed_in:
                    try:
                        context.storage_state(path=GOOGLE_AUTH_STATE_FILE)
                        self._login_status = "authenticated"
                    except Exception:
                        self._login_status = "error"
                        self._login_error = "Failed to save login state"
                else:
                    self._login_status = "error"
                    self._login_error = "Sign-in was not completed. Please try again."

                try:
                    browser.close()
                except Exception:
                    pass

        except Exception as e:
            self._login_status = "error"
            self._login_error = str(e)

    def start_job(self, config):
        """
        Start a new submission job.

        Args:
            config: dict with form_url, submit_url, fields, strategies,
                    count, delay_ms, use_playwright, proxies
                    mode: "google" (default) or "generic"

        Returns: job_id string
        """
        job_id = str(uuid.uuid4())[:8]

        count = min(int(config.get("count", 1)), MAX_SUBMISSIONS)
        delay_ms = int(config.get("delay_ms", DEFAULT_DELAY_MS))

        job_state = {
            "job_id": job_id,
            "mode": config.get("mode", "google"),
            "form_url": config.get("form_url", ""),
            "submit_url": config.get("submit_url", ""),
            "fields": config.get("fields", []),
            "strategies": config.get("strategies", {}),
            "total": count,
            "completed": 0,
            "failed": 0,
            "status": "running",
            "delay_ms": delay_ms,
            "use_playwright": config.get("use_playwright", False),
            "proxies": config.get("proxies", []),
            "hidden_fields": config.get("hidden_fields", {}),
            "submit_selector": config.get("submit_selector", ""),
        }

        stop_event = threading.Event()

        with self._lock:
            self._jobs[job_id] = job_state
            self._stop_events[job_id] = stop_event
            self._subscribers[job_id] = []

        thread = threading.Thread(
            target=self._run_loop,
            args=(job_id,),
            daemon=True,
        )
        thread.start()

        return job_id

    def stop_job(self, job_id):
        """Signal a running job to stop."""
        event = self._stop_events.get(job_id)
        if event:
            event.set()
            return True
        return False

    def subscribe(self, job_id):
        """Create and return a queue to receive SSE events for a job."""
        with self._lock:
            if job_id not in self._jobs:
                return None
            q = queue.Queue()
            self._subscribers.setdefault(job_id, []).append(q)
            return q

    def unsubscribe(self, job_id, q):
        """Remove a subscriber queue."""
        with self._lock:
            subs = self._subscribers.get(job_id, [])
            if q in subs:
                subs.remove(q)

    def _broadcast(self, job_id, data):
        """Send an event to all subscribers of a job."""
        with self._lock:
            for q in self._subscribers.get(job_id, []):
                try:
                    q.put_nowait(data)
                except queue.Full:
                    pass

    def _run_loop(self, job_id):
        """Main submission loop (runs in background thread)."""
        # Give SSE clients a moment to connect
        time.sleep(0.5)

        job = self._jobs[job_id]

        # Dispatch to generic mode if needed
        if job.get("mode") == "generic":
            return self._run_loop_generic(job_id)

        stop_event = self._stop_events[job_id]

        fields = job["fields"]
        strategies = job["strategies"]
        submit_url = job["submit_url"]
        total = job["total"]
        delay_ms = job["delay_ms"]
        use_playwright = job["use_playwright"]
        proxies = job["proxies"]
        form_url = job["form_url"]
        hidden_fields = job.get("hidden_fields", {})

        consecutive_failures = 0

        for i in range(total):
            if stop_event.is_set():
                job["status"] = "stopped"
                self._broadcast(job_id, {
                    "type": "stopped",
                    "completed": job["completed"],
                    "failed": job["failed"],
                    "total": total,
                })
                return

            # Generate form data for this submission
            form_data = self._build_form_data(fields, strategies, i)

            # Merge hidden fields (fvv, pageHistory, fbzx, etc.)
            for k, v in hidden_fields.items():
                if k not in form_data:
                    form_data[k] = v

            # Choose proxy
            proxy = None
            if proxies:
                proxy = proxies[i % len(proxies)]

            # Submit
            success = False
            error_msg = ""

            if use_playwright:
                success, error_msg = self._submit_playwright(form_url, form_data, fields, proxy)
            else:
                success, error_msg = self._submit_http_post(submit_url, form_data, form_url, proxy)
                # Fallback to playwright on auth failure or repeated failures
                if not success and ("401" in error_msg or consecutive_failures >= 3):
                    success, error_msg = self._submit_playwright(form_url, form_data, fields, proxy)

            if success:
                job["completed"] += 1
                consecutive_failures = 0
                # Include entry answers for log display
                answers = {k: v for k, v in form_data.items()
                           if k.startswith("entry.")}
                self._broadcast(job_id, {
                    "type": "success",
                    "index": i + 1,
                    "answers": answers,
                })
            else:
                job["failed"] += 1
                consecutive_failures += 1
                self._broadcast(job_id, {
                    "type": "error",
                    "index": i + 1,
                    "message": error_msg,
                })

            # Progress update
            self._broadcast(job_id, {
                "type": "progress",
                "completed": job["completed"],
                "failed": job["failed"],
                "total": total,
            })

            # Rate limit backoff
            actual_delay = delay_ms
            if consecutive_failures >= 2:
                actual_delay = min(delay_ms * (2 ** consecutive_failures), 30000)

            if i < total - 1:
                time.sleep(actual_delay / 1000.0)

        # Done
        job["status"] = "completed"
        self._broadcast(job_id, {
            "type": "complete",
            "completed": job["completed"],
            "failed": job["failed"],
            "total": total,
        })

    def _build_form_data(self, fields, strategies, submission_index):
        """
        Generate the complete form data dict for one submission.

        Returns: dict mapping entry IDs to values.
        Handles special cases for date/time fields.
        """
        form_data = {}

        for field in fields:
            entry_id = field.get("entry_id", "")
            ft = field.get("field_type", "")

            if ft == "file_upload":
                continue

            strategy = strategies.get(entry_id, {"strategy": "random"})
            value = generate_value(field, strategy, submission_index)

            # Handle special field types
            if ft == "date" and isinstance(value, str) and "-" in value:
                parts = value.split("-")
                if len(parts) == 3:
                    base_id = entry_id
                    form_data[base_id + "_year"] = parts[0]
                    form_data[base_id + "_month"] = str(int(parts[1]))
                    form_data[base_id + "_day"] = str(int(parts[2]))
                    continue

            if ft == "time" and isinstance(value, str) and ":" in value:
                parts = value.split(":")
                if len(parts) == 2:
                    base_id = entry_id
                    form_data[base_id + "_hour"] = str(int(parts[0]))
                    form_data[base_id + "_minute"] = str(int(parts[1]))
                    continue

            if ft == "checkbox" and isinstance(value, list):
                # Multiple values for same key — store as list
                form_data[entry_id] = value
                continue

            form_data[entry_id] = value

        return form_data

    def _submit_http_post(self, submit_url, form_data, form_url, proxy=None):
        """
        Submit via direct HTTP POST to /formResponse.

        Returns: (success: bool, error_message: str)
        """
        try:
            # Build POST body (handle multiple values for checkboxes)
            post_pairs = []
            for key, value in form_data.items():
                if isinstance(value, list):
                    for v in value:
                        post_pairs.append((key, v))
                else:
                    post_pairs.append((key, value))

            headers = {
                "User-Agent": random_user_agent(),
                "Referer": form_url,
                "Origin": "https://docs.google.com",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }

            # Load auth cookies if available
            auth_cookies = self._get_google_cookies()
            if auth_cookies:
                headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in auth_cookies.items())

            proxies_dict = None
            if proxy:
                proxies_dict = {"http": proxy, "https": proxy}

            response = requests.post(
                submit_url,
                data=post_pairs,
                headers=headers,
                proxies=proxies_dict,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            # Check for success — Google Forms returns 200 on success
            if response.status_code == 200:
                return True, ""

            if response.status_code == 429:
                return False, "Rate limited (429). Slowing down."

            # 400 usually means bad entry IDs or missing required fields
            if response.status_code == 400:
                return False, f"HTTP 400 — form data rejected. Check entry IDs. URL: {submit_url}"

            return False, f"HTTP {response.status_code} from {submit_url}"

        except requests.exceptions.ProxyError:
            return False, f"Proxy connection failed: {proxy}"
        except requests.exceptions.Timeout:
            return False, "Request timed out"
        except requests.exceptions.RequestException as e:
            return False, f"Request error: {str(e)}"

    def _submit_playwright(self, form_url, form_data, fields, proxy=None):
        """
        Fallback: fill and submit using Playwright browser automation.

        Returns: (success: bool, error_message: str)
        """
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                launch_args = {
                    "headless": PLAYWRIGHT_HEADLESS,
                    "args": ["--disable-blink-features=AutomationControlled"],
                }

                browser_context_args = {
                    "user_agent": random_user_agent(),
                }

                if proxy:
                    browser_context_args["proxy"] = {"server": proxy}

                # Load auth state if available
                if os.path.exists(GOOGLE_AUTH_STATE_FILE):
                    browser_context_args["storage_state"] = GOOGLE_AUTH_STATE_FILE

                browser = p.chromium.launch(**launch_args)
                context = browser.new_context(**browser_context_args)
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                page = context.new_page()

                try:
                    page.goto(form_url, wait_until="networkidle", timeout=30000)

                    # Handle Google Forms email consent checkbox if present
                    # (appears when form has "Collect verified email" enabled)
                    self._handle_email_consent(page)

                    # Fill each field
                    for field in fields:
                        entry_id = field.get("entry_id", "")
                        ft = field.get("field_type", "")

                        if ft == "file_upload":
                            continue

                        value = form_data.get(entry_id)
                        if value is None:
                            # Check for date/time split fields
                            if ft == "date":
                                value = "-".join([
                                    form_data.get(entry_id + "_year", "2025"),
                                    form_data.get(entry_id + "_month", "1").zfill(2),
                                    form_data.get(entry_id + "_day", "1").zfill(2),
                                ])
                            elif ft == "time":
                                value = ":".join([
                                    form_data.get(entry_id + "_hour", "12").zfill(2),
                                    form_data.get(entry_id + "_minute", "0").zfill(2),
                                ])
                            else:
                                continue

                        self._fill_field_playwright(page, field, value)

                    # Navigate through multi-page forms (click Next buttons)
                    prev_url = page.url
                    stuck_count = 0
                    for _ in range(20):  # max 20 pages
                        page.wait_for_timeout(1000)

                        # Check if Submit button is visible
                        submit_btn = self._find_form_button(page, ['submit', 'hantar', 'send', 'kirim', 'enviar'])
                        if submit_btn:
                            break

                        # Otherwise look for Next button and click it
                        next_btn = self._find_form_button(page, ['next', 'seterusnya', 'berikutnya', 'siguiente'])
                        if next_btn:
                            next_btn.click()
                            page.wait_for_timeout(2000)

                            # Check if page actually advanced
                            # Look for Back button as indicator of page change
                            back_btn = self._find_form_button(page, ['back', 'kembali', 'previous', 'anterior'])
                            current_url = page.url
                            if current_url == prev_url and not back_btn:
                                # Page didn't advance — validation likely failed
                                stuck_count += 1
                                if stuck_count >= 3:
                                    break  # Give up after 3 failed attempts
                                # Try re-filling visible fields more aggressively
                                page.wait_for_timeout(500)
                            else:
                                stuck_count = 0
                                prev_url = current_url

                            # Fill any fields on the current page
                            for field in fields:
                                entry_id = field.get("entry_id", "")
                                ft = field.get("field_type", "")
                                if ft == "file_upload":
                                    continue
                                value = form_data.get(entry_id)
                                if value is None:
                                    if ft == "date":
                                        value = "-".join([
                                            form_data.get(entry_id + "_year", "2025"),
                                            form_data.get(entry_id + "_month", "1").zfill(2),
                                            form_data.get(entry_id + "_day", "1").zfill(2),
                                        ])
                                    elif ft == "time":
                                        value = ":".join([
                                            form_data.get(entry_id + "_hour", "12").zfill(2),
                                            form_data.get(entry_id + "_minute", "0").zfill(2),
                                        ])
                                    else:
                                        continue
                                self._fill_field_playwright(page, field, value)
                        else:
                            # No Next or Submit found
                            break

                    if submit_btn:
                        submit_btn.click()
                        page.wait_for_timeout(3000)

                        # Check for confirmation
                        if "FormConfirmation" in page.url or page.query_selector(
                            '.freebirdFormviewerViewResponseConfirmationMessage'
                        ):
                            return True, ""

                        return True, ""
                    else:
                        # Collect visible button texts for debugging
                        btns_debug = []
                        for btn in page.query_selector_all('[role="button"], button'):
                            try:
                                if btn.is_visible():
                                    btns_debug.append(btn.inner_text().strip()[:30])
                            except Exception:
                                pass
                        # Check for validation errors
                        validation_errors = []
                        for err_el in page.query_selector_all('[role="alert"]'):
                            try:
                                err_text = err_el.inner_text().strip()
                                if err_text:
                                    validation_errors.append(err_text[:50])
                            except Exception:
                                pass
                        title = page.title() or ""
                        error_detail = (
                            f"Submit button not found. "
                            f"Page: {page.url} | Title: {title} | "
                            f"Buttons found: {btns_debug}"
                        )
                        if validation_errors:
                            error_detail += f" | Validation errors: {validation_errors}"
                        if stuck_count >= 3:
                            error_detail += " | Form stuck: required fields may not be filling correctly"
                        return False, error_detail

                finally:
                    browser.close()

        except Exception as e:
            return False, f"Playwright error: {str(e)}"

    def _find_form_button(self, page, text_matches):
        """Find a visible Google Forms button matching any of the given text labels."""
        # Try jsname selectors first (most reliable for Google Forms)
        if 'submit' in text_matches or 'hantar' in text_matches or 'send' in text_matches:
            try:
                btn = page.query_selector('div[jsname="M2UYVd"]')
                if btn and btn.is_visible():
                    return btn
            except Exception:
                pass
        if 'next' in text_matches or 'seterusnya' in text_matches:
            try:
                btn = page.query_selector('div[jsname="OCpkoe"]')
                if btn and btn.is_visible():
                    return btn
            except Exception:
                pass

        # Try class-based selectors for Google Forms
        if 'submit' in text_matches or 'hantar' in text_matches:
            try:
                btn = page.query_selector('.freebirdFormviewerViewNavigationSubmitButton')
                if btn and btn.is_visible():
                    return btn
            except Exception:
                pass

        # Try Playwright locator API (supports :has-text reliably)
        for text in text_matches:
            try:
                locator = page.locator(f'[role="button"]:has-text("{text}")')
                if locator.count() > 0 and locator.first.is_visible():
                    return locator.first.element_handle()
            except Exception:
                pass
            try:
                locator = page.locator(f'button:has-text("{text}")')
                if locator.count() > 0 and locator.first.is_visible():
                    return locator.first.element_handle()
            except Exception:
                pass

        # Fallback: scan all role="button" and button elements
        try:
            for btn in page.query_selector_all('[role="button"], button'):
                if not btn.is_visible():
                    continue
                text = (btn.inner_text() or "").strip().lower()
                if any(t in text for t in text_matches):
                    return btn
        except Exception:
            pass

        return None

    def _fill_field_playwright(self, page, field, value):
        """Fill a single field in the browser."""
        entry_id = field.get("entry_id", "")
        ft = field.get("field_type", "")

        # Skip synthetic email field — handled by Google auth + consent checkbox
        if field.get("_is_email") or entry_id == "emailAddress":
            return

        entry_num = entry_id.replace("entry.", "")

        try:
            # Find the question container scoped to this entry
            container = page.query_selector(f'[data-params*="{entry_num}"]')

            if ft in ("short_text", "paragraph"):
                selector = f'input[name="{entry_id}"], textarea[name="{entry_id}"]'
                el = page.query_selector(selector)
                if el:
                    el.fill(str(value))
                else:
                    # Try aria-label based selector
                    label = field.get("label", "")
                    if label:
                        el = page.query_selector(f'input[aria-label="{label}"]')
                        if el:
                            el.fill(str(value))

            elif ft == "radio":
                if not container:
                    return
                # Try clicking by data-value within the question container
                option_el = container.query_selector(f'[data-value="{value}"]')
                if option_el:
                    option_el.click()
                else:
                    # Try role="radio" elements by text match
                    for r in container.query_selector_all('[role="radio"]'):
                        r_text = (r.inner_text() or "").strip()
                        if r_text == value or value in r_text:
                            r.click()
                            break

            elif ft == "checkbox":
                if not container:
                    return
                values = value if isinstance(value, list) else [value]
                for v in values:
                    # Try data-answer-value within container
                    cb = container.query_selector(f'[data-answer-value="{v}"]')
                    if cb:
                        cb.click()
                        continue
                    # Try role="checkbox" by text match
                    for cb_el in container.query_selector_all('[role="checkbox"]'):
                        cb_text = (cb_el.inner_text() or "").strip()
                        if cb_text == v or v in cb_text:
                            cb_el.click()
                            break

            elif ft == "dropdown":
                if not container:
                    return
                # Click dropdown, then select option
                dropdown = container.query_selector('[role="listbox"]')
                if dropdown:
                    dropdown.click()
                    page.wait_for_timeout(500)
                    # Options appear in a global overlay, search page-wide
                    for opt in page.query_selector_all('[role="option"]'):
                        opt_text = (opt.inner_text() or "").strip()
                        if opt_text == value:
                            opt.click()
                            break

            elif ft == "linear_scale":
                if not container:
                    return
                scale_el = container.query_selector(f'[data-value="{value}"]')
                if scale_el:
                    scale_el.click()
                else:
                    # Try role="radio" for linear scales (they use radio role)
                    for r in container.query_selector_all('[role="radio"]'):
                        r_val = r.get_attribute('data-value') or (r.inner_text() or "").strip()
                        if str(value) == str(r_val):
                            r.click()
                            break

            elif ft in ("grid_radio", "grid_checkbox"):
                if not container:
                    return
                # Grid questions: each row has its own entry ID
                # The container for this specific row's entry
                row_el = container.query_selector(f'[data-value="{value}"]')
                if row_el:
                    row_el.click()
                else:
                    for r in container.query_selector_all('[role="radio"], [role="checkbox"]'):
                        r_val = r.get_attribute('data-value') or (r.inner_text() or "").strip()
                        if str(value) == str(r_val):
                            r.click()
                            break

            elif ft == "date":
                # Try filling date input directly
                date_input = page.query_selector(f'input[name="{entry_id}"][type="date"]')
                if date_input:
                    date_input.fill(str(value))
                elif container:
                    # Split into individual fields
                    parts = str(value).split("-")
                    if len(parts) == 3:
                        year_input = container.query_selector('input[aria-label*="Year"], input[aria-label*="year"]')
                        month_input = container.query_selector('input[aria-label*="Month"], input[aria-label*="month"]')
                        day_input = container.query_selector('input[aria-label*="Day"], input[aria-label*="day"]')
                        if day_input:
                            day_input.fill(parts[2])
                        if month_input:
                            month_input.fill(parts[1])
                        if year_input:
                            year_input.fill(parts[0])

            elif ft == "time":
                parts = str(value).split(":")
                if len(parts) == 2 and container:
                    hour_input = container.query_selector('input[aria-label*="Hour"], input[aria-label*="hour"]')
                    minute_input = container.query_selector('input[aria-label*="Minute"], input[aria-label*="minute"]')
                    if hour_input:
                        hour_input.fill(parts[0])
                    if minute_input:
                        minute_input.fill(parts[1])

        except Exception:
            pass  # Skip fields that can't be filled

    def _handle_email_consent(self, page):
        """Handle Google Forms email consent section.

        When a form has 'Collect verified email addresses' enabled,
        Google shows a consent checkbox that says 'Record [email] as the
        email to be included with my response'. This must be checked
        before the form can be submitted or navigated past page 1.
        """
        try:
            # Look for the email collection consent checkbox
            # It's typically an unchecked checkbox with email-related text
            consent_selectors = [
                # The checkbox input for email consent
                'input[name="emailReceipt"][type="checkbox"]',
                # Consent checkbox by aria-label
                '[role="checkbox"][aria-label*="email"]',
                '[role="checkbox"][aria-label*="Email"]',
            ]
            for sel in consent_selectors:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    # Check if it's already checked
                    checked = el.get_attribute('aria-checked') or el.get_attribute('checked')
                    if checked not in ('true', 'checked', True):
                        el.click()
                    return

            # Fallback: look for any checkbox near email-related text on the page
            # Google Forms wraps the consent in a container with identifiable structure
            for checkbox in page.query_selector_all('[role="checkbox"]'):
                try:
                    if not checkbox.is_visible():
                        continue
                    # Check parent/nearby text for email mention
                    parent = checkbox.evaluate_handle('el => el.closest("[data-params]") || el.parentElement?.parentElement')
                    parent_text = parent.evaluate('el => el ? el.innerText : ""') if parent else ""
                    if 'email' in parent_text.lower() or 'record' in parent_text.lower():
                        checked = checkbox.get_attribute('aria-checked')
                        if checked != 'true':
                            checkbox.click()
                        return
                except Exception:
                    continue

            # Also try: Google Forms sometimes uses a toggle/switch for email consent
            email_toggle = page.query_selector('.freebirdFormviewerViewItemsEmailCollectionItem [role="checkbox"]')
            if email_toggle and email_toggle.is_visible():
                checked = email_toggle.get_attribute('aria-checked')
                if checked != 'true':
                    email_toggle.click()

        except Exception:
            pass  # Email consent not present or already handled

    def _get_google_cookies(self):
        """Extract cookies from saved Playwright auth state for HTTP requests."""
        if not os.path.exists(GOOGLE_AUTH_STATE_FILE):
            return {}
        try:
            with open(GOOGLE_AUTH_STATE_FILE, 'r') as f:
                state = json.load(f)
            cookies = {}
            for cookie in state.get('cookies', []):
                if '.google.com' in cookie.get('domain', ''):
                    cookies[cookie['name']] = cookie['value']
            return cookies
        except (json.JSONDecodeError, IOError):
            return {}

    # ============ GENERIC WEB FORM METHODS ============

    def _run_loop_generic(self, job_id):
        """Submission loop for generic web forms (Playwright only)."""
        job = self._jobs[job_id]
        stop_event = self._stop_events[job_id]

        fields = job["fields"]
        strategies = job["strategies"]
        total = job["total"]
        delay_ms = job["delay_ms"]
        form_url = job["form_url"]
        proxies = job["proxies"]
        submit_selector = job.get("submit_selector", "")

        consecutive_failures = 0

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                launch_args = {"headless": PLAYWRIGHT_HEADLESS}
                browser = p.chromium.launch(**launch_args)

                for i in range(total):
                    if stop_event.is_set():
                        job["status"] = "stopped"
                        self._broadcast(job_id, {
                            "type": "stopped",
                            "completed": job["completed"],
                            "failed": job["failed"],
                            "total": total,
                        })
                        browser.close()
                        return

                    success = False
                    error_msg = ""

                    try:
                        # New context per submission for clean state
                        context_args = {"user_agent": random_user_agent()}
                        proxy = None
                        if proxies:
                            proxy = proxies[i % len(proxies)]
                            context_args["proxy"] = {"server": proxy}

                        context = browser.new_context(**context_args)
                        page = context.new_page()

                        page.goto(form_url, wait_until="networkidle", timeout=30000)

                        # Generate and fill form data
                        form_data = self._build_generic_form_data(fields, strategies, i)

                        for field in fields:
                            field_id = field.get("field_id", "")
                            ft = field.get("field_type", "")
                            if ft == "file_upload":
                                continue
                            value = form_data.get(field_id)
                            if value is not None:
                                self._fill_generic_field(page, field, value)

                        # Click submit
                        submitted = self._click_submit_button(page, submit_selector)
                        if submitted:
                            # Wait for response
                            page.wait_for_timeout(2000)
                            success = True
                        else:
                            error_msg = "Submit button not found"

                        context.close()

                    except Exception as e:
                        error_msg = f"Playwright error: {str(e)}"
                        try:
                            context.close()
                        except Exception:
                            pass

                    if success:
                        job["completed"] += 1
                        consecutive_failures = 0
                        answers = {f.get("field_id", ""): form_data.get(f.get("field_id", ""), "")
                                   for f in fields if f.get("field_type") != "file_upload"}
                        self._broadcast(job_id, {
                            "type": "success",
                            "index": i + 1,
                            "answers": answers,
                        })
                    else:
                        job["failed"] += 1
                        consecutive_failures += 1
                        self._broadcast(job_id, {
                            "type": "error",
                            "index": i + 1,
                            "message": error_msg,
                        })

                    self._broadcast(job_id, {
                        "type": "progress",
                        "completed": job["completed"],
                        "failed": job["failed"],
                        "total": total,
                    })

                    actual_delay = delay_ms
                    if consecutive_failures >= 2:
                        actual_delay = min(delay_ms * (2 ** consecutive_failures), 30000)

                    if i < total - 1:
                        time.sleep(actual_delay / 1000.0)

                browser.close()

        except Exception as e:
            job["failed"] += 1
            self._broadcast(job_id, {
                "type": "error",
                "index": 0,
                "message": f"Browser launch error: {str(e)}",
            })

        job["status"] = "completed"
        self._broadcast(job_id, {
            "type": "complete",
            "completed": job["completed"],
            "failed": job["failed"],
            "total": total,
        })

    def _build_generic_form_data(self, fields, strategies, submission_index):
        """Generate form data for a generic web form submission."""
        form_data = {}

        for field in fields:
            field_id = field.get("field_id", "")
            ft = field.get("field_type", "")

            if ft == "file_upload":
                continue

            strategy = strategies.get(field_id, {"strategy": "random"})
            value = generate_value(field, strategy, submission_index)

            if ft == "checkbox" and isinstance(value, list):
                form_data[field_id] = value
                continue

            form_data[field_id] = value

        return form_data

    def _fill_generic_field(self, page, field, value):
        """Fill a single field in a generic web form using CSS selectors."""
        selector = field.get("selector", "")
        ft = field.get("field_type", "")
        if not selector:
            return

        try:
            if ft in ("short_text", "paragraph"):
                el = page.query_selector(selector)
                if el:
                    el.click()
                    el.fill(str(value))

            elif ft == "radio":
                # Find the radio with matching label/value in the group
                name = field.get("name", "")
                if name:
                    radios = page.query_selector_all(f'input[name="{name}"]')
                    for radio in radios:
                        radio_id = radio.get_attribute("id") or ""
                        radio_value = radio.get_attribute("value") or ""
                        # Match by value attribute
                        if radio_value == value:
                            radio.click()
                            return
                        # Match by associated label text
                        if radio_id:
                            label = page.query_selector(f'label[for="{radio_id}"]')
                            if label and label.inner_text().strip() == value:
                                radio.click()
                                return
                    # Fallback: click first radio if no match
                    if radios:
                        radios[0].click()

            elif ft == "checkbox":
                values = value if isinstance(value, list) else [value]
                name = field.get("name", "")
                if name:
                    checkboxes = page.query_selector_all(f'input[name="{name}"]')
                    for cb in checkboxes:
                        cb_id = cb.get_attribute("id") or ""
                        cb_value = cb.get_attribute("value") or ""
                        cb_label_text = ""
                        if cb_id:
                            lbl = page.query_selector(f'label[for="{cb_id}"]')
                            if lbl:
                                cb_label_text = lbl.inner_text().strip()
                        if cb_value in values or cb_label_text in values:
                            cb.click()

            elif ft == "dropdown":
                el = page.query_selector(selector)
                if el:
                    # Try select_option by label, then by value
                    try:
                        el.select_option(label=str(value))
                    except Exception:
                        try:
                            el.select_option(value=str(value))
                        except Exception:
                            el.select_option(index=1)

            elif ft == "date":
                el = page.query_selector(selector)
                if el:
                    el.fill(str(value))

            elif ft == "time":
                el = page.query_selector(selector)
                if el:
                    el.fill(str(value))

        except Exception:
            pass

    def _click_submit_button(self, page, custom_selector=""):
        """Find and click the submit button on a generic form."""
        # 1. User-provided custom selector
        if custom_selector:
            try:
                btn = page.query_selector(custom_selector)
                if btn:
                    btn.click()
                    return True
            except Exception:
                pass

        # 2. Standard submit elements
        for sel in [
            'button[type="submit"]',
            'input[type="submit"]',
        ]:
            btn = page.query_selector(sel)
            if btn and self._is_element_visible(btn):
                btn.click()
                return True

        # 3. Buttons with submit-like text
        submit_texts = ["submit", "send", "save", "go", "ok", "hantar", "next", "continue"]
        buttons = page.query_selector_all("button, input[type='button'], a.btn")
        for btn in buttons:
            if not self._is_element_visible(btn):
                continue
            text = btn.inner_text().strip().lower() if btn.evaluate("el => el.tagName") != "INPUT" else (btn.get_attribute("value") or "").lower()
            if any(st in text for st in submit_texts):
                btn.click()
                return True

        # 4. Last button in form
        form_buttons = page.query_selector_all("form button")
        if form_buttons:
            last_btn = form_buttons[-1]
            if self._is_element_visible(last_btn):
                last_btn.click()
                return True

        return False

    def _is_element_visible(self, element):
        """Check if a Playwright element is visible."""
        try:
            return element.evaluate("""el => {
                if (el.offsetWidth === 0 && el.offsetHeight === 0) return false;
                let style = window.getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden';
            }""")
        except Exception:
            return False


# Singleton instance used by views
submitter_instance = FormSubmitter()
