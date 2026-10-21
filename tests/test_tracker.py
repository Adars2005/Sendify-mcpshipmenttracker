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
