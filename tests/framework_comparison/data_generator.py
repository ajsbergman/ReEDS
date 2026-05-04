"""
Parametric test problem generator for ReEDS framework comparison.

Models a simplified single-vintage capacity expansion LP with the same
indexing structure and constraint patterns as c_model.gms:

  Variables:   GEN[i,r,h,t], CAP[i,r,t], INV[i,r,t], FLOW[r,rr,h,t]
  Constraints: supply_demand, cap_limit, cap_accum, reserve_margin,
               trans_limit, mingen, emit_cap
  Objective:   min sum_t pvf[t] * (inv_cost + op_cost)

valcap[i,r,t] sparsity (like GAMS $valcap dollar-conditionals) restricts
which tech/region/year combinations are active, matching ReEDS behaviour
where not every tech is available in every region and year.

Four problem sizes:
  small  —   3 R,  4 I,   8 H,  2 T  (~250 active vars)
  medium —  15 R,  5 I,  24 H,  5 T  (~10k active vars)
  large  —  50 R,  6 I, 168 H, 10 T  (~450k active vars)
  xlarge — 100 R,  8 I, 200 H, 15 T  (~3M active vars, targets ~5 GB peak)
"""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import xarray as xr


SIZES = {
    "small":  dict(n_regions=3,   n_techs=4, n_hours=8,   n_years=2),
    "medium": dict(n_regions=15,  n_techs=5, n_hours=24,  n_years=5),
    "large":  dict(n_regions=50,  n_techs=6, n_hours=168, n_years=10),
    "xlarge": dict(n_regions=100, n_techs=8, n_hours=200, n_years=15),
}

# name, cost_inv($/MW), cost_op($/MWh), avail, is_vre, emit_rate(tCO2/MWh)
TECH_PARAMS = [
    ("gas_cc",   800_000,  30.0, 0.87, False, 0.40),
    ("gas_ct",   400_000,  65.0, 0.90, False, 0.55),
    ("wind",   1_500_000,   4.0, None, True,  0.00),
    ("solar",  1_000_000,   3.0, None, True,  0.00),
    ("coal",   3_000_000,  18.0, 0.85, False, 0.82),
    ("nuclear",5_000_000,  10.0, 0.92, False, 0.01),
    ("battery",  600_000,  12.0, 0.90, False, 0.00),
    ("geotherm",2_000_000, 20.0, 0.85, False, 0.04),
]

# Minimum load fraction for dispatchable techs (0 = unconstrained)
MINLOADFRAC = {
    "gas_cc":   0.40,
    "gas_ct":   0.00,
    "coal":     0.50,
    "nuclear":  0.70,
    "battery":  0.00,
    "geotherm": 0.30,
}


