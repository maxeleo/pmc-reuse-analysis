# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Branch and release model

- `main` — only tagged, tested releases
- `debug/*`, `feature/*` — in-progress work
- Tags: `vMAJOR.MINOR.PATCH` on each merge to `main`

## [Unreleased]

### Fixed
- (in progress on `debug/hang-on-year-collection`) silent hang near the end of
  a year during `run_massive_analysis_by_years` — CSV stops growing while the
  tqdm bar sits at ~97%; cause under investigation

## [0.1.0] — 2026-10-08

Initial public release — single notebook, year-by-year collection pipeline.

### Added
- `notebooks/pride_pmc_reuse_analysis.ipynb` — full pipeline:
  PMC search, XML full-text extraction, PRIDE identifier regex,
  year-by-year collection to bypass the 9,999-result eSearch cap,
  BioC-based enrichment, deduplication, frequency statistics
- `HOWTO.md`, `README.md`, `LICENSE` (MIT), `CITATION.cff`
- Pinned dependencies in `requirements.txt`
- Example output in `examples/sample_output.csv`

### Known issues
- `run_massive_analysis_by_years` may hang near the end of a year on large
  corpora without raising an exception — investigation on
  `debug/hang-on-year-collection`
