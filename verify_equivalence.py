#!/usr/bin/env python3
"""
Verify equivalence of setup-time and flow formulations for RCPSPTT.

For each instance:
  1. Solve with setup-time formulation → extract start times
  2. Fix those start times in flow formulation → check feasibility
  3. Solve with flow formulation → extract start times
  4. Fix those start times in setup-time formulation → check feasibility

If both directions succeed, the formulations agree on that instance.
"""

import argparse
import sys
import time
from pathlib import Path

from solve_rcpsptt import (
    load_instance, load_kraus_instance, collect_instances,
    _build_setup_data, compute_possible_transfers,
)


def extract_starts_optal(mdl, a, time_limit=60, nb_workers=8):
    """Solve OptalCP model and extract start times."""
    result = mdl.solve({"timeLimit": time_limit, "nbWorkers": nb_workers, "logLevel": 0})
    if result is None or result.solution is None:
        return None, None
    starts = []
    for var in a:
        starts.append(int(result.solution.get_start(var)))
    obj = int(result.solution.get_objective())
    return starts, obj


def extract_starts_cpo(mdl, a, time_limit=60, nb_workers=8):
    """Solve CPO model and extract start times."""
    result = mdl.solve(params={
        'TimeLimit': time_limit, 'Workers': nb_workers,
        'LogVerbosity': 'Quiet', 'LogPeriod': 5000,
    })
    if not result or result.get_solve_status() == 'Infeasible':
        return None, None
    obj_vals = result.get_objective_values()
    if obj_vals is None:
        return None, None
    starts = []
    for var in a:
        sol = result.get_var_solution(var)
        starts.append(sol.get_start())
    return starts, int(obj_vals[0])


# =============================================================================
# Build models that return (model, activity_vars) for solution extraction
# =============================================================================

def build_optal_setup_with_vars(inst):
    """Build OptalCP setup model, return (mdl, a)."""
    import optalcp as cp
    abs_A, abs_R, p, C, Q, E = (
        inst['abs_A'], inst['abs_R'], inst['p'], inst['C'],
        inst['Q'], inst['E'])

    mdl = cp.Model(name=f"rcpsptt_setup_{inst['name']}")
    a = [mdl.interval_var(length=p[i], name=f'a_{i}') for i in range(abs_A)]
    mdl.minimize(a[abs_A - 1].end())
    mdl.enforce([a[i].end_before_start(a[j]) for i, j in E])

    for r, cap, tasks_r, transitions in _build_setup_data(inst):
        copies = {}
        for j in tasks_r:
            for m in range(cap):
                copies[(j, m)] = mdl.interval_var(
                    length=p[j], optional=True, name=f'c_{j}_r{r}_m{m}')
        for j in tasks_r:
            mdl.enforce(
                mdl.sum(copies[(j, m)].presence() for m in range(cap)) == Q[j][r])
            for m in range(cap):
                mdl.enforce(a[j].start_at_start(copies[(j, m)]))
        n_tasks_r = len(tasks_r)
        for m in range(cap):
            machine_intervals = [copies[(j, m)] for j in tasks_r]
            seq = mdl.sequence_var(machine_intervals, types=list(range(n_tasks_r)),
                                   name=f'seq_r{r}_m{m}')
            mdl.enforce(seq.no_overlap(transitions))
    return mdl, a


