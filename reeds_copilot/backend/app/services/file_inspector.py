"""File inspection helpers – list, preview text, preview CSV, preview GDX."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..core.config import Settings

log = logging.getLogger(__name__)

TEXT_SUFFIXES = {
    ".py", ".gms", ".jl", ".r", ".sh", ".bat",
    ".md", ".rst", ".txt", ".json", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".opt", ".csv", ".tsv",
    ".html", ".xml", ".sql",
    ".lst", ".log", ".inc", ".dd", ".gpr",
}

_GDX_TYPE_NAMES = {0: "Set", 1: "Parameter", 2: "Variable", 3: "Equation", 4: "Alias"}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp"}


def safe_resolve(repo_root: Path, rel_path: str) -> Path:
    """Resolve *rel_path* relative to *repo_root* and ensure it stays inside."""
    resolved = (repo_root / rel_path).resolve()
    if not str(resolved).startswith(str(repo_root.resolve())):
        raise PermissionError("Path escapes repository root.")
    return resolved


def list_directory(repo_root: Path, rel_path: str) -> list[dict]:
    target = safe_resolve(repo_root, rel_path)
    if not target.is_dir():
        raise FileNotFoundError(f"Not a directory: {rel_path}")

    entries = []
    for child in sorted(target.iterdir()):
        if child.name.startswith("."):
            continue
        try:
            st = child.stat()
            size = st.st_size if child.is_file() else None
            mtime = st.st_mtime
        except OSError:
            size = None
            mtime = 0
        entries.append({
            "name": child.name,
            "rel_path": str(child.relative_to(repo_root)).replace("\\", "/"),
            "is_dir": child.is_dir(),
            "size": size,
            "modified_at": mtime,
        })
    return entries


MAX_FULL_SIZE = 10 * 1024 * 1024  # 10 MB safety cap for full view


def preview_file(
    repo_root: Path,
    rel_path: str,
    settings: Settings,
    full: bool = False,
    gdx_symbol: str | None = None,
    h5_dataset: str | None = None,
) -> dict:
    target = safe_resolve(repo_root, rel_path)
    if not target.is_file():
        raise FileNotFoundError(f"Not a file: {rel_path}")

    suffix = target.suffix.lower()
    result: dict = {"rel_path": rel_path, "file_type": suffix}

    if suffix == ".gdx":
        return _preview_gdx(target, rel_path, symbol=gdx_symbol)

    if suffix in (".h5", ".hdf5"):
        return _preview_h5(target, rel_path, dataset=h5_dataset)

    if suffix == ".csv":
        return _preview_csv(target, rel_path, settings, full=full)

    if suffix in IMAGE_SUFFIXES:
        result.update({
            "content": None,
            "is_image": True,
            "truncated": False,
        })
        return result

    if suffix in TEXT_SUFFIXES or suffix == "":
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if full:
            # Cap at 10 MB worth of text
            if target.stat().st_size > MAX_FULL_SIZE:
                lines = lines[:50000]
                truncated = True
            else:
                truncated = False
        else:
            truncated = len(lines) > settings.max_file_preview_lines
            if truncated:
                lines = lines[: settings.max_file_preview_lines]
        result.update({
            "content": "\n".join(lines),
            "truncated": truncated,
        })
        return result

    result["content"] = "(binary or unsupported file type)"
    return result


# ── GDX helpers (use gdxcc for speed) ─────────────────────────────────────────

def _gdx_list_symbols(target: Path) -> list[dict]:
    """Return a list of all symbols in a GDX file (fast, ~50 ms)."""
    import gdxcc

    H = gdxcc.new_gdxHandle_tp()
    gdxcc.gdxCreate(H, gdxcc.GMS_SSSIZE)
    rc = gdxcc.gdxOpenRead(H, str(target))
    if rc[0] == 0:
        gdxcc.gdxClose(H)
        raise RuntimeError(f"Cannot open GDX file: {target.name}")

    try:
        _, sym_count, _ = gdxcc.gdxSystemInfo(H)
        symbols: list[dict] = []
        for i in range(1, sym_count + 1):
            _, name, dims, typ = gdxcc.gdxSymbolInfo(H, i)
            _, records, _, expl = gdxcc.gdxSymbolInfoX(H, i)
            symbols.append({
                "name": name,
                "type": _GDX_TYPE_NAMES.get(typ, str(typ)),
                "dims": dims,
                "records": records,
                "description": expl or "",
            })
        return symbols
    finally:
        gdxcc.gdxClose(H)


def _gdx_read_symbol(target: Path, symbol: str, max_rows: int = 500) -> dict:
    """Read one symbol's data from a GDX file, returning columns + rows."""
    import gdxcc

    H = gdxcc.new_gdxHandle_tp()
    gdxcc.gdxCreate(H, gdxcc.GMS_SSSIZE)
    rc = gdxcc.gdxOpenRead(H, str(target))
    if rc[0] == 0:
        gdxcc.gdxClose(H)
        raise RuntimeError(f"Cannot open GDX file: {target.name}")

    try:
        ret, sym_nr = gdxcc.gdxFindSymbol(H, symbol)
        if sym_nr <= 0:
            raise KeyError(f"Symbol '{symbol}' not found in {target.name}")

        _, name, dims, typ = gdxcc.gdxSymbolInfo(H, sym_nr)
        _, total_records, _, expl = gdxcc.gdxSymbolInfoX(H, sym_nr)

        # Build column names: dim1..dimN + Value
        col_names = [f"dim{j+1}" for j in range(dims)]
        is_set = typ == 0  # Sets have no meaningful Value column
        if not is_set:
            col_names.append("Value")

        gdxcc.gdxDataReadStrStart(H, sym_nr)
        rows: list[dict] = []
        for _ in range(min(total_records, max_rows)):
            ret, keys, values, _ = gdxcc.gdxDataReadStr(H)
            if ret == 0:
                break
            row = {f"dim{j+1}": keys[j] for j in range(dims)}
            if not is_set:
                row["Value"] = values[0]
            rows.append(row)
        gdxcc.gdxDataReadDone(H)

        return {
            "columns": col_names,
            "rows": rows,
            "total_rows": total_records,
            "truncated": total_records > max_rows,
            "symbol_name": name,
            "symbol_type": _GDX_TYPE_NAMES.get(typ, str(typ)),
            "description": expl or "",
        }
    finally:
        gdxcc.gdxClose(H)


