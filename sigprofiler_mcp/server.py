"""MCP server exposing the SigProfiler suite as tools for LLM clients.

Wraps SigProfilerMatrixGenerator, SigProfilerAssignment, SigProfilerExtractor,
and sigProfilerPlotting so a client can run mutational-signature workflows by
calling tools instead of writing Python scripts by hand.

Imports of the SigProfiler packages are deferred to inside each tool function.
Importing SigProfilerExtractor eagerly pulls in torch, which is slow and only
needed for the extract_signatures tool.
"""

from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sigprofiler")


os.environ['SIGPROFILERMATRIXGENERATOR_VOLUME'] = '/references'

# SigProfiler tools print progress to stdout rather than raising on most
# recoverable issues, so we capture it and return a tail of it to the caller.
_LOG_TAIL_LINES = 40


def _tail(captured: str, lines: int = _LOG_TAIL_LINES) -> str:
    return "\n".join(captured.splitlines()[-lines:])


def _resolve_dir(path: str, must_exist: bool = True) -> Path:
    resolved = Path(path).expanduser().resolve()
    if must_exist and not resolved.is_dir():
        raise ValueError(f"Directory does not exist: {resolved}")
    return resolved


# Root directory the results viewer (viewer.py) watches. Tools that don't
# receive an explicit output path fall back to a named subdirectory here so
# results stay organized by sample/project and are discoverable by the viewer.
_OUTPUT_ROOT = Path(os.environ.get("OUTPUT_DIR", "mcp_outputs"))


def _default_output_dir(name: str) -> str:
    path = _OUTPUT_ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


# SigProfilerMatrixGenerator's installer writes a "logs" dir relative to the
# process's current working directory, which is often a read-only network
# mount when this server is launched from one. Run installs from a local dir.
_LOCAL_RUN_DIR = Path(__file__).resolve().parent


@contextlib.contextmanager
def _local_cwd():
    original = Path.cwd()
    os.chdir(_LOCAL_RUN_DIR)
    try:
        yield
    finally:
        os.chdir(original)


# Matches the genomes SigProfilerMatrixGenerator's CLI advertises as installable.
_SUPPORTED_GENOMES = {
    "GRCh37", "GRCh38", "mm9", "mm10", "mm39",
    "rn6", "rn7", "c_elegans", "dog", "ebv", "yeast",
}


def _is_genome_installed(genome: str) -> bool:
    from SigProfilerMatrixGenerator.scripts.ref_install import ReferenceDir

    # The installer deletes the per-genome fasta dir (and the whole
    # chrom_string dir) once it has generated the tsb files, so tsb/<genome>
    # is the only artifact that reliably survives a completed install.
    tsb_dir = ReferenceDir().get_tsb_dir() / genome
    return tsb_dir.is_dir() and any(tsb_dir.iterdir())


@mcp.tool()
def install_reference_genome(genome: str = "GRCh37") -> dict:
    """Download and install a reference genome used by SigProfilerMatrixGenerator.

    

    This is a one-time setup step (several GB download) that must complete
    before generate_matrix can be used with that genome.

    Args:
        genome: Which genome build to install. One of: GRCh37, GRCh38, mm9,
            mm10, mm39, rn6, rn7, c_elegans, dog, ebv, yeast.
    """

    if genome not in _SUPPORTED_GENOMES:
        raise ValueError(
            f"Unknown genome {genome!r}. Supported genomes: "
            f"{', '.join(sorted(_SUPPORTED_GENOMES))}."
        )

    if _is_genome_installed(genome):
        return {
            "genome": genome,
            "already_installed": True,
            "message": (
                f"{genome} is already installed -- no need to run "
                "install_reference_genome again for this genome."
            ),
        }






    from SigProfilerMatrixGenerator.scripts.ref_install import ReferenceDir
    from pathlib import Path

    _original_path_prop = getattr(ReferenceDir, 'path', None)

    ReferenceDir.path = property(lambda self: Path('/references'))


    from SigProfilerMatrixGenerator import install as genInstall
    import io
    import contextlib

    buf = io.StringIO()


    original_cwd = os.getcwd()
    os.chdir('/references')

    try:
        with contextlib.redirect_stdout(buf):
            genInstall.install(genome, bash=True)
    finally:
        os.chdir(original_cwd)
        if _original_path_prop:
            ReferenceDir.path = _original_path_prop

    return {
        "genome": genome,
        "already_installed": False,
        "log_tail": _tail(buf.getvalue()),
    }


