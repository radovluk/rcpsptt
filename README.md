# RCPSPTT — Exact Solvers with Setup-Time Reformulation

Comparing IBM CP Optimizer and OptalCP on the Resource Constrained Project Scheduling Problem with Transfer Times (RCPSPTT), using both the standard formulation and a novel setup-time reformulation.

## Problem

RCPSPTT extends the classical RCPSP by adding **transfer times** between tasks: when a resource unit finishes task *i* and moves to task *j*, there is a delay `Delta[i][j][r]` before it can begin working on *j*. The objective is to minimize the makespan (Cmax).

## Two Formulations

### 1. Standard Formulation (`optal` / `cpo`)

The direct CP model from the literature (Kraus 2025). For each pair of tasks `(i, j)` and resource `r`:

- **Optional interval variable** `z_{i,j,r}` representing the physical transfer (duration = `Delta[i][j][r]`)
- **Integer flow variable** `f_{i,j,r}` representing how many units of resource `r` move from `i` to `j`
- **Cumulative constraints** to enforce resource capacity

This produces `O(n^2 * R)` variables for `n` tasks and `R` resources. For 100 tasks and 5 resources, that is ~17,000 variables and ~26,000 constraints.

### 2. Setup-Time Formulation (`optal_setup` / `cpo_setup`)

A reformulation that decomposes each resource into **individual machine units** and models transfer times as **sequence-dependent setup times** using `no_overlap` with transition matrices.

For each resource `r` with capacity `a_r`:

```
Resource r (capacity a_r = 3)  →  Machine r_0, Machine r_1, Machine r_2

Task A (needs 2 units of r):
  A_m0 (optional), A_m1 (optional), A_m2 (optional)
  Constraint: exactly 2 of 3 copies must be present
  Constraint: present copies synchronized with main interval A

Task B (needs 1 unit of r):
  B_m0 (optional), B_m1 (optional), B_m2 (optional)
  Constraint: exactly 1 of 3 copies must be present

Per machine: no_overlap([A_mk, B_mk, ...], transition_matrix)
```

The `no_overlap` constraint with a transition matrix enforces that if task `i` is followed by task `j` on the same machine, there must be a gap of at least `Delta[i][j][r]` between the end of `i` and the start of `j`. This is enforced between **all pairs** of tasks on the machine, not just direct neighbors.

**Advantages:**
- Fewer variables: `O(n * sum(a_r))` instead of `O(n^2 * R)`
- Stronger propagation: `no_overlap` with transitions is one of the most optimized constraints in CP solvers
- No explicit flow variables — resource routing is handled implicitly by the sequence

**For 100 tasks, 5 resources (avg capacity 5):**

| | Standard | Setup-Time |
|---|---|---|
| Interval variables | ~8,500 | ~2,600 |
| Integer variables | ~8,500 | 0 |
| Constraints | ~26,000 | ~670 |
| Key constraint type | cumulative + if-then | no_overlap (dedicated algo) |

## Worked Example

Consider a small RCPSPTT instance with **3 real tasks** (plus supersource `S` and supersink `T`), **1 resource** with capacity **2**:

```
Tasks:  S (p=0, Q=2),  A (p=5, Q=1),  B (p=3, Q=2),  C (p=4, Q=1),  T (p=0, Q=2)
Precedence: A → C
Positions: A at (0,0),  B at (10,0),  C at (5,0)

Transfer times (Euclidean distance):
       S    A    B    C    T
  S [  0    0    0    0    0 ]
  A [  0    0   10    5    0 ]
  B [  0   10    0    5    0 ]
  C [  0    5    5    0    0 ]
  T [  0    0    0    0    0 ]

Resource demands: S needs 2 (=capacity), T needs 2, A needs 1, B needs 2, C needs 1
```

**Key observation:** Task B needs 2 units and task A needs 1 unit — together 3 > capacity 2. Therefore **A and B cannot run simultaneously**. This constraint, combined with the transfer times, drives the optimal makespan.

---

### Standard (Flow) Formulation — constraint by constraint

The flow formulation models resource movement as a **network flow**: for every pair of tasks `(i,j)`, we decide how many resource units travel from `i` to `j` and when the transfer happens.

#### Variable definitions

**(9a) Main interval variables** — one mandatory interval per task with fixed duration:

