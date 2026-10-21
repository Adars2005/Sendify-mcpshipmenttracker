import pytest

import tracker


def source_payload(reference="3476472018"):
    event = {
        "code": "DELIVERED",
        "date": "2026/05/20 14:54",
        "createdAt": "2026-05-20T14:54:00",
        "location": {"name": "Synthetic City", "code": "SYN", "countryCode": "SE"},
        "comment": "Synthetic delivery",
        "recipient": None,
        "reasons": [],
        "shellIconName": None,
    }
    detail = {
        "sttNumber": "STT-SYNTHETIC",
        "references": {
            "shipper": [],
            "consignee": [],
            "waybillAndConsignementNumbers": [reference],
            "additionalReferences": [],
            "originalStt": None,
        },
        "goods": {
            "pieces": 2,
            "weight": {"value": 125.5, "unit": "KGS"},
            "volume": {"value": 1.25, "unit": "CBM"},
            "dimensions": [],
            "loadingMeters": {"value": 0.5, "unit": "MTR"},
        },
        "events": [event],
        "packages": [{"id": "PACKAGE-SYNTHETIC", "events": []}],
        "location": {
            "shipperPlace": {"postCode": "12345", "city": "Origin", "country": "Sweden"},
            "consigneePlace": {"postCode": "54321", "city": "Destination", "country": "Denmark"},
        },
    }
    return {
        "reference_number": reference,
        "listing": {"result": [{"stt": "STT-SYNTHETIC", "lastEventCode": "DELIVERED"}]},
        "details": {"STT-SYNTHETIC": detail},
        "response_statuses": [("/shipments", 200)],
        "visible_text": "DSV Tracking",
    }


@pytest.mark.parametrize("value", ["3476472018", " 3476472018 ", "A-12345", "0012345678"])
def test_valid_reference_is_trimmed_and_preserved(value):
    assert tracker.validate_reference(value) == value.strip()


@pytest.mark.parametrize("value", ["", "   ", "1234", "bad ref", "x" * 41])
def test_invalid_reference(value):
    assert tracker.validate_reference(value) is None


def test_invalid_lookup_does_not_fetch(monkeypatch):
    def fail_if_called(_reference):
        raise AssertionError("invalid references must not reach the source")

    monkeypatch.setattr(tracker, "fetch_tracking_data", fail_if_called)
    result = tracker.lookup_shipment("bad ref")
    assert result.status == "invalid_reference"


def test_explicit_not_found_maps_to_not_found(monkeypatch):
    monkeypatch.setattr(
        tracker,
        "fetch_tracking_data",
        lambda _reference: (_ for _ in ()).throw(tracker.SourceNotFoundError()),
    )
    result = tracker.lookup_shipment("3476472018")
    assert result.status == "not_found"


def test_access_barrier_maps_to_blocked(monkeypatch):
    monkeypatch.setattr(
        tracker,
        "fetch_tracking_data",
        lambda _reference: (_ for _ in ()).throw(tracker.SourceBlockedError()),
    )
    result = tracker.lookup_shipment("3476472018")
    assert result.status == "blocked"


def test_unmatched_record_is_not_reported_as_not_found(monkeypatch):
    monkeypatch.setattr(
        tracker,
        "fetch_tracking_data",
        lambda _reference: {
            "listing": {"result": [{"stt": "STT-SYNTHETIC"}]},
            "details": {},
            "response_statuses": [("/shipments", 200)],
            "visible_text": "DSV Tracking",
        },
    )
    result = tracker.lookup_shipment("3476472018")
    assert result.status == "source_error"


def test_live_schema_normalizes_synthetic_fixture_values():
    data = source_payload()
    raw = tracker.extract_raw_shipment(data, "3476472018")
    result = tracker.normalize_shipment(raw, "3476472018")
    assert result.status == "ok"
    assert result.reference_number == "3476472018"
    assert result.sender.name is None
    assert result.sender.address == "12345, Origin, Sweden"
    assert result.receiver.address == "54321, Destination, Denmark"
    assert result.piece_count == 2
    assert result.total_weight == 125.5
    assert result.weight_unit == "KGS"
    assert result.packages[0].reference_number == "PACKAGE-SYNTHETIC"
    assert result.tracking_history[0].status == "DELIVERED"
    assert result.tracking_history[0].description == "Synthetic delivery"


