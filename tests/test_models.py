from models import ShipmentResult


def test_result_keeps_missing_fields_null():
    result = ShipmentResult(
        reference_number="0012345678",
        status="ok",
        message="Shipment information retrieved",
    )

    data = result.model_dump()
    assert data["reference_number"] == "0012345678"
    assert data["sender"] == {"name": None, "address": None}
    assert data["receiver"] == {"name": None, "address": None}
    assert data["packages"] == []
    assert data["tracking_history"] == []
