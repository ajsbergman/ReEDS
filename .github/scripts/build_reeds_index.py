from __future__ import annotations

"""
ReEDS FAISS Index Builder (CI / HPC)
====================================

Builds a FAISS vector index for the ReEDS repository so an AI agent can
quickly retrieve relevant code and documentation snippets.

In CI, this script is called by the update-index workflow with Gemini
embeddings.  On HPC you can still use HuggingFace or Ollama models.

Embedding providers are lazily imported so CI only needs the packages for
the chosen provider (Gemini by default).

Environment variables (all optional, sensible defaults):
    REEDS_REPO             Path to repo root (default: cwd)
    REEDS_INDEX_DIR        Where to write index.faiss / index.pkl
    REEDS_EMBED_MODEL      gemini:gemini-embedding-001 | hf:BAAI/bge-base-en-v1.5 | ollama:nomic-embed-text
    REEDS_INCREMENTAL      1 = append to existing index  (default 1)
    REEDS_SKIP_UNCHANGED   1 = skip files whose signature matches manifest  (default 1)
    REEDS_EMBED_BATCH      Batch size for embedding calls  (default 64)
    REEDS_EMBED_DEVICE     e.g. "cuda" for HuggingFace GPU
    GOOGLE_API_KEY         Required when using gemini: embeddings
"""

import os
import json
import time
import hashlib
import subprocess
from pathlib import Path
from typing import Iterable, Tuple, Optional, List, Dict

from tqdm import tqdm

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS

# ---------------------------------------------------------------------------
# 1) Configuration (env-driven)
# ---------------------------------------------------------------------------
DEFAULT_EMBED_MODEL = os.environ.get("REEDS_EMBED_MODEL", "gemini:gemini-embedding-001")
EMBED_BATCH_SIZE = int(os.environ.get("REEDS_EMBED_BATCH", "64"))
MAX_FILE_BYTES = int(os.environ.get("REEDS_MAX_FILE_BYTES", str(5_000_000)))
INCREMENTAL = os.environ.get("REEDS_INCREMENTAL", "1") == "1"
SKIP_UNCHANGED = os.environ.get("REEDS_SKIP_UNCHANGED", "1") == "1"

INCLUDE_EXT = {".md", ".rst", ".txt", ".py", ".gms", ".csv", ".yaml", ".yml"}
EXCLUDE_DIRS = {
    ".git", ".github", "__pycache__", ".pytest_cache",
    "outputs", "output", "runs", "run",
    "Augur", "ReEDS_Augur",
}
EXCLUDE_PATH_SUBSTR: set = set()

CSV_MAX_LINES = int(os.environ.get("REEDS_CSV_MAX_LINES", "4000"))
CHUNK_SIZE = int(os.environ.get("REEDS_CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.environ.get("REEDS_CHUNK_OVERLAP", "200"))


# ---------------------------------------------------------------------------
# 2) Utility helpers
# ---------------------------------------------------------------------------
def get_git_commit(repo: Path) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or None
    except Exception:
        return None


def sha1_bytes(b: bytes) -> str:
    h = hashlib.sha1()
    h.update(b)
    return h.hexdigest()


def safe_read_text(fp: Path) -> Optional[str]:
    try:
        raw = fp.read_bytes()
        if b"\x00" in raw[:4096]:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="ignore")
    except Exception:
        return None


def file_signature(fp: Path) -> Optional[Dict[str, int]]:
    try:
        st = fp.stat()
        return {"size": int(st.st_size), "mtime": int(st.st_mtime)}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 3) File crawling
# ---------------------------------------------------------------------------
def iter_files(repo: Path) -> Iterable[Path]:
    for p in repo.rglob("*"):
        if p.is_dir():
            continue
        ext = p.suffix.lower()
        if ext not in INCLUDE_EXT:
            continue
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        full_str = str(p)
        if any(s in full_str for s in EXCLUDE_PATH_SUBSTR):
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
        except Exception:
            continue
        yield p


