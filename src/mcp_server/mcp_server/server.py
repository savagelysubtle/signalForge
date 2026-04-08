"""SignalForge MCP server entry point.

Registers all tools and runs the server over stdio transport for
Claude Code integration.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_server.tools import execution, pipeline, portfolio, risk

mcp = FastMCP("signalforge")

# ------------------------------------------------------------------
# Pipeline tools — HTTP calls to the SignalForge backend
# ------------------------------------------------------------------

mcp.tool()(pipeline.run_pipeline)
mcp.tool()(pipeline.get_pipeline_progress)
mcp.tool()(pipeline.get_pipeline_result)
mcp.tool()(pipeline.list_strategies)
mcp.tool()(pipeline.list_recent_runs)

# ------------------------------------------------------------------
# Portfolio tools — direct IBKR connection
# ------------------------------------------------------------------

mcp.tool()(portfolio.get_account_summary)
mcp.tool()(portfolio.get_positions)
mcp.tool()(portfolio.get_open_orders)

# ------------------------------------------------------------------
# Execution tools — IBKR order placement (confirm-first)
# ------------------------------------------------------------------

mcp.tool()(execution.preview_order)
mcp.tool()(execution.place_order)
mcp.tool()(execution.cancel_order)
mcp.tool()(execution.close_position)

# ------------------------------------------------------------------
# Risk tools — monitoring and safety status
# ------------------------------------------------------------------

mcp.tool()(risk.get_daily_pnl)
mcp.tool()(risk.get_risk_status)


def main() -> None:
    """Run the MCP server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
