# RCPSPTT — Resource Constrained Project Scheduling with Transfer Times

Exact CP solvers (IBM CPO, OptalCP) applied to RCPSPTT using two formulations: standard **flow** and novel **setup-time** (no_overlap with transition matrices).

## Repository Structure

### Scripts

| File | Description |
|------|-------------|
| `solve_rcpsptt.py` | Main solver — builds and solves RCPSPTT models (flow + setup-time) for both IBM CPO and OptalCP. Reads PSPLIB `.sm` and Kraus JSON formats. CLI with `--solver`, `--timeLimit`, `--totalLimit`, `--format`, etc. |
| `run_rcpsptt.sh` | Batch runner — launches `solve_rcpsptt.py` across all instances. Modes: `all`, `psplib`, `kraus`, `kraus_setup`, `kraus_flow`. Configurable via env vars (`WORKERS`, `TIME_LIMIT`, `TOTAL_LIMIT`). |
| `verify_equivalence.py` | Verifies that setup-time and flow formulations are equivalent — solves with one, fixes start times in the other, checks feasibility. |
| `server/run_rcpsptt.sh` | Server deployment commands (rsync, docker, tmux) for krocan cluster. |

### Data

| Path | Description |
|------|-------------|
| `data/rcpsp_tt_instances/` | PSPLIB benchmark instances in `.sm` format (j30–j120, 32–122 jobs, 4 resources, ~408 instances). |
| `data/README.md` | Detailed statistics of instance sets (durations, transfer times, capacities, demands). |
| `kraus-diplomka/rcpsptt_docplex_solver-master/data/generated/` | Kraus's 100 JSON instances (100–7000 tasks, 5–100 resources, three distribution types: random, gauss, group). |
| `kraus-diplomka/kraus_instances/` | Subset of Kraus instances converted to `.sm` format (up to 500 tasks, 60 instances). |
| `kraus-diplomka/convert_kraus_to_sm.py` | Converter from Kraus JSON to PSPLIB `.sm` format. |

### Results

| Path | Description |
|------|-------------|
| `results/8.4.2026_flows/` | Flow formulation results on PSPLIB instances (OptalCP + CPO, j30–j120, 120s limit). |
| `results/9.4.2026_setuptimes/` | Setup-time formulation results on PSPLIB + converted Kraus instances (120s limit). |
| `results/10.4.2026_kraus/` | Setup-time results on all 100 Kraus JSON instances (OptalCP + CPO, 180s limit). |

Each results folder contains per-solver JSON files and an `analysis.ipynb` notebook with comparisons.

### Other

| Path | Description |
|------|-------------|
| `rcpsptt.ipynb` | Jupyter notebook — problem definition, both formulations (math + code), solve examples. |
| `model.txt` | CP model pseudocode / formulation reference. |
| `kraus-diplomka/F3-DP-2025-Kraus-Tomas.pdf` | Kraus's thesis on RCPSPTT instance generation and CP solving. |
| `RCPSPTT__definition_.pdf` | Formal problem definition. |

## Formulations

**Flow formulation**: Standard approach with optional transfer intervals `z_{i,j,r}` and integer flow variables `f_{i,j,r}`. O(n^2 x R) variables.

**Setup-time formulation**: Decomposes each resource into individual machines. Each task gets `C[r]` optional copies, synchronized with `start_at_start`. Machines use `no_overlap` with transition distance matrices. O(n x sum(C_r)) variables, stronger propagation.

## Instance Sets

### PSPLIB Instances (`data/rcpsp_tt_instances/`)

Standard PSPLIB benchmark instances extended with transfer time matrices (Poppenborg & Knust, 2016). Each instance has two variants (`_a`, `_b`) with different resource capacities and demands on the same precedence graph.

| Set  | Jobs (incl. src/sink) | Resources | Instances (_a + _b) |
|------|----------------------:|----------:|--------------------:|
| j30  |                    32 |         4 |          48 + 48    |
| j60  |                    62 |         4 |          48 + 48    |
| j90  |                    92 |         4 |          48 + 48    |
| j120 |                   122 |         4 |          60 + 60    |

#### Instance characteristics

**Durations and transfer times:**
- Durations: 1–10 (uniformly distributed, avg 5.5)
- Transfer times: 1–5 (uniformly distributed, avg 3.1, per resource pair)
- Duration-to-transfer-time ratio: ~1.8:1

**Resource capacities:**

| Set  | Capacity range | Avg  | Median |
|------|---------------:|-----:|-------:|
| j30  |          7–57  | 20.9 |     18 |
| j60  |         10–84  | 29.3 |     26 |
| j90  |        10–122  | 37.2 |     31 |
| j120 |         11–79  | 27.6 |     24 |