# ---------------------------------------------------------------------------
# 4) Chunking (code-aware split rules)
# ---------------------------------------------------------------------------
def make_splitter(ext: str) -> RecursiveCharacterTextSplitter:
    if ext == ".py":
        return RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
            separators=["\nclass ", "\ndef ", "\n\n", "\n", " ", ""],
        )
    if ext == ".gms":
        return RecursiveCharacterTextSplitter(
            chunk_size=min(CHUNK_SIZE, 900), chunk_overlap=min(CHUNK_OVERLAP, 150),
            separators=[";\n", "\n\n", "\n", " ", ""],
        )
    if ext in {".md", ".rst", ".txt"}:
        return RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
            separators=["\n## ", "\n### ", "\n#### ", "\n\n", "\n", " ", ""],
        )
    if ext in {".csv", ".yaml", ".yml"}:
        return RecursiveCharacterTextSplitter(
            chunk_size=min(CHUNK_SIZE, 800), chunk_overlap=min(CHUNK_OVERLAP, 120),
            separators=["\n", ",", " ", ""],
        )
    return RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


# ---------------------------------------------------------------------------
# 5) Embeddings  (lazy imports – only the chosen provider is loaded)
# ---------------------------------------------------------------------------
def make_embeddings() -> Tuple[object, str]:
    model_name = os.environ.get("REEDS_EMBED_MODEL", DEFAULT_EMBED_MODEL)

    # --- Gemini ---
    if model_name.lower().startswith("gemini:"):
        gemini_model = model_name.split(":", 1)[1]
        if not os.environ.get("GOOGLE_API_KEY"):
            raise RuntimeError("GOOGLE_API_KEY is required for Gemini embeddings.")
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        print(f"Using Gemini embeddings: {gemini_model}")
        return GoogleGenerativeAIEmbeddings(model=gemini_model), f"gemini:{gemini_model}"

    # --- Ollama ---
    if model_name.lower().startswith("ollama:") or model_name.lower() == "ollama":
        ollama_model = (
            model_name.split(":", 1)[1]
            if ":" in model_name
            else os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
        )
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        from langchain_ollama import OllamaEmbeddings
        print(f"Using Ollama embeddings: {ollama_model} (base: {base_url})")
        return OllamaEmbeddings(model=ollama_model, base_url=base_url), f"ollama:{ollama_model}"

    # --- HuggingFace (default fallback) ---
    if model_name.lower().startswith("hf:"):
        model_name = model_name.split(":", 1)[1]
    device = os.environ.get("REEDS_EMBED_DEVICE")
    model_kwargs = {}
    if device:
        model_kwargs["device"] = device
    encode_kwargs = {"normalize_embeddings": True}
    from langchain_community.embeddings import HuggingFaceEmbeddings
    print(f"Using HuggingFace embeddings: {model_name} | device={device or 'default'}")
    return (
        HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs=model_kwargs,
            encode_kwargs=encode_kwargs,
        ),
        f"hf:{model_name}",
    )


# ---------------------------------------------------------------------------
# 6) File → Documents
# ---------------------------------------------------------------------------
def file_to_documents(repo: Path, fp: Path) -> List[Document]:
    text = safe_read_text(fp)
    if not text:
        return []
    ext = fp.suffix.lower()
    if ext == ".csv":
        lines = text.splitlines()
        if len(lines) > CSV_MAX_LINES:
            text = "\n".join(lines[:CSV_MAX_LINES])
    sig = file_signature(fp) or {"size": -1, "mtime": -1}
    rel = fp.relative_to(repo)
    meta = {
        "path": str(fp),
        "rel_path": str(rel).replace("\\", "/"),
        "ext": ext,
        "size": sig["size"],
        "mtime": sig["mtime"],
    }
    return [Document(page_content=text, metadata=meta)]


def batched(items: List[Document], batch_size: int) -> Iterable[List[Document]]:
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


