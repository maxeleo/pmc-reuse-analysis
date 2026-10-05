# HOWTO — pmc-reuse-analysis

Technical guide to running the pipeline and understanding the code.

---

## Setup

```bash
git clone https://github.com/maxeleo/pmc-reuse-analysis.git
cd pmc-reuse-analysis

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env` in the project root:

```
NCBI_API_KEY=your_key_here
USER_EMAIL=your_email@example.com
```

`NCBI_API_KEY` raises the NCBI rate limit from 3 to 10 requests/second.
Free key: https://www.ncbi.nlm.nih.gov/account/

---

## Running the notebook

```bash
jupyter lab
```

Open `notebooks/pride_pmc_reuse_analysis.ipynb`. **Run cells top to bottom** — each cell depends on functions defined in earlier ones.

---

## Fetching and extraction

| Function | Description |
|---|---|
| `fetch_pmc_ids` | Queries PMC via eSearch, returns a list of numeric article IDs |
| `fetch_xml_content` | Downloads full-text XML for a batch of IDs; retries up to 3 times on network errors |
| `extract_article_info` | Pulls PMCID and title from an article XML node |
| `find_pride_ids` | Scans article text for PRIDE identifiers (`PXD######` / `PRD######`) |
| `extract_supplementary_info` | Lists supplementary file types from XML metadata |
| `process_single_batch` | One call = one batch of articles → list of found identifiers |

---

## Full corpus collection

```python
run_massive_analysis_by_years("Ovarian cancer proteomics", api_key=API_KEY)
```

NCBI eSearch returns at most **9,999 articles** per request — a hard server-side cap
regardless of the `retmax` value. Splitting by year works around this: each year is
a separate request with `limit=50000`, and results are appended to a single CSV
(`massive_analysis_{ts}.csv`). If the run is interrupted, data for completed years
is preserved.

Years in the pipeline: 2022–2026. To change the range, edit the `years` list in the function.

---

## Merge and deduplicate

If there were multiple runs or partial files to combine:

```python
# N files — full row deduplication
merge_pride_files(["run1.csv", "run2.csv", "run3.csv"])

# 2 files — deduplicate by PRIDE_ID + PMCID pair
merge_with_duplicate_analysis("a.csv", "b.csv")
```

---

## BioC verification (optional)

```python
verify_and_update_pride_ids_range(
    input_csv="massive_analysis_final.csv",
    start_row=0,
    end_row=500
)
```

For each row, queries the BioC full-text API and adds any PRIDE identifiers missed
by the main pipeline. BioC indexes the complete article text including tables and
figure captions.

> The NCBI OA supplementary archive API (`oa.fcgi`) was retired in August 2026
> and has been removed from this codebase. Verification is BioC-only.

---

## Frequency statistics

```python
compute_pride_frequency("massive_analysis_final.csv")
```

Counts how many times each PRIDE identifier appears across the corpus.
Writes `pride_id_frequency.csv`.

---

## Output files

| File | Source |
|---|---|
| `massive_analysis_{ts}.csv` | `run_massive_analysis_by_years` |
| `merged_pride_data.csv` | `merge_pride_files` |
| `merged_pride_analysis.csv` | `merge_with_duplicate_analysis` |
| `*_verified_rows_*.csv` | `verify_and_update_pride_ids_range` |
| `pride_id_frequency.csv` | `compute_pride_frequency` |
