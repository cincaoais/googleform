"""
Generic web form parser using Playwright.

Navigates to any URL, detects visible form fields (input, select, textarea),
and returns structured field data for auto-filling.
"""

import re
from playwright.sync_api import sync_playwright
from .config import PLAYWRIGHT_HEADLESS, random_user_agent


def parse_generic_form(url):
    """
    Parse any web page and extract form fields.

    Returns dict:
        {
            "page_url": str,
            "page_title": str,
            "fields": [GenericField, ...],
            "form_selector": str or None,
            "has_login": bool,
        }
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
        context = browser.new_context(user_agent=random_user_agent())
        page = context.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=30000)

            page_url = page.url
            page_title = page.title() or ""

            form_selector = _find_form_selector(page)
            has_login = _detect_login_page(page)
            fields = _extract_fields(page, form_selector)

            return {
                "page_url": page_url,
                "page_title": page_title,
                "fields": fields,
                "form_selector": form_selector,
                "has_login": has_login,
            }
        finally:
            browser.close()


def _find_form_selector(page):
    """Find the main <form> element's CSS selector, if any."""
    forms = page.query_selector_all("form")
    if not forms:
        return None

    # Prefer forms with visible input fields
    for i, form in enumerate(forms):
        inputs = form.query_selector_all("input, select, textarea")
        visible_inputs = [inp for inp in inputs if _is_visible(inp)]
        if visible_inputs:
            form_id = form.get_attribute("id")
            if form_id:
                return f"form#{form_id}"
            form_name = form.get_attribute("name")
            if form_name:
                return f'form[name="{form_name}"]'
            if len(forms) == 1:
                return "form"
            return f"form:nth-of-type({i + 1})"

    return "form"


def _extract_fields(page, form_selector):
    """Extract all visible form fields from the page."""
    scope = form_selector or "body"

    # Collect all input, select, textarea elements
    elements = page.query_selector_all(f"{scope} input, {scope} select, {scope} textarea")

    fields = []
    radio_groups = {}   # name -> field dict
    checkbox_groups = {}  # name -> field dict
    field_counter = 0

    for el in elements:
        if not _is_visible(el):
            continue

        tag = el.evaluate("el => el.tagName.toLowerCase()")
        input_type = (el.get_attribute("type") or "").lower()

        # Skip submit/reset/button/hidden/file inputs
        if tag == "input" and input_type in ("submit", "reset", "button", "hidden", "image", "file"):
            continue

        name = el.get_attribute("name") or ""
        id_attr = el.get_attribute("id") or ""
        placeholder = el.get_attribute("placeholder") or ""
        required = el.get_attribute("required") is not None
        label = _find_label(page, el, id_attr)

        # Handle radio buttons — group by name
        if tag == "input" and input_type == "radio":
            value = el.get_attribute("value") or ""
            option_label = _get_radio_checkbox_label(page, el) or value
            if name and name in radio_groups:
                radio_groups[name]["options"].append(option_label)
            else:
                field_id = f"gf_{field_counter}"
                field_counter += 1
                group = {
                    "field_id": field_id,
                    "selector": f'input[name="{name}"]' if name else _build_selector(el, id_attr),
                    "tag": "input",
                    "input_type": "radio",
                    "name": name,
                    "label": label or name,
                    "placeholder": "",
                    "required": required,
                    "options": [option_label],
                    "field_type": "radio",
                    "group_name": name,
                }
                if name:
                    radio_groups[name] = group
                fields.append(group)
            continue

        # Handle checkboxes — group by name
        if tag == "input" and input_type == "checkbox":
            value = el.get_attribute("value") or ""
            option_label = _get_radio_checkbox_label(page, el) or value
            if name and name in checkbox_groups:
                checkbox_groups[name]["options"].append(option_label)
            else:
                field_id = f"gf_{field_counter}"
                field_counter += 1
                group = {
                    "field_id": field_id,
                    "selector": f'input[name="{name}"]' if name else _build_selector(el, id_attr),
                    "tag": "input",
                    "input_type": "checkbox",
                    "name": name,
                    "label": label or name,
                    "placeholder": "",
                    "required": required,
                    "options": [option_label],
                    "field_type": "checkbox",
                    "group_name": name,
                }
                if name:
                    checkbox_groups[name] = group
                fields.append(group)
            continue

        # Handle <select>
        if tag == "select":
            options = []
            option_els = el.query_selector_all("option")
            for opt in option_els:
                val = opt.get_attribute("value") or ""
                text = opt.inner_text().strip()
                # Skip placeholder options (empty value or common placeholder text)
                if not val and not text:
                    continue
                if val == "" and text.lower() in ("select", "choose", "-- select --", "--select--", "please select", "pilih"):
                    continue
                options.append(text or val)

            field_id = f"gf_{field_counter}"
            field_counter += 1
            fields.append({
                "field_id": field_id,
                "selector": _build_selector(el, id_attr, name),
                "tag": "select",
                "input_type": "",
                "name": name,
                "label": label or name,
                "placeholder": "",
                "required": required,
                "options": options,
                "field_type": "dropdown",
            })
            continue

        # Handle textarea
        if tag == "textarea":
            field_id = f"gf_{field_counter}"
            field_counter += 1
            fields.append({
                "field_id": field_id,
                "selector": _build_selector(el, id_attr, name),
                "tag": "textarea",
                "input_type": "",
                "name": name,
                "label": label or name or placeholder,
                "placeholder": placeholder,
                "required": required,
                "options": [],
                "field_type": "paragraph",
            })
            continue

        # Handle regular inputs (text, email, number, tel, url, date, time, etc.)
        field_id = f"gf_{field_counter}"
        field_counter += 1
        field_type = _normalize_field_type(input_type)

        fields.append({
            "field_id": field_id,
            "selector": _build_selector(el, id_attr, name),
            "tag": "input",
            "input_type": input_type or "text",
            "name": name,
            "label": label or name or placeholder,
            "placeholder": placeholder,
            "required": required,
            "options": [],
            "field_type": field_type,
        })

    return fields


