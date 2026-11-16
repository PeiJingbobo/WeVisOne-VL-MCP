# Docker harness for developing dsh-wevisone-mcp-plugin without touching the
# real DSH installation on the host.
#
#   docker build -f plugin/Dockerfile -t dsh-plugin-dev plugin
#   docker run --rm -e WEVISONE_ENDPOINT=http://host.docker.internal:8000 \
#     -e WEVISONE_MCP_TOKEN=... dsh-plugin-dev
#
# What it proves: the real @deepseek-ai/dsh-tools registry accepts the plugin and
# the two tool schemas land in it. No LLM credentials are needed.
FROM node:24-bookworm-slim

WORKDIR /work

# Pin the DSH runtime so plugin debugging matches the released tool surface.
RUN npm install --global --no-audit --no-fund @deepseek-ai/dsh@0.1.1-rc.2 \
    && dsh --version

COPY dsh-wevisone-mcp-plugin /work/dsh-wevisone-mcp-plugin

WORKDIR /work/harness
COPY harness/package.json ./package.json
# --install-links copies the file: dependency instead of symlinking it, so the
# plugin resolves @deepseek-ai/dsh-tools from harness/node_modules.
RUN npm install --install-links --no-audit --no-fund
COPY harness/smoke.mjs ./smoke.mjs

ENV WEVISONE_ENDPOINT=http://host.docker.internal:8000
CMD ["node", "smoke.mjs"]
