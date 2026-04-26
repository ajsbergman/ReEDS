/** Guess highlight.js language from a filename extension. */
export function guessLang(filename: string): string | undefined {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    py: "python", gms: "gams", jl: "julia", r: "r", sh: "bash", bat: "dos",
    json: "json", yaml: "yaml", yml: "yaml", toml: "ini", cfg: "ini", ini: "ini",
    csv: "csv", tsv: "csv", md: "markdown", html: "xml", xml: "xml",
    sql: "sql", js: "javascript", ts: "typescript", opt: "ini",
    txt: "plaintext", log: "plaintext", lst: "plaintext",
    inc: "gams", dd: "gams", gpr: "ini",
  };
  return map[ext];
}
