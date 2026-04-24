import { useState, type FormEvent } from "react";
import {
  searchAPI,
  type SearchResult,
  type SearchResponse,
} from "../lib/api";

interface Props {
  onSelectFile: (path: string) => void;
}

const CATEGORIES = ["all", "docs", "code", "inputs", "outputs"] as const;

export default function SearchPanel({ onSelectFile }: Props) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("all");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch(e: FormEvent) {
    e.preventDefault();
    if (!query.trim() || loading) return;
    setError(null);
    setLoading(true);
    try {
      const res: SearchResponse = await searchAPI(query, category);
      setResults(res.results);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="center-panel">
      {error && <div className="error-banner">{error}</div>}
      <form className="search-bar" onSubmit={handleSearch}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search ReEDS repo…"
        />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <button type="submit" disabled={loading || !query.trim()}>
          Search
        </button>
      </form>
      <div className="search-results">
        {loading && <div className="loading">Searching…</div>}
        {results.map((r, i) => (
          <div
            key={i}
            className="search-hit"
            onClick={() => onSelectFile(r.file_path)}
          >
            <div className="path">{r.file_path}</div>
            <div className="snippet">{r.snippet}</div>
          </div>
        ))}
        {!loading && results.length === 0 && query && (
          <div className="loading">No results.</div>
        )}
      </div>
    </div>
  );
}
