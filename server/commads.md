# Activate VENV
source /home/lukas/optacp/bin/activate

# Copy image to cluster (159MB)
rsync -avP -e 'ssh -p 2229' \
  ~/Desktop/CIIRC/CP_Cookbook/docker/optalcp-solver.tar.gz \
  radovluk@rtime.ciirc.cvut.cz:~/

# On the cluster, load the image
docker load < ~/optalcp-solver.tar.gz

# Log into the cluster
ssh -p 2228 radovluk@rtime.ciirc.cvut.cz krocan
ssh -p 2229 radovluk@rtime.ciirc.cvut.cz kruta

# Run the docker
docker run --rm -it -v ~/rcpspas:/workspace optalcp-solver:latest bash

# Run the solver
python solve_rcpspas.py -d ASLIB/ASLIB0/ -t 5 --start 0 --end 1000 --solver optalcp -f original -w 32 -q -o optalcp_original.csv

# Tmux
tmux new -s rcpspas

Detach from tmux: Ctrl+B, then D

Reconnect later:
tmux attach -t rcpspas

# Push python skript to Krocan
rsync -avP -e 'ssh -p 2228'   ~/Desktop/CIIRC/RCPSPAS/RCPSPAS/run_all.sh   radovluk@rtime.ciirc.cvut.cz:~/rcpspas/

# Retrieve results from krocan:
rsync -avP -e 'ssh -p 2228'   radovluk@rtime.ciirc.cvut.cz:~/rcpspas/results2/   /home/lukas/Desktop/CIIRC/RCPSPAS/RCPSPAS/results/server/23.02.2026/

# Push the scripts
rsync -avP -e 'ssh -p 2228' \
  /home/lukas/Desktop/CIIRC/RCPSPAS/RCPSPAS/run_all.sh \
  radovluk@rtime.ciirc.cvut.cz:~/rcpspas/

bash run_all.sh

# Count occurences:

grep -c "Optimal" optalcp_original_ASLIB0.csv


# Retrive the rcpsp-timeoffs

rsync -avP -e 'ssh -p 2228' radovluk@rtime.ciirc.cvut.cz:~/rcpsp-timeoffs/results/ "/home/lukas/Desktop/CIIRC/PSPLIB - Benchmarks - Timeoffs/results"

# Run the debug version of OptalCP:
cd debug_mode
OPTALCP_SOLVER="$(pwd)/optalcp_wrapper.sh" node propagate_test.mjs


# 1. Push the new rg300 data
rsync -avP -e 'ssh -p 2228' \
  "/home/lukas/Desktop/CIIRC/PSPLIB - Benchmarks - Timeoffs/data/psplib-timeoffs/rg300" \
  radovluk@rtime.ciirc.cvut.cz:~/rcpsp-timeoffs/data/psplib-timeoffs/

# 2. Push the updated scripts
rsync -avP -e 'ssh -p 2228' \
  "/home/lukas/Desktop/CIIRC/PSPLIB - Benchmarks - Timeoffs/solve_rcpsp_timeoffs.py" \
  "/home/lukas/Desktop/CIIRC/PSPLIB - Benchmarks - Timeoffs/run_t1_all.sh" \
  radovluk@rtime.ciirc.cvut.cz:~/rcpsp-timeoffs/

# 3. Push the rg300 benchmark generator (optional, for reference)
rsync -avP -e 'ssh -p 2228' \
  "/home/lukas/Desktop/CIIRC/PSPLIB - Benchmarks - Timeoffs/benchmarks/rcpsp-timeoffs/benchmark_generator/rg300_extend.py" \
  radovluk@rtime.ciirc.cvut.cz:~/rcpsp-timeoffs/benchmarks/rcpsp-timeoffs/benchmark_generator/

# Inside the Docker container:
PYTHON=$(which python3) bash run_t1_all.sh
