# pmc-reuse-analysis

Mining PubMed Central (PMC) full-text literature to measure reuse of public
proteomics datasets, and downstream machine-learning analysis of a proteomics
tissue atlas.

## Overview

The project has two analysis tracks:

1. **PRIDE dataset reuse in the literature**
   Searches PMC for full-text articles and supplementary materials, extracts
   PRIDE proteomics identifiers (`PXD`/`PRD` accessions), and builds a
   deduplicated, enriched table of where public PRIDE datasets are referenced
   and reused. Uses the NCBI E-utilities / PMC and BioC APIs with incremental
   CSV checkpointing for large, year-by-year collection.

2. **Cell-type / tissue predictors**
   Trains classifiers (XGBoost) on a filtered proteomics tissue atlas to predict
   tissue of origin, including class-balancing and feature selection.

## Repository structure

```
.
├── notebooks/        # Analysis notebooks
│   ├── pride_pmc_reuse_analysis.ipynb   # PMC → PRIDE identifier mining pipeline
│   └── cell_type_predictors.ipynb       # Tissue-atlas ML classifiers
├── data/
│   ├── raw/          # Input data (not tracked)
│   └── processed/    # Derived/intermediate data (not tracked)
├── results/          # Figures, tables, model outputs (not tracked)
├── requirements.txt
├── .gitignore
└── README.md
```

`data/` and `results/` contents are git-ignored; only the directory structure is
tracked. Regenerate them by running the notebooks.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The cell-type predictor notebook reads from a MySQL database; set connection
details via environment variables / a local `.env` (not committed).

## Usage

Launch Jupyter and run the notebooks in `notebooks/`:

```bash
jupyter lab
```

Start with `pride_pmc_reuse_analysis.ipynb` for the literature-mining pipeline.
