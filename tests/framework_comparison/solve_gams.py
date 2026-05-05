"""
Native GAMS implementation of the ReEDS-representative LP test problem.

Generates a temporary .gms file from ProblemData, calls the GAMS 53 executable,
and parses the .lst output for timing and objective value.

Timing split:
  build_s = Python .gms generation time + GAMS compilation + GAMS GENERATION TIME
            (everything before the solver is handed the LP matrix)
  solve_s = GAMS SOLVE TIME (time inside HiGHS)

This matches how ReEDS currently runs — the full file-based GAMS workflow.
The solver argument sets the GAMS LP solver option (default "highs").
"""

from __future__ import annotations
import re
import subprocess
import tempfile
import time
from pathlib import Path

from data_generator import ProblemData

GAMS_EXE = r"C:\GAMS\53\gams.exe"


def _write_gms(data: ProblemData, gms_path: Path, solver: str) -> None:
    R, I, H, T = data.regions, data.techs, data.hours, data.years
    ri, ii, hi, ti = data.r_idx, data.i_idx, data.h_idx, data.t_idx

    lines = []

    # ---- Sets ---------------------------------------------------------------
    lines += [
        "Sets",
        f"  i  technologies  / {', '.join(I)} /",
        f"  r  regions       / {', '.join(R)} /",
        f"  h  hours         / {', '.join(str(h) for h in H)} /",
        f"  t  years         / {', '.join(str(t) for t in T)} /",
        ";",
        "Alias(r, rr);",
        "Alias(t, tt);",
        "",
        "Sets",
        "  rt(r,rr)  transmission routes /",
        *[f"    {a}.{b}" for (a, b) in data.routes],
        "  /",
        "",
        "  valcap(i,r,t)  active combinations /",
        *[
            f"    {i}.{r}.{t}"
            for i in I for r in R for t in T
            if data.valcap[ii[i], ri[r], ti[t]]
        ],
        "  /",
        ";",
        "",
    ]

    # dispatchable techs (non-zero mingen)
    disp = [i for i in I if data.minloadfrac[ii[i]] > 0]
    has_disp = bool(disp)
    has_emit = any(data.emit_rate[ii[i]] > 0 for i in I)

    # ---- Parameters ---------------------------------------------------------
    def param(name, domain, entries, desc=""):
        lines.append(f"Parameter {name}({domain}) {desc} /")
        lines.extend(f"  {e}" for e in entries)
        lines.extend(["/;", ""])

    param("load_p", "r,h,t",
          [f"{r}.{h}.{t}  {data.load[ri[r], hi[h], ti[t]]:.15g}"
           for r in R for h in H for t in T])

    param("cf_p", "i,h",
          [f"{i}.{h}  {data.cf[ii[i], hi[h]]:.15g}"
           for i in I for h in H])

    param("ci_p", "i,r",
          [f"{i}.{r}  {data.cap_init[ii[i], ri[r]]:.15g}"
           for i in I for r in R if data.cap_init[ii[i], ri[r]] > 0])

    param("cinv_p", "i",
          [f"{i}  {data.cost_inv[ii[i]]:.15g}" for i in I])

    param("cop_p", "i",
          [f"{i}  {data.cost_op[ii[i]]:.15g}" for i in I])

    param("tc_p", "r,rr",
          [f"{a}.{b}  {data.transcap[(a, b)]:.15g}" for (a, b) in data.routes])

    param("pvf_p", "t",
          [f"{t}  {data.pvf[ti[t]]:.15g}" for t in T])

    param("hw_p", "h",
          [f"{h}  {data.hours_weight[hi[h]]:.15g}" for h in H])

    param("peak_p", "r,t",
          [f"{r}.{t}  {float(data.load[ri[r], :, ti[t]].max()):.15g}"
           for r in R for t in T])

    if has_disp:
        param("mf_p", "i",
              [f"{i}  {data.minloadfrac[ii[i]]:.15g}"
               for i in I if data.minloadfrac[ii[i]] > 0])

    if has_emit:
        param("er_p", "i",
              [f"{i}  {data.emit_rate[ii[i]]:.15g}"
               for i in I if data.emit_rate[ii[i]] > 0])

    param("ec_p", "t",
          [f"{t}  {data.emit_cap[ti[t]]:.15g}" for t in T])

    # ---- Variables ----------------------------------------------------------
    lines += [
        "Variables",
        "  GEN(i,r,h,t)",
        "  CAP(i,r,t)",
        "  INV(i,r,t)",
        "  FLOW(r,rr,h,t)",
        "  Z",
        ";",
        "Positive Variables GEN, CAP, INV, FLOW;",
        "",
    ]

    # ---- Equations ----------------------------------------------------------
    eqs = [
        "eq_cap_accum(i,r,t)",
        "eq_cap_limit(i,r,h,t)",
    ]
    if has_disp:
        eqs.append("eq_mingen(i,r,h,t)")
    eqs += ["eq_supply(r,h,t)", "eq_reserve(r,t)", "eq_trans(r,rr,h,t)",
            "eq_emit(t)", "eq_obj"]
    lines += ["Equations", *[f"  {e}" for e in eqs], ";", ""]

    lines += [
        # 3D sparse set as domain controller — valid GAMS syntax
        "eq_cap_accum(valcap(i,r,t))..",
        "  CAP(i,r,t) =e= ci_p(i,r)",
        "    + Sum(tt$(Ord(tt) <= Ord(t) and valcap(i,r,tt)), INV(i,r,tt));",
        "",
        # Can't mix valcap(i,r,t) with free index h in header — use $ instead
        "eq_cap_limit(i,r,h,t)$(valcap(i,r,t))..",
        "  GEN(i,r,h,t) =l= cf_p(i,h) * CAP(i,r,t);",
        "",
    ]

    if has_disp:
        lines += [
            "eq_mingen(i,r,h,t)$(valcap(i,r,t) and mf_p(i) > 0)..",
            "  GEN(i,r,h,t) =g= mf_p(i) * CAP(i,r,t);",
            "",
        ]

    lines += [
        "eq_supply(r,h,t)..",
        "  Sum(i$valcap(i,r,t), GEN(i,r,h,t))",
        f"  + Sum(rt(rr,r), (1 - {data.tranloss}) * FLOW(rr,r,h,t))",
        "  - Sum(rt(r,rr), FLOW(r,rr,h,t))",
        "  =e= load_p(r,h,t);",
        "",
        "eq_reserve(r,t)..",
        f"  Sum(i$valcap(i,r,t), CAP(i,r,t)) =g= (1 + {data.prm}) * peak_p(r,t);",
        "",
        "eq_trans(rt(r,rr),h,t)..",
        "  FLOW(r,rr,h,t) =l= tc_p(r,rr);",
        "",
    ]

    if has_emit:
        lines += [
            "eq_emit(t)..",
            "  Sum((i,r,h)$(valcap(i,r,t) and er_p(i)),",
            "    er_p(i) * hw_p(h) * GEN(i,r,h,t)) =l= ec_p(t);",
            "",
        ]
    else:
        lines += ["eq_emit(t).. 0 =l= ec_p(t);", ""]

    lines += [
        "eq_obj..",
        "  Z =e= Sum(t, pvf_p(t) * (",
        "    Sum((i,r)$valcap(i,r,t), cinv_p(i) * INV(i,r,t))",
        "    + Sum((i,r,h)$valcap(i,r,t),",
        "        cop_p(i) * hw_p(h) * GEN(i,r,h,t))));",
        "",
        "Model reeds_mini / all /;",
        f"Option LP = {solver};",
        "Solve reeds_mini using LP minimizing Z;",
        "Display Z.l;",
    ]

    gms_path.write_text("\n".join(lines), encoding="ascii")


