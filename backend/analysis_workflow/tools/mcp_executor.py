"""MCP tool execution helpers — infrastructure layer, no business logic."""

import json
import logging

logger = logging.getLogger(f"backend.{__name__}")


def get_tool_definitions() -> list[dict]:
    """Get MCP tool definitions for the LLM (static, no session needed)."""
    try:
        from mcp_client import get_tool_definitions as _get_defs
        return _get_defs()
    except Exception as e:
        logger.warning(f"Could not get MCP tool definitions: {e}")
        return []


def execute_mcp_tool(name: str, arguments: dict) -> dict | str:
    """Execute an MCP tool by name. Returns result dict or error string.

    Tries to auto-reconnect if the MCP client is unavailable.
    """
    try:
        from mcp_client import get_mcp_client, init_mcp_client

        mcp = get_mcp_client()
        if mcp is None:
            # Try to initialize from DB config (lazy import to avoid circular deps)
            from ..runner import _get_db  # noqa: F811  — late import
            db = _get_db()
            mcp_url = db.get_config("mcp_server_url") or "" if db else ""
            if mcp_url:
                logger.info(f"Attempting lazy MCP connect to {mcp_url}")
                if init_mcp_client(mcp_url):
                    mcp = get_mcp_client()
            if mcp is None:
                return {"error": "MCP client not connected — is the MCP server running?"}

        result = mcp.call_tool(name, arguments)
        if result is None:
            # call_tool already tried reconnect — give up
            return {"error": f"Tool {name} returned no data — MCP server may be unreachable"}
        return result
    except Exception as e:
        logger.error(f"MCP tool {name} failed: {e}")
        return {"error": str(e)}
