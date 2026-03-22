# MCP
## Context7 Dockerfile

From https://github.com/upstash/context7/tree/master/packages/mcp
But I updated to latest node LTS.

```Dockerfile
FROM node:24-alpine

WORKDIR /app

# Install the latest version globally
RUN npm install -g @upstash/context7-mcp

# Expose default port if needed (optional, depends on MCP client interaction)
# EXPOSE 3000

# Default command to run the server
CMD ["context7-mcp"]
```

```bash
docker build -t berne/context7-mcp .
```

## Configuring Mistral Vibe MCP

### `~/.vibe/config.toml`
```toml
[[mcp_servers]]
name = "context7"
transport = "stdio"
command = "docker"
args = ["run", "-i", "--rm", "berne/context7-mcp"]
```

## Testing
```bash
xh POST http://localhost:3000/mcp accept:application/json,text/event-stream jsonrpc=2.0 id:=1 method=tools/list
```

```bash
jq '.result.tools | map(.name)'
```

```json
[
  "resolve-library-id",
  "query-docs"
]
```

