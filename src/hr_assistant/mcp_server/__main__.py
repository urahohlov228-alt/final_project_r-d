"""Run the MCP server over stdio — for Claude Desktop and other MCP hosts.

Claude Desktop config example (claude_desktop_config.json):
{
  "mcpServers": {
    "hr-assistant": {
      "command": "python",
      "args": ["-m", "hr_assistant.mcp_server"],
      "cwd": "/path/to/final_project_r-d"
    }
  }
}
"""

from ..config import get_settings
from ..logging_setup import setup_logging
from .server import build_mcp_server

if __name__ == "__main__":
    settings = get_settings()
    setup_logging(settings.log_level)
    build_mcp_server(settings).run(transport="stdio")