@dataclass
class ProblemData:
    """All sets and parameters for one problem instance."""

    # ---- sets -------------------------------------------------------
    regions: list[str]
    techs:   list[str]
    hours:   list[int]
    years:   list[int]
    routes:  list[tuple]

    # ---- scalar parameters ------------------------------------------
    prm:      float
    tranloss: float

    # ---- indexed parameters (numpy, indexed by position) ------------
    load:         np.ndarray   # [r, h, t]  demand [MW]
    cf:           np.ndarray   # [i, h]     capacity factor
    cost_inv:     np.ndarray   # [i]        $/MW annualised investment
    cost_op:      np.ndarray   # [i]        $/MWh variable O&M + fuel
    cap_init:     np.ndarray   # [i, r]     existing capacity [MW]
    transcap:     dict         # {(r,rr): MW}
    pvf:          np.ndarray   # [t]        present value factor
    hours_weight: np.ndarray   # [h]        hours per timeslice

    # ---- sparsity & new constraint parameters -----------------------
    valcap:      np.ndarray   # [i, r, t]  bool: tech/region/year active
    is_vre:      np.ndarray   # [i]        bool: VRE (no mingen, no emit)
    minloadfrac: np.ndarray   # [i]        min dispatch fraction (0=none)
    emit_rate:   np.ndarray   # [i]        tonne CO2/MWh (0 for VRE)
    emit_cap:    np.ndarray   # [t]        annual CO2 cap (tonne)

    # ---- index maps -------------------------------------------------
    r_idx: dict = field(repr=False)
    i_idx: dict = field(repr=False)
    h_idx: dict = field(repr=False)
    t_idx: dict = field(repr=False)

    # ---- xarray views (built lazily) --------------------------------
    _xr: dict = field(default_factory=dict, repr=False)

    # -----------------------------------------------------------------
    @property
    def n_active_irt(self) -> int:
        return int(self.valcap.sum())

    @property
    def n_vars(self) -> int:
        nH, nT = len(self.hours), len(self.years)
        n_routes = len(self.routes)
        irt = self.n_active_irt
        return irt * nH + irt + irt + n_routes * nH * nT

    @property
    def n_constraints(self) -> int:
        nR, nI, nH, nT = (len(self.regions), len(self.techs),
                          len(self.hours), len(self.years))
        n_routes = len(self.routes)
        irt = self.n_active_irt
        n_disp_irt = int(self.valcap[~self.is_vre].sum())
        return (nR * nH * nT         # supply_demand
                + irt * nH           # cap_limit
                + irt                # cap_accum
                + nR * nT            # reserve_margin
                + n_routes * nH * nT # trans_limit
                + n_disp_irt * nH    # mingen
                + nT)                # emit_cap

    def summary(self) -> str:
        return (f"|R|={len(self.regions)}  |I|={len(self.techs)}  "
                f"|H|={len(self.hours)}  |T|={len(self.years)}  "
                f"|routes|={len(self.routes)}  "
                f"valcap={self.n_active_irt:,}/{len(self.techs)*len(self.regions)*len(self.years):,}  "
                f"vars~{self.n_vars:,}  cons~{self.n_constraints:,}")

    def as_xarray(self) -> dict[str, xr.DataArray]:
        """Return parameters as labelled DataArrays for linopy."""
        if self._xr:
            return self._xr
        R, I, H, T = self.regions, self.techs, self.hours, self.years
        self._xr = {
            "load":         xr.DataArray(self.load,         dims=["r","h","t"],
                                         coords={"r":R,"h":H,"t":T}),
            "cf":           xr.DataArray(self.cf,           dims=["i","h"],
                                         coords={"i":I,"h":H}),
            "cost_inv":     xr.DataArray(self.cost_inv,     dims=["i"],
                                         coords={"i":I}),
            "cost_op":      xr.DataArray(self.cost_op,      dims=["i"],
                                         coords={"i":I}),
            "cap_init":     xr.DataArray(self.cap_init,     dims=["i","r"],
                                         coords={"i":I,"r":R}),
            "pvf":          xr.DataArray(self.pvf,          dims=["t"],
                                         coords={"t":T}),
            "hours_weight": xr.DataArray(self.hours_weight, dims=["h"],
                                         coords={"h":H}),
            "valcap":       xr.DataArray(self.valcap,       dims=["i","r","t"],
                                         coords={"i":I,"r":R,"t":T}),
            "minloadfrac":  xr.DataArray(self.minloadfrac,  dims=["i"],
                                         coords={"i":I}),
            "emit_rate":    xr.DataArray(self.emit_rate,    dims=["i"],
                                         coords={"i":I}),
            "emit_cap":     xr.DataArray(self.emit_cap,     dims=["t"],
                                         coords={"t":T}),
        }
        return self._xr


# -----------------------------------------------------------------
# Capacity factor profiles
# -----------------------------------------------------------------

def _wind_cf(n_hours: int, rng: np.random.Generator) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, n_hours, endpoint=False)
    base = 0.22 + 0.18 * np.sin(t + np.pi)
    noise = rng.uniform(-0.04, 0.04, n_hours)
    return np.clip(base + noise, 0.0, 1.0)


def _solar_cf(n_hours: int, rng: np.random.Generator) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, n_hours, endpoint=False)
    raw = np.maximum(0, np.cos(t - np.pi))
    scaled = 0.9 * raw / raw.max()
    noise = rng.uniform(-0.02, 0.02, n_hours)
    return np.clip(scaled + noise, 0.0, 1.0)


def _load_profile(n_regions: int, n_hours: int, n_years: int,
                  peak_mw: float, rng: np.random.Generator) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, n_hours, endpoint=False)
    daily = 0.6 + 0.4 * np.sin(t - np.pi / 2)
    load = np.zeros((n_regions, n_hours, n_years))
    for r in range(n_regions):
        region_peak = peak_mw * rng.uniform(0.7, 1.3)
        for yt in range(n_years):
            growth = 1.0 + 0.01 * yt
            noise = rng.uniform(0.95, 1.05, n_hours)
            load[r, :, yt] = region_peak * growth * daily * noise
    return load


