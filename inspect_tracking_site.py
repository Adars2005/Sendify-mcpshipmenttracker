"""Inspect response structure from ordinary DSV public-page navigation.

This script prints endpoint paths, HTTP status/content type, and JSON key
shapes only. It never prints payload values or writes captured payloads.
"""
from __future__ import annotations

import argparse
import json
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from tracker import SOURCE_TIMEOUT_MS, TRACKING_PAGE, validate_reference


def shape(value: object, depth: int = 0) -> object:
    if depth >= 4:
        return type(value).__name__
    if isinstance(value, dict):
        return {key: shape(child, depth + 1) for key, child in value.items()}
    if isinstance(value, list):
        return [shape(value[0], depth + 1)] if value else []
    return type(value).__name__


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference_number")
    args = parser.parse_args()
    reference = validate_reference(args.reference_number)
    if reference is None:
        parser.error("reference format is invalid")

    responses = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="en-US")
            page.on("response", lambda response: responses.append(response))
            page.goto(
                f"{TRACKING_PAGE}?refNumber={reference}&language_region=en-US_US",
                wait_until="domcontentloaded",
                timeout=SOURCE_TIMEOUT_MS,
            )
            necessary = page.get_by_role("button", name="Use necessary cookies only")
            if necessary.count():
                necessary.first.click(timeout=5_000)
            try:
                page.get_by_role("heading", name="DSV Tracking").wait_for(
                    state="visible", timeout=15_000
                )
            except PlaywrightTimeoutError:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=8_000)
            except PlaywrightTimeoutError:
                pass
            print("Final page host/path:", urlparse(page.url).netloc, urlparse(page.url).path)
            print("Page title:", page.title())
            for response in responses:
                request = response.request
                if request.resource_type not in {"xhr", "fetch"}:
                    continue
                path = urlparse(response.url).path
                if "/api/public/tracking-public/shipments" not in path:
                    continue
                content_type = response.headers.get("content-type", "")
                item = {
                    "path": path,
                    "status": response.status,
                    "resource_type": request.resource_type,
                    "content_type": content_type,
                }
                if "json" in content_type.lower():
                    try:
                        item["json_shape"] = shape(response.json())
                    except Exception:
                        item["json_shape"] = "unreadable"
                print(json.dumps(item, ensure_ascii=False))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