@mcp.tool()
def generate_matrix(
    project: str,
    input_dir: str,
    reference_genome: str = "GRCh37",
    exome: bool = False,
    output_dir: Optional[str] = None,
) -> dict:
    """Generate mutational matrices (SBS/DBS/ID) from VCF or MAF files.

    Args:
        project: Name for this run, used to label output files.
        input_dir: Directory containing input VCF/MAF mutation files.
        reference_genome: Genome build the mutations were called against.
            Must already be installed via install_reference_genome.
        exome: Restrict matrix generation to the exome.
        output_dir: Where to write the "output" directory. Defaults to
            OUTPUT_DIR/<project>.
    """
    from SigProfilerMatrixGenerator.scripts import (
        SigProfilerMatrixGeneratorFunc as matGen,
    )

    input_path = _resolve_dir(input_dir)
    if output_dir is None:
        output_dir = _default_output_dir(project)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        matrices = matGen.SigProfilerMatrixGeneratorFunc(
            project=project,
            reference_genome=reference_genome,
            path_to_input_files=str(input_path),
            exome=exome,
            output_directory=output_dir,
        )

    matrix_types = sorted(matrices.keys()) if isinstance(matrices, dict) else []
    resolved_output = Path(output_dir).resolve()
    return {
        "matrix_types_generated": matrix_types,
        "output_directory": str(resolved_output),
        "log_tail": _tail(buf.getvalue()),
    }


@mcp.tool()
def assign_signatures(
    samples: str,
    output: Optional[str] = None,
    genome_build: str = "GRCh37",
    cosmic_version: float = 3.4,
    signatures: Optional[str] = None,
    input_type: str = "matrix",
    exome: bool = False,
) -> dict:
    """Assign known COSMIC (or custom) mutational signatures to samples.

    Args:
        samples: Path to a mutational matrix file (or VCF/MAF directory if
            input_type is not "matrix") to decompose into signatures.
        output: Directory to write results (activities, plots, probabilities).
            Defaults to OUTPUT_DIR/<samples name>_assign.
        genome_build: Genome build of the samples, e.g. GRCh37, GRCh38.
        cosmic_version: Which COSMIC signature reference set to fit against.
        signatures: Optional path to a custom signatures file. If omitted,
            the bundled COSMIC signature database is used.
        input_type: "matrix", "vcf", or "seg" depending on the samples format.
        exome: Whether the samples are exome-restricted.
    """
    from SigProfilerAssignment import Analyzer as Analyze

    if output is None:
        output = _default_output_dir(f"{Path(samples).stem}_assign")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        Analyze.cosmic_fit(
            samples=samples,
            output=output,
            signatures=signatures,
            genome_build=genome_build,
            cosmic_version=cosmic_version,
            input_type=input_type,
            exome=exome,
        )
    return {
        "output_directory": str(Path(output).resolve()),
        "log_tail": _tail(buf.getvalue()),
    }


@mcp.tool()
def extract_signatures(
    input_data: str,
    output: Optional[str] = None,
    input_type: str = "matrix",
    reference_genome: str = "GRCh37",
    minimum_signatures: int = 1,
    maximum_signatures: int = 5,
    nmf_replicates: int = 20,
    cpu: int = -1,
) -> dict:
    """De novo extract mutational signatures from a mutational catalogue.

    This is the most expensive tool -- it runs many NMF replicates per
    candidate signature count and can take from minutes to hours depending
    on maximum_signatures and nmf_replicates. Start with small values
    (e.g. maximum_signatures=5, nmf_replicates=20) to sanity check a run
    before scaling up.

    Args:
        input_data: Path to a mutational matrix file, or a directory of
            VCF/MAF files if input_type is not "matrix".
        output: Directory to write extraction results. Defaults to
            OUTPUT_DIR/<input_data name>_extract.
        input_type: "matrix", "vcf", or "seg".
        reference_genome: Genome build, e.g. GRCh37, GRCh38.
        minimum_signatures: Smallest number of signatures to try extracting.
        maximum_signatures: Largest number of signatures to try extracting.
        nmf_replicates: Number of NMF replicates per signature count.
        cpu: Number of CPUs to use, -1 for all available.
    """
    from SigProfilerExtractor import sigpro as sig
    import os

    use_gpu_env = os.environ.get("USE_GPU", "True").strip().lower()
    should_use_gpu = use_gpu_env in ("true", "1", "yes")

    if output is None:
        output = _default_output_dir(f"{Path(input_data).stem}_extract")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sig.sigProfilerExtractor(
            input_type,
            output,
            input_data,
            reference_genome=reference_genome,
            minimum_signatures=minimum_signatures,
            maximum_signatures=maximum_signatures,
            nmf_replicates=nmf_replicates,
            cpu=cpu,
            gpu=should_use_gpu, # 2. Pass the dynamic boolean here
        )
    return {
        "output_directory": str(Path(output).resolve()),
        "log_tail": _tail(buf.getvalue()),
    }


