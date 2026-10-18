import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_tools_are_discoverable_and_callable():
    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server"],
            env={**os.environ, "PYTHONPATH": os.getcwd()},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert "investigate_system_tool" in names
                assert "create_coordination_task" in names
                result = await session.call_tool(
                    "get_system_overview_tool",
                    {"system_id": "system-checkout", "tenant_id": "tenant-a"},
                )
                assert result.isError is False

    asyncio.run(exercise())
