"""
Shared HTML-to-text helpers for SEC filing documents (10-Q/10-K/8-K exhibits,
DEF 14A proxies). No LLM calls here.
"""

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# SEC's inline-XBRL filings are valid XHTML with XML namespace declarations
# (xmlns:ix etc.); bs4's heuristic flags that as "looks like XML" even though
# parsing it as HTML is correct and intentional here.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

COVER_PAGE_BUDGET = 1500  # chars reserved for company/filing identity before jumping ahead


def strip_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Modern SEC filings use inline XBRL: a hidden <div style="display:none">
    # near the top of the document holds every tagged fact/context as raw
    # metadata. It's easily hundreds of KB and would otherwise consume the
    # entire max_chars budget before any real prose is reached.
    for tag in soup.find_all(style=lambda v: v and "display:none" in v.replace(" ", "").lower()):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def select_prose_window(text: str, max_chars: int, heading_pattern: str, skip_note: str) -> str:
    """
    Long SEC documents open with a cover page and, for 10-Q/10-K, the raw
    financial statement tables (already covered elsewhere via yfinance) --
    the prose that's unique to the document (MD&A, executive compensation
    discussion, etc.) comes later. A flat text[:max_chars] cap gets entirely
    consumed before reaching it. Instead: keep a small cover-page prefix for
    identity context, then jump to the target section.

    The heading's earlier occurrences are always the table of contents plus
    incidental cross-references elsewhere in the front matter (e.g. a
    forward-looking-statements disclaimer citing "Item 7" by name); the real
    section heading -- by definition of standard filing structure -- is the
    LAST occurrence in the document, since nothing legitimately cites it by
    full name again afterward. Falls back to a flat cap when the heading
    isn't found at all (e.g. 8-Ks).
    """
    if len(text) <= max_chars:
        return text

    matches = [m.start() for m in re.finditer(heading_pattern, text, re.IGNORECASE)]
    jump_to = matches[-1] if matches else None

    if jump_to is None or jump_to <= COVER_PAGE_BUDGET:
        return text[:max_chars]

    cover = text[:COVER_PAGE_BUDGET]
    remaining = max_chars - COVER_PAGE_BUDGET
    return cover + f" [...{skip_note}...] " + text[jump_to:jump_to + remaining]