def _find_label(page, element, id_attr):
    """Resolve label text for a form element."""
    # 1. <label for="id">
    if id_attr:
        label_el = page.query_selector(f'label[for="{id_attr}"]')
        if label_el:
            text = label_el.inner_text().strip()
            if text:
                return text

    # 2. aria-label
    aria_label = element.get_attribute("aria-label")
    if aria_label:
        return aria_label.strip()

    # 3. aria-labelledby
    labelledby = element.get_attribute("aria-labelledby")
    if labelledby:
        label_el = page.query_selector(f"#{labelledby}")
        if label_el:
            text = label_el.inner_text().strip()
            if text:
                return text

    # 4. Closest ancestor <label>
    parent_label = element.evaluate("""el => {
        let parent = el.parentElement;
        while (parent) {
            if (parent.tagName === 'LABEL') return parent.textContent.trim();
            parent = parent.parentElement;
        }
        return '';
    }""")
    if parent_label:
        return parent_label

    # 5. Preceding sibling or adjacent text
    adjacent_text = element.evaluate("""el => {
        // Check previous sibling
        let prev = el.previousElementSibling;
        if (prev && (prev.tagName === 'LABEL' || prev.tagName === 'SPAN' || prev.tagName === 'DIV')) {
            let t = prev.textContent.trim();
            if (t && t.length < 200) return t;
        }
        // Check parent's previous sibling
        let parentPrev = el.parentElement ? el.parentElement.previousElementSibling : null;
        if (parentPrev) {
            let t = parentPrev.textContent.trim();
            if (t && t.length < 200) return t;
        }
        return '';
    }""")
    if adjacent_text:
        return adjacent_text

    # 6. Placeholder
    placeholder = element.get_attribute("placeholder")
    if placeholder:
        return placeholder.strip()

    return ""


