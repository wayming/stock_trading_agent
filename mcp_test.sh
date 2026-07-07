#!/bin/bash
MCP="http://localhost:8081/mcp"
CT="Content-Type: application/json"
AC="Accept: application/json, text/event-stream"

# 1. initialize 并拿到 session
SESSION=$(curl -s -D - -X POST "$MCP" -H "$CT" -H "$AC" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
  | grep -i 'mcp-session-id' | awk '{print $2}' | tr -d '\r')

# 2. notifications/initialized
curl -s -X POST "$MCP" -H "$CT" -H "$AC" -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' > /dev/null

call() {
  echo "=== $1 ==="
  curl -s -X POST "$MCP" -H "$CT" -H "$AC" -H "Mcp-Session-Id: $SESSION" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}" \
    | grep '^data:' | sed 's/^data: //' | python3 -m json.tool
  echo ""
}

# tools/list
echo "=== tools/list ==="
curl -s -X POST "$MCP" -H "$CT" -H "$AC" -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | grep '^data:' | sed 's/^data: //' | python3 -c "
import sys,json
d=json.load(sys.stdin)
for t in d['result']['tools']:
    print(f\"  {t['name']}: {t['description'][:80]}\")" 2>/dev/null
echo ""

# 3 个 tool
call "list_metrics"        '{"exchange":"ASX","code":"MGX"}'
call "get_data_period"     '{"exchange":"ASX","code":"MGX"}'
call "get_financials"      '{"exchange":"HKG","code":"0700","metrics":["revenue","netinc","pe","pb"],"period":"2y"}'
