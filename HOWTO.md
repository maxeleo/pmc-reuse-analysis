# HOWTO — pmc-reuse-analysis

Technical guide to running the pipeline, understanding the code, and verifying correctness.

---

## Setup

```bash
git clone https://github.com/maxeleo/pmc-reuse-analysis.git
cd pmc-reuse-analysis

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env` in the project root (never committed):

```
NCBI_API_KEY=your_key_here
USER_EMAIL=your_email@example.com
```

`NCBI_API_KEY` raises the NCBI rate limit from 3 to 10 requests/second.
`USER_EMAIL` is a courtesy parameter for the NCBI ID Converter.
Get a free API key at: https://www.ncbi.nlm.nih.gov/account/

---

## Running the notebook

```bash
jupyter lab
```

Open `notebooks/pride_pmc_reuse_analysis.ipynb` and run cells top to bottom.
**All cells must be executed in order** — later cells depend on functions defined earlier.

---

## Pipeline walkthrough

### Section 1 — Imports & Configuration

```python
config = {
    "term": "Ovarian cancer proteomics",   # PubMed search query
    "years": 5                              # lookback window
}
API_KEY = os.getenv("NCBI_API_KEY")        # loaded from .env
PRIDE_PATTERN = re.compile(r'P[XR]D\d{6}', re.IGNORECASE)
```

Adjust `config["term"]` for a different topic. The pattern matches both `PXD######` and `PRD######`.

---

### Section 2 — Logging

All pipeline output goes through `log` (Python `logging`). A timestamped `.log` file
is created in `logs/` on each session start.

```python
log.info(...)   # progress messages
log.debug(...)  # per-article details (enabled via debug=True)
log.warning(...)
log.error(...)
```

---

### Section 3 — Core API functions

| Function | API endpoint | Purpose |
|---|---|---|
| `fetch_pmc_ids` | NCBI eSearch | Query PMC, get article ID list |
| `fetch_xml_content` | NCBI eFetch | Download full-text XML for a batch of IDs |
| `extract_article_info` | — (XML parse) | Pull PMCID and title from an article node |
| `find_pride_ids` | — (regex) | Scan full article text for PXD/PRD accessions |
| `extract_supplementary_info` | — (XML parse) | List supplementary file extensions from metadata |

`fetch_xml_content` retries up to 3 times on `ConnectionError`, `ChunkedEncodingError`,
and `Timeout`. Any other exception aborts and returns `None`.

---

### Section 4 — Batch processing

`process_single_batch(batch_ids, api_key, supp_files_enabled)` ties the above together:

```
fetch_xml_content → for each <article>:
    extract_article_info
    find_pride_ids
    extract_supplementary_info (optional)
→ list of {PRIDE_ID, PMCID, Title, Chars, Supp_Ext} dicts
```

Returns `[]` if the XML fetch fails.

---

### Section 5 — Main pipeline

```python
run_full_pride_analysis(config, limit=200, api_key=API_KEY)
```

| Parameter | Default | Description |
|---|---|---|
| `limit` | 50 | Max articles to fetch |
| `batch_size` | 50 | Articles per eFetch request |
| `rate_limit_delay` | 0.2s | Sleep between batches |
| `supp_files` | True | Include supplementary metadata |
| `results_file` | auto | Output CSV path |
| `debug` | False | Verbose per-article logging |

Results are written **incrementally** — the CSV is appended after each batch,
so a crash does not lose all work.

---

### Section 6 — Year-by-year collection

```python
run_massive_analysis_by_years("Ovarian cancer proteomics", api_key=API_KEY)
```

The NCBI eSearch API returns at most 10,000 results per request. This function
splits the search by calendar year (2022–2026) to collect the full corpus.
Use this for production runs; `run_full_pride_analysis` is for exploration.

---

### Section 7 — Merge & deduplicate

Two merge strategies:

| Function | Use when |
|---|---|
| `merge_pride_files(files)` | Merging 3+ CSVs; full row deduplication |
| `merge_with_duplicate_analysis(f1, f2)` | Merging 2 CSVs; dedup by PRIDE_ID + PMCID pair |