def _preview_gdx(target: Path, rel_path: str, symbol: str | None = None) -> dict:
    """Preview a GDX file: symbol list or single symbol data."""
    try:
        if symbol:
            info = _gdx_read_symbol(target, symbol)
            return {
                "rel_path": rel_path,
                "file_type": ".gdx",
                "columns": info["columns"],
                "rows": info["rows"],
                "total_rows": info["total_rows"],
                "truncated": info["truncated"],
                "gdx_symbol": info["symbol_name"],
            }
        else:
            symbols = _gdx_list_symbols(target)
            return {
                "rel_path": rel_path,
                "file_type": ".gdx",
                "gdx_symbols": symbols,
            }
    except Exception as exc:
        log.warning("GDX preview error: %s", exc)
        return {
            "rel_path": rel_path,
            "file_type": ".gdx",
            "content": f"Error reading GDX: {exc}",
        }


def _preview_csv(target: Path, rel_path: str, settings: Settings, full: bool = False) -> dict:
    max_rows = None if full else settings.max_csv_preview_rows
    try:
        df = pd.read_csv(target, nrows=max_rows, low_memory=False)
    except Exception as exc:
        return {
            "rel_path": rel_path,
            "file_type": ".csv",
            "content": f"Error reading CSV: {exc}",
        }

    # Count total rows cheaply
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            total_rows = sum(1 for _ in fh) - 1  # minus header
    except Exception:
        total_rows = len(df)

    display_rows = len(df) if full else min(len(df), settings.max_csv_preview_rows)

    return {
        "rel_path": rel_path,
        "file_type": ".csv",
        "columns": list(df.columns),
        "rows": df.head(display_rows).to_dict(orient="records"),
        "total_rows": total_rows,
        "truncated": total_rows > display_rows,
    }


# ── HDF5 helpers (use h5py) ───────────────────────────────────────────────────

def _h5_list_datasets(target: Path) -> list[dict]:
    """Walk an HDF5 file and return one entry per dataset."""
    import h5py

    out: list[dict] = []
    with h5py.File(target, "r") as f:
        def visit(name: str, obj) -> None:
            if isinstance(obj, h5py.Dataset):
                try:
                    shape_str = "×".join(str(s) for s in obj.shape) or "scalar"
                except Exception:
                    shape_str = "?"
                try:
                    dtype_str = str(obj.dtype)
                except Exception:
                    dtype_str = "?"
                out.append({
                    "name": "/" + name,
                    "shape": shape_str,
                    "dtype": dtype_str,
                    "size": int(obj.size) if hasattr(obj, "size") else 0,
                    "ndim": int(obj.ndim) if hasattr(obj, "ndim") else 0,
                })
        f.visititems(visit)
    return out