def _parse_lst(lst_path: Path) -> tuple[float, float, float]:
    """Return (objective, generation_time_s, solve_time_s) from .lst file."""
    text = lst_path.read_text(encoding="ascii", errors="replace")

    # Check for licensing or infeasibility problems before objective
    if "Licensing Problem" in text or "SOLVER STATUS     7" in text:
        raise RuntimeError("GAMS solver licensing problem — solver not covered by license")
    if "MODEL STATUS      4" in text or "MODEL STATUS      5" in text:
        raise RuntimeError("GAMS model infeasible or unbounded")

    obj = None
    for pat in [
        r"OBJECTIVE VALUE\s+([\d.E+\-]+)",
        r"Z\.L\s*=\s*([\d.E+\-]+)",
    ]:
        m = re.search(pat, text)
        if m:
            obj = float(m.group(1))
            break

    gen_m = re.search(r"GENERATION TIME\s+=\s+([\d.]+)\s+SECONDS", text)

    # Solver time: GAMS reports RESOURCE USAGE for most solvers (CPLEX, Gurobi);
    # HiGHS reports SOLVE TIME.  Fall back to 0 if neither is present (sub-ms solve).
    solve_m = re.search(r"RESOURCE USAGE,\s*LIMIT\s+([\d.]+)", text)
    if solve_m is None:
        solve_m = re.search(r"SOLVE TIME\s+=\s+([\d.]+)\s+SECONDS", text)

    if obj is None:
        snippet = text[-2000:] if len(text) > 2000 else text
        raise RuntimeError(f"Could not parse objective from {lst_path}:\n{snippet}")

    gen_s   = float(gen_m.group(1))   if gen_m   else 0.0
    solve_s = float(solve_m.group(1)) if solve_m else 0.0
    return obj, gen_s, solve_s


def solve(data: ProblemData, solver: str = "highs") -> tuple[float, float, float]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        gms  = tmp_path / "reeds_mini.gms"
        lst  = tmp_path / "reeds_mini.lst"

        # Python-side .gms file generation
        t0 = time.perf_counter()
        _write_gms(data, gms, solver)
        write_s = time.perf_counter() - t0

        # Full GAMS run: compilation + LP generation + solve
        t1 = time.perf_counter()
        result = subprocess.run(
            [GAMS_EXE, str(gms), "lo=0", f"o={lst}", f"curdir={tmp_path}"],
            capture_output=True, text=True,
        )
        gams_wall = time.perf_counter() - t1

        if result.returncode > 1:   # 0=ok, 1=warnings, 2+=error
            raise RuntimeError(
                f"GAMS exited {result.returncode}:\n"
                f"{result.stdout[-1000:]}\n{result.stderr[-500:]}"
            )

        obj, gen_s, solve_s = _parse_lst(lst)

    # build = Python write + everything GAMS did before handing off to the LP solver
    build_s = write_s + (gams_wall - solve_s)
    return obj, build_s, solve_s


if __name__ == "__main__":
    import sys
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    from data_generator import make_problem
    for size in ("small", "medium", "large"):
        data = make_problem(size)
        obj, b, s = solve(data)
        print(f"{size:6s}  obj={obj:>18,.0f}  build={b:.3f}s  solve={s:.3f}s")
