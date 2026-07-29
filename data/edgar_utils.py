"""
Shared helpers for talking to SEC EDGAR (free, public, no API key -- but SEC
requires a descriptive User-Agent and reasonable request rates, see
https://www.sec.gov/os/webmaster-faq#developers).
"""

import time
import requests
from bs4 import BeautifulSoup

from config import SEC_EDGAR_USER_AGENT

_HEADERS = {"User-Agent": SEC_EDGAR_USER_AGENT}

_ticker_cik_cache = None
_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 0.15  # stay comfortably under SEC's ~10 req/sec guidance


def _rate_limited_get(url: str, **kwargs):
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    resp = requests.get(url, headers=_HEADERS, timeout=15, **kwargs)
    _last_request_time = time.time()
    return resp


def get_cik_for_ticker(ticker: str) -> str | None:
    """
    Returns the 10-digit zero-padded CIK string for a ticker, or None if not found.
    Caches the full SEC ticker->CIK mapping in memory for the process lifetime.
    """
    global _ticker_cik_cache
    if _ticker_cik_cache is None:
        resp = _rate_limited_get("https://www.sec.gov/files/company_tickers.json")
        resp.raise_for_status()
        data = resp.json()
        # data is like {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        _ticker_cik_cache = {
            entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
            for entry in data.values()
        }
    return _ticker_cik_cache.get(ticker.upper())


def get_submissions(cik: str) -> dict:
    """Returns the SEC submissions JSON for a given CIK (recent filings list, etc.)."""
    resp = _rate_limited_get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    resp.raise_for_status()
    return resp.json()


def fetch_document(cik: str, accession_number: str, primary_document: str) -> str:
    """Fetches the raw text/HTML of a specific filing document."""
    accession_no_dashes = accession_number.replace("-", "")
    cik_int = str(int(cik))  # EDGAR archive URLs want the CIK without leading zeros
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}/{primary_document}"
    resp = _rate_limited_get(url)
    resp.raise_for_status()
    return resp.text


def find_exhibit_document(cik: str, accession_number: str, type_prefix: str) -> str | None:
    """
    Returns the filename of the largest document tagged with the given SEC
    document Type prefix (e.g. "EX-99" for a press release exhibit) within
    one filing, or None if there isn't one. Filers name exhibit files
    however they like (sometimes with no "ex99" in the name at all), so this
    reads the filing's own index page, where SEC assigns an authoritative
    Type per document -- far more reliable than guessing from filenames.
    primaryDocument in the submissions JSON only ever names ONE document, but
    a filing like an earnings 8-K attaches the actual press release as a
    separate exhibit in the same accession.
    """
    accession_no_dashes = accession_number.replace("-", "")
    cik_int = str(int(cik))
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}/{accession_number}-index.html"
    resp = _rate_limited_get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    candidates = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        doc_type = cells[3].get_text(strip=True)
        if not doc_type.upper().startswith(type_prefix.upper()):
            continue
        link = cells[2].find("a")
        if not link or not link.get("href"):
            continue
        filename = link["href"].rsplit("/", 1)[-1]
        size_text = cells[4].get_text(strip=True) if len(cells) > 4 else ""
        size = int(size_text) if size_text.isdigit() else 0
        candidates.append((filename, size))

    if not candidates:
        return None
    return max(candidates, key=lambda c: c[1])[0]


def strip_xml_namespaces(elem):
    """
    Strips the '{namespace}' prefix from every tag name in an ElementTree
    tree, in place. SEC's ownership forms (4, 144) declare no default
    namespace, but the newer 13D/13G XML schema does -- without this,
    plain elem.find("tagName") silently returns nothing on those.
    """
    for e in elem.iter():
        if "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
    return elem