```
a_S: mandatory, length=0    (supersource — instantaneous)
a_A: mandatory, length=5
a_B: mandatory, length=3
a_C: mandatory, length=4
a_T: mandatory, length=0    (supersink — instantaneous)
```

Each task **must** be executed (mandatory). The solver decides when (start time).

**(9c) Transfer interval variables** — one optional interval per feasible transfer `(i,j,r)`:

```
z_{S,A}: optional, length=0       z_{S,B}: optional, length=0       z_{S,C}: optional, length=0
z_{A,B}: optional, length=10      z_{A,C}: optional, length=5       z_{A,T}: optional, length=0
z_{B,A}: optional, length=10      z_{B,C}: optional, length=5       z_{B,T}: optional, length=0
z_{C,B}: optional, length=5       z_{C,T}: optional, length=0
```

Each transfer interval represents the **physical movement** of resource units from task `i` to task `j`. The duration equals the transfer time `Delta[i][j]`. The interval is *optional* — it exists only if the transfer actually happens.

**(9b) Flow variables** (OptalCP version) — one optional integer per feasible transfer:

```
f_{S,A}: optional integer ∈ [1,1]     f_{S,B}: optional integer ∈ [1,2]     f_{S,C}: optional integer ∈ [1,1]
f_{A,B}: optional integer ∈ [1,1]     f_{A,C}: optional integer ∈ [1,1]     f_{A,T}: optional integer ∈ [1,1]
f_{B,A}: optional integer ∈ [1,1]     f_{B,C}: optional integer ∈ [1,1]     f_{B,T}: optional integer ∈ [1,2]
f_{C,B}: optional integer ∈ [1,1]     f_{C,T}: optional integer ∈ [1,1]
```

Each flow variable says **how many units** travel along a transfer edge. The upper bound `U_{i,j} = min(Q_i, Q_j)` — you cannot transfer more units than either task uses. The variable is *optional* with domain `[1, U]`: if present, the flow is at least 1.

**Total: 5 main intervals + 11 transfer intervals + 11 flow integers = 27 variables.**

#### Constraints

**(1) Objective — minimize makespan:**

```
minimize end(a_T)
```

We want the project to finish as early as possible. The sink `T` is the last task — its end time is the makespan.

**(2) Precedence:**

```
endBeforeStart(a_A, a_C)       // end(A) ≤ start(C)
```

For each edge in the precedence graph: the predecessor must finish before the successor can start. In our example, only one: A → C.

**(3) Source flow initialization — all units leave from source:**

```
f_{S,A} + f_{S,B} + f_{S,C} = 2     (= C₀, the resource capacity)
```

All resource units start at the supersource S. Exactly `C₀ = 2` units must depart from S to other tasks. This "pumps" the entire flow network.

**(4) Presence synchronization (OptalCP version):**

```
presence(f_{S,A}) = presence(z_{S,A})
presence(f_{S,B}) = presence(z_{S,B})
presence(f_{S,C}) = presence(z_{S,C})
presence(f_{A,B}) = presence(z_{A,B})
presence(f_{A,C}) = presence(z_{A,C})
presence(f_{A,T}) = presence(z_{A,T})
presence(f_{B,A}) = presence(z_{B,A})
presence(f_{B,C}) = presence(z_{B,C})
presence(f_{B,T}) = presence(z_{B,T})
presence(f_{C,B}) = presence(z_{C,B})
presence(f_{C,T}) = presence(z_{C,T})
```

The flow variable and transfer interval go hand in hand: either both exist (the transfer happens) or both are absent (it does not). Since `f ∈ [1,U]`, being present automatically means flow ≥ 1.

**(5) Flow conservation — inflow into each task:**

```
f_{S,A} + f_{B,A} = 1                     // A needs Q_{A} = 1 unit
f_{S,B} + f_{A,B} + f_{C,B} = 2           // B needs Q_{B} = 2 units
f_{S,C} + f_{A,C} + f_{B,C} = 1           // C needs Q_{C} = 1 unit
f_{A,T} + f_{B,T} + f_{C,T} = 2           // T needs Q_{T} = 2 units
```

Like Kirchhoff's law: whatever a task needs, it must receive from predecessors. The total inflow must equal the demand.

**(6) Flow conservation — outflow from each task:**