def build_optal_flow_with_vars(inst):
    """Build OptalCP flow model, return (mdl, a)."""
    import optalcp as cp
    abs_A, abs_R, p, C, Q, E, Delta, T = (
        inst['abs_A'], inst['abs_R'], inst['p'], inst['C'],
        inst['Q'], inst['E'], inst['Delta'], inst['T'])

    mdl = cp.Model(name=f"rcpsptt_flow_{inst['name']}")
    a = [mdl.interval_var(length=p[i], name=f'a_{i}') for i in range(abs_A)]
    f = {(i, j, r): mdl.int_var(min=1, max=U_ijr, name=f'f_{i}_{j}_{r}', optional=True)
         for (i, j, r), U_ijr in T.items()}
    z = {(i, j, r): mdl.interval_var(length=Delta[i][j][r], optional=True,
                                     name=f'z_{i}_{j}_{r}')
         for (i, j, r) in T.keys()}

    mdl.minimize(a[abs_A - 1].end())
    mdl.enforce([a[i].end_before_start(a[j]) for i, j in E])

    for r in range(abs_R):
        if outgoing := [f[(0, j, r)] for j in range(abs_A) if (0, j, r) in T]:
            mdl.enforce(mdl.sum(outgoing) == C[r])

    for (i, j, r) in T.keys():
        mdl.enforce(f[(i, j, r)].presence() == z[(i, j, r)].presence())

    for i in range(1, abs_A):
        for r in range(abs_R):
            if Q[i][r] > 0:
                if incoming := [f[(j, i, r)] for j in range(abs_A) if (j, i, r) in T]:
                    mdl.enforce(mdl.sum(incoming) == Q[i][r])

    for i in range(1, abs_A - 1):
        for r in range(abs_R):
            if Q[i][r] > 0:
                if outgoing := [f[(i, j, r)] for j in range(abs_A) if (i, j, r) in T]:
                    mdl.enforce(mdl.sum(outgoing) == Q[i][r])

    for (i, j, r) in T.keys():
        mdl.enforce(a[i].end_before_start(z[(i, j, r)]))
        mdl.enforce(z[(i, j, r)].end_before_start(a[j]))

    for r in range(abs_R):
        activity_pulses = [mdl.pulse(a[i], Q[i][r]) for i in range(abs_A) if Q[i][r] > 0]
        transfer_pulses = [mdl.pulse(z[(i, j, r)], f[(i, j, r)])
                           for (i2, j2, res) in T.keys()
                           if res == r and Delta[i2][j2][r] > 0
                           for i, j in [(i2, j2)]]
        if all_pulses := activity_pulses + transfer_pulses:
            mdl.enforce(mdl.sum(all_pulses) <= C[r])

    return mdl, a


def build_optal_flow_fixed(inst, starts):
    """Build OptalCP flow model with fixed start times. Return (mdl, a)."""
    import optalcp as cp
    abs_A, abs_R, p, C, Q, E, Delta, T = (
        inst['abs_A'], inst['abs_R'], inst['p'], inst['C'],
        inst['Q'], inst['E'], inst['Delta'], inst['T'])

    mdl = cp.Model(name=f"rcpsptt_flow_fixed_{inst['name']}")
    a = [mdl.interval_var(length=p[i], name=f'a_{i}') for i in range(abs_A)]

    # Fix start times
    for i in range(abs_A):
        mdl.enforce(a[i].start() == starts[i])

    f = {(i, j, r): mdl.int_var(min=1, max=U_ijr, name=f'f_{i}_{j}_{r}', optional=True)
         for (i, j, r), U_ijr in T.items()}
    z = {(i, j, r): mdl.interval_var(length=Delta[i][j][r], optional=True,
                                     name=f'z_{i}_{j}_{r}')
         for (i, j, r) in T.keys()}

    # No objective needed — just check feasibility
    mdl.minimize(a[abs_A - 1].end())

    mdl.enforce([a[i].end_before_start(a[j]) for i, j in E])

    for r in range(abs_R):
        if outgoing := [f[(0, j, r)] for j in range(abs_A) if (0, j, r) in T]:
            mdl.enforce(mdl.sum(outgoing) == C[r])

    for (i, j, r) in T.keys():
        mdl.enforce(f[(i, j, r)].presence() == z[(i, j, r)].presence())

    for i in range(1, abs_A):
        for r in range(abs_R):
            if Q[i][r] > 0:
                if incoming := [f[(j, i, r)] for j in range(abs_A) if (j, i, r) in T]:
                    mdl.enforce(mdl.sum(incoming) == Q[i][r])

    for i in range(1, abs_A - 1):
        for r in range(abs_R):
            if Q[i][r] > 0:
                if outgoing := [f[(i, j, r)] for j in range(abs_A) if (i, j, r) in T]:
                    mdl.enforce(mdl.sum(outgoing) == Q[i][r])

    for (i, j, r) in T.keys():
        mdl.enforce(a[i].end_before_start(z[(i, j, r)]))
        mdl.enforce(z[(i, j, r)].end_before_start(a[j]))

    for r in range(abs_R):
        activity_pulses = [mdl.pulse(a[i], Q[i][r]) for i in range(abs_A) if Q[i][r] > 0]
        transfer_pulses = [mdl.pulse(z[(i, j, r)], f[(i, j, r)])
                           for (i2, j2, res) in T.keys()
                           if res == r and Delta[i2][j2][r] > 0
                           for i, j in [(i2, j2)]]
        if all_pulses := activity_pulses + transfer_pulses:
            mdl.enforce(mdl.sum(all_pulses) <= C[r])

    return mdl, a


