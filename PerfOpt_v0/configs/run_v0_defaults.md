# run_v0_defaults.json (简要说明)

- 默认行为：`scripts/run_v0.py` 不传 `--config` 时，会自动加载 `configs/run_v0_defaults.json`（若文件存在）。

- `dt/steps`：仿真步长/步数（单次评估固定跑完这一段轨迹）
- `integrator`：MuJoCo 数值积分器（`euler`/`rk4`）；RK4 更准但更慢
- `ff_mode`：控制/前馈模式
  - `no`：纯 PID（禁用逆动力学前馈）
  - `ref`：`tau = ID(q_ref, qd_ref, qdd_ref) + PID`
  - `meas`：`tau = ID(q_meas, qd_meas, qdd_ref) + PID`
  - `ideal`：理想 computed-torque 上限（禁用限幅）：`tau = ID(q_meas, qd_meas, qdd_cmd)`
- `traj=sine_pos`：正弦“位置”参考（默认带可选软启动）
- `traj=cosine_pos`：余弦形式位移参考（t=0 位置连续且速度为 0，可关闭软启动）
  - `sine_freq`：频率(Hz)
  - `sine_phase`：相位(rad)。注意：非零相位会改变初始位置；主线建议用 `0`（避免 t=0 位置阶跃/偏置）
  - `sine_ramp_time`：软启动时长(s)。设为 0 表示关闭软启动
  - `sine_amp_scale`：幅值比例(0~1)，用于缩放“可行的最大位移幅值”
  - `sine_cycles`：仿真整数周期数（sine_* 专用），避免只跑半个周期导致指标不稳定
- 位移幅值裁剪（防逼近限位）：根据 MJCF 的 joint range 计算每个关节可用摆幅（留 margin），并裁剪正弦位置幅值 `B`
- 速度约束：`vel_limits` 是每关节速度上限(rad/s)，同时用于统计 `qd_u=max(|qd|)/vel_limits`；正弦位置幅值 `B` 也会被裁剪以满足峰值速度不超过 `vel_limits`
- 力矩约束：`torque_limit` 为每关节力矩限幅(Nm)
- `freq_band`：振动能量(vib_energy)的频域统计带宽（FFT band）
- `preset/weights/use_baseline`：模式权重 + 指标基线归一化（用于让不同量纲的项更可比）
- `engine/jobs/max_trials/target_e_max`：优化器类型/并行 trial 数/最大试验数/停止阈值（可行解满足 `e_max <= target_e_max`）
- `viewer`：可选 MuJoCo 可视化（仅在“非优化运行”或“优化结束后回放 best”时打开；开启后会一直显示直到你关闭窗口）
- `load_result`：可选加载历史优化结果（如 `artifacts/opt_result.json`）并用其中的 `kp/ki/kd` 来回放；如果 `--viewer` 且未显式给 kp/kd/ki，会自动尝试加载 `artifacts/opt_result.json`
- `kp/kd/ki`：每关节 PID 初始值；当你不在命令行显式传入 `--kp/--kd/--ki` 时，会使用这里的值（便于你先手动找一组“能抗重力稳定跑”的参数）

当前仓库默认配置倾向于“更激励”的对比（`traj=cosine_pos` + `integrator=rk4` + 整数周期），便于快速暴露控制/数值问题。
