# cost_mult_{GSw_TransCostMultScen}.csv

Time-varying multipliers on transmission and interconnection cost, selected by
`GSw_TransCostMultScen`. Long format: `component,t,mult`. For each model year the
multiplier in force is the one at the latest listed year <= that model year; years
before the first listed year use 1. These stack multiplicatively on top of the static
switches (GSw_TransCostMult, GSw_InterconnectionCostMult, GSw_SpurCostMult,
GSw_FedLandCostMult).

| component | what it scales |
|---|---|
| `inter` | capex of transmission lines that cross an **interconnect** boundary (Eastern/Western/ERCOT). Lines within an interconnect are not scaled. |
| `intra` | Sw_TransIntraCost, the intra-zone network reinforcement charge on INV_POI |
| `spur`  | cost_spur component of the VRE supply-curve interconnection cost |
| `poi`   | cost_poi component (flat POI tariff) |
| `reinf` | cost_reinforcement component (network reinforcement beyond the POI) |

The supply-curve components (`spur`, `poi`, `reinf`) are written to rsc_combined.csv
by writesupplycurves.py and recombined in b_inputs.gms into a time-varying
m_rsc_dat_t. Bin assignment still uses the un-multiplied base cost.

`cost_mult_enhanced.csv` encodes the "Enhanced Transmission Case" table from the
client's 2026 permitting-reform scenarios sheet, with this mapping of their rows:

| sheet row | component | note |
|---|---|---|
| Interconnection Cost Adder | `inter` | Per the client, "Interconnection Transmission" means lines between the three US interconnections, so this adder is scoped to those routes. DERIVED from that definition, not stated explicitly for the cost adder. |
| Intrazone Transmission Cost Adder | `intra` | |
| Spur Line Cost Adder | `spur` + `poi` | Per the client, the spur adder applies to the POI charge as well. |
| Network Reinforcement Cost Adder | `reinf` | |