def build_optal_setup_fixed(inst, starts):
    """Build OptalCP setup model with fixed start times. Return (mdl, a)."""
    import optalcp as cp
    abs_A, abs_R, p, C, Q, E = (
        inst['abs_A'], inst['abs_R'], inst['p'], inst['C'],
        inst['Q'], inst['E'])

    mdl = cp.Model(name=f"rcpsptt_setup_fixed_{inst['name']}")
    a = [mdl.interval_var(length=p[i], name=f'a_{i}') for i in range(abs_A)]

    # Fix start times
    for i in range(abs_A):
        mdl.enforce(a[i].start() == starts[i])

    mdl.minimize(a[abs_A - 1].end())
    mdl.enforce([a[i].end_before_start(a[j]) for i, j in E])

    for r, cap, tasks_r, transitions in _build_setup_data(inst):
        copies = {}
        for j in tasks_r:
            for m in range(cap):
                copies[(j, m)] = mdl.interval_var(
                    length=p[j], optional=True, name=f'c_{j}_r{r}_m{m}')
        for j in tasks_r:
            mdl.enforce(
                mdl.sum(copies[(j, m)].presence() for m in range(cap)) == Q[j][r])
            for m in range(cap):
                mdl.enforce(a[j].start_at_start(copies[(j, m)]))
        n_tasks_r = len(tasks_r)
        for m in range(cap):
            machine_intervals = [copies[(j, m)] for j in tasks_r]
            seq = mdl.sequence_var(machine_intervals, types=list(range(n_tasks_r)),
                                   name=f'seq_r{r}_m{m}')
            mdl.enforce(seq.no_overlap(transitions))

    return mdl, a


# =============================================================================
# Verification logic
# =============================================================================

def verify_instance(inst, time_limit=60, nb_workers=8):
    """Verify equivalence on one instance. Returns dict with results."""
    name = inst['name']
    abs_A = inst['abs_A']
    results = {'instance': name, 'n_jobs': abs_A}

    # --- Direction 1: setup → flow ---
    print(f"  [setup→flow] Solving setup-time model...", end=" ", flush=True)
    mdl_s, a_s = build_optal_setup_with_vars(inst)
    starts_setup, obj_setup = extract_starts_optal(mdl_s, a_s, time_limit, nb_workers)

    if starts_setup is None:
        print("NO SOLUTION")
        results['setup_obj'] = None
        results['setup_to_flow'] = 'no_setup_solution'
    else:
        print(f"obj={obj_setup}")
        results['setup_obj'] = obj_setup

        # Print schedule
        print(f"    Schedule (first 10 activities):")
        for i in range(min(10, abs_A)):
            print(f"      a_{i}: start={starts_setup[i]}, "
                  f"end={starts_setup[i] + inst['p'][i]}, dur={inst['p'][i]}")
        if abs_A > 10:
            print(f"      ... ({abs_A - 10} more)")

        # Fix in flow model
        print(f"  [setup→flow] Checking in flow model...", end=" ", flush=True)
        mdl_f_fixed, a_f_fixed = build_optal_flow_fixed(inst, starts_setup)
        starts_check, obj_check = extract_starts_optal(
            mdl_f_fixed, a_f_fixed, time_limit, nb_workers)

        if starts_check is not None:
            print(f"FEASIBLE (obj={obj_check})")
            results['setup_to_flow'] = 'ok'
            results['setup_to_flow_obj'] = obj_check
            if obj_check != obj_setup:
                print(f"    WARNING: objectives differ! setup={obj_setup}, flow={obj_check}")
        else:
            print("INFEASIBLE!")
            results['setup_to_flow'] = 'infeasible'

    # --- Direction 2: flow → setup ---
    print(f"  [flow→setup] Solving flow model...", end=" ", flush=True)
    mdl_f, a_f = build_optal_flow_with_vars(inst)
    starts_flow, obj_flow = extract_starts_optal(mdl_f, a_f, time_limit, nb_workers)

    if starts_flow is None:
        print("NO SOLUTION")
        results['flow_obj'] = None
        results['flow_to_setup'] = 'no_flow_solution'
    else:
        print(f"obj={obj_flow}")
        results['flow_obj'] = obj_flow

        print(f"    Schedule (first 10 activities):")
        for i in range(min(10, abs_A)):
            print(f"      a_{i}: start={starts_flow[i]}, "
                  f"end={starts_flow[i] + inst['p'][i]}, dur={inst['p'][i]}")
        if abs_A > 10:
            print(f"      ... ({abs_A - 10} more)")

        # Fix in setup model
        print(f"  [flow→setup] Checking in setup model...", end=" ", flush=True)
        mdl_s_fixed, a_s_fixed = build_optal_setup_fixed(inst, starts_flow)
        starts_check2, obj_check2 = extract_starts_optal(
            mdl_s_fixed, a_s_fixed, time_limit, nb_workers)

        if starts_check2 is not None:
            print(f"FEASIBLE (obj={obj_check2})")
            results['flow_to_setup'] = 'ok'
            results['flow_to_setup_obj'] = obj_check2
            if obj_check2 != obj_flow:
                print(f"    WARNING: objectives differ! flow={obj_flow}, setup={obj_check2}")
        else:
            print("INFEASIBLE!")
            results['flow_to_setup'] = 'infeasible'

    return results


