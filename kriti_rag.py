"""
kriti_rag.py — Local RAG layer for Kriti.

Ingests markdown / .txt files from a configurable directory, chunks them by
heading/paragraph (not fixed byte windows), generates embeddings via Ollama
(nomic-embed-text), stores them in SQLite + sqlite-vec, and retrieves the
top-k most relevant chunks for a given query.

All embedding is local — no external API calls.
"""

import hashlib
import json
import os
import re
import sqlite3
import struct

import requests

# ── Constants ─────────────────────────────────────────────────────────────────

SAVE_DIR        = os.path.expanduser("~/.life_missions")
RAG_DB_PATH     = os.path.join(SAVE_DIR, "rag.db")
RAG_CONFIG_PATH = os.path.join(SAVE_DIR, "rag_config.json")

DEFAULT_RAG_CONFIG = {
    "docs_dir":    "",                   # set by user; empty = RAG disabled
    "embed_model": "nomic-embed-text",   # Ollama model for embeddings
    "top_k":       5,                    # chunks to inject per query
    "min_chunk_chars": 80,               # ignore chunks shorter than this
    "max_chunk_chars": 1200,             # split paragraphs longer than this
}

EMBEDDING_DIM = 768   # nomic-embed-text outputs 768-dim vectors

# ── Config ────────────────────────────────────────────────────────────────────

def rag_load_config() -> dict:
    """Load RAG config from disk; create defaults if missing."""
    os.makedirs(SAVE_DIR, exist_ok=True)
    if os.path.exists(RAG_CONFIG_PATH):
        try:
            with open(RAG_CONFIG_PATH) as f:
                cfg = json.load(f)
            # Back-fill any new keys added after initial creation
            changed = False
            for k, v in DEFAULT_RAG_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
                    changed = True
            if changed:
                rag_save_config(cfg)
            return cfg
        except (json.JSONDecodeError, ValueError):
            pass
    cfg = dict(DEFAULT_RAG_CONFIG)
    rag_save_config(cfg)
    return cfg


