from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from models import Package, Party, ShipmentResult, TrackingEvent

logger = logging.getLogger(__name__)

TRACKING_PAGE = "https://www.dsv.com/mydsv/tracking-public/"
SHIPMENTS_API_PATH = "/nges-portal/api/public/tracking-public/shipments"
SOURCE_TIMEOUT_MS = 45_000
REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{4,39}$")


class SourceBlockedError(Exception):
    """The source returned an access or verification barrier."""


class SourceNotFoundError(Exception):
    """The public tracker explicitly reported no matching shipment."""


class SourceLayoutError(Exception):
    """The source returned content that cannot safely be mapped."""


def tracking_url(reference_number: str) -> str:
    query = urlencode({"refNumber": reference_number, "language_region": "en-US_US"})
    return f"{TRACKING_PAGE}?{query}"


def validate_reference(reference_number: str) -> str | None:
    """Return a trimmed reference if it passes basic input hygiene."""
    reference = reference_number.strip()
    return reference if REFERENCE_PATTERN.fullmatch(reference) else None


def _classify_visible_text(text: str) -> None:
    normalized = " ".join(text.casefold().split())
    if any(
        marker in normalized
        for marker in (
            "access denied",
            "verify you are human",
            "captcha",
            "unusual traffic",
            "request blocked",
        )
    ):
        raise SourceBlockedError("The public tracking page presented an access barrier.")
    if any(
        marker in normalized
        for marker in (
            "shipment not found",
            "no shipments found",
            "no shipment found",
            "no results found",
        )
    ):
        raise SourceNotFoundError("The public tracker reported no matching shipment.")


def fetch_tracking_data(reference_number: str) -> dict[str, Any]:
    """Read shipment JSON returned during normal public-page navigation.

    The browser follows the same public UI flow a person uses. It does not call
    the observed endpoint directly, retry manually, or bypass access controls.
    Only response JSON is held in memory for normalization; it is never logged
    or written to disk.
    """
    url = tracking_url(reference_number)
    listing: dict[str, Any] | None = None
    details: dict[str, dict[str, Any]] = {}
    statuses: list[tuple[str, int]] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(locale="en-US")

                def capture_response(response: Any) -> None:
                    nonlocal listing
                    path = urlparse(response.url).path
                    if not path.startswith(SHIPMENTS_API_PATH):
                        return
                    statuses.append((path, response.status))
                    if response.status != 200:
                        return
                    if "json" not in response.headers.get("content-type", "").lower():
                        return
                    try:
                        payload = response.json()
                    except Exception:
                        return
                    if path == SHIPMENTS_API_PATH and isinstance(payload, dict):
                        listing = payload
                    elif path.startswith(SHIPMENTS_API_PATH + "/") and isinstance(payload, dict):
                        stt_number = payload.get("sttNumber")
                        if isinstance(stt_number, str):
                            details[stt_number] = payload

                page.on("response", capture_response)
                page.goto(url, wait_until="domcontentloaded", timeout=SOURCE_TIMEOUT_MS)

                # The consent layer can cover the page on first use. Select only
                # necessary cookies so the normal public lookup can continue.
                necessary_cookies = page.get_by_role(
                    "button", name=re.compile(r"use necessary cookies only", re.IGNORECASE)
                )
                if necessary_cookies.count() > 0:
                    necessary_cookies.first.click(timeout=5_000)

                try:
                    page.get_by_role("heading", name="DSV Tracking").wait_for(
                        state="visible", timeout=15_000
                    )
                except PlaywrightTimeoutError:
                    pass
                try:
                    # The page may retain analytics connections; cap this wait.
                    page.wait_for_load_state("networkidle", timeout=8_000)
                except PlaywrightTimeoutError:
                    pass
                visible_text = page.locator("body").inner_text(timeout=10_000)
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise TimeoutError("The public tracking page timed out.") from exc
    except PlaywrightError as exc:
        message = str(exc).casefold()
        if any(term in message for term in ("403", "429", "access denied", "blocked")):
            raise SourceBlockedError("The public tracking page blocked this lookup.") from exc
        raise RuntimeError("Could not load the public tracking page.") from exc

    _classify_visible_text(visible_text)
    return {
        "reference_number": reference_number,
        "listing": listing,
        "details": details,
        "response_statuses": statuses,
        "visible_text": visible_text,
    }


def _all_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _all_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_strings(child)


