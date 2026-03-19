"""
Google Form parser using Playwright.

Primary strategy: parse FB_PUBLIC_LOAD_DATA_ embedded JavaScript variable.
Fallback strategy: parse the rendered DOM via Playwright selectors.
"""

import re
import json
from playwright.sync_api import sync_playwright
from .config import PLAYWRIGHT_HEADLESS, GFORM_TYPE_MAP


def parse_form(url):
    """
    Parse a Google Form URL and return its structure.

    Returns dict:
        {
            "form_id": str,
            "form_url": str,
            "title": str,
            "description": str,
            "fields": [FormField dict, ...],
            "total_pages": int,
            "requires_signin": bool,
            "submit_url": str,
        }
    """
    url = _normalize_url(url)
    form_id = _extract_form_id(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            page_source = page.content()

            requires_signin = _detect_requires_signin(page_source, page.url)

            # Try FB_PUBLIC_LOAD_DATA_ first
            fields, section_count, collects_email = _parse_fb_public_load_data(page_source)

            # Fallback to DOM parsing
            if not fields:
                fields = _parse_dom(page)
                section_count = 0
                collects_email = False

            # If form collects email, add it as a synthetic field at the top
            if collects_email:
                fields.insert(0, {
                    "entry_id": "emailAddress",
                    "label": "Email Address",
                    "description": "This form collects your email address.",
                    "field_type": "short_text",
                    "required": True,
                    "options": [],
                    "other_option": False,
                    "_is_email": True,
                })

            title, description = _extract_title_description(page_source, page)

            # Extract the actual submit URL from the page
            submit_url = _extract_submit_url(page_source, page, form_id)

            # Extract hidden fields (fvv, pageHistory, etc.)
            hidden_fields = _extract_hidden_fields(page_source, page)

            # Fix pageHistory for multi-section forms
            if section_count > 0:
                page_indices = ",".join(str(i) for i in range(section_count + 1))
                hidden_fields["pageHistory"] = page_indices

            total_pages = section_count + 1

            return {
                "form_id": form_id,
                "form_url": url,
                "title": title,
                "description": description,
                "fields": fields,
                "total_pages": total_pages,
                "requires_signin": requires_signin,
                "submit_url": submit_url,
                "hidden_fields": hidden_fields,
                "collects_email": collects_email,
            }
        finally:
            browser.close()


def _normalize_url(url):
    """Ensure URL ends with /viewform."""
    url = url.strip()
    # Remove query string for normalization, then re-add
    if "?" in url:
        base, query = url.split("?", 1)
    else:
        base, query = url, ""

    if not base.endswith("/viewform"):
        base = base.rstrip("/")
        if base.endswith("/edit"):
            base = base[:-5] + "/viewform"
        elif not base.endswith("/viewform"):
            base += "/viewform"

    return base + ("?" + query if query else "")


def _extract_form_id(url):
    """Extract form ID from URL."""
    # Pattern: /forms/d/e/{ID}/ or /forms/d/{ID}/
    match = re.search(r"/forms/d/(?:e/)?([a-zA-Z0-9_-]+)", url)
    if match:
        return match.group(1)
    raise ValueError(f"Could not extract form ID from URL: {url}")


def _extract_submit_url(page_source, page, form_id):
    """
    Extract the actual form submission URL from the page.
    This handles both /d/e/{ID}/ and /d/{ID}/ URL patterns correctly.
    """
    # Strategy 1: Find the form action attribute in HTML
    action_match = re.search(
        r'<form[^>]+action="(https://docs\.google\.com/forms/[^"]*formResponse[^"]*)"',
        page_source
    )
    if action_match:
        return action_match.group(1)

    # Strategy 2: Look in FB_PUBLIC_LOAD_DATA_ for the form response URL
    fb_match = re.search(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>", page_source, re.DOTALL)
    if fb_match:
        try:
            data = json.loads(fb_match.group(1))
            # The form response URL is sometimes at data[14] or similar
            raw = json.dumps(data)
            url_match = re.search(
                r'(https://docs\.google\.com/forms/d/e/[a-zA-Z0-9_-]+/formResponse)',
                raw
            )
            if url_match:
                return url_match.group(1)
        except (json.JSONDecodeError, TypeError):
            pass

    # Strategy 3: Derive from the current page URL
    # If the page URL has /d/e/{id}/, use that directly
    page_url = page.url
    e_match = re.search(r'(https://docs\.google\.com/forms/d/e/[a-zA-Z0-9_-]+)', page_url)
    if e_match:
        return e_match.group(1) + "/formResponse"

    # Strategy 4: Derive from the page source — look for any /d/e/ pattern
    e_src_match = re.search(
        r'(https://docs\.google\.com/forms/d/e/[a-zA-Z0-9_-]+)',
        page_source
    )
    if e_src_match:
        return e_src_match.group(1) + "/formResponse"

    # Fallback: construct from form_id (may not work for /d/{EDIT_ID}/ URLs)
    return f"https://docs.google.com/forms/d/e/{form_id}/formResponse"


def _extract_hidden_fields(page_source, page):
    """
    Extract hidden form fields that Google Forms expects in POST submissions.
    These include fvv, draftResponse, pageHistory, fbzx, etc.
    """
    hidden = {}

    # Extract from the page using Playwright
    try:
        hidden_inputs = page.query_selector_all('form input[type="hidden"]')
        for inp in hidden_inputs:
            name = inp.get_attribute("name")
            value = inp.get_attribute("value")
            if name and not name.startswith("entry."):
                hidden[name] = value or ""
    except Exception:
        pass

    # Ensure essential fields are present
    if "fvv" not in hidden:
        hidden["fvv"] = "1"
    if "pageHistory" not in hidden:
        hidden["pageHistory"] = "0"

    # Extract fbzx from page source if not found
    if "fbzx" not in hidden:
        fbzx_match = re.search(r'"fbzx"\s*:\s*"([^"]+)"', page_source)
        if fbzx_match:
            hidden["fbzx"] = fbzx_match.group(1)

    return hidden


def _detect_requires_signin(page_source, current_url):
    """Check if the form requires Google sign-in."""
    signin_indicators = [
        "accounts.google.com/signin",
        "accounts.google.com/v3/signin",
        "accounts.google.com/ServiceLogin",
        "data-email-required",
        "freebirdFormviewerViewNavigationPasswordRequired",
    ]
    for indicator in signin_indicators:
        if indicator in page_source or indicator in current_url:
            return True
    return False


def _extract_title_description(page_source, page):
    """Extract form title and description."""
    title = ""
    description = ""

    # Try from FB_PUBLIC_LOAD_DATA_
    match = re.search(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>", page_source, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, list) and len(data) > 1:
                info = data[1]
                if isinstance(info, list) and len(info) > 0:
                    title = info[8] if len(info) > 8 and info[8] else ""
                    description = info[0] if len(info) > 0 and isinstance(info[0], str) else ""
        except (json.JSONDecodeError, IndexError, TypeError):
            pass

    # Fallback to DOM
    if not title:
        try:
            el = page.query_selector('[data-document-title]')
            if el:
                title = el.get_attribute('data-document-title') or ""
        except Exception:
            pass

    if not title:
        try:
            el = page.query_selector('.freebirdFormviewerViewHeaderTitle')
            if el:
                title = el.inner_text()
        except Exception:
            pass

    if not description:
        try:
            el = page.query_selector('.freebirdFormviewerViewHeaderDescription')
            if el:
                description = el.inner_text()
        except Exception:
            pass

    return title, description


def _parse_fb_public_load_data(page_source):
    """
    Parse the FB_PUBLIC_LOAD_DATA_ JavaScript variable embedded in the page.

    This variable contains the complete form structure as a nested JSON array.

    Returns: (fields, section_count, collects_email)
        - fields: list of FormField dicts, or None if parsing fails
        - section_count: number of section headers (page breaks) found
        - collects_email: whether the form has "Collect email addresses" enabled
    """
    match = re.search(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>", page_source, re.DOTALL)
    if not match:
        return None, 0, False

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None, 0, False

    if not isinstance(data, list) or len(data) < 2:
        return None, 0, False

    # Detect "Collect email addresses" setting
    # data[1][10][3] == 2 means "collect responder input email"
    # data[1][10][3] == 1 means "collect verified email" (requires sign-in)
    collects_email = False
    try:
        email_setting = data[1][10][3]
        if email_setting in (1, 2):
            collects_email = True
    except (IndexError, TypeError):
        pass

    try:
        # data[1][1] contains the array of question items
        questions_data = data[1][1]
        if not isinstance(questions_data, list):
            return None, 0, collects_email
    except (IndexError, TypeError):
        return None, 0, collects_email

    fields = []
    section_count = 0

    for item in questions_data:
        try:
            # Type 8 = section header / page break
            if isinstance(item, list) and len(item) > 3 and item[3] == 8:
                section_count += 1
                continue

            parsed = _parse_fb_question_item(item)
            if parsed:
                if isinstance(parsed, list):
                    fields.extend(parsed)
                else:
                    fields.append(parsed)
        except (IndexError, TypeError, KeyError):
            continue

    return (fields if fields else None), section_count, collects_email


def _parse_fb_question_item(item):
    """Parse a single question item from FB_PUBLIC_LOAD_DATA_."""
    if not isinstance(item, list) or len(item) < 4:
        return None

    label = item[1] if len(item) > 1 and isinstance(item[1], str) else ""
    description = item[2] if len(item) > 2 and isinstance(item[2], str) else ""
    type_int = item[3] if len(item) > 3 else None

    if type_int is None or type_int not in GFORM_TYPE_MAP:
        return None

    field_type = GFORM_TYPE_MAP[type_int]

    # Get answer containers from item[4]
    answer_containers = item[4] if len(item) > 4 and isinstance(item[4], list) else []

    if not answer_containers:
        return None

    # Handle grid types (multiple rows, each with its own entry ID)
    if field_type in ("grid_radio", "grid_checkbox"):
        return _parse_grid_field(item, label, field_type, answer_containers)

    # Standard single-answer fields
    container = answer_containers[0]
    if not isinstance(container, list) or len(container) < 1:
        return None

    entry_id = str(container[0]) if container[0] is not None else None
    if not entry_id:
        return None

    # Extract options (for choice types)
    options = []
    other_option = False
    if len(container) > 1 and isinstance(container[1], list):
        for opt in container[1]:
            if isinstance(opt, list) and len(opt) > 0 and isinstance(opt[0], str):
                options.append(opt[0])

    # Check for "Other" option
    if len(container) > 4 and container[4] is not None:
        # Some forms encode the "other" option availability here
        if isinstance(container[4], list):
            for sub in container[4]:
                if isinstance(sub, list) and len(sub) > 0:
                    other_option = True
                    break

    # Required flag
    required = False
    if len(container) > 2 and container[2]:
        required = bool(container[2])

    # Linear scale details
    scale_min = 1
    scale_max = 5
    low_label = ""
    high_label = ""
    if field_type == "linear_scale":
        if options:
            try:
                scale_min = int(options[0]) if options[0].isdigit() else 1
                scale_max = int(options[-1]) if options[-1].isdigit() else 5
            except (ValueError, IndexError):
                pass
        if len(container) > 3 and isinstance(container[3], list):
            labels = container[3]
            low_label = labels[0] if len(labels) > 0 and isinstance(labels[0], str) else ""
            high_label = labels[1] if len(labels) > 1 and isinstance(labels[1], str) else ""

    field = {
        "entry_id": f"entry.{entry_id}",
        "label": label,
        "description": description,
        "field_type": field_type,
        "required": required,
        "options": options,
        "other_option": other_option,
    }

    if field_type == "linear_scale":
        field["scale_min"] = scale_min
        field["scale_max"] = scale_max
        field["low_label"] = low_label
        field["high_label"] = high_label

    return field


def _parse_grid_field(item, label, field_type, answer_containers):
    """Parse a grid (radio or checkbox grid) field into multiple sub-fields."""
    fields = []

    # Extract column options from the first container
    column_options = []
    if answer_containers and isinstance(answer_containers[0], list):
        container = answer_containers[0]
        if len(container) > 1 and isinstance(container[1], list):
            for opt in container[1]:
                if isinstance(opt, list) and len(opt) > 0 and isinstance(opt[0], str):
                    column_options.append(opt[0])

    for container in answer_containers:
        if not isinstance(container, list) or len(container) < 1:
            continue

        entry_id = str(container[0]) if container[0] is not None else None
        if not entry_id:
            continue

        # Row label
        row_label = ""
        if len(container) > 3 and isinstance(container[3], list):
            row_labels = container[3]
            row_label = row_labels[0] if row_labels and isinstance(row_labels[0], str) else ""

        required = False
        if len(container) > 2 and container[2]:
            required = bool(container[2])

        fields.append({
            "entry_id": f"entry.{entry_id}",
            "label": f"{label} [{row_label}]" if row_label else label,
            "description": "",
            "field_type": field_type,
            "required": required,
            "options": column_options,
            "other_option": False,
        })

    return fields if fields else None


def _parse_dom(page):
    """
    Fallback: parse form fields from the rendered DOM using Playwright selectors.
    """
    fields = []

    # Try to find question containers via data-params attribute
    question_els = page.query_selector_all('[data-params]')

    for el in question_els:
        try:
            field = _parse_dom_question(page, el)
            if field:
                fields.append(field)
        except Exception:
            continue

    # If data-params approach didn't work, try alternative selectors
    if not fields:
        fields = _parse_dom_alternative(page)

    return fields if fields else []


def _parse_dom_question(page, el):
    """Parse a single question element from the DOM."""
    data_params = el.get_attribute('data-params')
    if not data_params:
        return None

    # data-params contains a percent-encoded JSON-like string
    # Format: %.@.[entry_id,...,field_type,...]
    entry_id = None
    field_type = "short_text"

    # Extract entry ID using regex
    entry_match = re.search(r'\[(\d{7,}),', data_params)
    if entry_match:
        entry_id = entry_match.group(1)

    if not entry_id:
        return None

    # Get label
    label = ""
    heading = el.query_selector('[role="heading"]')
    if heading:
        label = heading.inner_text().strip()
    if not label:
        label_el = el.query_selector('.freebirdFormviewerComponentsQuestionBaseTitle')
        if label_el:
            label = label_el.inner_text().strip()

    # Detect field type from DOM elements
    options = []
    if el.query_selector('[role="radiogroup"]') or el.query_selector('div[data-value]'):
        field_type = "radio"
        for opt_el in el.query_selector_all('[data-value]'):
            val = opt_el.get_attribute('data-value')
            if val:
                options.append(val)
    elif el.query_selector('[role="group"]') and el.query_selector('[role="checkbox"]'):
        field_type = "checkbox"
        for opt_el in el.query_selector_all('[role="checkbox"]'):
            label_el = opt_el.query_selector('.docssharedWizToggleLabeledPrimaryText')
            if label_el:
                options.append(label_el.inner_text().strip())
    elif el.query_selector('[role="listbox"]'):
        field_type = "dropdown"
        for opt_el in el.query_selector_all('[role="option"]'):
            text = opt_el.inner_text().strip()
            if text and text != "Choose":
                options.append(text)
    elif el.query_selector('textarea'):
        field_type = "paragraph"
    elif el.query_selector('input[type="date"]'):
        field_type = "date"
    elif el.query_selector('input[type="time"]'):
        field_type = "time"

    # Required detection
    required = False
    if el.query_selector('[aria-required="true"]'):
        required = True
    elif '*' in (el.query_selector('[role="heading"]') or el).inner_text():
        required = True

    return {
        "entry_id": f"entry.{entry_id}",
        "label": label,
        "description": "",
        "field_type": field_type,
        "required": required,
        "options": options,
        "other_option": False,
    }


def _parse_dom_alternative(page):
    """Alternative DOM parsing using broader selectors."""
    fields = []

    # Look for all input/textarea/select elements with entry.* names
    inputs = page.query_selector_all('input[name^="entry."], textarea[name^="entry."], select[name^="entry."]')
    seen_ids = set()

    for inp in inputs:
        name = inp.get_attribute('name')
        if not name or name in seen_ids:
            continue
        seen_ids.add(name)

        input_type = inp.get_attribute('type') or 'text'
        tag = inp.evaluate('el => el.tagName.toLowerCase()')

        if tag == 'textarea':
            field_type = 'paragraph'
        elif tag == 'select':
            field_type = 'dropdown'
        elif input_type == 'hidden':
            continue
        else:
            field_type = 'short_text'

        # Try to find the label
        label = ""
        aria_label = inp.get_attribute('aria-label')
        if aria_label:
            label = aria_label

        required = inp.get_attribute('required') is not None or inp.get_attribute('aria-required') == 'true'

        options = []
        if tag == 'select':
            for opt in inp.query_selector_all('option'):
                text = opt.inner_text().strip()
                if text:
                    options.append(text)

        fields.append({
            "entry_id": name,
            "label": label or name,
            "description": "",
            "field_type": field_type,
            "required": required,
            "options": options,
            "other_option": False,
        })

    return fields
