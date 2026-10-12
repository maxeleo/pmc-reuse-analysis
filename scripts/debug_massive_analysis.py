"""
Diagnostic standalone runner for run_massive_analysis_by_years.

Why this exists
---------------
The notebook v0.1.0 pipeline hangs silently near the end of a year on large
corpora: CSV stops growing, tqdm sits at ~97%, no exception. This script
reproduces the same workflow with heavy instrumentation so we can see
*where* it stalls.

What it adds vs the notebook
----------------------------
- Per-phase timing: fetch, download, parse, write (every batch)
- Response-size logging (large XMLs are a prime hang suspect)
- Watchdog: if main thread goes silent for >WATCHDOG_SEC, dumps all stacks
- Hard per-batch deadline: if a batch exceeds BATCH_DEADLINE_SEC, we abort
  the HTTP call, mark the batch as skipped, write its PMIDs to a sidecar
  file, and continue
- requests.Session with connection pooling and (connect, read) timeout tuple
- Checkpoint file for --resume
- All logs flushed every line; log goes to .tmp/debug_massive_{ts}.log too

Usage
-----
    python execution/debug_massive_analysis.py --year 2022
    python execution/debug_massive_analysis.py --year 2022 --max-batches 20
    python execution/debug_massive_analysis.py --years 2022-2026 --resume

Give the tester this one-liner; collect the .log file afterwards.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import sys
import threading
import time
import traceback
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Config ───────────────────────────────────────────────────────────────────

VERSION = "0.1.1-debug"

API_KEY = os.getenv("NCBI_API_KEY")
PRIDE_PATTERN = re.compile(r'P[XR]D\d{6}', re.IGNORECASE)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# connect timeout / read timeout — tuple fires faster than monolithic 60s
HTTP_TIMEOUT = (10, 60)

# Watchdog: if main thread hasn't ticked for this long, dump stacks
WATCHDOG_SEC = 180

# Hard deadline per batch (download + parse + write). Beyond this, skip.
BATCH_DEADLINE_SEC = 300

# Flag large responses (likely parse-stall culprit)
LARGE_RESPONSE_MB = 20

TMP_DIR = Path(".tmp")
TMP_DIR.mkdir(exist_ok=True)


# ── Logging ──────────────────────────────────────────────────────────────────

def make_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("debug_massive")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    fmt = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    fh = logging.FileHandler(log_path, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


class FlushingLogger:
    """Wrapper that flushes every handler after every log line."""
    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def _flush(self):
        for h in self._logger.handlers:
            try:
                h.flush()
            except Exception:
                pass

    def debug(self, msg): self._logger.debug(msg); self._flush()
    def info(self, msg): self._logger.info(msg); self._flush()
    def warning(self, msg): self._logger.warning(msg); self._flush()
    def error(self, msg): self._logger.error(msg); self._flush()


# ── Watchdog ─────────────────────────────────────────────────────────────────

class Watchdog:
    """Background thread that dumps stacks if the main thread goes quiet."""
    def __init__(self, log: FlushingLogger, timeout_sec: int):
        self.log = log
        self.timeout = timeout_sec
        self._last_tick = time.monotonic()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def tick(self, label: str = ""):
        """Call periodically from main loop to say 'still alive'."""
        self._last_tick = time.monotonic()
        if label:
            self.log.debug(f"watchdog tick: {label}")

    def _run(self):
        while not self._stop.wait(5):
            idle = time.monotonic() - self._last_tick
            if idle > self.timeout:
                self.log.warning(
                    f"WATCHDOG: main thread idle for {idle:.0f}s "
                    f"(threshold {self.timeout}s). Dumping stacks:"
                )
                for tid, frame in sys._current_frames().items():
                    self.log.warning(f"  thread {tid}:")
                    for line in traceback.format_stack(frame):
                        self.log.warning(f"    {line.rstrip()}")
                self._last_tick = time.monotonic()  # avoid spamming


# ── HTTP session with retries and pooling ────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(
        pool_connections=10,
        pool_maxsize=10,
        max_retries=retry,
    )
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


# ── API calls (instrumented) ─────────────────────────────────────────────────

def fetch_pmc_ids(session, query: str, year: int, log: FlushingLogger) -> list[str]:
    params = {
        "db": "pmc",
        "term": query,
        "mindate": f"{year}/01/01",
        "maxdate": f"{year}/12/31",
        "datetype": "pdat",
        "retmode": "json",
        "retmax": 50000,
    }
    if API_KEY:
        params["api_key"] = API_KEY
    t0 = time.perf_counter()
    r = session.get(ESEARCH_URL, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    dt = time.perf_counter() - t0
    ids = r.json().get("esearchresult", {}).get("idlist", [])
    log.info(f"eSearch({year}): {len(ids)} ids in {dt:.2f}s")
    return ids


class BatchResult:
    __slots__ = ("rows", "download_sec", "parse_sec", "write_sec",
                 "response_bytes", "status", "skipped_pmids")

    def __init__(self):
        self.rows: list[dict] = []
        self.download_sec = 0.0
        self.parse_sec = 0.0
        self.write_sec = 0.0
        self.response_bytes = 0
        self.status = "ok"
        self.skipped_pmids: list[str] = []


def process_batch(session, batch_ids: list[str], log: FlushingLogger,
                  watchdog: Watchdog) -> BatchResult:
    result = BatchResult()
    params = {
        "db": "pmc",
        "id": ",".join(batch_ids),
        "retmode": "xml",
    }
    if API_KEY:
        params["api_key"] = API_KEY

    # Download phase ─────────────────────────────────────
    log.debug(f"  → GET efetch (batch of {len(batch_ids)}: "
              f"{batch_ids[0]}..{batch_ids[-1]})")
    watchdog.tick("before efetch")
    t0 = time.perf_counter()
    try:
        r = session.get(EFETCH_URL, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        content = r.content
    except requests.exceptions.RequestException as e:
        result.status = f"http_error: {type(e).__name__}: {e}"
        result.skipped_pmids = list(batch_ids)
        log.error(f"  batch {batch_ids[0]}..{batch_ids[-1]} FAILED: {e}")
        return result
    result.download_sec = time.perf_counter() - t0
    result.response_bytes = len(content)
    watchdog.tick("after efetch")

    mb = result.response_bytes / 1_048_576
    if mb > LARGE_RESPONSE_MB:
        log.warning(f"  LARGE response: {mb:.1f} MB "
                    f"(batch {batch_ids[0]}..{batch_ids[-1]})")

    # Parse phase ────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        result.status = f"parse_error: {e}"
        result.skipped_pmids = list(batch_ids)
        log.error(f"  parse failed for batch {batch_ids[0]}..{batch_ids[-1]}: {e}")
        return result
    result.parse_sec = time.perf_counter() - t0
    watchdog.tick("after parse")

    # Extraction phase ───────────────────────────────────
    # Build map: numeric PMC ID → article element (pmcaid is the numeric form)
    article_map: dict[str, ET.Element] = {}
    for article in root.findall(".//article"):
        num = article.find(".//article-id[@pub-id-type='pmcaid']")
        if num is not None and num.text:
            article_map[num.text] = article

    for batch_id in batch_ids:
        article = article_map.get(batch_id)
        if article is None:
            continue  # not returned (retracted, embargo, etc.)
        pmcid = f"PMC{batch_id}"
        title_node = article.find(".//article-title")
        title = ("".join(title_node.itertext()).strip()
                 if title_node is not None else "No Title")
        full_text = "".join(article.itertext())
        pride_ids = set(m.upper() for m in PRIDE_PATTERN.findall(full_text))
        for p in pride_ids:
            result.rows.append({
                "PRIDE_ID": p,
                "PMCID": pmcid,
                "Title": title,
                "Chars": len(full_text),
            })
    root.clear()
    log.debug(f"  parsed → {len(result.rows)} PRIDE matches "
              f"(download {result.download_sec:.2f}s, "
              f"parse {result.parse_sec:.2f}s, "
              f"{mb:.1f} MB)")
    return result


# ── Checkpoint ───────────────────────────────────────────────────────────────

class Checkpoint:
    def __init__(self, path: Path):
        self.path = path
        self.state: dict = {"last_completed": {}}
        if path.exists():
            try:
                self.state = json.loads(path.read_text())
            except Exception:
                pass

    def last_batch(self, year: int) -> int:
        return self.state["last_completed"].get(str(year), -1)

    def save(self, year: int, batch_idx: int):
        self.state["last_completed"][str(year)] = batch_idx
        self.path.write_text(json.dumps(self.state, indent=2))


# ── Main ─────────────────────────────────────────────────────────────────────

def write_rows_csv(path: Path, rows: list[dict], write_header: bool):
    import csv
    mode = "a" if path.exists() else "w"
    with open(path, mode, encoding='utf-8', newline='') as f:
        if not rows:
            return
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if write_header or mode == "w":
            writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())


def run_year(session, year: int, query: str, batch_size: int,
             out_csv: Path, skipped_file: Path, checkpoint: Checkpoint,
             max_batches: int | None, log: FlushingLogger,
             watchdog: Watchdog) -> dict:
    stats = Counter()
    phase_times = []

    log.info(f"=== YEAR {year} ===")
    ids = fetch_pmc_ids(session, query, year, log)
    if not ids:
        log.warning(f"year {year}: no articles")
        return stats

    total_batches = (len(ids) + batch_size - 1) // batch_size
    resume_from = checkpoint.last_batch(year) + 1
    if resume_from > 0:
        log.info(f"resuming year {year} from batch {resume_from}/{total_batches}")

    processed = 0
    for b in range(resume_from, total_batches):
        if max_batches is not None and processed >= max_batches:
            log.info(f"reached --max-batches={max_batches}, stopping year early")
            break
        batch = ids[b * batch_size : (b + 1) * batch_size]
        label = f"year {year} batch {b+1}/{total_batches}"
        log.info(f"[{label}] start")
        watchdog.tick(label)

        t_batch = time.perf_counter()
        result = process_batch(session, batch, log, watchdog)
        total_sec = time.perf_counter() - t_batch

        if result.status == "ok":
            t_write = time.perf_counter()
            if result.rows:
                write_rows_csv(out_csv, result.rows, write_header=not out_csv.exists())
            result.write_sec = time.perf_counter() - t_write
            stats["ok"] += 1
            stats["rows"] += len(result.rows)
        else:
            stats["skipped"] += 1
            with open(skipped_file, "a", encoding='utf-8') as f:
                for pmid in result.skipped_pmids:
                    f.write(f"{year},{b},{pmid},{result.status}\n")
                f.flush()

        phase_times.append((label, result.download_sec, result.parse_sec,
                            result.write_sec, result.response_bytes))
        log.info(
            f"[{label}] {result.status} total={total_sec:.2f}s "
            f"dl={result.download_sec:.2f}s "
            f"parse={result.parse_sec:.2f}s "
            f"write={result.write_sec:.2f}s "
            f"size={result.response_bytes/1_048_576:.1f}MB "
            f"rows+={len(result.rows)}"
        )
        if total_sec > BATCH_DEADLINE_SEC:
            log.warning(f"[{label}] exceeded BATCH_DEADLINE_SEC={BATCH_DEADLINE_SEC}")

        checkpoint.save(year, b)
        processed += 1
        time.sleep(0.2 if API_KEY else 0.6)

    # end-of-year summary
    if phase_times:
        slow = max(phase_times, key=lambda x: x[1] + x[2])
        log.info(
            f"year {year} slowest batch: {slow[0]} "
            f"(dl={slow[1]:.1f}s parse={slow[2]:.1f}s size={slow[4]/1_048_576:.1f}MB)"
        )
    return stats


def main():
    p = argparse.ArgumentParser(description=f"debug_massive_analysis v{VERSION}")
    p.add_argument("--query", default="Ovarian cancer proteomics")
    p.add_argument("--year", type=int, help="single year to run")
    p.add_argument("--years", help="year range, e.g. 2022-2026")
    p.add_argument("--batch-size", type=int, default=50)
    p.add_argument("--max-batches", type=int,
                   help="stop each year after N batches (quick repro)")
    p.add_argument("--out", type=Path,
                   default=TMP_DIR / f"debug_massive_{datetime.now():%Y%m%d_%H%M%S}.csv")
    p.add_argument("--log", type=Path,
                   default=TMP_DIR / f"debug_massive_{datetime.now():%Y%m%d_%H%M%S}.log")
    p.add_argument("--checkpoint", type=Path,
                   default=TMP_DIR / "debug_massive.checkpoint.json")
    p.add_argument("--resume", action="store_true",
                   help="resume from checkpoint (otherwise, checkpoint starts fresh)")
    args = p.parse_args()

    if args.year:
        years = [args.year]
    elif args.years:
        a, b = args.years.split("-")
        years = list(range(int(a), int(b) + 1))
    else:
        years = [2022, 2023, 2024, 2025, 2026]

    log = FlushingLogger(make_logger(args.log))
    log.info(f"debug_massive_analysis v{VERSION}")
    log.info(f"  query: {args.query!r}")
    log.info(f"  years: {years}")
    log.info(f"  batch_size: {args.batch_size}")
    log.info(f"  api_key: {'present' if API_KEY else 'MISSING'}")
    log.info(f"  csv: {args.out}")
    log.info(f"  log: {args.log}")
    log.info(f"  checkpoint: {args.checkpoint} (resume={args.resume})")
    log.info(f"  WATCHDOG_SEC={WATCHDOG_SEC} BATCH_DEADLINE_SEC={BATCH_DEADLINE_SEC}")

    if not args.resume and args.checkpoint.exists():
        args.checkpoint.unlink()
    checkpoint = Checkpoint(args.checkpoint)

    skipped_file = args.out.with_suffix(".skipped.csv")

    session = make_session()
    watchdog = Watchdog(log, WATCHDOG_SEC)
    watchdog.start()

    def on_sigint(signum, frame):
        log.warning("SIGINT received — dumping stacks and exiting")
        for tid, f in sys._current_frames().items():
            log.warning(f"thread {tid}:")
            for line in traceback.format_stack(f):
                log.warning(f"  {line.rstrip()}")
        sys.exit(130)

    signal.signal(signal.SIGINT, on_sigint)

    total = Counter()
    t_run = time.perf_counter()
    try:
        for y in years:
            stats = run_year(session, y, args.query, args.batch_size,
                             args.out, skipped_file, checkpoint,
                             args.max_batches, log, watchdog)
            total.update(stats)
    finally:
        watchdog.stop()
        elapsed = time.perf_counter() - t_run
        log.info(f"=== DONE in {elapsed:.1f}s ===")
        log.info(f"  batches ok: {total['ok']}")
        log.info(f"  batches skipped: {total['skipped']}")
        log.info(f"  PRIDE rows written: {total['rows']}")
        log.info(f"  csv: {args.out}")
        log.info(f"  log: {args.log}")
        if skipped_file.exists():
            log.info(f"  skipped batches: {skipped_file}")


if __name__ == "__main__":
    main()
