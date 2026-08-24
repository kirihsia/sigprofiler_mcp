#!/bin/bash

# Define the local output directory for the container volume mount
export OUTPUT_DIR="/app/mcp_outputs"
mkdir -p $OUTPUT_DIR

# 1. Start the Streamlit Web Viewer in the background
streamlit run viewer.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true &

# 2. Start the MCP server in the foreground for stdio communication
python server.py