```
f_{A,B} + f_{A,C} + f_{A,T} = 1           // A releases Q_{A} = 1 unit
f_{B,A} + f_{B,C} + f_{B,T} = 2           // B releases Q_{B} = 2 units
f_{C,B} + f_{C,T} = 1                      // C releases Q_{C} = 1 unit
(S is handled by constraint (3), T is the sink — no outflow)
```

Whatever a task consumed, it must send on. Nothing is created or destroyed — flow conservation.

**(7) Temporal linking — THIS IS THE KEY CONSTRAINT:**

For each transfer `(i,j)`:

```
endBeforeStart(a_S, z_{S,A})  ∧  endBeforeStart(z_{S,A}, a_A)
endBeforeStart(a_S, z_{S,B})  ∧  endBeforeStart(z_{S,B}, a_B)
endBeforeStart(a_S, z_{S,C})  ∧  endBeforeStart(z_{S,C}, a_C)
endBeforeStart(a_A, z_{A,B})  ∧  endBeforeStart(z_{A,B}, a_B)
endBeforeStart(a_A, z_{A,C})  ∧  endBeforeStart(z_{A,C}, a_C)
endBeforeStart(a_A, z_{A,T})  ∧  endBeforeStart(z_{A,T}, a_T)
endBeforeStart(a_B, z_{B,A})  ∧  endBeforeStart(z_{B,A}, a_A)
endBeforeStart(a_B, z_{B,C})  ∧  endBeforeStart(z_{B,C}, a_C)
endBeforeStart(a_B, z_{B,T})  ∧  endBeforeStart(z_{B,T}, a_T)
endBeforeStart(a_C, z_{C,B})  ∧  endBeforeStart(z_{C,B}, a_B)
endBeforeStart(a_C, z_{C,T})  ∧  endBeforeStart(z_{C,T}, a_T)
```

The transfer interval `z_{i,j}` must lie **between** the end of task `i` and the start of task `j`. This is how transfer times are enforced: since `z_{A,C}` has fixed length 5, we get `end(A) + 5 ≤ start(C)`.

Example: if the transfer A→B is active (`z_{A,B}` present, length=10), then:
```
end(a_A) ≤ start(z_{A,B})  and  end(z_{A,B}) ≤ start(a_B)
  ⟹  end(A) + 10 ≤ start(B)
```

**(8) Cumulative capacity:**

```
pulse(a_A, 1) + pulse(a_B, 2) + pulse(a_C, 1)
  + pulse(z_{A,B}, f_{A,B})         // Delta=10 > 0, transfer occupies capacity
  + pulse(z_{A,C}, f_{A,C})         // Delta=5 > 0
  + pulse(z_{B,A}, f_{B,A})         // Delta=10 > 0
  + pulse(z_{B,C}, f_{B,C})         // Delta=5 > 0
  + pulse(z_{C,B}, f_{C,B})         // Delta=5 > 0
  ≤ 2   (= C₀)     ...at every point in time
```

(S and T have p=0, so their pulse is zero. Transfers with Delta=0 are excluded — they have no duration.)

At every moment, the total number of active resource units must not exceed the capacity. This counts **both** running tasks (`pulse(a_i, Q_i)` = rectangle of height `Q_i` during task execution) **and** transfers in progress (`pulse(z_{i,j}, f_{i,j})` = rectangle of height = number of units in transit). A unit "on the road" is unavailable for anything else.

---

### Setup-Time Formulation — constraint by constraint

The setup-time formulation takes a different approach: instead of modeling resource flow, it **decomposes each resource into individual machine units** and models transfers as gaps between tasks on the same machine.

#### Variable definitions

**(S6a) Main interval variables** — identical to flow formulation:

```
a_S: mandatory, length=0
a_A: mandatory, length=5
a_B: mandatory, length=3
a_C: mandatory, length=4
a_T: mandatory, length=0
```

**(S6b) Task copies on machines** — one optional interval per (task, machine) pair:

```
c_{S,m0}: optional, length=0      c_{S,m1}: optional, length=0
c_{A,m0}: optional, length=5      c_{A,m1}: optional, length=5
c_{B,m0}: optional, length=3      c_{B,m1}: optional, length=3
c_{C,m0}: optional, length=4      c_{C,m1}: optional, length=4
c_{T,m0}: optional, length=0      c_{T,m1}: optional, length=0
```

Each task has an **optional copy on every machine**. A copy has the same duration as the main interval. The solver decides which copies are present — this implicitly assigns tasks to machines.

**(S6c) Sequence variables:**

