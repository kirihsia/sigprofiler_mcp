import os
import time
import glob
import streamlit as st
import plotly.graph_objects as go
from plot_utils import load_signatures, build_plot_data

st.set_page_config(page_title="SigProfiler Plot Gallery", layout="wide")

# Fetch output directory from environment, default to /app/mcp_outputs
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/mcp_outputs")

st.markdown("""
    <style>
    .main-header { font-size: 26px; font-weight: bold; margin-bottom: 2px; }
    .sub-header { color: #666; font-size: 14px; margin-bottom: 20px; }
    .dir-badge { background-color: #eef2f6; padding: 6px 12px; border-radius: 6px; font-family: monospace; font-size: 13px; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">Mutational Signatures Plot Gallery</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Browse and view your extraction results in real-time</div>', unsafe_allow_html=True)
st.markdown(f'Plot directory: <span class="dir-badge">{OUTPUT_DIR}</span>', unsafe_allow_html=True)
st.divider()

def get_signature_files(directory):
    if not os.path.exists(directory):
        return []
    files = glob.glob(os.path.join(directory, "**", "*[Ss]ignatures*.txt"), recursive=True) + \
            glob.glob(os.path.join(directory, "*.txt"))
    return sorted(list(set(files)), key=os.path.getmtime, reverse=True)

all_files = get_signature_files(OUTPUT_DIR)

with st.sidebar:
    st.header("Analysis Sessions")
    auto_refresh = st.checkbox("Auto-refresh for new results", value=True)

    if not all_files:
        st.warning("No analysis results found yet.")
        selected_file = None
    else:
        file_options = {
            f: f"📊 {os.path.basename(f)} ({time.strftime('%m/%d %H:%M', time.localtime(os.path.getmtime(f)))})"
            for f in all_files
        }
        selected_file = st.radio(
            "Select result file:",
            options=list(file_options.keys()),
            format_func=lambda x: file_options[x]
        )

if selected_file and os.path.exists(selected_file):
    try:
        df = load_signatures(selected_file)
        sig_cols = [c for c in df.columns if c not in ("MutationType", "Subs", "Base5", "Base3", "_order")]
        n_sigs = len(sig_cols)

        st.subheader(f"Solution: N = {n_sigs} Signatures ({os.path.basename(selected_file)})")

        cols = st.columns(2)
        for idx, sig_name in enumerate(sig_cols):
            with cols[idx % 2]:
                traces, layout = build_plot_data(df, sig_col=sig_name, sig_name=sig_name)
                fig = go.Figure(data=traces, layout=layout)
                st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Failed to parse file: {e}")
else:
    st.info("Waiting for MCP tools to complete computation and write to the output directory...")

if auto_refresh:
    time.sleep(3)
    current_files = get_signature_files(OUTPUT_DIR)
    if current_files != all_files:
        st.rerun()