# ---------------------------------------------------------------------------
# 7) Main pipeline
# ---------------------------------------------------------------------------
def main():
    repo = Path(os.environ.get("REEDS_REPO", ".")).expanduser().resolve()
    out_dir = Path(os.environ.get("REEDS_INDEX_DIR", "./reeds_index")).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("ReEDS repo:", repo)
    print("Index dir:", out_dir)
    print("Incremental:", INCREMENTAL, "| Skip unchanged:", SKIP_UNCHANGED)

    if not repo.exists():
        raise FileNotFoundError(f"REEDS_REPO path does not exist: {repo}")
    if not repo.is_dir():
        raise NotADirectoryError(f"REEDS_REPO path is not a directory: {repo}")

    embeddings, embed_name = make_embeddings()

    vectordb: Optional[FAISS] = None
    existing_index = (out_dir / "index.faiss").exists() and (out_dir / "index.pkl").exists()

    # Load previous manifest for skip-unchanged comparison
    prev_file_sigs: Dict[str, Dict[str, int]] = {}
    prev_manifest_path = out_dir / "manifest.json"
    if prev_manifest_path.exists():
        try:
            prev = json.loads(prev_manifest_path.read_text(encoding="utf-8"))
            prev_file_sigs = prev.get("file_signatures", {}) or {}
        except Exception:
            prev_file_sigs = {}

    if INCREMENTAL and existing_index:
        try:
            vectordb = FAISS.load_local(
                str(out_dir), embeddings, allow_dangerous_deserialization=True,
            )
            print("Loaded existing FAISS index from:", out_dir)
        except Exception as e:
            print("Warning: failed to load existing index; rebuilding.", str(e))
            vectordb = None

    manifest: Dict[str, object] = {
        "repo": str(repo),
        "git_commit": get_git_commit(repo),
        "created_utc": int(time.time()),
        "embed_model": embed_name,
        "include_ext": sorted(INCLUDE_EXT),
        "exclude_dirs": sorted(EXCLUDE_DIRS),
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "incremental": INCREMENTAL,
        "skip_unchanged": SKIP_UNCHANGED,
        "file_signatures": {},
    }

    files = list(iter_files(repo))
    print("Files to consider:", len(files))
    if not files:
        print("No files matched filters.")
        return

    total_chunks = 0
    indexed_files = 0
    skipped_files = 0
    new_file_sigs: Dict[str, Dict[str, int]] = {}

    for fp in tqdm(files, desc="Indexing files", unit="file"):
        rel = str(fp.relative_to(repo)).replace("\\", "/")
        sig = file_signature(fp)
        if sig:
            new_file_sigs[rel] = sig

        if SKIP_UNCHANGED and INCREMENTAL and existing_index and sig:
            prev_sig = prev_file_sigs.get(rel)
            if (
                prev_sig
                and prev_sig.get("size") == sig.get("size")
                and prev_sig.get("mtime") == sig.get("mtime")
            ):
                skipped_files += 1
                continue

        docs = file_to_documents(repo, fp)
        if not docs:
            continue
        splitter = make_splitter(fp.suffix.lower())
        chunks = splitter.split_documents(docs)
        if not chunks:
            continue

        for c in chunks:
            content_bytes = c.page_content.encode("utf-8", errors="ignore")
            c.metadata["chunk_sha1"] = sha1_bytes(content_bytes[:20000])

        for batch in batched(chunks, EMBED_BATCH_SIZE):
            if vectordb is None:
                vectordb = FAISS.from_documents(batch, embeddings, normalize_L2=True)
            else:
                vectordb.add_documents(batch)

        total_chunks += len(chunks)
        indexed_files += 1

    if vectordb is None:
        print("No chunks were indexed.")
        return

    vectordb.save_local(str(out_dir))
    manifest["file_signatures"] = new_file_sigs
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\nSaved FAISS index to: {out_dir}")
    print(f"  embed_model: {embed_name}")
    print(f"  files_indexed: {indexed_files}")
    if INCREMENTAL and existing_index and SKIP_UNCHANGED:
        print(f"  files_skipped: {skipped_files}")
    print(f"  chunks_added: {total_chunks}")


if __name__ == "__main__":
    main()
