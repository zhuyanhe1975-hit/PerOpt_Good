# Design: PerfOpt（v0 最小可运行实现）

## 1. 单入口与模块边界

- 单入口脚本：`scripts/run_v0.py`（实际逻辑在 `perfopt/cli/run_v0_cli.py`）
- MuJoCo CPU 后端：`perfopt/backend/cpu_backend.py`
- 轨迹：`perfopt/trajectory/*`
  - `cosine_position.py`：余弦位移（默认，t=0 速度为 0，支持整数周期）
  - `sine_position.py` / `sine_velocity.py`：用于对比与踩坑复现
  - `limited_linear.py`：限速线段往返（备用）
- FK / TCP：`perfopt/kinematics/mujoco_fk.py`（基于 MuJoCo state 取 TCP site）
- 控制器：`perfopt/controller/*`
  - PID：每关节独立 `kp/ki/kd`
  - 逆动力学：`perfopt/controller/mujoco_ff.py`（`mj_inverse`）
  - `ff_mode` 四档：`no/ref/meas/ideal`
- 指标：`perfopt/metrics/*`（time/error/vibration/energy/torque）
- 评估流水线：`perfopt/eval/*`（single-run 与 batch-run 统一）
- 优化：`perfopt/optimization/optuna_runner.py`

## 2. v0 控制闭环（同一套框架下切换 ff_mode）

单步循环（每个仿真 tick）：
1) 轨迹产生参考：`q_ref, qd_ref, qdd_ref`
2) 读取当前 state：`q_meas, qd_meas`（来自上一轮 `mj_step` 的状态）
3) 计算力矩（按 `ff_mode`）：
   - `no`：`tau = PID(q_ref-q_meas, qd_ref-qd_meas)`
   - `ref`：`tau = ID(q_ref, qd_ref, qdd_ref) + PID(...)`
   - `meas`：`tau = ID(q_meas, qd_meas, qdd_ref) + PID(...)`
   - `ideal`：理想 computed-torque 上限：`tau = ID(q_meas, qd_meas, qdd_cmd)`，其中
     `qdd_cmd = qdd_ref + Kp*(q_ref-q_meas) + Kd*(qd_ref-qd_meas)`
4) 工程模式下施加约束：关节限位 / 速度上限 / 力矩限幅（ideal 模式可禁用限幅用于上限对照）
5) `mj_step` 推进；记录 `tcp`, `tau`, `qd` 等序列；评估结束后汇总指标与 loss

## 3. 统一 loss（快/准/稳/能耗的可解释合成）

v0 采用“可解释子项 + 加权合成”：
- `L_quick`：节拍（cycle_time）
- `L_true`：跟踪（e_max / rmse）
- `L_stable`：振动能量（vib_energy，频带能量 proxy）
- `L_energy`：能耗 proxy（当前 dt 敏感，只用于同 dt 相对比较）

支持 `use_baseline`：将指标按 baseline 归一化，避免量纲差异导致某些项被“淹没”。

## 4. 并行优化（Optuna + 多进程默认）

- `--jobs` 控制并行 trial 数
- 默认 `--jobs-backend process`：使用 sqlite storage（默认 `sqlite:///artifacts/optuna.db`）实现多进程并行
- 可切换 `--jobs-backend thread`：在 trial 很短时可能加速不明显

## 5. 可复现性（load-result 的一致性检查）

优化结果 `artifacts/opt_result.json` 会保存关键条件（如 `ff_mode/integrator/dt/traj` 等）。
当 `--load-result` 时：
- 若未显式传入 `--ff-mode`，会优先采用结果里保存的 `ff_mode`
- 若当前运行关键配置与保存时不一致，会打印 warning（提示可能无法复现）

## 6. MJCF 接触策略（高风险源）

接触/自碰会显著放大误差并误导优化。
v0 默认优先保证“无自碰可控环境”跑通主线（见 `models/er15-1400.mjcf.xml` 的碰撞过滤策略）。
后续回归真实工况时，应逐步恢复必要接触，并保持可切换与可复现（不要靠临时脚本改模型）。
