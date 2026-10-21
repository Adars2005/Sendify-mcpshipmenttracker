import pytest
from mcp import Client

import server
from server import mcp
from models import ShipmentResult


@pytest.mark.anyio
async def test_tool_is_discoverable_and_returns_structured_invalid_result():
    async with Client(mcp) as client:
        listing = await client.list_tools()
        tool = next(item for item in listing.tools if item.name == "track_db_schenker_shipment")
        assert "reference_number" in tool.input_schema["properties"]

        result = await client.call_tool(
            "track_db_schenker_shipment",
            {"reference_number": "bad ref"},
        )
        assert result.is_error is not True
        assert result.structured_content["status"] == "invalid_reference"


@pytest.mark.anyio
async def test_tool_returns_structured_success_result(monkeypatch):
    def fake_lookup(reference_number):
        return ShipmentResult(
            reference_number=reference_number,
            status="ok",
            message="Synthetic fixture result",
            piece_count=2,
        )

    monkeypatch.setattr(server, "lookup_shipment", fake_lookup)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "track_db_schenker_shipment",
            {"reference_number": "SYNTHETIC123"},
        )

    assert result.is_error is not True
    assert result.structured_content["reference_number"] == "SYNTHETIC123"
    assert result.structured_content["status"] == "ok"
    assert result.structured_content["piece_count"] == 2