# -----------------------------------------------------------------
# Ring transmission topology
# -----------------------------------------------------------------

def _ring_routes(regions: list[str], capacity_mw: float) -> tuple[list, dict]:
    n = len(regions)
    routes = []
    transcap = {}
    for i in range(n):
        r  = regions[i]
        rr = regions[(i + 1) % n]
        routes.append((r, rr))
        routes.append((rr, r))
        transcap[(r,  rr)] = capacity_mw
        transcap[(rr, r)]  = capacity_mw
    return routes, transcap


# -----------------------------------------------------------------
# valcap generation
# -----------------------------------------------------------------

def _make_valcap(n_techs: int, n_regions: int, n_years: int,
                 is_vre: np.ndarray, minloadfrac: np.ndarray,
                 rng: np.random.Generator) -> np.ndarray:
    """
    Build a [n_techs, n_regions, n_years] bool mask.

    Each tech enters in a random early year and is available in a
    random subset of regions (60-100%), mimicking GAMS $valcap.

    Feasibility guarantees (applied after random sampling):
    - At least 1 dispatchable (non-VRE) tech active per (r, t) so
      demand can always be met even at hours when VRE CF is near zero.
    - At least 1 VRE tech active per (r, t) so the emission cap is
      achievable.
    """
    valcap = np.zeros((n_techs, n_regions, n_years), dtype=bool)
    entry_year_idx = rng.integers(0, max(1, n_years // 3), size=n_techs)
    region_frac    = rng.uniform(0.6, 1.0, size=n_techs)

    for i in range(n_techs):
        ey = entry_year_idx[i]
        n_avail = max(1, int(np.ceil(region_frac[i] * n_regions)))
        avail_r = rng.choice(n_regions, size=n_avail, replace=False)
        for r in avail_r:
            for t in range(n_years):
                if t >= ey:
                    valcap[i, r, t] = True

    disp_idx = np.where(~is_vre)[0]
    vre_idx  = np.where(is_vre)[0]
    # Prefer lowest-mingen dispatchable when forcing — prevents excess supply
    # at minimum-load hours from making the system infeasible
    disp_by_mingen = sorted(disp_idx, key=lambda i: minloadfrac[i])

    for r in range(n_regions):
        for t in range(n_years):
            # Always force the lowest-mingen dispatchable (gas_ct, mingen=0)
            # into every (r,t).  This guarantees that 60% of cap_init carries
            # zero forced dispatch, keeping system mingen below minimum load.
            if len(disp_by_mingen) > 0:
                valcap[disp_by_mingen[0], r, t] = True

            # Ensure at least 1 VRE (so emission cap is achievable)
            if not valcap[vre_idx, r, t].any() and len(vre_idx) > 0:
                forced = rng.choice(vre_idx)
                valcap[forced, r, t] = True

    return valcap


# -----------------------------------------------------------------
# Main factory
# -----------------------------------------------------------------

def make_problem(size: str = "small", seed: int = 42) -> ProblemData:
    """
    Build a ProblemData instance for the given size key.

    Parameters
    ----------
    size : "small" | "medium" | "large" | "xlarge"
    seed : random seed for reproducibility
    """
    if size not in SIZES:
        raise ValueError(f"size must be one of {list(SIZES)}")
    cfg = SIZES[size]
    rng = np.random.default_rng(seed)

    n_regions = cfg["n_regions"]
    n_hours   = cfg["n_hours"]
    n_years   = cfg["n_years"]
    n_techs   = cfg["n_techs"]

    # ---- sets -------------------------------------------------------
    regions = [f"r{i:02d}" for i in range(n_regions)]
    techs   = [TECH_PARAMS[i][0] for i in range(n_techs)]
    hours   = list(range(n_hours))
    years   = [2030 + 5 * y for y in range(n_years)]

    # ---- tech classification ----------------------------------------
    is_vre      = np.array([TECH_PARAMS[i][3] for i in range(n_techs)], dtype=bool)
    emit_rate   = np.array([TECH_PARAMS[i][5] for i in range(n_techs)], dtype=float)
    minloadfrac = np.array([MINLOADFRAC.get(TECH_PARAMS[i][0], 0.0)
                            for i in range(n_techs)], dtype=float)

    # ---- capacity factor [i, h] ------------------------------------
    cf = np.zeros((n_techs, n_hours))
    for idx, (name, _, _, avail, vre, _) in enumerate(TECH_PARAMS[:n_techs]):
        if vre and name == "wind":
            cf[idx] = _wind_cf(n_hours, rng)
        elif vre and name == "solar":
            cf[idx] = _solar_cf(n_hours, rng)
        else:
            cf[idx] = avail

    # ---- cost vectors -----------------------------------------------
    cost_inv = np.array([TECH_PARAMS[i][1] for i in range(n_techs)], float)
    cost_op  = np.array([TECH_PARAMS[i][2] for i in range(n_techs)], float)

    # ---- load [r, h, t] --------------------------------------------
    peak_mw = {"small": 300.0, "medium": 1_000.0,
               "large": 5_000.0, "xlarge": 10_000.0}[size]
    load = _load_profile(n_regions, n_hours, n_years, peak_mw, rng)

    # ---- initial capacity: assigned below after valcap is known ----
    avg_peak = load[:, :, 0].max(axis=1)

    # ---- transmission -----------------------------------------------
    trans_cap_mw = 0.20 * float(np.mean(avg_peak))
    routes, transcap = _ring_routes(regions, trans_cap_mw)

    # ---- time parameters --------------------------------------------
    hours_weight = np.full(n_hours, 8760.0 / n_hours)
    pvf = np.array([1.0 / (1.07 ** (y - 2030)) for y in years])

    # ---- valcap sparsity mask [i, r, t] ----------------------------
    valcap = _make_valcap(n_techs, n_regions, n_years, is_vre, minloadfrac, rng)

    # ---- initial capacity: assign to lowest-mingen valcap-active dispatchables
    # Sorting by mingen minimises forced dispatch at minimum-load hours.
    cap_init = np.zeros((n_techs, n_regions))
    disp_techs = [i for i in range(n_techs) if not is_vre[i]]
    for r in range(n_regions):
        total = 0.55 * avg_peak[r]
        active_disp = sorted(
            [i for i in disp_techs if valcap[i, r, 0]],
            key=lambda i: minloadfrac[i],
        )
        if len(active_disp) >= 1:
            cap_init[active_disp[0], r] = 0.6 * total
        if len(active_disp) >= 2:
            cap_init[active_disp[1], r] = 0.4 * total
        elif len(active_disp) == 1:
            cap_init[active_disp[0], r] = total

    # ---- emission cap [t] ------------------------------------------
    # Set cap at 70% of total load × mean dispatchable emit rate.
    # Feasible (VRE can cover 30%+) and binding in most solutions.
    total_annual_load = np.einsum("rht,h->t", load, hours_weight)   # [t]
    disp_emit = emit_rate[~is_vre]
    mean_emit  = float(disp_emit.mean()) if len(disp_emit) > 0 else 0.5
    emit_cap   = total_annual_load * mean_emit * 0.70

    # ---- index maps -------------------------------------------------
    r_idx = {r: i for i, r in enumerate(regions)}
    i_idx = {t: i for i, t in enumerate(techs)}
    h_idx = {h: i for i, h in enumerate(hours)}
    t_idx = {t: i for i, t in enumerate(years)}

    return ProblemData(
        regions=regions, techs=techs, hours=hours, years=years,
        routes=routes,
        prm=0.15, tranloss=0.02,
        load=load, cf=cf,
        cost_inv=cost_inv, cost_op=cost_op,
        cap_init=cap_init, transcap=transcap,
        pvf=pvf, hours_weight=hours_weight,
        valcap=valcap, is_vre=is_vre,
        minloadfrac=minloadfrac, emit_rate=emit_rate, emit_cap=emit_cap,
        r_idx=r_idx, i_idx=i_idx, h_idx=h_idx, t_idx=t_idx,
    )


if __name__ == "__main__":
    for size in ("small", "medium", "large", "xlarge"):
        p = make_problem(size)
        print(f"{size:6s}: {p.summary()}")