**Task resource usage — multi-resource tasks are common:**
Tasks use 1–4 resources. The distribution is consistent across all sets:

| # Resources used | Share  |
|-----------------:|-------:|
| 1                | ~33%   |
| 2                | ~16%   |
| 3                | ~17%   |
| 4                | ~33%   |

About 2/3 of tasks use 2+ resources (multi-resource), and 1/3 use all 4 resources.

**Demand values:**
- Range: 1–10 (uniformly distributed, avg 5.5)
- Demand == Capacity: <0.2% of assignments (almost never)
- Avg demand/capacity ratio: 17–28% depending on set (tasks use a small fraction of resource capacity)

#### Impact on formulations

The **setup-time formulation** creates `C[r]` optional interval copies per task per resource. With capacities of 7–122 and demands of 1–10, each task requires `Q[j][r]` copies to be present (selected) out of `C[r]` available machines.

| Set  | Avg setup intervals | Approx flow variables |
|------|--------------------:|----------------------:|
| j30  |              1,932  |                 4,096 |
| j60  |              5,652  |                15,376 |
| j90  |             10,715  |                33,856 |
| j120 |              8,964  |                59,536 |

Setup-time formulation creates fewer variables than flow, but the `no_overlap` with transition matrices produces stronger propagation per machine.

### Kraus Instances — Original JSON (`kraus-diplomka/rcpsptt_docplex_solver-master/data/generated/`)

Full benchmark set from Kraus's thesis (F3-DP-2025-Kraus-Tomas) in the original JSON format. Instances are generated with three position distribution types: `random`, `gauss` (Gaussian), and `group` (clustered). Each task is assigned to a 3D element position; transfer times are computed as Euclidean distances between elements.

| Tasks | Jobs (incl. src/sink) | Resources | Instances |
|------:|----------------------:|----------:|----------:|
|   100 |                   102 |      5-10 |        10 |
|   200 |                   202 |     10-20 |        10 |
|   300 |                   302 |     15-30 |        10 |
|   500 |                   502 |     25-50 |        10 |
|   800 |                   802 |     40-80 |        10 |
|  1000 |                  1002 |    50-100 |        10 |
|  2000 |                  2002 |    50-100 |        10 |
|  3000 |                  3002 |    50-100 |        10 |
|  5000 |                  5002 |    50-100 |        10 |
|  7000 |                  7002 |    50-100 |        10 |
| **Total** | | | **100** |

### Kraus Instances — Converted to .sm (`kraus-diplomka/kraus_instances/`)

A subset of the Kraus instances converted from JSON to PSPLIB `.sm` format using `convert_kraus_to_sm.py`. Only instances up to 500 tasks have been converted (60 out of 100).

| Tasks | Jobs (incl. src/sink) | Resources | Instances |
|------:|----------------------:|----------:|----------:|
|   100 |                   102 |      5-10 |        10 |
|   200 |                   202 |     10-20 |        10 |
|   300 |                   302 |     15-30 |        10 |
|   500 |                   502 |     25-50 |        30 |

### Scale Comparison

The two instance sets differ significantly in scale:

| Property           | PSPLIB               | Kraus                  |
|--------------------|----------------------|------------------------|
| Durations          | 1–10 (uniform, avg 5.5) | 500–10000 (avg ~5100) |
| Transfer times     | 1–5 (uniform, avg 3.1)  | 200–13000 (avg ~4000) |
| Resources          | 4                    | 5–100                  |
| Resource capacities| 7–122 (avg ~29)      | up to 1000             |
| Tasks multi-res?   | Yes (67% use 2+ res) | Yes                    |
| Demands            | 1–10 (uniform)       | varies                 |
| Scale factor       | ~1x                  | ~1000x                 |

## Results

Results are stored in `results/` with one subfolder per experiment. Each folder contains JSON files (one per solver×set combination) and an `analysis.ipynb` notebook.

### Result JSON format

Each entry in a result JSON represents one solver run on one instance:

```json
{
  "instance": "j301_a",
  "solver": "optal_setup",
  "tuned": false,
  "n_jobs": 32,
  "n_resources": 4,
  "objective": 57,
  "state": "Optimal",
  "duration": 0.161,
  "build_time": 0.08,
  "best_solution_time": 0.138,
  "time_limit": 120,
  "workers": 8
}
```

| Field | Meaning |
|-------|---------|
| `state` | `Optimal` — proven best; `Feasible` — a solution found but not proven optimal (hit time limit); `NoSolution` — no solution found within the time limit |
| `objective` | Makespan (project completion time, minimize). `null` if no solution found. |
| `duration` | Total wall-clock time of the solve call (seconds). |
| `build_time` | Time to construct the CP model (seconds). |
| `best_solution_time` | Time until the best found solution was discovered (seconds). |
| `tuned` | Whether OptalCP tuned search parameters were used. |

