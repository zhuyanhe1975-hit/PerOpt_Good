# PerfOpt v0（最小可运行 Demo）

PerfOpt 面向 ER15-1400 工业机器人：在 MuJoCo 中跑一条固定参考轨迹，通过优化 6 关节独立 PID 参数，实现“快/准/稳/能耗”的可复现对比。

本仓库坚持最小化：只保留一条主线入口 `scripts/run_v0.py`，其余均为支撑模块。

## 1.  hookup（运行前）

推荐在 `mjwarp_env`（你本地已安装 MuJoCo / CUDA / PyTorch / mujoco_warp）：

```bash
source $(conda info --base)/etc/profile.d/conda.sh
conda activate mjwarp_env
```

若 viewer 出现 OpenGL 相关警告，可尝试：

```bash
export MUJOCO_GL=egl
```

## 1.1 一键启动（前后端联动）

在仓库根目录执行：

```bash
/home/yhzhu/LoongEnv/PerOpt/start_all.sh
```

一键启动会：
- 清理占用端口（8080/3000）
- 后台启动后端（HTTP API）
- 后台启动前端并打开浏览器

停止服务：

```bash
/home/yhzhu/LoongEnv/PerOpt/stop_all.sh
```

## 2. 单入口：scripts/run_v0.py

默认行为：不传 `--config` 时自动加载 `configs/run_v0_defaults.json`（如果该文件存在）。

### 2.1 直接跑一遍（不优化）

```bash
python scripts/run_v0.py
```

### 2.2 启动优化（Optuna）

```bash
python scripts/run_v0.py --optimize --engine optuna --jobs 8 --print-interval 1
```

达到阈值提前停止（例如 `e_max < 0.1m`）：

```bash
python scripts/run_v0.py --optimize --engine optuna --jobs 8 --target-e-max 0.1
```

输出更干净：

```bash
python scripts/run_v0.py --optimize --engine optuna --jobs 8 --quiet
```

### 2.3 前馈/控制模式（ff_mode）

统一使用 `--ff-mode {no,ref,meas,ideal}`：

- `no`：纯 PID（无逆动力学前馈）
- `ref`：`tau = ID(q_ref, qd_ref, qdd_ref) + PID`
- `meas`：`tau = ID(q_meas, qd_meas, qdd_ref) + PID`
- `ideal`：理想 computed-torque 上限（禁用限幅）：`tau = ID(q_meas, qd_meas, qdd_cmd)`

示例：

```bash
python scripts/run_v0.py --ff-mode no
python scripts/run_v0.py --ff-mode meas
```

### 2.4 compare-ff（4 模式对比）

同一组 PD / 同一工况下，对比 4 个前馈模式并输出曲线：

```bash
python scripts/run_v0.py --compare-ff --quiet
```

输出：
- `artifacts/compare_ff_modes.json`
- `artifacts/compare_ff_modes.png`（TCP 误差时序）
- `artifacts/compare_ff_torque.png`（6 关节力矩时序）

### 2.5 Viewer（仅回放，不在 trial 中打开）

```bash
python scripts/run_v0.py --viewer
```

说明：优化结束可用 `--viewer` 回放 best；窗口关闭后程序退出。

## 3. 结果文件与可复现性

### 3.1 opt_result.json

默认优化结果会写入 `artifacts/opt_result.json`，内容包含：
- `kp/kd/ki`（6 关节独立参数）
- `ff_mode` / `integrator` 等关键运行条件（用于回放/复现）

加载结果：

```bash
python scripts/run_v0.py --load-result artifacts/opt_result.json
```

行为约定：
- 如果你没有显式传 `--ff-mode`，会优先采用 `opt_result.json` 里保存的 `ff_mode`
- 若当前 CLI/config 的关键项（dt/轨迹/限幅等）与结果保存时不一致，会打印 warning（提示可能无法复现）

### 3.2 optuna.db

多进程并行 `--jobs-backend process` 需要 Optuna storage（SQLite），默认会用：

- `sqlite:///artifacts/optuna.db`

用于：
- 支撑多进程并行 trial（进程间共享 study）
- 启动 Optuna Dashboard 查看 trial 曲线

Dashboard 示例：

```bash
optuna-dashboard sqlite:///artifacts/optuna.db --host 127.0.0.1 --port 8080
```

## 4. 更多文档

- 参数解释：`configs/run_v0_defaults.md`
- 常用命令速查：`docs/run_v0_cli_cheatsheet.md`
- 开发日志（关键结论 + 复现条件）：`docs/dev_log.md`
- 工业机器人经验沉淀（可复用 skill）：`industrial_robot_skill.md`

## 5. HTTP 后端（给前端调用）

后端脚本：`scripts/perfopt_http_backend.py`

默认端口：`127.0.0.1:8080`

启动示例：

```bash
PERFOPT_HOST=127.0.0.1 PERFOPT_PORT=8080 python scripts/perfopt_http_backend.py
```

健康检查：

```bash
curl http://127.0.0.1:8080/health
```

注意：若端口被占用会导致前端 `Failed to fetch`，请先运行 `stop_all.sh` 释放端口。