def main():
    parser = argparse.ArgumentParser(description='Verify setup-time ↔ flow equivalence')
    parser.add_argument('--data', type=str, default='data/rcpsp_tt_instances')
    parser.add_argument('--set', nargs='+', default=['j30'])
    parser.add_argument('--format', type=str, choices=['psplib', 'kraus'], default=None, dest='fmt')
    parser.add_argument('--max', type=int, default=10)
    parser.add_argument('--timeLimit', type=int, default=60)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()

    instances = collect_instances(args.data, args.set, fmt=args.fmt)
    instances = instances[:args.max]

    if not instances:
        print(f"No instances found in {args.data}")
        return 1

    print("=" * 70)
    print("RCPSPTT Formulation Equivalence Verification")
    print("=" * 70)
    print(f"  Instances: {len(instances)}")
    print(f"  Time limit: {args.timeLimit}s per solve")
    print(f"  Workers: {args.workers}")
    print("=" * 70)

    all_results = []
    for inst_path in instances:
        name = inst_path.stem
        print(f"\n{'─' * 70}")
        print(f"Instance: {name}")
        print(f"{'─' * 70}")

        fmt = args.fmt
        if fmt is None:
            fmt = "kraus" if str(inst_path).endswith(".json") else "psplib"
        if fmt == "kraus":
            inst = load_kraus_instance(str(inst_path))
        else:
            inst = load_instance(str(inst_path))

        res = verify_instance(inst, args.timeLimit, args.workers)
        all_results.append(res)

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"{'Instance':<30} {'Setup→Flow':<15} {'Flow→Setup':<15} {'Setup Obj':<12} {'Flow Obj':<12}")
    print("-" * 84)
    for r in all_results:
        s2f = r.get('setup_to_flow', '?')
        f2s = r.get('flow_to_setup', '?')
        so = r.get('setup_obj', '-')
        fo = r.get('flow_obj', '-')
        print(f"{r['instance']:<30} {s2f:<15} {f2s:<15} {str(so):<12} {str(fo):<12}")

    # Check for failures
    failures = [r for r in all_results
                if r.get('setup_to_flow') == 'infeasible' or r.get('flow_to_setup') == 'infeasible']
    if failures:
        print(f"\n*** {len(failures)} EQUIVALENCE FAILURES! ***")
        return 1
    else:
        print(f"\nAll verified instances are consistent.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