def extract_raw_shipment(source_data: dict[str, Any], reference_number: str) -> dict[str, Any]:
    """Select the one matching shipment from observed page responses."""
    _classify_visible_text(source_data.get("visible_text", ""))
    listing = source_data.get("listing")
    if not isinstance(listing, dict):
        statuses = source_data.get("response_statuses", [])
        if any(status in (403, 429) for _, status in statuses):
            raise SourceBlockedError("The public tracking API did not allow this lookup.")
        raise SourceLayoutError("The public page did not return a usable shipment list.")

    records = listing.get("result")
    if not isinstance(records, list):
        raise SourceLayoutError("The shipment list has an unexpected structure.")
    if not records:
        raise SourceNotFoundError("The public tracker returned no matching shipments.")
    details_by_stt = source_data.get("details", {})
    if not isinstance(details_by_stt, dict):
        raise SourceLayoutError("Shipment detail responses have an unexpected structure.")

    # The page normally returns one search result. For multiple results, only
    # select when the requested reference occurs in the source's explicit
    # reference fields; otherwise return an ambiguity error rather than guess.
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        stt_number = record.get("stt")
        detail = details_by_stt.get(stt_number) if isinstance(stt_number, str) else None
        if not isinstance(detail, dict):
            continue
        refs = detail.get("references", {})
        explicit_match = any(
            value.casefold() == reference_number.casefold()
            for value in _all_strings(refs)
        )
        if explicit_match:
            matches.append((record, detail))

    if len(matches) != 1:
        if not matches and any(status in (403, 429) for _, status in source_data.get("response_statuses", [])):
            raise SourceBlockedError("The public tracking API did not return shipment details.")
        if not records:
            raise SourceNotFoundError("The public tracker returned no matching shipments.")
        raise SourceLayoutError("The page returned multiple or unmatched shipment records.")

    record, detail = matches[0]
    if not isinstance(detail.get("goods"), dict) or not isinstance(detail.get("events"), list):
        raise SourceLayoutError("Shipment detail fields changed from the observed source structure.")
    return {"record": record, "detail": detail}


def _place_address(place: Any) -> str | None:
    if not isinstance(place, dict):
        return None
    # These keys and their meaning were observed in the successful DSV public
    # response. This produces only the locality shown publicly, not a street address.
    parts = [place.get(key) for key in ("postCode", "city", "country")]
    values = [str(part).strip() for part in parts if isinstance(part, str) and part.strip()]
    return ", ".join(values) or None


def _event_timestamp(event: dict[str, Any]) -> str | None:
    date = event.get("date")
    if isinstance(date, str) and date.strip():
        return date.strip()
    created_at = event.get("createdAt")
    return created_at.strip() if isinstance(created_at, str) and created_at.strip() else None


