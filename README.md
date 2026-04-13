# RCPSPTT — Resource Constrained Project Scheduling with Transfer Times

Exact CP solvers (IBM CPO, OptalCP) applied to RCPSPTT using two formulations: standard **flow** and novel **setup-time** (no_overlap with transition matrices).

## Repository Structure

### Scripts

| File | Description |
|------|-------------|
| `solve_rcpsptt.py` | Main solver — builds and solves RCPSPTT models (flow + setup-time) for both IBM CPO and OptalCP. Reads PSPLIB `.sm` and Kraus JSON formats. CLI with `--solver`, `--timeLimit`, `--totalLimit`, `--format`, etc. |
| `run_rcpsptt.sh` | Batch runner — launches `solve_rcpsptt.py` across all instances. Modes: `all`, `psplib`, `kraus`, `kraus_setup`, `kraus_flow`. Configurable via env vars (`WORKERS`, `TIME_LIMIT`, `TOTAL_LIMIT`). |
| `verify_equivalence.py` | Verifies that setup-time and flow formulations are equivalent — solves with one, fixes start times in the other, checks feasibility. |

### Data

| Path | Description |
|------|-------------|
| `data/rcpsp_tt_instances/` | PSPLIB benchmark instances in `.sm` format (j30–j120, 32–122 jobs, 4 resources, ~200 instances). |
| `data/README.md` | Detailed statistics of instance sets (durations, transfer times, capacities, demands). |
| `kraus-diplomka/rcpsptt_docplex_solver-master/data/generated/` | Kraus's 100 JSON instances (100–7000 tasks, 5–100 resources, three distribution types: random, gauss, group). |
| `kraus-diplomka/kraus_instances/` | Subset of Kraus instances converted to `.sm` format (up to 500 tasks, 36 instances). |
| `kraus-diplomka/convert_kraus_to_sm.py` | Converter from Kraus JSON to PSPLIB `.sm` format. |

### Results

| Path | Description |
|------|-------------|
| `results/8.4.2026_flows/` | Flow formulation results on PSPLIB instances (OptalCP + CPO, j30–j120). |
| `results/9.4.2026_setuptimes/` | Setup-time formulation results on PSPLIB + converted Kraus instances. |
| `results/10.4.2026_kraus/` | Setup-time results on all 100 Kraus JSON instances (OptalCP + CPO, 180s limit). |

Each results folder contains per-solver JSON files and an `analysis.ipynb` notebook with comparisons.

### Other

| Path | Description |
|------|-------------|
| `rcpsptt.ipynb` | Jupyter notebook — problem definition, both formulations (math + code), solve examples. |
| `server/commads.md` | Server deployment commands (rsync, docker, tmux) for krocan cluster. |
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

A subset of the Kraus instances converted from JSON to PSPLIB `.sm` format using `convert_kraus_to_sm.py`. Only instances up to 500 tasks have been converted so far (36 out of 100).

| Tasks | Jobs (incl. src/sink) | Resources | Instances |
|------:|----------------------:|----------:|----------:|
|   100 |                   102 |      5-10 |        10 |
|   200 |                   202 |     10-20 |        10 |
|   300 |                   302 |     15-30 |        10 |
|   500 |                   502 |     25-50 |         6 |

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