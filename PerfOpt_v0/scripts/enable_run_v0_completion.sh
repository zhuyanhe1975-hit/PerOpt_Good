#!/usr/bin/env bash
# Enable argcomplete for PerfOpt's scripts/run_v0.py in a persistent, non-global way.
#
# Usage:
#   source /home/yhzhu/LoongEnv/PerfOpt_v0/scripts/enable_run_v0_completion.sh
#
# Recommended (persistent):
#   echo 'source /home/yhzhu/LoongEnv/PerfOpt_v0/scripts/enable_run_v0_completion.sh' >> ~/.bashrc
#
# This script is safe to source multiple times.

_perfopt_run_v0_try_enable_completion() {
  # Already enabled in this shell.
  if [[ -n "${__PERFOPT_RUN_V0_COMPLETION_ENABLED:-}" ]]; then
    return 0
  fi

  # Only supports bash; quietly no-op for other shells.
  if [[ -z "${BASH_VERSION:-}" ]]; then
    return 0
  fi

  # argcomplete is installed into the active python environment; after conda activate
  # the command should exist. We re-try on each prompt until it becomes available.
  if ! command -v register-python-argcomplete >/dev/null 2>&1; then
    return 0
  fi

  local script_path="/home/yhzhu/LoongEnv/PerfOpt_v0/scripts/run_v0.py"
  if [[ ! -f "$script_path" ]]; then
    return 0
  fi

  # Enable completion only for this script.
  eval "$(register-python-argcomplete "$script_path")"
  __PERFOPT_RUN_V0_COMPLETION_ENABLED=1

  # Remove ourselves from PROMPT_COMMAND to avoid repeated work.
  if [[ -n "${PROMPT_COMMAND:-}" ]]; then
    PROMPT_COMMAND="${PROMPT_COMMAND//_perfopt_run_v0_try_enable_completion; /}"
    PROMPT_COMMAND="${PROMPT_COMMAND//; _perfopt_run_v0_try_enable_completion/}"
    PROMPT_COMMAND="${PROMPT_COMMAND//_perfopt_run_v0_try_enable_completion/}"
    PROMPT_COMMAND="${PROMPT_COMMAND#; }"
    PROMPT_COMMAND="${PROMPT_COMMAND%; }"
  fi
}

# Try immediately (covers shells where argcomplete is already available).
_perfopt_run_v0_try_enable_completion

# Also hook into PROMPT_COMMAND so it turns on automatically after `conda activate mjwarp_env`.
if [[ -z "${__PERFOPT_RUN_V0_PROMPT_HOOKED:-}" ]]; then
  if [[ -z "${PROMPT_COMMAND:-}" ]]; then
    PROMPT_COMMAND="_perfopt_run_v0_try_enable_completion"
  else
    case ";$PROMPT_COMMAND;" in
      *";_perfopt_run_v0_try_enable_completion;"*) : ;;
      *) PROMPT_COMMAND="_perfopt_run_v0_try_enable_completion; $PROMPT_COMMAND" ;;
    esac
  fi
  __PERFOPT_RUN_V0_PROMPT_HOOKED=1
fi

