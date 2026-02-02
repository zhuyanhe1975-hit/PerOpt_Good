# Tasks: PerfOpt 开发任务清单（最小可运行主线）

说明：本清单以“可复现实验 + 可解释对比”为优先级，严格最小化；不追求一口气做大系统。

## Phase 0: 工程卫生（DONE）
- [x] 单入口：`scripts/run_v0.py`（逻辑集中在 `perfopt/cli/run_v0_cli.py`）
- [x] 最小包结构：`perfopt/*`（backend/controller/trajectory/metrics/optimization/eval）

## Phase 1: 最小评估闭环（DONE）
- [x] MJCF 校验与可复现加载：`perfopt/mjcf/validator.py` + `scripts/validate_mjcf.py`
- [x] CPU rollout：`perfopt/backend/cpu_backend.py`
- [x] TCP 误差：`perfopt/kinematics/mujoco_fk.py` + `perfopt/metrics/error.py`
- [x] 轨迹：`traj=cosine_pos`（主线）+ 备选 `sine_pos/sine_vel/linear`
- [x] 控制器：6 关节独立 PID + `ff_mode={no,ref,meas,ideal}`
- [x] 指标：cycle/e_max/rmse/vib_energy/energy(proxy)/torque_stats
- [x] 统一 loss：权重 + baseline 归一化（`perfopt/optimization/loss.py`）

## Phase 2: 对比与可视化（DONE）
- [x] 预设权重：`perfopt/configs/scenarios.py`（Quick/True/Stable）
- [x] compare-ff：4 模式对比（TCP 误差 + 力矩曲线 + JSON）
- [x] viewer：仅“非优化/优化结束回放”打开，关闭窗口后退出

## Phase 3: 可信度提升（TODO，仍保持最小化）
- [ ] 能耗指标物理化：从 proxy 过渡到“机械功(有符号) + 热损耗(tau^2)”的可解释指标（并明确 dt/周期归一化）
- [ ] 工况版本化：`opt_result.json` 保存更完整的“工况签名”，并支持按工况命名输出（避免加载旧结果误导）
- [ ] 限幅与 NaN 收敛：当出现饱和/越界/NaN 时，统一给出可解释的 fail reason（便于优化器学习）

## Phase 4: 明确非 v0（以后再做）
- [ ] GPU 后端（mujoco_warp / MJX）进入主线
- [ ] 在线辨识（摩擦/刚度/载荷）与完整驱动模型
- [ ] 完整 jerk/time-scaling 轨迹规划器（对标 ABB QuickMove/TrueMove/StableMove）
