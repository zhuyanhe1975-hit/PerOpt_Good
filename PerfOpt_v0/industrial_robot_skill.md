---
name: industrial-robot-perfopt-playbook
description: PerfOpt 工业机器人(ER15-1400)仿真与参数优化的关键经验总结：MJCF建模踩坑、轨迹设计、computed-torque前馈、数值精度与调试方法。
---

# 工业机器人开发经验沉淀（PerfOpt v0）

目标：把“能跑起来”推进到“可解释、可复现实验”，避免在 MuJoCo + 逆动力学 + 优化里反复走弯路。

## 1. 初期大坑：MJCF 碰撞/接触导致的“假问题”

### 现象
- 关节跟踪明显跟不上、误差很大、能量/振动指标异常。
- 加大力矩上限/调大 Kp 也不收敛，甚至越调越糟。
- 看起来像控制/动力学模型错了，实际是接触在“打架”。

### 根因
- MJCF 中链节之间（尤其是关节两侧相邻实体）存在碰撞对，或自碰撞未被正确过滤。
- 接触约束会在求解器里产生很强的非线性“额外力”，把闭环与前馈都扰乱。

### 经验做法
- 对控制/优化主线，优先保证“无接触/无自碰撞”的最小闭环可控环境：
  - 禁用相邻关节连接两侧的碰撞（collision filter / contype/conaffinity / exclude）。
  - 先跑通 tracking，再逐步打开必要的碰撞（例如工件/环境）。
- 任何“跟踪跟不上”的排查顺序里，**接触/碰撞优先级要高于 PID**。

## 2. TCP 误差的正确性：先确认“末端位置真的在更新”

### 常见误判
- 误差巨大（>1m）时，第一反应是控制器太差，但更常见是：
  - TCP 取错对象（body vs site），或者 body_name 不存在导致 TCP 恒为 [0,0,0]。
  - kinematics 没有在正确的 state 上 `mj_forward`，导致位置不刷新。

### 经验做法
- 明确 TCP 的定义：建议用 `site`（工具坐标）而不是 `body` 原点。
- 每次改模型/改名字后，先做“零动作测试”：
  - 固定 qpos，不同步进下 tcp 应保持不变；
  - 轻微改变 qpos，tcp 应相应变化（单调/连续）。

## 3. 工程可行的力矩施加：`ctrl` vs `qfrc_applied`

### 关键区别
- `data.ctrl[:]`：驱动 actuator（可能有 gear/gain/dynamics/limit），**不等价于关节力矩**。
- `data.qfrc_applied[:]`：直接施加广义力矩（ideal actuator），更接近控制理论里的 “tau”。

### 经验做法
- 做“理想 computed-torque 上限测试”时：
  - 强制使用 `qfrc_applied`，并清零 `ctrl`，避免 actuator 映射带来的非理想。
- 做“工程现实模式”时：
  - 可以用 `ctrl`，但必须明确 actuator 的含义与单位映射，否则调参会变成盲人摸象。

## 4. 统一架构下的 computed-torque（严格形式）与前馈策略

### 严格 computed-torque（推荐的“理想上限”）
- 采样保持（工程时序）：
  - 在第 k 个控制周期，用 `mj_step` 后得到的实测 `q_meas, qd_meas` 作为当前状态；
  - 构造命令加速度：
    - `qdd_cmd = qdd_ref + Kp*(q_ref - q_meas) + Kd*(qd_ref - qd_meas)`
  - 再做逆动力学：
    - `tau = ID(q_meas, qd_meas, qdd_cmd)`

### 非理想模式的前馈（更工程）
- 前馈用实测状态（而不是参考状态）更稳：
  - `tau_ff = ID(q_meas, qd_meas, qdd_ref)`
  - `tau = tau_ff + tau_fb`
- 如果前馈改用 `(q_ref, qd_ref, qdd_ref)`，在误差存在时更容易出现“前馈打偏”。