_PLOT_FUNCTIONS_WITH_CONTEXT = {"SBS", "DBS", "ID"}
_PLOT_FUNCTIONS_WITHOUT_CONTEXT = {"CNV", "SV"}


@mcp.tool()
def plot_signatures(
    matrix_path: str,
    project: str,
    mutation_type: str,
    output_path: Optional[str] = None,
    plot_type: Optional[str] = None,
    percentage: bool = False,
) -> dict:
    """Plot a mutational matrix or signature as a PDF.

    Args:
        matrix_path: Path to the matrix file to plot (e.g. output of
            generate_matrix or a signatures file from extract_signatures).
        project: Name of the sample set, used in the plot title/filename.
        mutation_type: One of "SBS", "DBS", "ID", "CNV", "SV" -- selects
            which plotting routine to use.
        output_path: Directory to write the plot PDF into. Defaults to
            OUTPUT_DIR/<project>_plots.
        plot_type: Required for SBS/DBS/ID -- the context size of the
            matrix, e.g. "96", "288", "384", "1536" for SBS. Ignored for
            CNV/SV.
        percentage: Show the y-axis as a percentage instead of raw counts.
    """
    import sigProfilerPlotting as sigPlt

    if output_path is None:
        output_path = _default_output_dir(f"{project}_plots")

    mutation_type = mutation_type.upper()
    buf = io.StringIO()

    if mutation_type in _PLOT_FUNCTIONS_WITH_CONTEXT:
        if not plot_type:
            raise ValueError(f"plot_type is required for mutation_type={mutation_type}")
        plot_fn = {"SBS": sigPlt.plotSBS, "DBS": sigPlt.plotDBS, "ID": sigPlt.plotID}[mutation_type]
        with contextlib.redirect_stdout(buf):
            plot_fn(matrix_path, output_path, project, plot_type, percentage=percentage)
    elif mutation_type in _PLOT_FUNCTIONS_WITHOUT_CONTEXT:
        plot_fn = {"CNV": sigPlt.plotCNV, "SV": sigPlt.plotSV}[mutation_type]
        with contextlib.redirect_stdout(buf):
            plot_fn(matrix_path, output_path, project, percentage=percentage)
    else:
        raise ValueError(f"Unknown mutation_type: {mutation_type!r}")

    return {
        "output_directory": str(Path(output_path).resolve()),
        "log_tail": _tail(buf.getvalue()),
    }


