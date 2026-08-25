import pandas as pd

COLORS = {
    "C>A": "#8B0000", "C>G": "#8B0A50", "C>T": "#B35900",
    "T>A": "#4B0082", "T>C": "#00008B", "T>G": "#006400",
}
SUBS_ORDER = ["C>A", "C>G", "C>T", "T>A", "T>C", "T>G"]
BASES = ["A", "C", "G", "T"]

def load_signatures(path):
    df = pd.read_csv(path, sep="\t")
    df["Subs"] = df["MutationType"].str.extract(r"\[(.*)\]")
    df["Base5"] = df["MutationType"].str[0]
    df["Base3"] = df["MutationType"].str[-1]
    order = {(s, b5, b3): i for i, (s, b5, b3) in enumerate(
        (s, b5, b3) for s in SUBS_ORDER for b5 in BASES for b3 in BASES
    )}
    df["_order"] = df.apply(lambda r: order[(r["Subs"], r["Base5"], r["Base3"])], axis=1)
    df = df.sort_values("_order").reset_index(drop=True)
    return df

def build_ticktext(df):
    ticktext = []
    for _, row in df.iterrows():
        color = COLORS[row["Subs"]]
        mid = row["Subs"].split(">")[0]
        ticktext.append(
            f'{row["Base5"]}<span style="color: {color}; font-family: monospace;"><b>{mid}</b></span>{row["Base3"]}'
        )
    return ticktext

def build_shapes():
    shapes = []
    for i, subs in enumerate(SUBS_ORDER):
        start = i * 16
        shapes.append({
            "type": "rect", "xref": "x", "yref": "paper",
            "x0": start - 0.4, "x1": start + 15.4, "y0": 1.04, "y1": 1.01,
            "fillcolor": COLORS[subs], "line": {"width": 0},
        })
    for i in range(1, 6):
        shapes.append({
            "type": "line", "xref": "x", "yref": "paper",
            "x0": i * 16 - 0.5, "x1": i * 16 - 0.5, "y0": 0, "y1": 1,
            "line": {"color": "#e0e0e0", "width": 1},
        })
    shapes.append({
        "type": "line", "xref": "x", "yref": "paper",
        "x0": 95.5, "x1": 95.5, "y0": 0, "y1": 1,
        "line": {"color": "#e0e0e0", "width": 1},
    })
    return shapes

def build_group_annotations():
    return [{
        "xref": "x", "yref": "paper", "xanchor": "center", "yanchor": "bottom",
        "x": i * 16 + 7.5, "y": 1.04, "text": f"<b>{subs}</b>", "showarrow": False,
        "font": {"size": 14}, "align": "center",
    } for i, subs in enumerate(SUBS_ORDER)]

def build_plot_data(df, sig_col, sig_name):
    total = df[sig_col].sum()
    percentages = (df[sig_col] / total * 100)
    ticktext = build_ticktext(df)

    traces = []
    for i, subs in enumerate(SUBS_ORDER):
        start = i * 16
        traces.append({
            "name": subs, "type": "bar",
            "marker": {"color": COLORS[subs]},
            "x": list(range(start, start + 16)),
            "y": percentages.iloc[start:start + 16].tolist(),
            "hoverinfo": "x+y", "showlegend": False,
        })

    layout = {
        "height": 420,
        "margin": {"l": 50, "r": 20, "t": 60, "b": 90},
        "xaxis": {
            "showticklabels": True, "showline": True, "tickangle": -90,
            "tickfont": {"family": "monospace", "color": "#777", "size": 9},
            "tickmode": "array", "tickvals": list(range(96)), "ticktext": ticktext,
            "linecolor": "#E0E0E0", "linewidth": 1,
        },
        "yaxis": {
            "autorange": False, "range": [0, max(percentages) * 1.15],
            "linecolor": "#D3D3D3", "linewidth": 1,
            "showgrid": True, "gridcolor": "#F5F5F5",
            "title": {"text": "Percentage (%)", "font": {"size": 11}},
            "ticksuffix": "%",
        },
        "shapes": build_shapes(),
        "annotations": build_group_annotations() + [{
            "xref": "paper", "yref": "paper", "xanchor": "left", "yanchor": "bottom",
            "x": 0.01, "y": 1.12, "text": f"<b>{sig_name}</b>", "showarrow": False,
            "font": {"size": 16},
        }],
        "plot_bgcolor": "white", "paper_bgcolor": "white",
    }
    return traces, layout