def _parse_event_datetime(value: str) -> datetime | None:
    for candidate in (value, value.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    try:
        return datetime.strptime(value, "%Y/%m/%d %H:%M")
    except ValueError:
        return None


def _normalize_events(raw_events: list[Any]) -> tuple[list[TrackingEvent], bool]:
    events: list[TrackingEvent] = []
    for raw in raw_events:
        if not isinstance(raw, dict):
            continue
        code = raw.get("code")
        comment = raw.get("comment")
        location = raw.get("location")
        location_name = location.get("name") if isinstance(location, dict) else None
        description = comment.strip() if isinstance(comment, str) else ""
        if not description and not isinstance(code, str):
            continue
        events.append(
            TrackingEvent(
                timestamp=_event_timestamp(raw),
                status=code if isinstance(code, str) else None,
                description=description or (code if isinstance(code, str) else "Tracking update"),
                location=location_name if isinstance(location_name, str) else None,
            )
        )

    parsed = [_parse_event_datetime(event.timestamp) if event.timestamp else None for event in events]
    can_sort = bool(events) and all(value is not None for value in parsed)
    if can_sort:
        events = [event for _, event in sorted(zip(parsed, events), key=lambda pair: pair[0])]
    return events, can_sort


def normalize_shipment(raw_shipment: dict[str, Any], reference_number: str) -> ShipmentResult:
    """Normalize fields observed in the DSV public shipment response."""
    detail = raw_shipment["detail"]
    goods = detail.get("goods", {})
    location = detail.get("location", {})
    if not isinstance(goods, dict) or not isinstance(location, dict):
        raise SourceLayoutError("Shipment detail fields changed from the observed source structure.")

    shipper_address = _place_address(location.get("shipperPlace"))
    consignee_address = _place_address(location.get("consigneePlace"))
    raw_events = detail.get("events", [])
    events, events_sorted = _normalize_events(raw_events if isinstance(raw_events, list) else [])

    raw_packages = detail.get("packages", [])
    packages: list[Package] = []
    package_events_unmapped = False
    if isinstance(raw_packages, list):
        for raw_package in raw_packages:
            if not isinstance(raw_package, dict):
                continue
            package_id = raw_package.get("id")
            raw_package_events = raw_package.get("events", [])
            package_events: list[TrackingEvent] = []
            if isinstance(raw_package_events, list) and raw_package_events:
                # Package-event details were empty in the available live
                # sample. Only reuse the shipment mapping when it has the same
                # observed event keys; otherwise preserve no guessed timeline.
                known_events = [
                    event
                    for event in raw_package_events
                    if isinstance(event, dict)
                    and any(key in event for key in ("code", "date", "location", "comment"))
                ]
                if len(known_events) == len(raw_package_events):
                    package_events, _ = _normalize_events(known_events)
                else:
                    package_events_unmapped = True
            packages.append(
                Package(
                    reference_number=package_id if isinstance(package_id, str) else None,
                    tracking_history=package_events,
                )
            )

    weight = goods.get("weight") if isinstance(goods.get("weight"), dict) else {}
    volume = goods.get("volume") if isinstance(goods.get("volume"), dict) else {}
    loading_meters = goods.get("loadingMeters") if isinstance(goods.get("loadingMeters"), dict) else {}
    last_code = detail.get("lastEventCode") or raw_shipment["record"].get("lastEventCode")
    if not last_code and events:
        last_code = events[-1].status

    warnings: list[str] = []
    references = detail.get("references")
    shipper_refs = references.get("shipper") if isinstance(references, dict) else None
    consignee_refs = references.get("consignee") if isinstance(references, dict) else None
    if shipper_refs:
        warnings.append("Sender reference fields are present but their name/address mapping is not verified.")
    else:
        warnings.append("Sender name is not exposed by the public record; only the shipper place is available.")
    if consignee_refs:
        warnings.append("Receiver reference fields are present but their name/address mapping is not verified.")
    else:
        warnings.append("Receiver name is not exposed by the public record; only the consignee place is available.")
    if not shipper_address:
        warnings.append("Sender address is not exposed by the public record.")
    else:
        warnings.append("Sender address is a public locality only; no street address was exposed.")
    if not consignee_address:
        warnings.append("Receiver address is not exposed by the public record.")
    else:
        warnings.append("Receiver address is a public locality only; no street address was exposed.")
    if goods.get("dimensions"):
        warnings.append("The source returned dimensions, but their current shape is not mapped to package dimensions.")
    else:
        warnings.append("Per-package dimensions are not exposed in the public record.")
    if packages and not any(package.tracking_history for package in packages):
        warnings.append("No package-specific tracking events were exposed for this shipment.")
    if package_events_unmapped:
        warnings.append("Package events were returned in an unverified format and were not mapped.")
    if not events:
        warnings.append("No shipment tracking events were exposed by the public record.")
    elif not events_sorted:
        warnings.append("Some event timestamps could not be parsed; the source order was retained.")
    if isinstance(raw_events, list) and any(
        isinstance(event, dict) and event.get("reasons")
        for event in raw_events
    ):
        warnings.append("Event reasons were present in a source format that has not been mapped.")

    return ShipmentResult(
        reference_number=reference_number,
        status="ok",
        message="Public shipment information retrieved.",
        shipment_status=last_code if isinstance(last_code, str) else None,
        sender=Party(name=None, address=shipper_address),
        receiver=Party(name=None, address=consignee_address),
        piece_count=goods.get("pieces") if isinstance(goods.get("pieces"), int) else None,
        total_weight=weight.get("value") if isinstance(weight, dict) and isinstance(weight.get("value"), (int, float)) else None,
        weight_unit=weight.get("unit") if isinstance(weight, dict) and isinstance(weight.get("unit"), str) else None,
        total_volume=volume.get("value") if isinstance(volume, dict) and isinstance(volume.get("value"), (int, float)) else None,
        volume_unit=volume.get("unit") if isinstance(volume, dict) and isinstance(volume.get("unit"), str) else None,
        loading_meters=loading_meters.get("value") if isinstance(loading_meters, dict) and isinstance(loading_meters.get("value"), (int, float)) else None,
        loading_meters_unit=loading_meters.get("unit") if isinstance(loading_meters, dict) and isinstance(loading_meters.get("unit"), str) else None,
        packages=packages,
        tracking_history=events,
        warnings=warnings,
        source_url=tracking_url(reference_number),
    )


def lookup_shipment(reference_number: str) -> ShipmentResult:
    """Look up one reference and return a structured outcome."""
    reference = validate_reference(reference_number)
    if reference is None:
        return ShipmentResult(
            reference_number=reference_number.strip(),
            status="invalid_reference",
            message="The reference format is invalid.",
        )

    try:
        source_data = fetch_tracking_data(reference)
        raw_shipment = extract_raw_shipment(source_data, reference)
        return normalize_shipment(raw_shipment, reference)
    except SourceNotFoundError:
        return ShipmentResult(
            reference_number=reference,
            status="not_found",
            message="The public tracker reports no matching shipment.",
            source_url=tracking_url(reference),
        )
    except SourceBlockedError:
        return ShipmentResult(
            reference_number=reference,
            status="blocked",
            message="The public tracking source did not allow this lookup to complete.",
            warnings=["Do not bypass access or verification controls."],
            source_url=tracking_url(reference),
        )
    except TimeoutError:
        return ShipmentResult(
            reference_number=reference,
            status="source_error",
            message="The public tracking request timed out.",
            source_url=tracking_url(reference),
        )
    except SourceLayoutError as exc:
        logger.warning("Unmapped tracking response (%s)", type(exc).__name__)
        return ShipmentResult(
            reference_number=reference,
            status="source_error",
            message="The tracking page returned data that could not be safely mapped.",
            warnings=[str(exc)],
            source_url=tracking_url(reference),
        )
    except Exception as exc:
        # Shipment references can be sensitive. Keep them and upstream details
        # out of logs, including exception messages that may contain URLs/data.
        logger.error("Shipment lookup failed (%s)", type(exc).__name__)
        return ShipmentResult(
            reference_number=reference,
            status="source_error",
            message="An unexpected error occurred while retrieving shipment information.",
            source_url=tracking_url(reference),
        )
