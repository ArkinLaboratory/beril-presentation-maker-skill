# worker_pool.sh — bounded-concurrency batch runner for the orchestrator.
#
# v0.4 M3 (M3_PUNCH_LIST.md Tier B; V0_4_ARCHITECTURE.md §7.3 / §20.3).
# Sourced by presentation_maker.sh for parallel per-substory slide
# composition, and unit-tested in isolation by tests/unit/test_worker_pool.py.
#
# This file defines functions only — it sets no shell options and runs
# no top-level code, so sourcing it is side-effect free.
#
#   wp_run_pool MAX LOGDIR LABEL RUNNER  ID...
#
#     MAX     max workers run concurrently (integer >= 1). IDs are
#             processed in batches of MAX: a batch is launched, drained,
#             then the next batch starts. (Batched, not a rolling pool —
#             `wait -n` is bash 4.3+, and macOS ships bash 3.2.)
#     LOGDIR  directory for per-job logs (created if absent).
#     LABEL   filename stem for per-job logs: "$LOGDIR/$LABEL-$ID.log".
#     RUNNER  name of a shell function. For each ID, `RUNNER <ID>` runs
#             in a backgrounded subshell; the subshell inherits the
#             caller's variables and functions, so RUNNER may read
#             orchestrator globals. RUNNER's return code is the job's
#             outcome — make it the last command, or `return` explicitly.
#     ID...   one whitespace-free token per job.
#
#   Each job's stdout+stderr is captured to its log. A job that returns 0
#   has its log removed; a job that fails has its log preserved AND
#   echoed (indented) to stderr. wp_run_pool returns 0 iff every job
#   returned 0, 1 if any job failed, 2 on a usage error.
#
# bash 3.2-compatible: indexed arrays + `+=` + `${!arr[@]}` only; no
# associative arrays, no `wait -n`.

wp_run_pool() {
  if [[ $# -lt 4 ]]; then
    echo "wp_run_pool: usage: wp_run_pool MAX LOGDIR LABEL RUNNER ID..." >&2
    return 2
  fi
  local max="$1" logdir="$2" label="$3" runner="$4"
  shift 4

  case "$max" in
    ''|*[!0-9]*)
      echo "wp_run_pool: MAX must be a positive integer (got '$max')" >&2
      return 2 ;;
  esac
  if [[ "$max" -lt 1 ]]; then
    echo "wp_run_pool: MAX must be >= 1 (got '$max')" >&2
    return 2
  fi
  if ! declare -F "$runner" >/dev/null 2>&1; then
    echo "wp_run_pool: runner function '$runner' is not defined" >&2
    return 2
  fi

  local -a ids=("$@")
  local total=${#ids[@]}
  [[ $total -eq 0 ]] && return 0
  mkdir -p "$logdir"

  local overall_fail=0 start=0
  while [[ $start -lt $total ]]; do
    # --- launch one batch of up to $max jobs -----------------------
    local -a b_ids=() b_pids=() b_logs=()
    local n=0
    while [[ $n -lt $max && $((start + n)) -lt $total ]]; do
      local id="${ids[$((start + n))]}"
      local log="$logdir/${label}-${id}.log"
      : > "$log"
      # `trap - EXIT` clears any inherited EXIT trap so a worker
      # subshell cannot re-fire the orchestrator's finalize hook.
      ( trap - EXIT; "$runner" "$id" ) > "$log" 2>&1 &
      b_ids+=("$id"); b_pids+=("$!"); b_logs+=("$log")
      n=$((n + 1))
    done
    # --- drain the batch, collecting each job's exit code ----------
    local i
    for i in "${!b_ids[@]}"; do
      if wait "${b_pids[$i]}"; then
        rm -f "${b_logs[$i]}"
        echo "  [worker-pool] ${b_ids[$i]}: ok" >&2
      else
        local rc=$?
        overall_fail=1
        echo "  [worker-pool] ${b_ids[$i]}: FAILED (exit $rc) — log follows:" >&2
        sed 's/^/      /' "${b_logs[$i]}" >&2 || true
        echo "  [worker-pool] ${b_ids[$i]}: log preserved at ${b_logs[$i]}" >&2
      fi
    done
    start=$((start + n))
  done

  return $overall_fail
}
