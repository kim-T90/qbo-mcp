"""Entry point: python -m quickbooks_mcp"""

from quickbooks_mcp.server import mcp

if __name__ == "__main__":
    mcp.run()