def rag_save_config(cfg: dict) -> None:
    os.makedirs(SAVE_DIR, exist_ok=True)
    with open(RAG_CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Database ──────────────────────────────────────────────────────────────────

def _open_db() -> sqlite3.Connection:
    """Open rag.db and load the sqlite-vec extension."""
    os.makedirs(SAVE_DIR, exist_ok=True)
    try:
        import sqlite_vec
    except ImportError:
        raise RuntimeError(
            "sqlite-vec not installed. Run: pip install sqlite-vec"
        )
    conn = sqlite3.connect(RAG_DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist yet."""
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS chunks (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT    NOT NULL,
            file_hash TEXT    NOT NULL,
            chunk_idx INTEGER NOT NULL,
            heading   TEXT,
            text      TEXT    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_path);

        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings USING vec0(
            chunk_id INTEGER PRIMARY KEY,
            embedding FLOAT[{EMBEDDING_DIM}]
        );
    """)
    conn.commit()


# ── Chunking ──────────────────────────────────────────────────────────────────

def _file_hash(path: str) -> str:
    """SHA-256 of file contents — used to detect unchanged files."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def rag_chunk_document(path: str, min_chars: int = 80, max_chars: int = 1200) -> list[dict]:
    """
    Split a markdown or .txt file into semantic chunks.

    Strategy:
    - Markdown: split on headings (# / ## / ###). Each heading starts a new
      chunk; its content is further split on blank-line paragraph boundaries
      if it exceeds max_chars.
    - Plain text: split on double-newline paragraph boundaries.
    - Never cuts mid-sentence at a fixed byte offset.
    - Drops chunks shorter than min_chars (usually just whitespace or lone headings).

    Returns a list of {"heading": str|None, "text": str} dicts.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()

    is_md = path.lower().endswith(".md") or path.lower().endswith(".markdown")
    chunks = []

    if is_md:
        # Split on markdown headings — keep the heading line as part of the chunk
        heading_re = re.compile(r'^(#{1,6}\s+.+)$', re.MULTILINE)
        parts = heading_re.split(raw)
        # parts alternates: [pre-heading-text, heading, section, heading, section, ...]
        current_heading = None
        current_body = parts[0] if parts else ""

        i = 1
        while i < len(parts):
            heading_line = parts[i].strip()
            body = parts[i + 1] if i + 1 < len(parts) else ""
            # Flush previous section
            _flush_section(current_heading, current_body, chunks, min_chars, max_chars)
            current_heading = heading_line
            current_body = body
            i += 2
        _flush_section(current_heading, current_body, chunks, min_chars, max_chars)
    else:
        # Plain text: split on blank lines
        paragraphs = re.split(r'\n\s*\n', raw)
        for para in paragraphs:
            para = para.strip()
            if len(para) < min_chars:
                continue
            if len(para) > max_chars:
                for sub in _split_long_paragraph(para, max_chars):
                    chunks.append({"heading": None, "text": sub})
            else:
                chunks.append({"heading": None, "text": para})

    return chunks


def _flush_section(heading, body, out, min_chars, max_chars):
    """Split a markdown section body into paragraph-level chunks and append to out."""
    body = body.strip()
    if not body and (not heading or len(heading) < min_chars):
        return
    # Combine heading + body into a single block, then split on blank lines
    full = (f"{heading}\n\n{body}" if heading else body).strip()
    paragraphs = re.split(r'\n\s*\n', full)
    first = True
    for para in paragraphs:
        para = para.strip()
        if len(para) < min_chars:
            continue
        # For the first paragraph of a section, keep heading context
        chunk_heading = heading if first else None
        first = False
        if len(para) > max_chars:
            for sub in _split_long_paragraph(para, max_chars):
                out.append({"heading": chunk_heading, "text": sub})
                chunk_heading = None  # only first sub-chunk gets the heading label
        else:
            out.append({"heading": chunk_heading, "text": para})


def _split_long_paragraph(text: str, max_chars: int) -> list[str]:
    """
    Split an oversized paragraph on sentence boundaries ('. ', '! ', '? ').
    Falls back to newline split, then hard-caps as last resort.
    Never cuts inside a word.
    """
    # Try sentence-boundary split first
    sentence_re = re.compile(r'(?<=[.!?])\s+')
    sentences = sentence_re.split(text)
    parts = []
    buf = ""
    for s in sentences:
        if buf and len(buf) + 1 + len(s) > max_chars:
            parts.append(buf.strip())
            buf = s
        else:
            buf = (buf + " " + s).strip() if buf else s
    if buf.strip():
        parts.append(buf.strip())
    return parts if parts else [text[:max_chars]]


# ── Embedding via Ollama ──────────────────────────────────────────────────────

def rag_embed(text: str, host: str, model: str) -> list[float]:
    """
    Generate an embedding vector via Ollama's /api/embed endpoint.
    Returns a list of floats (length = EMBEDDING_DIM).
    Raises on network or model errors so the caller can surface them cleanly.
    """
    url = f"{host}/api/embed"
    payload = {"model": model, "input": text}
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    # Ollama /api/embed returns {"embeddings": [[...]] }
    # /api/embeddings (old endpoint) returns {"embedding": [...]}
    if "embeddings" in data:
        return data["embeddings"][0]
    elif "embedding" in data:
        return data["embedding"]
    else:
        raise ValueError(f"Unexpected Ollama embed response keys: {list(data.keys())}")


def _vec_to_bytes(vec: list[float]) -> bytes:
    """Pack a float list into a bytes blob sqlite-vec expects."""
    return struct.pack(f"{len(vec)}f", *vec)


# ── Indexing ──────────────────────────────────────────────────────────────────

def rag_index(
    docs_dir: str,
    host: str,
    embed_model: str,
    min_chars: int = 80,
    max_chars: int = 1200,
    force: bool = False,
    progress_cb=None,
) -> dict:
    """
    Incrementally index all .md and .txt files under docs_dir.

    - Computes a SHA-256 hash per file.
    - Skips files whose hash matches what's already in the DB (incremental).
    - Deletes old chunks for any file that has changed, then re-embeds.
    - force=True re-embeds everything from scratch.
    - progress_cb(msg: str) is called with status lines if provided.

    Returns {"indexed": int, "skipped": int, "deleted": int, "chunks": int}.
    """
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    if not docs_dir or not os.path.isdir(docs_dir):
        raise ValueError(f"docs_dir is not a valid directory: '{docs_dir!r}'")

    conn = _open_db()
    _init_schema(conn)

    # Gather all eligible files
    eligible_exts = {".md", ".markdown", ".txt"}
    all_files = []
    for root, _, files in os.walk(docs_dir):
        for fname in files:
            if any(fname.lower().endswith(ext) for ext in eligible_exts):
                all_files.append(os.path.join(root, fname))
    all_files.sort()

    # Load existing hashes from DB
    existing = {}  # file_path → file_hash
    for row in conn.execute("SELECT DISTINCT file_path, file_hash FROM chunks"):
        existing[row[0]] = row[1]

    stats = {"indexed": 0, "skipped": 0, "deleted": 0, "chunks": 0}

    for fpath in all_files:
        try:
            fhash = _file_hash(fpath)
        except OSError:
            log(f"  [skip] can't read {fpath}")
            continue

        if not force and existing.get(fpath) == fhash:
            log(f"  [skip] unchanged: {os.path.relpath(fpath, docs_dir)}")
            stats["skipped"] += 1
            continue

        # Delete old chunks for this file (both tables)
        old_ids = [r[0] for r in conn.execute(
            "SELECT id FROM chunks WHERE file_path = ?", (fpath,)
        )]
        if old_ids:
            placeholders = ",".join("?" * len(old_ids))
            conn.execute(f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({placeholders})", old_ids)
            conn.execute("DELETE FROM chunks WHERE file_path = ?", (fpath,))
            conn.commit()
            stats["deleted"] += len(old_ids)
            log(f"  [re-index] {os.path.relpath(fpath, docs_dir)} (removed {len(old_ids)} old chunks)")

        # Chunk the document
        chunks = rag_chunk_document(fpath, min_chars=min_chars, max_chars=max_chars)
        log(f"  [index] {os.path.relpath(fpath, docs_dir)} → {len(chunks)} chunks")

        for idx, chunk in enumerate(chunks):
            try:
                vec = rag_embed(chunk["text"], host, embed_model)
            except Exception as e:
                log(f"    [embed error chunk {idx}]: {e}")
                continue

            # Insert chunk metadata
            cur = conn.execute(
                "INSERT INTO chunks (file_path, file_hash, chunk_idx, heading, text) VALUES (?,?,?,?,?)",
                (fpath, fhash, idx, chunk.get("heading"), chunk["text"])
            )
            chunk_id = cur.lastrowid

            # Insert embedding — sqlite-vec expects binary blob
            vec_blob = _vec_to_bytes(vec)
            conn.execute(
                "INSERT INTO chunk_embeddings (chunk_id, embedding) VALUES (?,?)",
                (chunk_id, vec_blob)
            )
            stats["chunks"] += 1

        conn.commit()
        stats["indexed"] += 1

    conn.close()
    return stats


# ── Retrieval ─────────────────────────────────────────────────────────────────

def rag_retrieve(
    query: str,
    top_k: int,
    host: str,
    embed_model: str,
    allowed_dirs: list[str] | None = None,
) -> list[dict]:
    """
    Embed the query and return the top-k most similar chunks from the index.

    allowed_dirs: if provided, only chunks whose file_path starts with one of
    these prefixes are considered. Used by personas to scope retrieval.

    Returns list of {"text": str, "heading": str|None, "file": str, "score": float}.
    """
    if not os.path.exists(RAG_DB_PATH):
        return []

    try:
        vec = rag_embed(query, host, embed_model)
    except Exception:
        return []

    vec_blob = _vec_to_bytes(vec)

    conn = _open_db()
    _init_schema(conn)

    try:
        # sqlite-vec KNN search
        rows = conn.execute(
            """
            SELECT
                ce.chunk_id,
                ce.distance,
                c.file_path,
                c.heading,
                c.text
            FROM chunk_embeddings ce
            JOIN chunks c ON c.id = ce.chunk_id
            WHERE ce.embedding MATCH ?
              AND k = ?
            ORDER BY ce.distance
            """,
            (vec_blob, top_k * 3)   # over-fetch then filter by allowed_dirs
        ).fetchall()
    except Exception:
        conn.close()
        return []

    conn.close()

    results = []
    for chunk_id, distance, file_path, heading, text in rows:
        if allowed_dirs:
            if not any(
                os.path.abspath(file_path).startswith(os.path.abspath(d))
                for d in allowed_dirs
            ):
                continue
        results.append({
            "text":    text,
            "heading": heading,
            "file":    file_path,
            "score":   round(float(distance), 4),
        })
        if len(results) >= top_k:
            break

    return results


def rag_format_context(chunks: list[dict], docs_dir: str = "") -> str:
    """
    Format retrieved chunks for injection into Kriti's system prompt.
    Keeps source file visible so Kriti can cite it if asked.
    """
    if not chunks:
        return ""
    lines = []
    for i, c in enumerate(chunks, 1):
        rel = os.path.relpath(c["file"], docs_dir) if docs_dir else c["file"]
        header = f"[{i}] {rel}"
        if c.get("heading"):
            header += f" — {c['heading']}"
        lines.append(header)
        lines.append(c["text"])
        lines.append("")
    return "\n".join(lines).strip()


# ── Index stats ───────────────────────────────────────────────────────────────

def rag_stats() -> dict:
    """Return basic index statistics: total files, total chunks."""
    if not os.path.exists(RAG_DB_PATH):
        return {"files": 0, "chunks": 0}
    try:
        conn = _open_db()
        _init_schema(conn)
        files  = conn.execute("SELECT COUNT(DISTINCT file_path) FROM chunks").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        conn.close()
        return {"files": files, "chunks": chunks}
    except Exception:
        return {"files": 0, "chunks": 0}


def rag_clear_index() -> None:
    """Wipe the entire index. Use before a force re-index if schema changed."""
    if os.path.exists(RAG_DB_PATH):
        os.remove(RAG_DB_PATH)