_SBS4608_PAGE_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px 24px 60px; background: #fafafa; line-height: 1.5; }}
h1 {{ font-size: 1.3rem; }}
h2 {{ border-top: 2px solid #ddd; padding-top: 20px; margin-top: 50px; font-size: 1.05rem; }}
nav.toc {{
  position: sticky; top: 0; z-index: 10;
  background: #fff; border: 1px solid #ddd; border-radius: 6px;
  padding: 10px 14px; margin: 16px 0 24px; display: flex; gap: 10px; flex-wrap: wrap;
  align-items: center;
}}
nav.toc span.label {{ font-weight: 600; color: #555; font-size: 0.85rem; margin-right: 4px; }}
nav.toc a {{
  text-decoration: none; color: #1a4fa0; font-size: 0.85rem;
  padding: 4px 10px; border: 1px solid #cddaf0; border-radius: 999px; background: #f2f6ff;
}}
nav.toc a:hover {{ background: #e2ecff; }}
.legend {{
  display: flex; gap: 14px; flex-wrap: wrap; align-items: center;
  background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 10px 14px; margin-bottom: 24px;
}}
.legend .swatch {{ display: inline-flex; align-items: center; gap: 6px; font-size: 0.85rem; color: #333; }}
.legend .dot {{ width: 12px; height: 12px; border-radius: 3px; display: inline-block; border: 1px solid rgba(0,0,0,0.15); }}
.plot {{ background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 8px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<nav class="toc">
<span class="label">Jump to signature:</span>
{toc_links}
</nav>
<div class="legend">
<span class="label" style="margin-right:0;">Substitution type colors:</span>
{legend_swatches}
</div>
{sections}
<script>
{plot_calls}
</script>
</body>
</html>
"""


@mcp.tool()
def plot_signatures_interactive(
    matrix_path: str,
    project: str,
    output_path: Optional[str] = None,
    signatures: Optional[list] = None,
    include_detailed_heatmaps: bool = True,
) -> dict:
    """Build an interactive multi-panel HTML plot for SBS-4608 (pentanucleotide
    + strand) mutational signatures.

    Unlike plot_signatures (a static PDF of just the bar profile), this
    combines, per signature, in one Plotly figure: the 96-context bar
    profile, "front"/"back" pentanucleotide detail heatmaps, a total heatmap
    with Transcribed/Untranscribed/intergenic hover proportions, and stacked
    Transcribed-vs-Untranscribed + Genic-vs-Intergenic strand-bias bars.

    Args:
        matrix_path: Path to a *_Signatures.txt (or matrix) file whose
            mutationType rows are strand-tagged pentanucleotide contexts,
            e.g. "T:AA[C>A]AA" (4608 rows per signature: 6 substitutions x
            16 x 16 flanking-dinucleotide combos x 3 strand tags T/U/N).
            Not the same as a plain 96/288/384/1536-context matrix -- use
            plot_signatures for those.
        project: Name for this run, used in the output filename and page title.
        output_path: Directory to write the HTML into. Defaults to
            OUTPUT_DIR/<project>_plots.
        signatures: Which signature columns to plot. Defaults to every
            column in the file other than MutationType.
        include_detailed_heatmaps: Include the front/back pentanucleotide
            detail heatmaps (in addition to the total heatmap).
    """
    import json
    from sigprofiler_mcp.sbs4608.sbs4608_data import SBS4608Data, load_raw4608
    from sigprofiler_mcp.sbs4608.sbs4608_plot_config import SBS4608PlotConfig, SBS_COLOR
    from sigprofiler_mcp.sbs4608.sbs4608_plot_builder import SBS4608PlotBuilder

    matrix_file = Path(matrix_path).expanduser().resolve()
    if not matrix_file.is_file():
        raise ValueError(f"matrix_path does not exist: {matrix_file}")

    with open(matrix_file) as f:
        header = f.readline().rstrip("\n").split("\t")
    available_columns = [c for c in header if c != "MutationType"]
    sig_columns = signatures or available_columns
    missing = [s for s in sig_columns if s not in available_columns]
    if missing:
        raise ValueError(
            f"Signature(s) not found in {matrix_file}: {missing}. "
            f"Available columns: {available_columns}"
        )

    if output_path is None:
        output_path = _default_output_dir(f"{project}_plots")
    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{project}_interactive.html"

    sections = []
    plot_calls = []
    for sig in sig_columns:
        raw4608 = load_raw4608(str(matrix_file), sig)
        data = SBS4608Data(raw4608, sig, main_plot_type="default")
        config = SBS4608PlotConfig(
            include_detailed_heatmaps=include_detailed_heatmaps, main_plot_type="default"
        )
        builder = SBS4608PlotBuilder(data, config)
        fig = builder.build()
        div_id = f"plot-{sig}"
        sections.append(f'<h2 id="{sig}">{sig}</h2>\n<div class="plot" id="{div_id}"></div>')
        plot_calls.append(
            f'Plotly.newPlot("{div_id}", {json.dumps(fig["traces"])}, '
            f'{json.dumps(fig["layout"])}, {json.dumps(fig["config"])});'
        )

    legend_swatches = "\n".join(
        f'<span class="swatch"><span class="dot" style="background:{color};"></span>{mutation}</span>'
        for mutation, color in SBS_COLOR.items()
    )
    toc_links = "\n".join(f'<a href="#{sig}">{sig}</a>' for sig in sig_columns)
    title = f"{project} -- interactive SBS-4608 signature plots"

    html = _SBS4608_PAGE_TEMPLATE.format(
        title=title,
        toc_links=toc_links,
        legend_swatches=legend_swatches,
        sections="\n".join(sections),
        plot_calls="\n".join(plot_calls),
    )
    out_file.write_text(html, encoding="utf-8")

    return {
        "output_file": str(out_file.resolve()),
        "signatures_plotted": sig_columns,
    }


@mcp.tool()
def plot_signatures_static(
    matrix_path: str,
    project: str,
    output_path: Optional[str] = None,
    signatures: Optional[list] = None,
    include_detailed_heatmaps: bool = True,
) -> dict:
    """Build a static (non-interactive) PDF version of the SBS-4608 plot.

    Same multi-panel figure as plot_signatures_interactive -- per signature,
    in one figure: the 96-context bar profile, "front"/"back" pentanucleotide
    detail heatmaps, a total heatmap, and stacked Transcribed-vs-Untranscribed
    + Genic-vs-Intergenic strand-bias bars -- but rendered as a static PDF
    (one page per signature) instead of an interactive HTML page. Use this
    when the plot needs to go into a manuscript, a print handout, or anywhere
    an HTML file with embedded JavaScript isn't practical; use
    plot_signatures_interactive when the viewer needs hover tooltips or the
    Main Plot Type / plot-options controls.

    Requires the `kaleido` package for static rendering, plus a local
    Chrome/Chromium install. kaleido finds an existing Chrome/Chromium
    automatically on most machines; if it can't, run `plotly_get_chrome`
    once (works on macOS, Windows, and Linux x86-64).

    Args:
        matrix_path: Path to a *_Signatures.txt (or matrix) file whose
            mutationType rows are strand-tagged pentanucleotide contexts,
            e.g. "T:AA[C>A]AA" (4608 rows per signature). Same format as
            plot_signatures_interactive expects.
        project: Name for this run, used in the output filename and the
            per-page signature title.
        output_path: Directory to write the PDF into. Defaults to
            OUTPUT_DIR/<project>_plots.
        signatures: Which signature columns to plot. Defaults to every
            column in the file other than MutationType.
        include_detailed_heatmaps: Include the front/back pentanucleotide
            detail heatmaps (in addition to the total heatmap).
    """
    import tempfile

    import kaleido
    import plotly.graph_objects as go
    from pypdf import PdfWriter

    from sigprofiler_mcp.sbs4608.sbs4608_data import SBS4608Data, load_raw4608
    from sigprofiler_mcp.sbs4608.sbs4608_plot_builder import SBS4608PlotBuilder
    from sigprofiler_mcp.sbs4608.sbs4608_plot_config import SBS4608PlotConfig

    matrix_file = Path(matrix_path).expanduser().resolve()
    if not matrix_file.is_file():
        raise ValueError(f"matrix_path does not exist: {matrix_file}")

    with open(matrix_file) as f:
        header = f.readline().rstrip("\n").split("\t")
    available_columns = [c for c in header if c != "MutationType"]
    sig_columns = signatures or available_columns
    missing = [s for s in sig_columns if s not in available_columns]
    if missing:
        raise ValueError(
            f"Signature(s) not found in {matrix_file}: {missing}. "
            f"Available columns: {available_columns}"
        )

    if output_path is None:
        output_path = _default_output_dir(f"{project}_plots")
    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{project}.pdf"

    # Plotly.js silently falls back to its schema default ("auto") for an
    # invalid annotation xanchor/yanchor value, which is how the interactive
    # HTML path renders fine even though some annotations here use "bottom"/
    # "top" for xanchor (not a valid enum member). The Python graph_objects
    # validator used for static rendering is strict, so normalize first --
    # this reproduces the same fallback the browser already applies, rather
    # than changing how anything looks.
    valid_anchors = {"auto", "left", "center", "right"}

    writer = PdfWriter()
    with tempfile.TemporaryDirectory() as tmp_dir:
        for sig in sig_columns:
            raw4608 = load_raw4608(str(matrix_file), sig)
            data = SBS4608Data(raw4608, sig, main_plot_type="default")
            config = SBS4608PlotConfig(
                include_detailed_heatmaps=include_detailed_heatmaps, main_plot_type="default"
            )
            builder = SBS4608PlotBuilder(data, config)
            fig_dict = builder.build()

            layout = dict(fig_dict["layout"])
            annotations = [dict(a) for a in layout.get("annotations", [])]
            for ann in annotations:
                if ann.get("xanchor") not in valid_anchors:
                    ann["xanchor"] = "auto"
            layout["annotations"] = annotations

            fig = go.Figure(data=fig_dict["traces"], layout=layout)
            page_path = Path(tmp_dir) / f"{sig}.pdf"
            kaleido.write_fig_sync(fig, path=str(page_path))
            writer.append(str(page_path))

        with open(out_file, "wb") as f:
            writer.write(f)

    return {
        "output_file": str(out_file.resolve()),
        "signatures_plotted": sig_columns,
    }


@mcp.tool()
def get_viewer_url() -> dict:
    """Get the URL of the SigProfiler results web viewer.

    The viewer runs in a separate, persistent container (started
    independently of this MCP server) so its address stays fixed
    regardless of how many MCP connections are active.
    """
    return {
        "url": "http://localhost:8501",
        "note": (
            "Shows plots for signature files under OUTPUT_DIR. "
            "Requires the standalone sigprofiler-viewer container to be running."
        ),
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
