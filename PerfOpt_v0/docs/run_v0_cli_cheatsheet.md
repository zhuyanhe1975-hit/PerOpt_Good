---
title: PerfOpt v0 CLI Cheatsheet
date: 2026-01-30
---

# PerfOpt v0 CLI Cheatsheet（scripts/run_v0.py）

目标：把常用命令/配置记下来，避免每次都翻代码或 `--help`。

默认行为：
- 不传 `--config` 时，会自动加载 `configs/run_v0_defaults.json`（若文件存在）
- 主要输出写到 `artifacts/`

运行前（推荐）
```bash
source $(conda info --base)/etc/profile.d/conda.sh
conda activate mjwarp_env
```

## 1) 最常用：直接跑一遍

```bash
python scripts/run_v0.py
```

显式指定 config（可选）：
```bash
python scripts/run_v0.py --config configs/run_v0_defaults.json
```

## 2) 优化（Optuna）

并行优化（CPU 多核）：
```bash
python scripts/run_v0.py --optimize --engine optuna --jobs 8 --print-interval 1
```

更干净的输出：
```bash
python scripts/run_v0.py --optimize --engine optuna --jobs 8 --quiet
```

达到阈值提前停止（例如 `e_max < 0.1m`）：
```bash
python scripts/run_v0.py --optimize --engine optuna --jobs 8 --target-e-max 0.1
```

并行后端（默认多进程）：
- `--jobs-backend process`（默认）：需要 Optuna sqlite storage（默认 `sqlite:///artifacts/optuna.db`）
- `--jobs-backend thread`：多线程；在 trial 很短时可能加速不明显

## 3) 前馈/控制模式（ff_mode）

统一用 `--ff-mode {no,ref,meas,ideal}`：
- `no`：纯 PID（无逆动力学前馈）
- `ref`：`tau = ID(q_ref,qd_ref,qdd_ref) + PID`
- `meas`：`tau = ID(q_meas,qd_meas,qdd_ref) + PID`
- `ideal`：理想 computed-torque 上限（禁用限幅）：`tau = ID(q_meas,qd_meas,qdd_cmd)`

示例：
```bash
python scripts/run_v0.py --ff-mode no
python scripts/run_v0.py --ff-mode meas
```

## 4) compare-ff（4 模式对比）

同一组 PD / 同一工况下，对比 4 种模式：
```bash
python scripts/run_v0.py --compare-ff --quiet
```

输出：
- `artifacts/compare_ff_modes.json`
- `artifacts/compare_ff_modes.png`（TCP 误差时序）
- `artifacts/compare_ff_torque.png`（6 关节力矩时序）

## 5) 画力矩曲线（单次运行）

```bash
python scripts/run_v0.py --ff-mode no --plot-torque artifacts/torque_no_ff.png --quiet
```

## 6) Viewer（只回放，不在 trial 中打开）

不优化，直接回放（若未显式指定 gains，会尝试加载 `artifacts/opt_result.json`）：
```bash
python scripts/run_v0.py --viewer
```

优化结束后自动回放 best：
```bash
python scripts/run_v0.py --optimize --engine optuna --jobs 8 --viewer
```

若出现 OpenGL/NV-GLX 提示，可尝试：
```bash
export MUJOCO_GL=egl
```

## 7) 结果保存/复现：opt_result.json

优化默认写入：
- `artifacts/opt_result.json`

加载结果回放：
```bash
python scripts/run_v0.py --load-result artifacts/opt_result.json
```

说明：
- 若未显式传 `--ff-mode`，会优先采用 `opt_result.json` 保存的 `ff_mode`
- 若 dt/轨迹/限幅等与保存时不一致，会打印 warning（提示可能无法复现）

## 8) Optuna Dashboard

默认 sqlite：
- `sqlite:///artifacts/optuna.db`

启动 dashboard：
```bash
optuna-dashboard sqlite:///artifacts/optuna.db --host 127.0.0.1 --port 8080
```

## 9) 配置文件说明

配置项解释见：
- `configs/run_v0_defaults.md`

## 10) TAB 补全（仅为 scripts/run_v0.py 注册）

先安装（在 `mjwarp_env` 中）：
```bash
python -m pip install argcomplete
```

仅对当前 shell 会话启用（只影响 `scripts/run_v0.py`）：
```bash
eval "$(register-python-argcomplete scripts/run_v0.py)"
```

之后可用：
- `python scripts/run_v0.py --<TAB>` 自动提示参数

想“一直有效”（不做全局补全），推荐把仓库脚本挂到 bash 启动：
```bash
source /home/yhzhu/LoongEnv/PerfOpt_v0/scripts/enable_run_v0_completion.sh
```

它会在你 `conda activate mjwarp_env` 后自动启用补全（无需重开终端）。
