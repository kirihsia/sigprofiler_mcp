"""Interactive SBS-4608 (pentanucleotide + strand context) plotting engine.

Ported from a JS toolkit (AnnotationBuilder.js, BarTraceBuilder.js,
BiasTraceBuilder.js, HeatmapTraceBuilder.js, LayoutBuilder.js,
MutationData.js, SBS4608Data.js, SBS4608PlotBuilder.js,
SBS4608PlotConfig.js, TickLabelFormatter.js, TraceFormatter.js) that
originally lived under project7/. Produces plain dict traces/layout
(Plotly JSON) with no dependency on the plotly package itself -- only
json.dumps is needed to embed the figure in an HTML page.
"""