```
sigma_{m0} = sequenceVar({c_{S,m0}, c_{A,m0}, c_{B,m0}, c_{C,m0}, c_{T,m0}})
sigma_{m1} = sequenceVar({c_{S,m1}, c_{A,m1}, c_{B,m1}, c_{C,m1}, c_{T,m1}})
```

Each machine has a sequence variable that groups all copies on that machine. It determines the ordering in which tasks execute on each machine.

**Total: 5 main intervals + 10 optional copies = 15 variables (no flow integers).**

#### Constraints

**(S1) Objective — same as flow:**

```
minimize end(a_T)
```

**(S2) Precedence — same as flow:**

```
endBeforeStart(a_A, a_C)       // end(A) ≤ start(C)
```

**(S3) Demand — how many copies must be present:**

```
presence(c_{S,m0}) + presence(c_{S,m1}) = 2       // S uses all machines (Q_S = capacity = 2)
presence(c_{A,m0}) + presence(c_{A,m1}) = 1       // A needs 1 machine
presence(c_{B,m0}) + presence(c_{B,m1}) = 2       // B needs both machines!
presence(c_{C,m0}) + presence(c_{C,m1}) = 1       // C needs 1 machine
presence(c_{T,m0}) + presence(c_{T,m1}) = 2       // T uses all machines
```

Instead of flow conservation, we directly state: "a task needing `Q` units must run on exactly `Q` machines." Task B needs 2 units = it must run on both machines. Task A needs 1 = it runs on exactly one (the solver picks which).

**(S4) Synchronization — copies aligned with main interval:**

```
startAtStart(a_S, c_{S,m0})      startAtStart(a_S, c_{S,m1})
startAtStart(a_A, c_{A,m0})      startAtStart(a_A, c_{A,m1})
startAtStart(a_B, c_{B,m0})      startAtStart(a_B, c_{B,m1})
startAtStart(a_C, c_{C,m0})      startAtStart(a_C, c_{C,m1})
startAtStart(a_T, c_{T,m0})      startAtStart(a_T, c_{T,m1})
```

If a copy is present, it must start at the same time as the main interval. This ensures that copies on different machines are synchronized (B_m0 and B_m1 start and end at the same time). If a copy is absent, the constraint is automatically satisfied (a property of `startAtStart`).

**(S5) No-overlap with transition matrix — THIS IS THE KEY CONSTRAINT:**

```
noOverlap(sigma_{m0}, D)      // on Machine 0
noOverlap(sigma_{m1}, D)      // on Machine 1

where D (transition matrix, indices S=0, A=1, B=2, C=3, T=4):
         S   A   B   C   T
    S [  0   0   0   0   0 ]
    A [  0   0  10   5   0 ]
    B [  0  10   0   5   0 ]
    C [  0   5   5   0   0 ]
    T [  0   0   0   0   0 ]
```

On each machine: **no two present tasks may overlap in time**, and between the end of task `i` and the start of task `j` there must be a gap of at least `D[i][j]` (= the transfer time). This is enforced between **all pairs** of tasks on the machine, not just direct neighbors in the sequence.

This implicitly enforces transfer times: if task A is followed by task C on Machine 0, then `end(A) + D[A][C] = end(A) + 5 ≤ start(C)`. No explicit transfer intervals or flow variables are needed — **the routing is implicit** in which tasks share a machine.

---

### Optimal Solution (Cmax = 18)

Task B needs 2 units and task A needs 1 unit — together 3 > capacity 2. **A and B cannot run simultaneously.** The optimal solution schedules S first, then A and C (with transfer time), while B must wait for both units to become available.

#### Setup-Time Solution

```
Machine 0: S[0,0] → C[5,9]  → B[15,18] → T[18,18]
Machine 1: S[0,0] → A[0,5]  → B[15,18] → T[18,18]

Timeline:
  S: [0,0]   A: [0,5]   C: [5,9]   B: [15,18]   T: [18,18]
  Cmax = 18
```

**Verification — every constraint checked:**

**(S3) Demand:**
```
S: m0=present + m1=present = 2 ✓
A: m0=absent  + m1=present = 1 ✓    (A is on Machine 1 only)
B: m0=present + m1=present = 2 ✓    (B is on both machines)
C: m0=present + m1=absent  = 1 ✓    (C is on Machine 0 only)
T: m0=present + m1=present = 2 ✓
```

