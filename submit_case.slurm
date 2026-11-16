#!/bin/bash
#SBATCH --job-name=chem201305
#SBATCH --partition=bigmem
#SBATCH --nodes=1
#SBATCH --ntasks=24
#SBATCH --ntasks-per-node=24
#SBATCH --output=job-%j.out
#SBATCH --error=job-%j.err

# Submit in a prepared runtime directory: sbatch /absolute/path/submit_case.slurm real
# or: sbatch /absolute/path/submit_case.slurm wrf
# Adapt partition/tasks to your cluster. This script intentionally has no MOZBC stage.
set -eo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit this file using sbatch from the runtime directory}"
stage="${1:-}"
case "$stage" in
    real|wrf) ;;
    *) printf 'Usage: sbatch submit_case.slurm real|wrf\n' >&2; exit 2 ;;
esac
env_script="${WRF_ENV:-/data1/share/elzd_2023_00080/xiaji/WRF_INTEL/wrf-chem_icc.sh}"
[[ -r "$env_script" ]] || { printf 'Missing environment script: %s\n' "$env_script" >&2; exit 1; }
source "$env_script"
set -eo pipefail
export OMP_NUM_THREADS=1
ulimit -s unlimited
[[ -x "./${stage}.exe" && -s namelist.input ]] || { printf 'Missing executable/namelist\n' >&2; exit 1; }
if [[ "$stage" == wrf ]]; then
    for name in wrfinput_d01 wrfinput_d02 wrfbdy_d01 wrflowinp_d01 wrflowinp_d02 wrfbiochemi_d01 wrfbiochemi_d02; do
        [[ -s "$name" ]] || { printf 'Missing input: %s\n' "$name" >&2; exit 1; }
    done
    shopt -s nullglob
    for domain in 01 02; do
        emission_files=(wrfchemi_d"$domain"_*)
        [[ ${#emission_files[@]} -eq 49 ]] || { printf 'Expected 49 emission files for d%s\n' "$domain" >&2; exit 1; }
    done
fi
log_dir="$PWD/logs/${stage}-${SLURM_JOB_ID:?}"
mkdir -p "$log_dir/previous-rsl"
shopt -s nullglob
previous=(rsl.error.* rsl.out.*)
if (( ${#previous[@]} )); then mv -- "${previous[@]}" "$log_dir/previous-rsl/"; fi
printf 'Stage: %s\nDirectory: %s\nMPI tasks: %s\n' "$stage" "$PWD" "${SLURM_NTASKS:?}"
mpirun -np "$SLURM_NTASKS" "./${stage}.exe" 2>&1 | tee "$log_dir/stdout.log"
if [[ "$stage" == real ]]; then marker='SUCCESS COMPLETE REAL_EM INIT'; else marker='SUCCESS COMPLETE WRF'; fi
grep -Fq "$marker" rsl.error.0000 || { printf 'Success marker missing. Inspect %s/rsl.error.*\n' "$PWD" >&2; exit 1; }
cp -p -- rsl.error.* rsl.out.* "$log_dir/"
printf 'SUCCESS: %s; saved logs: %s\n' "$stage" "$log_dir"
