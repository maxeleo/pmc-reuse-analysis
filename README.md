# pmc-reuse-analysis

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Mining PubMed Central (PMC) full-text literature to measure reuse of public
proteomics datasets deposited in PRIDE.

## Overview

Searches PMC for full-text articles, extracts PRIDE identifiers
(`PXD######` / `PRD######`) via regex over article XML, and builds a
deduplicated frequency table showing how often each public PRIDE dataset is
referenced across the literature.

Collection uses a year-by-year strategy to bypass the NCBI eSearch hard cap
of 9,999 results per request. Optional BioC full-text verification catches
identifiers missed in the primary XML pass.

## Repository structure

```
.
├── notebooks/
│   └── pride_pmc_reuse_analysis.ipynb   # Full literature-mining pipeline
├── data/
│   └── raw/                             # Downloaded articles and CSVs
├── results/                             # Figures, frequency tables
├── examples/
│   └── sample_output.csv        # Example output (10 rows)
├── requirements.txt
├── HOWTO.md
├── CITATION.cff
├── LICENSE
├── .gitignore
└── README.md
```

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set NCBI_API_KEY and USER_EMAIL
jupyter lab             # open notebooks/pride_pmc_reuse_analysis.ipynb
```

See [HOWTO.md](HOWTO.md) for the full function reference and output file descriptions.
Release history is in [CHANGELOG.md](CHANGELOG.md).

## Related projects

- Cell-type / tissue predictors (XGBoost on proteomics tissue atlas):
  [CompOmics/Tissue_prediction_manuscript](https://github.com/CompOmics/Tissue_prediction_manuscript)
