---
title: PerfOpt v0 Development Log
date: 2026-01-30
---

# PerfOpt v0 开发日志（摘记）

原则：只记录“对后续工业机器人开发有复用价值”的结论与复现实验条件。

## 2026-02-02 一键启动/停止与端口治理

- 新增根目录脚本：`start_all.sh` / `stop_all.sh`
- `start_all.sh` 会优先清理 8080/3000 端口占用并后台启动前后端
- `stop_all.sh` 会强制结束前端与后端进程并释放端口
- 经验：若出现前端 `Failed to fetch`，先检查 8080 是否被占用且 `/health` 是否可达

## 2026-01-29~30 关键踩坑

### 1) MJCF 碰撞/接触：会把控制与优化全部带偏
- 现象：误差巨大、怎么调 PID 都不稳定；指标离谱；看起来像动力学/控制错了。
- 根因：自碰撞/相邻连接体碰撞导致接触约束“打架”，引入强非线性额外力。
- 结论：排查顺序里“接触/碰撞”优先级要高于 PID；先跑通无自碰最小环境，再逐步恢复真实接触。

### 2) Viewer 秒退/退出行为
- 曾出现：viewer 闪退、关闭窗口程序不退出。
- 修复策略：viewer 生命周期与主程序同步；窗口关闭后退出；避免变量名遮蔽导致 `sleep` 失效。

## 2026-01-30 轨迹设计：余弦位移是主线最稳选择

### 为什么不用正弦速度（sine_vel）
- 正弦速度积分会出现漂移/逼近限位；哪怕裁剪幅值，也容易引入非预期偏置。

### 为什么推荐余弦位移（cosine_pos）
- `t=0` 天然满足：`q_ref(0)=q0` 且 `qd_ref(0)=0`，不需要软启动。
- 对指标更稳定：配合 `sine_cycles`（整数周期）避免半周期导致 rmse/FFT 不稳。

## 2026-01-30 理想上限验证：数值精度决定误差地板

### 理想 computed-torque 上限（ff_mode=ideal）
- 控制律（离散采样保持）：
  - `qdd_cmd = qdd_ref + Kp*(q_ref-q_meas) + Kd*(qd_ref-qd_meas)`
  - `tau = ID(q_meas, qd_meas, qdd_cmd)`
- 目的：提供“理论上限参照”，用于判断误差是否主要由数值/离散决定。

### 经验：dt 越小，ideal 的误差越低
在相同轨迹/同一组 PD 下，减小 dt 会显著降低 `e_max`（离散与数值误差主导）。
在 `traj=cosine_pos` + `integrator=rk4` 下已观察到 `e_max` 可进入 <0.1mm 量级（需要更小 dt）。

## 2026-01-30 compare-ff：4 模式对比（no/ref/meas/ideal）

`--compare-ff` 固定“同一组 PD + 同一工况”对比 4 种模式：
- `no`：纯 PID
- `ref`：`ID(q_ref, qd_ref, qdd_ref) + PID`
- `meas`：`ID(q_meas, qd_meas, qdd_ref) + PID`
- `ideal`：理想上限 `ID(q_meas, qd_meas, qdd_cmd)`（禁用限幅）

输出：
- `artifacts/compare_ff_modes.png`：TCP 误差时序
- `artifacts/compare_ff_torque.png`：6 关节力矩时序（四模式叠加）
- `artifacts/compare_ff_modes.json`：指标 + `torque_stats`

### 关键结论：手调一组“能抗重力稳定跑”的 PD 极其重要
在 PD 未稳定前：
- `ref`/`meas` 可能出现“看似有隐藏疾病”的退化（甚至长时间后发散），本质是闭环没站稳或工况/结果不匹配。

在 PD 稳定后（示例结果，仅用于说明趋势）：
- 工况 A：`dt=0.001, f=0.25Hz, amp=0.5, rk4, cycles=2`
  - `no`   e_max≈0.108m（明显跟不上）
  - `ref`  e_max≈4e-5 m（几十微米）
  - `meas` e_max≈4e-5 m（几十微米）
  - `ideal` e_max≈9e-5 m（同量级，受数值影响）
- 工况 B：`dt=0.001, f=0.5Hz, amp=0.8, rk4, cycles=2`
  - `no`   e_max≈0.229m
  - `ref`  e_max≈7e-4 m
  - `meas` e_max≈7e-4 m
  - `ideal` e_max≈2e-3 m（dt 进一步变小后会下降）

解读：
- `no` 往往发散/大误差（尤其高频/大幅值）。
- `ref` 与 `meas` 在“PD 足够好 + 轨迹数值友好”时都能达到高精度；二者差异更多来自噪声/离散效应。
- `ideal` 是上限参照，但同样受 dt 与积分器影响（不代表永远最好）。

## 2026-01-30 复现性：load-result 的冲突提示是必须的

踩坑：
- 在新工况（dt/频率/幅值/轨迹类型）下加载旧 `opt_result.json`，会得到误导性的 compare-ff 结论。

修复方向（已实现）：
- `opt_result.json` 保存 `ff_mode/integrator/...` 等关键条件
- `--load-result` 时若与当前 CLI/config 不一致，打印 warning 提示“可能无法复现”
- 若未显式传 `--ff-mode`，会优先采用结果保存的 `ff_mode`

## 2026-01-30 并行优化：默认多进程（Optuna + sqlite）

- 默认 `--jobs-backend process`，使用 `sqlite:///artifacts/optuna.db` 共享 study
- 可用 `optuna-dashboard` 观察 trial 曲线与最优解演进
- 注意：并行会出现部分 trial 的 `nan/inf`（越界/不稳定），应在 objective 中统一标记为不可行并给出 reason