### Experiment 1 — Flow formulation on PSPLIB (`8.4.2026_flows/`)

120s time limit, 8 workers. Both solvers use the standard flow formulation.

| Set  | Total | CPO solved | CPO optimal | OptalCP solved | OptalCP optimal |
|------|------:|-----------:|------------:|---------------:|----------------:|
| j30  |    48 |     45     |          16 |             20 |              19 |
| j60  |    48 |     42     |          12 |             10 |              10 |
| j90  |    48 |     44     |           6 |              3 |               3 |
| j120 |    60 |     40     |           0 |              0 |               0 |

**Takeaway:** CPO finds solutions reliably (it uses an LNS-based strategy that finds feasible solutions fast). OptalCP finds far fewer solutions with the flow formulation — it times out on most j90+ instances before finding any solution. When OptalCP does find a solution, it is often optimal, suggesting strong propagation once it gets started. Neither solver proves optimality on j120 within 120s.

### Experiment 2 — Setup-time formulation on PSPLIB + Kraus .sm (`9.4.2026_setuptimes/`)

120s time limit, 8 workers. Both solvers use the setup-time (no_overlap + transitions) formulation.

**PSPLIB:**

| Set  | Total | CPO solved | CPO optimal | OptalCP solved | OptalCP optimal |
|------|------:|-----------:|------------:|---------------:|----------------:|
| j30  |    48 |     48     |           8 |             48 |              10 |
| j60  |    48 |     48     |           9 |             48 |               9 |
| j90  |    48 |     48     |          10 |             48 |              12 |
| j120 |    60 |     60     |           0 |             54 |               0 |

**Converted Kraus .sm (100–300 tasks, 36 instances used):**

| Solver | Total | Solved | Optimal | Avg best_solution_time |
|--------|------:|-------:|--------:|-----------------------:|
| CPO    |    36 |     36 |      36 |                  0.03s |
| OptalCP|    36 |     35 |      35 |                  6.94s |

**Takeaway:** The setup-time formulation is dramatically better than flow for both solvers. OptalCP goes from solving 0 j120 instances with flow to solving 54/60 with setup-time. CPO solves all PSPLIB instances and all Kraus .sm instances to optimality. Both formulations produce equivalent optimal values (verified by `verify_equivalence.py`). CPO finds its best solution extremely quickly (avg < 0.1s), while OptalCP takes longer but still within limits.

### Experiment 3 — Setup-time formulation on Kraus JSON (`10.4.2026_kraus/`)

180s time limit, 16 workers. Setup-time formulation on all 100 Kraus JSON instances (100–7000 tasks).

| Solver  | Total | Solved (Feasible) | No solution | Timeout | Avg best_solution_time |
|---------|------:|------------------:|------------:|--------:|-----------------------:|
| CPO     |   100 |                60 |           0 |      40 |                  0.06s |
| OptalCP |   100 |                42 |          18 |      40 |                126.42s |

**Takeaway:** On large-scale Kraus instances, CPO is significantly more reliable — it never fails to find any solution (0 `NoSolution`), while OptalCP finds nothing for 18 instances. CPO's first feasible solution is found almost instantly (0.06s average), whereas OptalCP's average of 126s means it is still searching near the end of the time limit. The 40 `Timeout` entries for each solver indicate that for larger instances (800+ tasks) both solvers run out of time before proving optimality.

### Summary

| Formulation | Solver | PSPLIB coverage | Large-instance reliability |
|-------------|--------|-----------------|---------------------------|
| Flow        | CPO    | Good (≈90%)     | Moderate                  |
| Flow        | OptalCP| Poor (≈25%)     | Poor                      |
| Setup-time  | CPO    | **100%**        | **High** (fastest solution) |
| Setup-time  | OptalCP| **≈97%**        | Moderate                  |

The setup-time formulation is the recommended formulation. CPO is the better choice for large instances where finding any feasible solution matters; OptalCP may find marginally better solutions on small-to-medium instances if given enough time.

## Usage

```bash
# Solve PSPLIB j30 with both solvers (flow formulation)
python3 solve_rcpsptt.py --set j30 --solver both --timeLimit 60

# Solve Kraus JSON instances with setup-time formulation
python3 solve_rcpsptt.py --data kraus-diplomka/rcpsptt_docplex_solver-master/data/generated \
    --format kraus --solver optal_setup --timeLimit 180 --totalLimit 270

# Batch run
TIME_LIMIT=180 bash run_rcpsptt.sh kraus

# Verify formulation equivalence
python3 verify_equivalence.py --set j30 --max 10 --timeLimit 60
```