def test_visible_not_found_messages():
    with pytest.raises(tracker.SourceNotFoundError):
        tracker._classify_visible_text("Shipment not found!")


def test_visible_access_barriers():
    with pytest.raises(tracker.SourceBlockedError):
        tracker._classify_visible_text("Access denied")


def test_event_ordering_when_timestamps_parse():
    events, sorted_events = tracker._normalize_events(
        [
            {"code": "later", "date": "2026/05/20 14:54", "location": {}, "comment": ""},
            {"code": "earlier", "date": "2026/05/19 15:46", "location": {}, "comment": ""},
        ]
    )
    assert sorted_events is True
    assert [event.status for event in events] == ["earlier", "later"]


def test_missing_optional_fields_are_reported_without_crashing():
    payload = source_payload()
    detail = payload["details"]["STT-SYNTHETIC"]
    detail["goods"] = {"pieces": 1}
    detail["location"] = {}
    detail["events"] = []
    detail["packages"] = []

    raw = tracker.extract_raw_shipment(payload, "3476472018")
    result = tracker.normalize_shipment(raw, "3476472018")

    assert result.status == "ok"
    assert result.sender.address is None
    assert result.receiver.address is None
    assert result.total_weight is None
    assert result.packages == []
    assert result.tracking_history == []
    assert any("No shipment tracking events" in warning for warning in result.warnings)


def test_package_events_are_normalized_when_source_provides_them():
    payload = source_payload()
    detail = payload["details"]["STT-SYNTHETIC"]
    detail["packages"][0]["events"] = [
        {
            "code": "ARRIVED",
            "date": "2026/05/19 15:46",
            "comment": "Package arrived",
            "location": {"name": "Synthetic Hub"},
        }
    ]

    result = tracker.normalize_shipment(
        tracker.extract_raw_shipment(payload, "3476472018"), "3476472018"
    )

    assert result.packages[0].tracking_history[0].status == "ARRIVED"
    assert result.packages[0].tracking_history[0].location == "Synthetic Hub"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("timed out"), "source_error"),
        (tracker.SourceBlockedError("blocked"), "blocked"),
        (tracker.SourceNotFoundError("missing"), "not_found"),
        (RuntimeError("upstream changed"), "source_error"),
    ],
)
def test_upstream_failures_return_predictable_status(monkeypatch, error, expected):
    def raise_error(_reference):
        raise error

    monkeypatch.setattr(tracker, "fetch_tracking_data", raise_error)
    result = tracker.lookup_shipment("3476472018")
    assert result.status == expected
    assert result.reference_number == "3476472018"


def test_http_access_denial_is_classified_as_blocked():
    source_data = {
        "listing": None,
        "details": {},
        "response_statuses": [("/shipments", 403)],
        "visible_text": "DSV Tracking",
    }
    with pytest.raises(tracker.SourceBlockedError):
        tracker.extract_raw_shipment(source_data, "3476472018")


def test_malformed_upstream_shape_is_source_error(monkeypatch):
    monkeypatch.setattr(
        tracker,
        "fetch_tracking_data",
        lambda _reference: {
            "listing": {"result": "not-a-list"},
            "details": {},
            "response_statuses": [],
            "visible_text": "DSV Tracking",
        },
    )
    assert tracker.lookup_shipment("3476472018").status == "source_error"


def test_lookup_error_logs_do_not_include_tracking_reference(monkeypatch, caplog):
    secret_reference = "PRIVATE12345"

    def fail(_reference):
        raise RuntimeError("upstream error for PRIVATE12345")

    monkeypatch.setattr(tracker, "fetch_tracking_data", fail)
    result = tracker.lookup_shipment(secret_reference)

    assert result.status == "source_error"
    assert secret_reference not in caplog.text
    assert "upstream error for" not in caplog.text
