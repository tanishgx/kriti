"""
kriti_websearch.py — Web search grounding for Kriti.

Slots into the RAG pipeline as a second retrieval source.
When Kriti (or the user) decides a query needs live information,
this module fetches results from DuckDuckGo, formats them as
source-cited snippets, and injects them into the system prompt
exactly like RAG chunks — same injection point, same citation style.

Architecture decisions (explicit):
- No API key, no cloud calls: DuckDuckGo HTML search only.
- Web results are clearly labelled as WEB SEARCH RESULTS to distinguish
  them from local RAG chunks — Kriti must not confuse the two.
- Per-persona gating: web_search_enabled flag in persona config controls
  whether a persona is allowed to trigger web search at all.
  Personas can also restrict to specific allowed_domains.
- Search is triggered in two ways:
    1. Automatic: if the query matches a "web-worthy" classifier
       (recency keywords: today, latest, news, current, price, weather…)
       AND the persona permits it AND web is enabled in the global config.
    2. Explicit: Kriti emits [[WEB_SEARCH:query]] — gated through the
       same whitelist/persona dispatch path.
- Result count and snippet length are configurable.
- Web search results are never persisted (unlike RAG chunks which live in
  the sqlite-vec DB) — they are ephemeral, per-turn context.
"""

import json
import os
import time
import re
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────

SAVE_DIR             = os.path.expanduser("~/.life_missions")
WEBSEARCH_CONFIG_PATH = os.path.join(SAVE_DIR, "websearch_config.json")

DEFAULT_CONFIG = {
    "enabled":          True,        # global on/off switch
    "max_results":      5,           # snippets injected per query
    "snippet_max_chars": 400,        # truncate long snippets
    "auto_trigger":     True,        # auto-detect recency queries
    "rate_limit_secs":  4.0,         # minimum seconds between requests
    "safe_search":      "moderate",  # "on" | "moderate" | "off"
}

# Keywords that suggest the query needs live/recent information
RECENCY_KEYWORDS = {
    "today", "yesterday", "latest", "current", "now", "live",
    "news", "update", "recent", "price", "weather", "stock",
    "score", "result", "match", "2025", "2026",
}

_last_search_ts: float = 0.0   # module-level rate-limit tracker


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    os.makedirs(SAVE_DIR, exist_ok=True)
    if os.path.exists(WEBSEARCH_CONFIG_PATH):
        try:
            with open(WEBSEARCH_CONFIG_PATH) as f:
                cfg = json.load(f)
            changed = False
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
                    changed = True
            if changed:
                save_config(cfg)
            return cfg
        except (json.JSONDecodeError, ValueError):
            pass
    save_config(dict(DEFAULT_CONFIG))
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    os.makedirs(SAVE_DIR, exist_ok=True)
    with open(WEBSEARCH_CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Persona web-search gating ─────────────────────────────────────────────────

def persona_allows_web(persona: Optional[dict]) -> bool:
    """
    Returns True if the active persona permits web search.
    Default (no persona, or persona without explicit flag): allowed.
    Persona can opt out by setting "web_search_enabled": false.
    """
    if persona is None:
        return True
    return persona.get("web_search_enabled", True)


def persona_allowed_domains(persona: Optional[dict]) -> list[str]:
    """
    Returns list of allowed domains for this persona, or [] for no restriction.
    Persona sets "web_search_domains": ["arxiv.org", "worldquant.com"] to restrict.
    """
    if persona is None:
        return []
    return persona.get("web_search_domains", [])


# ── Query analysis ─────────────────────────────────────────────────────────────

def is_web_worthy(query: str) -> bool:
    """
    Return True if the query likely needs live/recent web data.
    Checked only when auto_trigger=True.
    """
    q = query.lower()
    return any(kw in q for kw in RECENCY_KEYWORDS)


# ── Search ────────────────────────────────────────────────────────────────────

def web_search(
    query: str,
    max_results: int = 5,
    snippet_max_chars: int = 400,
    safe_search: str = "moderate",
    allowed_domains: Optional[list[str]] = None,
) -> list[dict]:
    """
    Run a DuckDuckGo text search.

    Returns a list of:
        {"title": str, "url": str, "snippet": str}

    Raises on network errors so callers can catch and degrade gracefully.
    """
    global _last_search_ts

    # Rate limiting
    now = time.time()
    elapsed = now - _last_search_ts
    cfg = load_config()
    min_gap = cfg.get("rate_limit_secs", 4.0)
    if elapsed < min_gap:
        time.sleep(min_gap - elapsed)
    _last_search_ts = time.time()

    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            raise RuntimeError(
                "No search library found. Run: pip install ddgs"
            )

    safe_map = {"on": "strict", "moderate": "moderate", "off": "off"}
    safe = safe_map.get(safe_search, "moderate")

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, safesearch=safe, max_results=max_results * 3):
            url     = r.get("href", "") or r.get("url", "")
            title   = r.get("title", "")
            snippet = r.get("body", "") or r.get("snippet", "")

            # Domain filter (persona restriction)
            if allowed_domains:
                if not any(d.lower() in url.lower() for d in allowed_domains):
                    continue

            snippet = snippet[:snippet_max_chars]
            if snippet and len(snippet) == snippet_max_chars:
                last_period = snippet.rfind(". ")
                if last_period > snippet_max_chars // 2:
                    snippet = snippet[:last_period + 1]

            results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= max_results:
                break

    return results


# ── Formatting ────────────────────────────────────────────────────────────────

def format_web_results(results: list[dict]) -> str:
    """
    Format web results for injection into Kriti's system prompt.
    Same citation style as rag_format_context: numbered, source shown.
    """
    if not results:
        return ""
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[W{i}] {r['title']}")
        lines.append(f"     Source: {r['url']}")
        if r.get("snippet"):
            lines.append(f"     {r['snippet']}")
        lines.append("")
    return "\n".join(lines).strip()


# ── Decision helper (called from screen_kriti per-turn) ───────────────────────

def should_search(
    query: str,
    cfg: dict,
    persona: Optional[dict],
    explicit: bool = False,
) -> bool:
    """
    Returns True if a web search should run for this query.

    explicit=True: user or Kriti explicitly asked (via [[WEB_SEARCH:…]])
    explicit=False: auto-trigger path — only fires if auto_trigger is on
                    and the query has recency keywords.
    """
    if not cfg.get("enabled", True):
        return False
    if not persona_allows_web(persona):
        return False
    if explicit:
        return True
    return cfg.get("auto_trigger", True) and is_web_worthy(query)
