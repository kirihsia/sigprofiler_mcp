#!/bin/bash

# Define the local output directory for the container volume mount
export OUTPUT_DIR="${OUTPUT_DIR:-/app/mcp_outputs}"
mkdir -p $OUTPUT_DIR

# Disable Streamlit usage statistics
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Start Streamlit in the background.
# Redirect all its output away from the MCP STDIO channel.
streamlit run sigprofiler_mcp/viewer.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    > /tmp/sigmcp_streamlit.log 2>&1 &

# Start MCP server in the foreground.
exec python sigprofiler_mcp/server.py