Both write a deduplicated CSV and return a DataFrame.

---

### Section 8 — BioC verification

```python
verify_and_update_pride_ids_range(
    input_csv="merged_pride_analysis_final.csv",
    start_row=0,
    end_row=500
)
```

For each row in the range, `process_single_article` queries the BioC full-text API
and updates the `PRIDE_ID` column with any newly found accessions.

> **API status (October 2026):** BioC full-text (`bionlp/RESTful/pmcoa.cgi`) is active.
> The OA supplementary archive API (`oa.fcgi`) was retired by NCBI in August 2026
> and has been removed from this codebase.

Helper functions in this section:

| Function | Purpose |
|---|---|
| `extract_pride_ids_from_content(content)` | PRIDE regex on raw text or bytes |
| `get_pmcid_from_pmid(pmid)` | Convert PMID → PMCID via ID Converter (XML, new endpoint) |
| `parse_pmcid_from_string(s)` | Normalise PMCID strings (`PMC###`, `PMID:###`, bare digit) |

---

### Section 9 — Frequency statistics

```python
compute_pride_frequency("merged_pride_analysis_final.csv")
```

Counts how many times each PRIDE accession appears across all articles.
Writes `pride_id_frequency.csv` and logs the top 20.

---

## API dependency status

| Service | Base URL | Status (Oct 2026) |
|---|---|---|
| NCBI eSearch | `eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi` | ✅ active |
| NCBI eFetch | `eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi` | ✅ active |
| BioC full-text | `ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi` | ✅ active |
| ID Converter | `pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/` | ✅ active (new endpoint) |
| OA archive | `ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi` | ❌ retired Aug 2026 |

---

## Testing

### Unit tests (no network, instant)

```bash
.venv/bin/python -m pytest execution/test_pride_analysis.py -v
```

65 tests. All HTTP calls are mocked. Covers every function in the notebook.

### Integration audit (real API calls, ~30s)

```bash
.venv/bin/python execution/audit_notebook.py
```

Makes small live requests to NCBI to verify each pipeline section end-to-end.
Prints `✓ PASS / ⚠ WARN / ✗ FAIL` per section with a release recommendation.

**Expected output (October 2026):**

```
✓ PASS  fetch_pmc_ids
✓ PASS  fetch_xml_content
✓ PASS  extract_article_info
✓ PASS  find_pride_ids
✓ PASS  extract_supplementary_info
✓ PASS  process_single_batch
✓ PASS  get_pmcid_from_pmid
✓ PASS  merge + frequency
⚠ WARN  BioC API            ← works; small test sample had no PRIDE IDs in text
✗ FAIL  OA archive (oa.fcgi) ← retired; removed from notebook
```

> Both test files are gitignored (`execution/`) and not part of the published repository.

---

## Output files

| File | Description |
|---|---|
| `pride_analysis_L{N}_{ts}.csv` | Raw results from `run_full_pride_analysis` |
| `massive_analysis_{ts}.csv` | Raw results from `run_massive_analysis_by_years` |
| `merged_pride_data.csv` | Output of `merge_pride_files` |
| `merged_pride_analysis.csv` | Output of `merge_with_duplicate_analysis` |
| `*_verified_rows_*.csv` | Output of `verify_and_update_pride_ids_range` |
| `pride_id_frequency.csv` | Output of `compute_pride_frequency` |
| `logs/session_{ts}.log` | Timestamped log file for each session |

All output files are gitignored (`data/`, `results/`, `*.log`).

---

## Recommended workflow

```
1. Set config["term"] for your query
2. Run Section 1–5 with limit=200 to validate the pipeline returns results
3. Run Section 6 (run_massive_analysis_by_years) for full corpus collection
4. Run Section 7 to merge partial runs and remove duplicates
5. Run Section 8 on the merged file for BioC verification (optional enrichment)
6. Run Section 9 to compute frequency statistics
```
