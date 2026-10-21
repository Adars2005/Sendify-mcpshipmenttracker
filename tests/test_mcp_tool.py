import pytest
from mcp import Client

from server import mcp


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