**(S4) Synchronization:**
```
start(a_A)=0 = start(c_{A,m1})=0 ✓     (c_{A,m0} absent → auto-satisfied)
start(a_B)=15 = start(c_{B,m0})=15 = start(c_{B,m1})=15 ✓
start(a_C)=5 = start(c_{C,m0})=5 ✓     (c_{C,m1} absent → auto-satisfied)
```

**(S2) Precedence:**
```
end(a_A) = 5 ≤ start(a_C) = 5 ✓
```

**(S5) No-overlap on Machine 0** (present: S, C, B, T):
```
S → C: end(S)=0  + D[S,C]=0 = 0  ≤ 5=start(C)  ✓
C → B: end(C)=9  + D[C,B]=5 = 14 ≤ 15=start(B) ✓     ← transfer time enforced!
B → T: end(B)=18 + D[B,T]=0 = 18 ≤ 18=start(T) ✓
```

**(S5) No-overlap on Machine 1** (present: S, A, B, T):
```
S → A: end(S)=0  + D[S,A]=0 = 0  ≤ 0=start(A)  ✓
A → B: end(A)=5  + D[A,B]=10 = 15 ≤ 15=start(B) ✓    ← transfer time enforced! (bottleneck)
B → T: end(B)=18 + D[B,T]=0 = 18 ≤ 18=start(T) ✓
```

The bottleneck is on Machine 1: the transfer A→B takes 10 time units, so B cannot start before time 15.

#### Equivalent Flow Solution

The same schedule expressed as a network flow:

```
Flow:
  f_{S,A}=1   f_{S,C}=1             (3): 1+1 = 2 ✓
  f_{A,B}=1                          (6): outflow A = 1 ✓
  f_{C,B}=1                          (6): outflow C = 1 ✓
  f_{B,T}=2                          (6): outflow B = 2 ✓
                                      (5): inflow A: f_{S,A} = 1 ✓
                                      (5): inflow B: f_{A,B}+f_{C,B} = 1+1 = 2 ✓
                                      (5): inflow C: f_{S,C} = 1 ✓
                                      (5): inflow T: f_{B,T} = 2 ✓

Timeline:
  a_S:[0,0]  a_A:[0,5]  a_C:[5,9]  a_B:[15,18]  a_T:[18,18]

Transfer intervals (only those with Delta > 0):
  z_{A,B}: length=10, [5,15]      // end(A)=5 ≤ 5=start(z) ✓, end(z)=15 ≤ 15=start(B) ✓
  z_{C,B}: length=5,  [9,14]      // end(C)=9 ≤ 9=start(z) ✓, end(z)=14 ≤ 15=start(B) ✓

Capacity check (8) at every time point:
  t=0..5:  pulse(A,1) = 1                                    ≤ 2 ✓
  t=5..9:  pulse(C,1) + pulse(z_{A,B},1) = 1+1 = 2          ≤ 2 ✓
  t=9..14: pulse(z_{A,B},1) = 1                              ≤ 2 ✓
  t=14..15: pulse(z_{A,B},1) = 1                             ≤ 2 ✓
  t=15..18: pulse(B,2) = 2                                   ≤ 2 ✓
```

Both units of resource are accounted for at all times. Between t=5 and t=9, one unit runs task C while the other is in transit from A to B.

#### Correspondence between the two solutions

The two solutions are **the same schedule** expressed differently:

| Setup-time view | Flow view |
|---|---|
| Machine 0: S → C → B → T | f_{S,C}=1, f_{C,B}=1, f_{B,T} (1 of 2) |
| Machine 1: S → A → B → T | f_{S,A}=1, f_{A,B}=1, f_{B,T} (1 of 2) |
| Gap on M0 between C and B = 6 ≥ D[C,B]=5 | z_{C,B}: length=5, occupies capacity |
| Gap on M1 between A and B = 10 = D[A,B]=10 | z_{A,B}: length=10, occupies capacity |

---

### Formulation Comparison

| | Flow | Setup-Time |
|---|---|---|
| **How routing is modeled** | Explicitly: f_{i,j} = how many units flow | Implicitly: task sequences on machines |
| **How transfer times are enforced** | Transfer interval z_{i,j} with fixed duration | Gap in no_overlap (transition matrix) |
| **How capacity is enforced** | Cumulative constraint (pulse) | No-overlap on each machine |
| **Variables (this example)** | 5 main + 11 z + 11 f = **27** | 5 main + 10 copies = **15** |
| **Equivalence** | Same optimum (Cmax=18), mutually convertible solutions |

