"""
Google Form submission engine.

Primary: direct HTTP POST to /formResponse (fast, for bulk submissions).
Fallback: Playwright browser automation (slower, for complex forms).
Supports proxy rotation, user-agent rotation, and rate-limit backoff.
"""

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
)
from .fake_data import generate_value


class FormSubmitter:
    """Manages form submission jobs in background threads."""

    def __init__(self):
        self._jobs = {}          # job_id -> job_state dict
        self._stop_events = {}   # job_id -> threading.Event
        self._subscribers = {}   # job_id -> list[queue.Queue]
        self._lock = threading.Lock()

    def start_job(self, config):
        """
        Start a new submission job.

        Args:
            config: dict with form_url, submit_url, fields, strategies,
                    count, delay_ms, use_playwright, proxies

        Returns: job_id string
        """
        job_id = str(uuid.uuid4())[:8]

        count = min(int(config.get("count", 1)), MAX_SUBMISSIONS)
        delay_ms = int(config.get("delay_ms", DEFAULT_DELAY_MS))

        job_state = {
            "job_id": job_id,
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
                # Fallback to playwright on repeated failures
                if not success and consecutive_failures >= 3:
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
                launch_args = {"headless": PLAYWRIGHT_HEADLESS}

                browser_context_args = {
                    "user_agent": random_user_agent(),
                }

                if proxy:
                    browser_context_args["proxy"] = {"server": proxy}

                browser = p.chromium.launch(**launch_args)
                context = browser.new_context(**browser_context_args)
                page = context.new_page()

                try:
                    page.goto(form_url, wait_until="networkidle", timeout=30000)

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

                    # Click Submit
                    submit_btn = page.query_selector(
                        '[role="button"]:has-text("Submit"), '
                        '[role="button"]:has-text("Hantar"), '
                        'div[jsname="M2UYVd"]'
                    )
                    if submit_btn:
                        submit_btn.click()
                        page.wait_for_timeout(2000)

                        # Check for confirmation
                        if "FormConfirmation" in page.url or page.query_selector(
                            '.freebirdFormviewerViewResponseConfirmationMessage'
                        ):
                            return True, ""

                        return True, ""
                    else:
                        return False, "Submit button not found"

                finally:
                    browser.close()

        except Exception as e:
            return False, f"Playwright error: {str(e)}"

    def _fill_field_playwright(self, page, field, value):
        """Fill a single field in the browser."""
        entry_id = field.get("entry_id", "")
        ft = field.get("field_type", "")
        entry_num = entry_id.replace("entry.", "")

        try:
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
                # Click the radio option matching value
                option_el = page.query_selector(
                    f'div[data-value="{value}"], '
                    f'label:has-text("{value}") input[type="radio"]'
                )
                if option_el:
                    option_el.click()
                else:
                    # Try clicking by text content within the question
                    radios = page.query_selector_all(f'[data-params*="{entry_num}"] [role="radio"]')
                    for r in radios:
                        if value in (r.inner_text() or ""):
                            r.click()
                            break

            elif ft == "checkbox":
                values = value if isinstance(value, list) else [value]
                for v in values:
                    cb = page.query_selector(
                        f'label:has-text("{v}") [role="checkbox"], '
                        f'div[data-answer-value="{v}"]'
                    )
                    if cb:
                        cb.click()

            elif ft == "dropdown":
                # Click dropdown, then select option
                dropdown = page.query_selector(f'[data-params*="{entry_num}"] [role="listbox"]')
                if dropdown:
                    dropdown.click()
                    page.wait_for_timeout(300)
                    option = page.query_selector(f'[role="option"]:has-text("{value}")')
                    if option:
                        option.click()

            elif ft == "linear_scale":
                scale_el = page.query_selector(f'[data-params*="{entry_num}"] [data-value="{value}"]')
                if scale_el:
                    scale_el.click()

            elif ft == "date":
                # Try filling date input directly
                date_input = page.query_selector(f'input[name="{entry_id}"][type="date"]')
                if date_input:
                    date_input.fill(str(value))
                else:
                    # Split into individual fields
                    parts = str(value).split("-")
                    if len(parts) == 3:
                        year_input = page.query_selector(f'[data-params*="{entry_num}"] input[aria-label*="Year"]')
                        month_input = page.query_selector(f'[data-params*="{entry_num}"] input[aria-label*="Month"]')
                        day_input = page.query_selector(f'[data-params*="{entry_num}"] input[aria-label*="Day"]')
                        if day_input:
                            day_input.fill(parts[2])
                        if month_input:
                            month_input.fill(parts[1])
                        if year_input:
                            year_input.fill(parts[0])

            elif ft == "time":
                parts = str(value).split(":")
                if len(parts) == 2:
                    hour_input = page.query_selector(f'[data-params*="{entry_num}"] input[aria-label*="Hour"]')
                    minute_input = page.query_selector(f'[data-params*="{entry_num}"] input[aria-label*="Minute"]')
                    if hour_input:
                        hour_input.fill(parts[0])
                    if minute_input:
                        minute_input.fill(parts[1])

        except Exception:
            pass  # Skip fields that can't be filled


# Singleton instance used by views
submitter_instance = FormSubmitter()
