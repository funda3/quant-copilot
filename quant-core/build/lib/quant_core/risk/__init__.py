"""
risk — Sensitivity and risk analytics.

Implemented modules
-------------------
ladder.py     — Bucketed key-rate PV01 ladder for vanilla IRS
                (:func:`~quant_core.risk.ladder.pv01_ladder_irs`)
scenario.py   — Parallel curve-shift scenario runner for vanilla IRS
                (:func:`~quant_core.risk.scenario.run_parallel_curve_scenarios_irs`)
bond_risk.py  — DV01, modified duration, Macaulay duration, and convexity
                for fixed-rate bonds
                (:func:`~quant_core.risk.bond_risk.bond_dv01`,
                 :func:`~quant_core.risk.bond_risk.modified_duration`,
                 :func:`~quant_core.risk.bond_risk.macaulay_duration`,
                 :func:`~quant_core.risk.bond_risk.bond_convexity`)
"""
