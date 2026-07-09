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

    from SigProfilerMatrixGenerator import install as genInstall

    buf = io.StringIO()
    with _local_cwd(), contextlib.redirect_stdout(buf):
        genInstall.install(genome, bash=True)
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
            inside input_dir.
    """
    from SigProfilerMatrixGenerator.scripts import (
        SigProfilerMatrixGeneratorFunc as matGen,
    )

    input_path = _resolve_dir(input_dir)

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
    resolved_output = Path(output_dir).resolve() if output_dir else input_path / "output"
    return {
        "matrix_types_generated": matrix_types,
        "output_directory": str(resolved_output),
        "log_tail": _tail(buf.getvalue()),
    }


@mcp.tool()
def assign_signatures(
    samples: str,
    output: str,
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
        genome_build: Genome build of the samples, e.g. GRCh37, GRCh38.
        cosmic_version: Which COSMIC signature reference set to fit against.
        signatures: Optional path to a custom signatures file. If omitted,
            the bundled COSMIC signature database is used.
        input_type: "matrix", "vcf", or "seg" depending on the samples format.
        exome: Whether the samples are exome-restricted.
    """
    from SigProfilerAssignment import Analyzer as Analyze

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
    output: str,
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
        output: Directory to write extraction results.
        input_type: "matrix", "vcf", or "seg".
        reference_genome: Genome build, e.g. GRCh37, GRCh38.
        minimum_signatures: Smallest number of signatures to try extracting.
        maximum_signatures: Largest number of signatures to try extracting.
        nmf_replicates: Number of NMF replicates per signature count.
        cpu: Number of CPUs to use, -1 for all available.
    """
    from SigProfilerExtractor import sigpro as sig

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
    output_path: str,
    project: str,
    mutation_type: str,
    plot_type: Optional[str] = None,
    percentage: bool = False,
) -> dict:
    """Plot a mutational matrix or signature as a PDF.

    Args:
        matrix_path: Path to the matrix file to plot (e.g. output of
            generate_matrix or a signatures file from extract_signatures).
        output_path: Directory to write the plot PDF into.
        project: Name of the sample set, used in the plot title/filename.
        mutation_type: One of "SBS", "DBS", "ID", "CNV", "SV" -- selects
            which plotting routine to use.
        plot_type: Required for SBS/DBS/ID -- the context size of the
            matrix, e.g. "96", "288", "384", "1536" for SBS. Ignored for
            CNV/SV.
        percentage: Show the y-axis as a percentage instead of raw counts.
    """
    import sigProfilerPlotting as sigPlt

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


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