def _h5_read_dataset(target: Path, dataset: str, max_rows: int = 500) -> dict:
    """Read one dataset's data, returning columns/rows similar to GDX preview."""
    import h5py
    import numpy as np

    with h5py.File(target, "r") as f:
        if dataset not in f:
            raise KeyError(f"Dataset '{dataset}' not found in {target.name}")
        obj = f[dataset]
        if not isinstance(obj, h5py.Dataset):
            raise KeyError(f"'{dataset}' is not a dataset")

        shape = obj.shape
        ndim = obj.ndim
        total_rows = int(shape[0]) if ndim >= 1 else 1

        # Scalar
        if ndim == 0:
            val = obj[()]
            if isinstance(val, bytes):
                val = val.decode("utf-8", errors="replace")
            return {
                "columns": ["Value"],
                "rows": [{"Value": _to_jsonable(val)}],
                "total_rows": 1,
                "truncated": False,
                "shape": "scalar",
                "dtype": str(obj.dtype),
            }

        # 1-D
        if ndim == 1:
            n = min(total_rows, max_rows)
            data = obj[:n]
            rows = [{"Value": _to_jsonable(v)} for v in data]
            return {
                "columns": ["Value"],
                "rows": rows,
                "total_rows": total_rows,
                "truncated": total_rows > n,
                "shape": "×".join(str(s) for s in shape),
                "dtype": str(obj.dtype),
            }

        # 2-D — show columns named col0..colN
        if ndim == 2:
            n = min(total_rows, max_rows)
            data = obj[:n, :]
            cols = [f"col{j}" for j in range(shape[1])]
            rows = [
                {cols[j]: _to_jsonable(data[i, j]) for j in range(shape[1])}
                for i in range(n)
            ]
            return {
                "columns": cols,
                "rows": rows,
                "total_rows": total_rows,
                "truncated": total_rows > n,
                "shape": "×".join(str(s) for s in shape),
                "dtype": str(obj.dtype),
            }

        # Higher-dim — slice the leading axis, show flattened summary per row
        n = min(total_rows, max_rows)
        rows = []
        for i in range(n):
            slab = np.asarray(obj[i])
            preview = ", ".join(str(_to_jsonable(v)) for v in slab.ravel()[:8])
            if slab.size > 8:
                preview += f", … ({slab.size} values)"
            rows.append({"Index": i, "Slice shape": "×".join(str(s) for s in slab.shape), "Preview": preview})
        return {
            "columns": ["Index", "Slice shape", "Preview"],
            "rows": rows,
            "total_rows": total_rows,
            "truncated": total_rows > n,
            "shape": "×".join(str(s) for s in shape),
            "dtype": str(obj.dtype),
        }


def _to_jsonable(v):
    """Coerce a single HDF5 value to something JSON-serializable."""
    import numpy as np

    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", errors="replace")
        except Exception:
            return repr(v)
    if isinstance(v, np.generic):
        try:
            return v.item()
        except Exception:
            return str(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    return v


def _preview_h5(target: Path, rel_path: str, dataset: str | None = None) -> dict:
    """Preview an HDF5 file: dataset list or single dataset data."""
    try:
        if dataset:
            info = _h5_read_dataset(target, dataset)
            return {
                "rel_path": rel_path,
                "file_type": target.suffix.lower(),
                "columns": info["columns"],
                "rows": info["rows"],
                "total_rows": info["total_rows"],
                "truncated": info["truncated"],
                "h5_dataset": dataset,
                "h5_shape": info["shape"],
                "h5_dtype": info["dtype"],
            }
        else:
            datasets = _h5_list_datasets(target)
            return {
                "rel_path": rel_path,
                "file_type": target.suffix.lower(),
                "h5_datasets": datasets,
            }
    except Exception as exc:
        log.warning("HDF5 preview error: %s", exc)
        return {
            "rel_path": rel_path,
            "file_type": target.suffix.lower(),
            "content": f"Error reading HDF5: {exc}",
        }
