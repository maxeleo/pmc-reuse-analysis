# pmc-reuse-analysis

Mining PubMed Central (PMC) full-text literature to measure reuse of public
proteomics datasets deposited in PRIDE.

## Overview

This project searches PMC for full-text articles and supplementary materials,
extracts PRIDE proteomics identifiers (`PXD`/`PRD` accessions), and builds a
deduplicated, enriched table of where public PRIDE datasets are referenced and
reused. Uses the NCBI E-utilities / PMC and BioC APIs with incremental CSV
checkpointing for large, year-by-year collection.

## Repository structure

```
.
├── notebooks/
│   └── pride_pmc_reuse_analysis.ipynb   # Full literature-mining pipeline
├── data/
│   ├── raw/          # Input data (not tracked)
│   └── processed/    # Derived/intermediate data (not tracked)
├── results/          # Figures, tables, outputs (not tracked)
├── requirements.txt
├── .gitignore
└── README.md
```

`data/` and `results/` contents are git-ignored; only the directory structure
is tracked via `.gitkeep`. Regenerate by running the notebook.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root (never committed):

```
NCBI_API_KEY=your_ncbi_api_key
USER_EMAIL=your_email@example.com
```

## Usage

```bash
jupyter lab
```

Open `notebooks/pride_pmc_reuse_analysis.ipynb` and run cells top to bottom.

## Pipeline stages

| Section | Description |
|---|---|
| 1. Search | `fetch_pmc_ids` — query PMC eSearch for article IDs by term + date range |
| 2. Extract | `fetch_xml_content` + `find_pride_ids` — batch XML fetch, regex for PXD/PRD |
| 3. Collect | `run_full_pride_analysis` — batched pipeline with incremental CSV checkpointing |
| 4. Scale | `run_massive_analysis_by_years` — year-by-year to bypass the 10k API limit |
| 5. Merge | `merge_pride_files` / `merge_with_duplicate_analysis` — deduplication |
| 6. Verify | `verify_and_update_pride_ids_range` — BioC API + OA supplementary archive search |
| 7. Stats | `compute_pride_frequency` — PRIDE ID frequency table |

## Related projects

- Cell-type / tissue predictors (XGBoost on proteomics tissue atlas):
  [CompOmics/Tissue_prediction_manuscript](https://github.com/CompOmics/Tissue_prediction_manuscript)