**Converting between formulations:**
- **Flow → Setup-time:** A flow `f_{i,j}=k` means `k` units travel from `i` to `j`. Assign those `k` machines so that both `i` and `j` run on them — this creates the machine sequences.
- **Setup-time → Flow:** If tasks `i` and `j` are consecutive on machine `m`, set `f_{i,j} += 1` — the number of shared machines between consecutive tasks gives the flow.

**Why lower bounds differ:** The flow formulation has explicit flow conservation constraints (5,6) that tighten the relaxation. The setup-time formulation lacks these — the solver only knows that tasks on each machine do not overlap. This is why the setup-time formulation typically finds optimal solutions quickly but has **weaker lower bounds** (harder to prove optimality).

## Usage

```bash
# Solve with a specific solver variant:
python solve_rcpsptt.py --solver optal_setup --set j30 --timeLimit 120

# Available solvers:
#   optal        — OptalCP, standard formulation
#   optal_setup  — OptalCP, setup-time formulation
#   cpo          — IBM CPO, standard formulation
#   cpo_setup    — IBM CPO, setup-time formulation
#   both         — optal + cpo (standard)
#   both_setup   — optal_setup + cpo_setup

# Run full benchmark:
bash run_rcpsptt.sh            # All instances
bash run_rcpsptt.sh psplib     # Only PSPLIB
bash run_rcpsptt.sh kraus      # Only Kraus instances

# Environment variables for run_rcpsptt.sh:
WORKERS=32 TIME_LIMIT=120 bash run_rcpsptt.sh
```

## Data

See [data/README.md](data/README.md) for instance descriptions.

- `data/rcpsp_tt_instances/` — PSPLIB instances (j30–j120, 32–122 jobs, 4 resources)
- `kraus-diplomka/kraus_instances/` — Kraus instances converted to .sm format (102–502 jobs, 5–50 resources)

## Server Deployment (Krocan)

```bash
# 1. Push code and data to server
rsync -avP -e 'ssh -p 2228' \
  ~/Desktop/CIIRC/RCPSPTT/solve_rcpsptt.py \
  ~/Desktop/CIIRC/RCPSPTT/run_rcpsptt.sh \
  radovluk@rtime.ciirc.cvut.cz:~/rcpsptt/

rsync -avP -e 'ssh -p 2228' \
  ~/Desktop/CIIRC/RCPSPTT/data/rcpsp_tt_instances/ \
  radovluk@rtime.ciirc.cvut.cz:~/rcpsptt/data/rcpsp_tt_instances/

rsync -avP -e 'ssh -p 2228' \
  ~/Desktop/CIIRC/RCPSPTT/kraus-diplomka/kraus_instances/ \
  radovluk@rtime.ciirc.cvut.cz:~/rcpsptt/kraus-diplomka/kraus_instances/

# 2. SSH into the server
ssh -p 2228 radovluk@rtime.ciirc.cvut.cz

# 3. Run inside Docker
docker run --rm -it -v ~/rcpsptt:/workspace optalcp-solver:latest bash

# 4. Inside Docker — run benchmarks in tmux
tmux new -s rcpsptt
cd /workspace
PYTHON=$(which python3) WORKERS=32 TIME_LIMIT=120 bash run_rcpsptt.sh

# Detach: Ctrl+B, then D
# Reattach: tmux attach -t rcpsptt

# 5. Retrieve results
rsync -avP -e 'ssh -p 2228' \
  radovluk@rtime.ciirc.cvut.cz:~/rcpsptt/results/ \
  ~/Desktop/CIIRC/RCPSPTT/results/server/
```

## Early Results (j301, 32 jobs, 4 resources)

| Solver | Cmax | Time to solution | Status | Variables |
|---|---|---|---|---|
| optal (standard) | 57 | 0.17s | Optimal | 268 intervals |
| optal_setup | 57 | 0.03s | Feasible (LB=51) | 417 intervals |
| cpo (standard) | 57 | 0.45s | Optimal | 504 vars |
| cpo_setup | 57 | 0.09s | Feasible (LB=41) | 458 vars |

Both setup formulations find the correct solution quickly but have weaker lower bounds (harder to prove optimality) due to the relaxation of explicit flow conservation constraints.
