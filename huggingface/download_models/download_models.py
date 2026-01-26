#!/usr/bin/env python3
"""Download models defined in a huggingface.yaml manifest file.

The manifest file format (YAML)::

    models:
      - repo: owner/model-repo
        ref: main                # optional, defaults to "main"
        include: "*.gguf"        # optional glob pattern (or list of patterns)
        exclude: "*.ckpt"        # optional glob pattern (or list of patterns)

Each entry mirrors the options of the ``hf download`` CLI.  The script prints the
equivalent ``hf download`` command for each model, performs the download (unless
``--dry-run`` is given), and finally runs ``hf cache ls`` and ``hf cache verify``
to list and verify the local cache.
"""

import argparse
import logging
import subprocess
import sys
import difflib
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from importlib.metadata import version, PackageNotFoundError

import yaml
from huggingface_hub import snapshot_download

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def load_manifest(file_path: Path) -> Dict[str, Any]:
    """Load the manifest file.

    Returns a dictionary with at least a ``models`` key (list).  If the file does
    not exist or cannot be parsed, the function exits with an error message.
    """
    if not file_path.is_file():
        sys.exit(f"Manifest file not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            sys.exit(f"Failed to parse manifest file {file_path}: {exc}")
    return data


def build_hf_command(
    repo: str,
    ref: Optional[str] = None,
    include: Optional[Union[str, List[str]]] = None,
    exclude: Optional[Union[str, List[str]]] = None,
) -> str:
    """Construct the equivalent ``hf download`` CLI command.

    ``include`` and ``exclude`` can be a single glob string or a list of strings.
    """
    parts = ["hf", "download", repo]
    if ref:
        parts[-1] = f"{repo}@{ref}"
    if include:
        if isinstance(include, list):
            for pat in include:
                parts.extend(["--include", pat])
        else:
            parts.extend(["--include", include])
    if exclude:
        if isinstance(exclude, list):
            for pat in exclude:
                parts.extend(["--exclude", pat])
        else:
            parts.extend(["--exclude", exclude])
    return " ".join(parts)


def download_model(
    repo: str,
    ref: Optional[str] = None,
    include: Optional[Union[str, List[str]]] = None,
    exclude: Optional[Union[str, List[str]]] = None,
) -> None:
    """Download a model using ``huggingface_hub.snapshot_download``.

    ``include`` maps to ``allow_patterns`` and ``exclude`` to ``ignore_patterns``.
    The function relies on the default cache directory used by the hub.
    """
    # Normalise patterns for ``snapshot_download`` (expects lists)
    allow = [include] if isinstance(include, str) else (include or None)
    ignore = [exclude] if isinstance(exclude, str) else (exclude or None)

    logging.info(
        f"Downloading repo %s%s", repo, f"@{ref}" if ref else ""
    )
    snapshot_download(
        repo_id=repo,
        ref=ref or "main",
        allow_patterns=allow,
        ignore_patterns=ignore,
        local_dir=None,
    )
    # Get a new line because huggingface_hub has probably hasn't terminated the line
    print()


def get_cache_listing() -> List[str]:
    """Return a list of lines from ``hf cache ls`` output."""
    try:
        result = subprocess.run(
            ["hf", "cache", "ls"], check=True, text=True, capture_output=True
        )
        return result.stdout.splitlines()
    except subprocess.CalledProcessError as exc:
        logging.error("hf cache ls failed with exit code %s", exc.returncode)
        return []

def verify_cache(repo: str, ref: Optional[str] = None) -> None:
    """Run ``hf cache verify``; include ``--revision`` if provided."""
    cmd = ["hf", "cache", "verify", repo]
    if ref:
        cmd.extend(["--revision", ref])
    logging.info("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd, check=True, text=True, capture_output=True
        )
        sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
    except subprocess.CalledProcessError as exc:
        logging.error("Command %s failed with exit code %s", " ".join(cmd), exc.returncode)
        if exc.stdout:
            sys.stdout.write(exc.stdout)
        if exc.stderr:
            sys.stderr.write(exc.stderr)

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download models defined in a huggingface.yaml manifest file."
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        default="huggingface.yaml",
        help="Path to the manifest file (default: huggingface.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the hf download commands without performing the download",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the package version and exit",
    )
    args = parser.parse_args()
    if args.version:
        try:
            pkg_version = version("download-models")
        except PackageNotFoundError:
            pkg_version = "0.0.0"
        print(pkg_version)
        return
    # version already handled above

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    manifest_path = Path(args.manifest_file)
    data = load_manifest(manifest_path)
    models: List[Dict[str, Any]] = data.get("models", [])
    # placeholder for initial_cache default
    initial_cache = []  # default, will be set if models exist

    if not models:
        logging.info("No models defined in %s", manifest_path)
    else:
        # Capture initial cache state
        initial_cache = get_cache_listing()
        logging.info("\nInitial cache state:")
        for line in initial_cache:
            logging.info(line)

        for entry in models:
            repo = entry.get("repo")
            if not repo:
                logging.warning("Skipping entry without 'repo' key: %s", entry)
                continue
            ref = entry.get("ref")
            include = entry.get("include")
            exclude = entry.get("exclude")

            # Build and print the equivalent CLI command
            cmd_str = build_hf_command(
                repo=repo, ref=ref, include=include, exclude=exclude
            )
            logging.info("Equivalent command: %s", cmd_str)

            if not args.dry_run:
                download_model(
                    repo=repo, ref=ref, include=include, exclude=exclude
                )
                # Verify cache after each download, passing ref if present
                verify_cache(repo, ref=ref)

    # After all downloads (or dry‑run) show final cache state and diff
    final_cache = get_cache_listing()
    logging.info("\nFinal cache state:")
    for line in final_cache:
        logging.info(line)
    # Show diff
    diff = "".join(difflib.unified_diff(initial_cache, final_cache, fromfile='initial', tofile='final', lineterm=''))
    if diff:
        logging.info("\nCache changes (colourised):")
        for line in diff.splitlines():
            if line.startswith('+') and not line.startswith('+++'):
                logging.info(f"\x1b[32m{line}\x1b[0m")  # green
            elif line.startswith('-') and not line.startswith('---'):
                logging.info(f"\x1b[31m{line}\x1b[0m")  # red
            else:
                logging.info(line)


if __name__ == "__main__":
    main()