## 5. 参考轨迹设计：一切“高精度”先从轨迹开始

### 正弦位置的两个坑
- 仅靠相位让 `t=0` 速度为 0（例如 `phi=-pi/2`）会导致：
  - `q_ref(0) = q0 - B`，这是**位置阶跃**，误差会瞬间爆炸（甚至出现 ~2π 的角度跳变）。
- 软启动（envelope）能避免速度阶跃，但可能引入过渡段峰值。

### 实用解：余弦形式位移（强烈推荐）
用余弦位移参考避免 t=0 位置/速度阶跃：
- `q_ref(t) = q0 + sgn * B * (1 - cos(wt + phi))/2`
- 天然满足：
  - `q_ref(0)=q0`
  - `qd_ref(0)=0`
  - 适合关闭软启动

### “整数周期”原则（指标稳定性）
- 对周期轨迹，尽量模拟整数个周期（`cycles`），避免只跑半周期导致：
  - rmse/e_max/振动频域统计不稳定；
  - 优化器在噪声上做无意义搜索。

### 幅值裁剪原则（防止假优化）
幅值不只要受关节限位，还要受速度上限约束：
- 正弦位置：`qd_peak ~ B*w`（再叠加软启动项）
- 余弦位移：`qd_peak ~ 0.5*B*w`

否则会出现“参考根本达不到限位附近”的现象（被 `vel_limits` 裁剪住）。

## 6. 数值精度就是“控制能力”的上限（理想模式下尤甚）

### 关键结论（来自实验）
- 在理想 computed-torque + ideal actuator 下，残余 TCP 误差主要由：
  - 离散时间采样保持（dt）
  - 数值积分器（Euler vs RK4）
  - 求解器数值误差
 共同决定。

### 可复现实验规律
- 减小 dt 会显著降低 e_max（常呈近似比例下降）。
- 切换到 RK4 在相同 dt 下通常更准。
- 在“更激励”的工况（更高频率/更大幅值）下，需要更小 dt 才能达到亚毫米。

## 7. 调试方法论：先证明“动力学一致”，再谈“控制好不好”

### 必备诊断（computed-torque 场景）
在同一时刻状态对齐（避免一步错位）：
- 写入力矩后先 `mj_forward` 得到当前 `qacc`
- 用 `mj_inverse(q,qd,qacc)` 得到 `qfrc_inverse(state)`
- 对比：
  - `||tau_applied - qfrc_inverse(state)||`

如果这个不是 0（或极小），优先排查：
- 力矩施加通道（ctrl vs qfrc_applied）
- 诊断是否对齐同一时刻
- actuator 映射

### 误差定位（时序 + 分布）
不要只看 e_max：
- 输出 TCP error 的 mean/max，并画 `time -> error` 曲线。
- 输出每关节 `|q_err|` 的 mean/max，定位“哪个关节、哪段时间”贡献最大。

## 8. 工程组织与可复现性

### 配置管理
- 所有输入条件（dt、integrator、traj、freq、limits、cycles、优化器参数）集中到 JSON。
- 额外解释写到同名 `.md`，JSON 保持纯数据（可 diff、可版本化）。

### 单入口原则
- 保持一个可运行入口脚本（例如 `scripts/run_v0.py`），支持：
  - 直接跑、优化、加载上次结果回放、viewer、debug 输出。

### viewer 原则
- 优化过程不实时开 viewer（会拖慢、干扰并行）。
- 只在非优化或优化结束后回放 best；回放支持循环播放。

## 9. 一句话原则（用于日常自检）

- 误差大：先排碰撞/接触，再看 TCP 是否正确更新，再看 actuator 映射，再谈 PID。
- 追极限：先把参考轨迹做“数值友好”（余弦位移、整数周期），再切 RK4、减 dt。
- 做对比：必须保证“同一时刻对齐”的诊断，否则会被离散错位误导。

