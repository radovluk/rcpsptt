#!/usr/bin/env python3
"""
RCPSPTT Solver Runner — Compare IBM CPO and OptalCP on RCPSP with Transfer Times

Solves RCPSPTT instances (PSPLIB .sm format with TRANSFERTIMES sections) using
IBM CP Optimizer (docplex.cp) and/or OptalCP. Results are tracked as JSON with
per-instance solution details (objective, state, runtime, etc.).

Usage:
    # Solve all j30 instances with both solvers:
    python solve_rcpsptt.py --set j30

    # Solve with OptalCP only, 120s per instance:
    python solve_rcpsptt.py --solver optal --timeLimit 120

    # Solve first 5 instances, save to custom output:
    python solve_rcpsptt.py --set j30 --max 5 --output results/my_run/

    # Resume a previous run:
    python solve_rcpsptt.py --set j30 --solver both

    # Dry run:
    python solve_rcpsptt.py --set j30 --dry-run
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = SCRIPT_DIR / "data" / "rcpsp_tt_instances"

SETS = ["j30", "j60", "j90", "j120"]


# =============================================================================
# INSTANCE PARSING (from rcpsptt.ipynb)
# =============================================================================

def parse_rcpsp_psplib(filepath):
    """
    Parses a .sm file (PSPLIB format for RCPSP with transfer times)
    and returns a dictionary with the project data.
    """
    with open(filepath, 'r') as f:
        content = f.read()

    data = {}
    match = re.search(r'jobs \(incl\. supersource/sink \):\s*(\d+)', content)
    data['n_jobs'] = int(match.group(1)) if match else 0
    match = re.search(r' - renewable\s*:\s*(\d+)', content)
    data['n_resources'] = int(match.group(1)) if match else 0
    n_jobs = data['n_jobs']
    n_res = data['n_resources']
    data['precedence_arcs'] = []
    prec_start = content.find('PRECEDENCE RELATIONS:')
    prec_end = content.find('****************', prec_start)
    prec_section = content[prec_start:prec_end]

    for line in prec_section.splitlines()[2:]:
        if not line.strip():
            continue
        parts = [int(p) for p in line.strip().split()]
        predecessor = parts[0]
        successors = parts[3:]
        for succ in successors:
            data['precedence_arcs'].append((predecessor - 1, succ - 1))

    data['durations'] = []
    data['demands'] = []
    req_start = content.find('REQUESTS/DURATIONS:')
    req_end = content.find('****************', req_start)
    req_section = content[req_start:req_end]

    for line in req_section.splitlines()[3:]:
        if not line.strip():
            continue
        parts = [int(p) for p in line.strip().split()]
        data['durations'].append(parts[2])
        data['demands'].append(parts[3:])

    cap_start = content.find('RESOURCEAVAILABILITIES:')
    cap_end = content.find('****************', cap_start)
    cap_section = content[cap_start:cap_end]

    cap_line = cap_section.splitlines()[2]
    data['capacities'] = [int(p) for p in cap_line.strip().split()]
    data['transfer_times'] = []
    current_pos = cap_end

    for _ in range(n_res):
        tt_start = content.find('TRANSFERTIMES', current_pos)
        tt_end = content.find('****************', tt_start)
        tt_section = content[tt_start:tt_end]

        matrix = []
        lines = tt_section.splitlines()[3:]

        for i in range(n_jobs):
            line = lines[i]
            parts = [int(p) for p in line.strip().split()]
            matrix.append(parts[1:])

        data['transfer_times'].append(matrix)
        current_pos = tt_end
    return data


def compute_transitive_closure(edges, n_jobs):
    """Computes transitive closure using Floyd-Warshall."""
    adj = [[False] * n_jobs for _ in range(n_jobs)]
    for i, j in edges:
        adj[i][j] = True
    for k in range(n_jobs):
        for i in range(n_jobs):
            for j in range(n_jobs):
                adj[i][j] = adj[i][j] or (adj[i][k] and adj[k][j])
    return [(i, j) for i in range(n_jobs) for j in range(n_jobs) if adj[i][j]]


def compute_possible_transfers(abs_A, abs_R, Q, C, E, max_flow_limit=1000):
    """Generates the set T (feasible transfers) and upper bounds U."""
    T = {}
    E_set = set(E)
    for i in range(abs_A):
        for j in range(abs_A):
            if i == j or (j, i) in E_set:
                continue
            for r in range(abs_R):
                source_has_resource = (i == 0 or Q[i][r] > 0)
                target_needs_resource = (j == abs_A - 1 or Q[j][r] > 0)
                if source_has_resource and target_needs_resource:
                    max_flow = C[r] if i == 0 else min(Q[i][r], C[r])
                    T[(i, j, r)] = min(max_flow, max_flow_limit)
    return T


def load_instance(filepath):
    """Load and preprocess a RCPSPTT instance from a .sm file.

    Returns a dict with: abs_A, abs_R, p, C, Q, E, Delta, T
    """
    data = parse_rcpsp_psplib(filepath)
    abs_A = data['n_jobs']
    abs_R = data['n_resources']
    p = data['durations']
    C = data['capacities']
    Q = data['demands']
    E = compute_transitive_closure(data['precedence_arcs'], abs_A)

    # Enforce Q[0,r] = Cr and Q[last,r] = Cr
    Q[0] = C[:]
    Q[abs_A - 1] = C[:]

    # Build Delta[i][j][r]
    Delta = []
    for i in range(abs_A):
        Delta.append([])
        for j in range(abs_A):
            Delta[i].append([])
            for r in range(abs_R):
                Delta[i][j].append(data['transfer_times'][r][i][j])

    T = compute_possible_transfers(abs_A, abs_R, Q, C, E)

    return {
        'abs_A': abs_A, 'abs_R': abs_R, 'p': p, 'C': C, 'Q': Q,
        'E': E, 'Delta': Delta, 'T': T, 'name': Path(filepath).stem,
    }


# =============================================================================
# IBM CPO MODEL
# =============================================================================

def build_model_cpo(inst):
    """Build IBM CPO model for RCPSPTT (from rcpsptt.ipynb)."""
    from docplex.cp.model import CpoModel

    abs_A, abs_R, p, C, Q, E, Delta, T = (
        inst['abs_A'], inst['abs_R'], inst['p'], inst['C'],
        inst['Q'], inst['E'], inst['Delta'], inst['T'])

    mdl = CpoModel(name=f"rcpsptt_cpo_{inst['name']}")

    # (10a): a_i (mandatory interval variables)
    a = [mdl.interval_var(size=p[i], name=f'a_{i}') for i in range(abs_A)]

    # (10b): f_{i,j,r} (integer flow variables)
    f = {(i, j, r): mdl.integer_var(min=0, max=U_ijr, name=f'f_{i}_{j}_{r}')
         for (i, j, r), U_ijr in T.items()}

    # (10c): z_{i,j,r} (optional transfer intervals)
    z = {(i, j, r): mdl.interval_var(size=Delta[i][j][r], optional=True,
                                     name=f'z_{i}_{j}_{r}')
         for (i, j, r) in T.keys()}

    # Helper: pulse expressions for cumulative constraint
    cumulative_contributions = {
        (i, j, r): mdl.pulse(z[(i, j, r)], (0, T[(i, j, r)]))
        for (i, j, r) in T.keys() if Delta[i][j][r] > 0
    }

    # (1): Minimize makespan
    mdl.add(mdl.minimize(mdl.end_of(a[abs_A - 1])))

    # (2) Precedence relations
    mdl.add([mdl.end_before_start(a[i], a[j]) for i, j in E])

    # (3) Source flow initialization
    for r in range(abs_R):
        if outgoing := [f[(0, j, r)] for j in range(abs_A) if (0, j, r) in T]:
            mdl.add(mdl.sum(outgoing) == C[r])

    # (4) Implication for instantaneous transfers (Delta = 0)
    mdl.add(mdl.if_then(f[(i, j, r)] >= 1, mdl.presence_of(z[(i, j, r)]))
            for (i, j, r) in T.keys() if Delta[i][j][r] == 0)

    # (5) Flow-height linkage for durative transfers
    for (i, j, r), pulse in cumulative_contributions.items():
        mdl.add(f[(i, j, r)] == mdl.height_at_start(z[(i, j, r)], pulse))

    # (6) Flow conservation (into activity)
    for i in range(1, abs_A):
        for r in range(abs_R):
            if Q[i][r] > 0:
                if incoming := [f[(j, i, r)] for j in range(abs_A) if (j, i, r) in T]:
                    mdl.add(mdl.sum(incoming) == Q[i][r])

    # (7) Flow conservation (out of activity)
    for i in range(1, abs_A - 1):
        for r in range(abs_R):
            if Q[i][r] > 0:
                if outgoing := [f[(i, j, r)] for j in range(abs_A) if (i, j, r) in T]:
                    mdl.add(mdl.sum(outgoing) == Q[i][r])

    # (8) Temporal linking for transfers
    for (i, j, r) in T.keys():
        mdl.add(mdl.end_before_start(a[i], z[(i, j, r)]))
        mdl.add(mdl.end_before_start(z[(i, j, r)], a[j]))

    # (9) Resource capacity (cumulative constraint)
    for r in range(abs_R):
        activity_pulses = [mdl.pulse(a[i], Q[i][r]) for i in range(abs_A) if Q[i][r] > 0]
        transfer_pulses = [pulse for (i, j, res), pulse in cumulative_contributions.items() if res == r]
        if pulses := activity_pulses + transfer_pulses:
            mdl.add(mdl.sum(pulses) <= C[r])

    return mdl


# =============================================================================
# OPTALCP MODEL
# =============================================================================

def build_model_optal(inst):
    """Build OptalCP model for RCPSPTT (from rcpsptt.ipynb)."""
    import optalcp as cp

    abs_A, abs_R, p, C, Q, E, Delta, T = (
        inst['abs_A'], inst['abs_R'], inst['p'], inst['C'],
        inst['Q'], inst['E'], inst['Delta'], inst['T'])

    mdl = cp.Model(name=f"rcpsptt_optal_{inst['name']}")

    # (9a): a_i (mandatory interval variables)
    a = [mdl.interval_var(length=p[i], name=f'a_{i}') for i in range(abs_A)]

    # (9b): f_{i,j,r} (optional integer flow variables with min=1)
    f = {(i, j, r): mdl.int_var(min=1, max=U_ijr, name=f'f_{i}_{j}_{r}', optional=True)
         for (i, j, r), U_ijr in T.items()}

    # (9c): z_{i,j,r} (optional interval variables for transfers)
    z = {(i, j, r): mdl.interval_var(length=Delta[i][j][r], optional=True,
                                     name=f'z_{i}_{j}_{r}')
         for (i, j, r) in T.keys()}

    # (1): Minimize makespan
    mdl.minimize(a[abs_A - 1].end())

    # (2) Precedence relations
    mdl.enforce([a[i].end_before_start(a[j]) for i, j in E])

    # (3) Source flow initialization
    for r in range(abs_R):
        if outgoing := [f[(0, j, r)] for j in range(abs_A) if (0, j, r) in T]:
            mdl.enforce(mdl.sum(outgoing) == C[r])

    # (4) Presence synchronization: flow present iff transfer interval present
    for (i, j, r) in T.keys():
        mdl.enforce(f[(i, j, r)].presence() == z[(i, j, r)].presence())

    # (5) Flow conservation (into activity)
    for i in range(1, abs_A):
        for r in range(abs_R):
            if Q[i][r] > 0:
                if incoming := [f[(j, i, r)] for j in range(abs_A) if (j, i, r) in T]:
                    mdl.enforce(mdl.sum(incoming) == Q[i][r])

    # (6) Flow conservation (out of activity)
    for i in range(1, abs_A - 1):
        for r in range(abs_R):
            if Q[i][r] > 0:
                if outgoing := [f[(i, j, r)] for j in range(abs_A) if (i, j, r) in T]:
                    mdl.enforce(mdl.sum(outgoing) == Q[i][r])

    # (7) Temporal linking for transfers
    for (i, j, r) in T.keys():
        mdl.enforce(a[i].end_before_start(z[(i, j, r)]))
        mdl.enforce(z[(i, j, r)].end_before_start(a[j]))

    # (8) Resource capacity (cumulative constraint)
    for r in range(abs_R):
        activity_pulses = [mdl.pulse(a[i], Q[i][r]) for i in range(abs_A) if Q[i][r] > 0]
        transfer_pulses = [mdl.pulse(z[(i, j, r)], f[(i, j, r)])
                           for (i, j, res) in T.keys()
                           if res == r and Delta[i][j][r] > 0]
        if all_pulses := activity_pulses + transfer_pulses:
            mdl.enforce(mdl.sum(all_pulses) <= C[r])

    return mdl


# =============================================================================
# SOLVER EXECUTION
# =============================================================================

def _parse_cpo_best_solution_time(log_text):
    """Extract the time of the last solution found from CPO log output."""
    last_time = None
    for line in log_text.split('\n'):
        if line.strip().startswith('!'):
            for tok in reversed(line.split()):
                if tok.endswith('s'):
                    try:
                        last_time = float(tok[:-1])
                        break
                    except ValueError:
                        continue
    return last_time


def solve_with_cpo(mdl, nb_workers, time_limit, log_verbosity):
    """Run CPO solver. Returns result dict."""
    from io import StringIO

    log_map = {0: 'Quiet', 1: 'Terse', 2: 'Normal', 3: 'Verbose'}
    # Always use at least Terse internally so we can parse best solution time
    internal_verbosity = max(log_verbosity, 1)
    params = {
        'TimeLimit': time_limit,
        'Workers': nb_workers,
        'LogVerbosity': log_map.get(internal_verbosity, 'Terse'),
        'LogPeriod': 5000,
    }

    log_buffer = StringIO()
    if log_verbosity > 0:
        class TeeStream:
            def __init__(self, *streams):
                self.streams = streams
            def write(self, data):
                for s in self.streams:
                    s.write(data)
            def flush(self):
                for s in self.streams:
                    s.flush()
        log_output = TeeStream(sys.stdout, log_buffer)
    else:
        log_output = log_buffer

    t0 = time.monotonic()
    result = mdl.solve(params=params, log_output=log_output)
    wall_time = round(time.monotonic() - t0, 3)

    solve_status = result.get_solve_status() if result else None
    obj_values = result.get_objective_values() if result else None
    cmax = int(obj_values[0]) if obj_values else None

    if solve_status == "Optimal":
        state = "Optimal"
    elif cmax is not None:
        state = "Feasible"
    else:
        state = "NoSolution"

    best_solution_time = _parse_cpo_best_solution_time(log_buffer.getvalue())

    return cmax, state, wall_time, best_solution_time


def solve_with_optal(mdl, nb_workers, time_limit, log_verbosity):
    """Run OptalCP solver. Returns result dict."""
    params = {
        "timeLimit": time_limit,
        "nbWorkers": nb_workers,
        "logLevel": min(log_verbosity, 2),
        "logPeriod": 5,
    }

    t0 = time.monotonic()
    result = mdl.solve(params)
    wall_time = round(time.monotonic() - t0, 3)

    cmax = None
    try:
        if result is not None and result.solution is not None:
            cmax = int(result.solution.get_objective())
    except (AttributeError, TypeError):
        pass

    proof = False
    try:
        proof = getattr(result, "proof", False)
    except (AttributeError, TypeError):
        pass

    if proof:
        state = "Optimal"
    elif cmax is not None:
        state = "Feasible"
    else:
        state = "NoSolution"

    best_solution_time = None
    try:
        st = result.solution_time
        if st is not None:
            best_solution_time = round(st, 3)
    except (AttributeError, TypeError):
        pass

    return cmax, state, wall_time, best_solution_time


# =============================================================================
# SOLVE SINGLE INSTANCE
# =============================================================================

def solve_instance(filepath, solver_name, nb_workers, time_limit, log_verbosity):
    """Solve one RCPSPTT instance. Returns a result dict (JSON-serializable)."""
    inst = load_instance(filepath)

    t_build_start = time.monotonic()
    if solver_name == "cpo":
        mdl = build_model_cpo(inst)
    else:
        mdl = build_model_optal(inst)
    build_time = round(time.monotonic() - t_build_start, 3)

    if solver_name == "cpo":
        cmax, state, wall_time, best_solution_time = solve_with_cpo(
            mdl, nb_workers, time_limit, log_verbosity)
    else:
        cmax, state, wall_time, best_solution_time = solve_with_optal(
            mdl, nb_workers, time_limit, log_verbosity)

    return {
        "instance": inst['name'],
        "solver": solver_name,
        "n_jobs": inst['abs_A'],
        "n_resources": inst['abs_R'],
        "objective": cmax,
        "state": state,
        "duration": wall_time,
        "build_time": build_time,
        "best_solution_time": best_solution_time,
        "time_limit": time_limit,
        "workers": nb_workers,
    }


# =============================================================================
# INSTANCE COLLECTION
# =============================================================================

def _natural_sort_key(path):
    return [int(s) if s.isdigit() else s.lower() for s in re.split(r'(\d+)', path.name)]


def _instance_set(name):
    """Determine which set (j30/j60/j90/j120) an instance belongs to."""
    for s in SETS:
        if name.startswith(s):
            return s
    return None


def collect_instances(data_dir, sets=None):
    """Collect _a.sm instance files matching the given set filters."""
    data_dir = Path(data_dir)
    files = sorted(data_dir.glob("*_a.sm"), key=_natural_sort_key)

    if sets:
        files = [f for f in files if _instance_set(f.stem.replace('_a', '')) in sets]

    return files


# =============================================================================
# BATCH RUNNER WITH JSON TRACKING
# =============================================================================

def run_solver_batch(instances, solver_name, nb_workers, time_limit,
                     log_verbosity, out_file):
    """Run a solver on all instances, tracking results as JSON.

    Supports resume: if out_file exists, previously solved instances are skipped.
    Results are saved incrementally after each instance.
    """
    all_results = []

    # Resume: load previous results
    if out_file and out_file.exists():
        with open(out_file) as f:
            all_results = json.load(f)
        solved_names = {r['instance'] for r in all_results}
        remaining = [inst for inst in instances
                     if inst.stem.replace('_a', '') not in solved_names]
        if len(remaining) != len(instances):
            print(f"    Resuming: {len(all_results)} previous results loaded, "
                  f"{len(remaining)} remaining")
            instances = remaining

    if not instances:
        print(f"    All instances already solved")
        return all_results

    total = len(instances)

    for idx, instance_path in enumerate(instances):
        instance_name = instance_path.stem.replace('_a', '')
        print(f"\n  [{idx+1}/{total}] {instance_name}")
        sys.stdout.flush()

        try:
            result = solve_instance(
                str(instance_path), solver_name,
                nb_workers, time_limit, log_verbosity)

            bst = result['best_solution_time']
            bst_str = f"{bst}s" if bst is not None else "N/A"
            print(f"    objective={result['objective']}  state={result['state']}  "
                  f"duration={result['duration']}s  "
                  f"best_solution_time={bst_str}")

        except Exception as e:
            result = {
                "instance": instance_name,
                "solver": solver_name,
                "n_jobs": None,
                "n_resources": None,
                "objective": None,
                "state": "Error",
                "duration": None,
                "build_time": None,
                "best_solution_time": None,
                "time_limit": time_limit,
                "workers": nb_workers,
                "error": str(e),
            }
            print(f"    ERROR: {e}", file=sys.stderr)

        all_results.append(result)

        # Save incrementally
        if out_file:
            with open(out_file, 'w') as f:
                json.dump(all_results, f, indent=2)

        sys.stdout.flush()

    return all_results


def print_summary(results, label):
    """Print summary stats for a set of results."""
    if not results:
        return
    total = len(results)
    solved = [r for r in results if r.get('objective') is not None and r.get('state') != 'Error']
    proven = [r for r in solved if r.get('state') == 'Optimal']
    errors = [r for r in results if r.get('state') == 'Error']

    print(f"  {label}: {len(solved)}/{total} solved "
          f"({len(proven)} optimal, {len(errors)} errors)")
    if solved:
        times = [r['duration'] for r in solved if r['duration'] is not None]
        if times:
            print(f"    Time: avg={sum(times)/len(times):.2f}s, "
                  f"max={max(times):.2f}s, total={sum(times):.1f}s")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Compare IBM CPO and OptalCP on RCPSPTT instances',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s --set j30 --max 5
  %(prog)s --set j30 j60 --solver optal --timeLimit 120
  %(prog)s --solver both --timeLimit 60
  %(prog)s --set j30 --dry-run
"""
    )

    # Filtering
    parser.add_argument('--set', nargs='+', choices=SETS, default=None,
                        metavar='SET', help='Instance sets (j30 j60 j90 j120)')
    parser.add_argument('--max', type=int, default=None,
                        help='Max instances to run')
    parser.add_argument('--start', type=int, default=0,
                        help='Start index (0-based, default: 0)')
    parser.add_argument('--end', type=int, default=None,
                        help='End index (exclusive)')

    # Solver options
    parser.add_argument('--solver', choices=['optal', 'cpo', 'both'], default='both',
                        help='Solver to use (default: both)')
    parser.add_argument('--timeLimit', type=int, default=60,
                        help='Time limit per instance in seconds (default: 60)')
    parser.add_argument('--workers', type=int, default=16,
                        help='Number of solver workers (default: 16)')
    parser.add_argument('--logLevel', type=int, default=0, choices=[0, 1, 2, 3],
                        help='Solver log verbosity (default: 0)')

    # Paths
    parser.add_argument('--data', type=str, default=None,
                        help=f'Data directory (default: {DEFAULT_DATA_DIR})')
    parser.add_argument('--output', type=str, default=None,
                        help='Output directory for results (default: results/rcpsptt/)')

    # Misc
    parser.add_argument('--dry-run', action='store_true',
                        help='Show instances that would be solved without running')

    args = parser.parse_args()

    # Determine solvers
    solvers = []
    if args.solver in ('optal', 'both'):
        solvers.append('optal')
    if args.solver in ('cpo', 'both'):
        solvers.append('cpo')

    # Collect instances
    data_dir = args.data or str(DEFAULT_DATA_DIR)
    instances = collect_instances(data_dir, args.set)
    instances = instances[args.start:args.end]

    if args.max:
        instances = instances[:args.max]

    if not instances:
        print(f"No instances found in {data_dir}")
        return 1

    # Setup output directory
    results_dir = Path(args.output) if args.output else SCRIPT_DIR / "results" / "rcpsptt"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Print config
    filter_desc = []
    if args.set:
        filter_desc.append(f"sets={','.join(args.set)}")
    if args.start or args.end:
        filter_desc.append(f"slice=[{args.start}:{args.end}]")

    print("=" * 70)
    print("RCPSPTT Benchmark Runner (Transfer Times)")
    print("=" * 70)
    print(f"  Data:       {data_dir}")
    print(f"  Instances:  {len(instances)}" + (f" (max {args.max})" if args.max else ""))
    print(f"  Filters:    {', '.join(filter_desc) if filter_desc else 'none'}")
    print(f"  Solvers:    {', '.join(solvers)}")
    print(f"  Time limit: {args.timeLimit}s per instance")
    print(f"  Workers:    {args.workers}")
    print(f"  Output:     {results_dir}")

    est_runs = len(instances) * len(solvers)
    est_time = est_runs * args.timeLimit / 60
    print(f"  Total runs: {est_runs} (est. ~{est_time:.0f} min worst case)")
    print("=" * 70)

    if args.dry_run:
        print(f"\nDry run - {len(instances)} instances would be solved:")
        for inst in instances[:20]:
            print(f"  {inst.name}")
        if len(instances) > 20:
            print(f"  ... and {len(instances) - 20} more")
        print(f"\nSolvers: {', '.join(solvers)}")
        return 0

    start_time = time.time()

    # Run each solver
    for solver_name in solvers:
        print(f"\n{'#' * 70}")
        print(f"# Solver: {solver_name.upper()}")
        print(f"{'#' * 70}")

        # Build output filename
        parts = [solver_name]
        if args.set and len(args.set) < len(SETS):
            parts.append('_'.join(args.set))
        out_file = results_dir / f"{'_'.join(parts)}.json"

        results = run_solver_batch(
            instances, solver_name,
            args.workers, args.timeLimit, args.logLevel,
            out_file=out_file
        )

        print(f"\n  Saved: {out_file}")
        print_summary(results, solver_name.upper())

    elapsed = time.time() - start_time
    print(f"\n{'=' * 70}")
    print(f"Done in {elapsed/60:.1f} min")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
