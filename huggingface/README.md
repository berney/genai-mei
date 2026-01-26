# Hugging Face Model Downloader

This project provides a tool to download Hugging Face models based on a YAML configuration file.

## Configuration

The configuration file (`huggingface.yaml`) defines model repositories and optional include/exclude/ref settings.

Example lock file:

```yaml
models:
  # Example just repo
  - repo: my-org/my-model
  # Example repo + include pattern
  - repo: my-org/my-model
    include: path/to/files/*
  # Example repo + include + exclude + ref
  - repo: my-org/my-model
    include: path/to/files/*
    exclude: path/to/ignore/*
    ref: v1.2.3
```

Each entry mirrors the options of the `hf download` CLI. The script prints the equivalent `hf download` command for each model, performs the download (unless `--dry-run` is given), and finally runs `hf cache ls` and `hf cache verify` to list and verify the local cache.

## Usage

```bash
python download_models.py [lock_file]
```

Options:
- `--dry-run`: Print the hf download commands without performing the download
- `--version`: Print the package version and exit