def _get_radio_checkbox_label(page, element):
    """Get the label text for a radio or checkbox input."""
    id_attr = element.get_attribute("id") or ""

    if id_attr:
        label_el = page.query_selector(f'label[for="{id_attr}"]')
        if label_el:
            return label_el.inner_text().strip()

    # Check parent label
    parent_text = element.evaluate("""el => {
        let parent = el.parentElement;
        if (parent && parent.tagName === 'LABEL') {
            // Get text content excluding the input itself
            let clone = parent.cloneNode(true);
            let inputs = clone.querySelectorAll('input');
            inputs.forEach(i => i.remove());
            return clone.textContent.trim();
        }
        return '';
    }""")
    if parent_text:
        return parent_text

    # Next sibling text
    sibling_text = element.evaluate("""el => {
        let next = el.nextSibling;
        if (next && next.nodeType === 3) return next.textContent.trim();
        let nextEl = el.nextElementSibling;
        if (nextEl && (nextEl.tagName === 'LABEL' || nextEl.tagName === 'SPAN')) {
            return nextEl.textContent.trim();
        }
        return '';
    }""")
    return sibling_text or ""


def _build_selector(element, id_attr="", name=""):
    """Generate a stable CSS selector for an element."""
    if id_attr:
        return f"#{id_attr}"
    if name:
        tag = element.evaluate("el => el.tagName.toLowerCase()")
        return f'{tag}[name="{name}"]'
    # Fallback: generate a unique path
    return element.evaluate("""el => {
        let parts = [];
        while (el && el !== document.body) {
            let tag = el.tagName.toLowerCase();
            let parent = el.parentElement;
            if (parent) {
                let siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
                if (siblings.length > 1) {
                    let idx = siblings.indexOf(el) + 1;
                    tag += ':nth-of-type(' + idx + ')';
                }
            }
            parts.unshift(tag);
            el = parent;
        }
        return parts.join(' > ');
    }""")


def _normalize_field_type(input_type):
    """Map HTML input type to a field_type compatible with fake_data.py."""
    mapping = {
        "text": "short_text",
        "email": "short_text",
        "tel": "short_text",
        "url": "short_text",
        "number": "short_text",
        "password": "short_text",
        "search": "short_text",
        "date": "date",
        "time": "time",
        "datetime-local": "date",
        "month": "short_text",
        "week": "short_text",
        "color": "short_text",
        "range": "short_text",
    }
    return mapping.get(input_type, "short_text")


def _is_visible(element):
    """Check if an element is visible on the page."""
    try:
        return element.evaluate("""el => {
            if (el.offsetWidth === 0 && el.offsetHeight === 0) return false;
            let style = window.getComputedStyle(el);
            if (style.display === 'none') return false;
            if (style.visibility === 'hidden') return false;
            if (style.opacity === '0') return false;
            return true;
        }""")
    except Exception:
        return False


def _detect_login_page(page):
    """Check if the page has login/authentication elements."""
    indicators = [
        "accounts.google.com/signin",
        "accounts.google.com/v3/signin",
        "accounts.google.com/ServiceLogin",
        'button:has-text("Sign in with Google")',
        'a:has-text("Sign in with Google")',
        '[data-provider="google"]',
    ]

    page_content = page.content().lower()
    page_url = page.url.lower()

    # Check URL
    for indicator in indicators[:3]:
        if indicator.lower() in page_url:
            return True

    # Check page content
    for indicator in indicators[:3]:
        if indicator.lower() in page_content:
            return True

    # Check for Google sign-in buttons via selectors
    for selector in indicators[3:]:
        try:
            el = page.query_selector(selector)
            if el and _is_visible(el):
                return True
        except Exception:
            pass

    # Check for generic login forms
    login_keywords = ["sign in", "log in", "login", "signin"]
    for kw in login_keywords:
        try:
            btn = page.query_selector(f'button:has-text("{kw}")')
            if btn and _is_visible(btn):
                return True
        except Exception:
            pass

    return False
