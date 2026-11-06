<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# Industrial Robot Arm Optimizer (Frontend)

前端默认与本仓库的 PerfOpt_v0 后端对接，页面端口固定为 `http://localhost:3000/`。

## 一键启动（推荐）

在仓库根目录执行：

```bash
/home/yhzhu/LoongEnv/PerOpt/start_all.sh
```

说明：
- 会先启动后端并检查 `/health`
- 再后台启动前端（不弹出额外 terminal）
- 自动打开 `http://localhost:3000/`

## 手动启动

**Prerequisites:** Node.js

1) 安装依赖

```bash
npm install
```

2) 运行前端（固定端口 3000）

```bash
npm run dev -- --port 3000 --host 127.0.0.1
```

## 后端依赖

默认后端地址：`http://127.0.0.1:8080`

若后端未启动，前端会提示 `Backend: OFFLINE` 并退化为本地 fallback 仿真。

## 可选：Gemini Key

如需 AI 战略层功能，请在未提交的 `.env.local` 填写（不要把密钥写进仓库或 Pages 构建产物）：

```
GEMINI_API_KEY=YOUR_API_KEY
```

当前优化循环没有调用该接口。未设置时构建使用空字符串。

## GitHub Pages

生产构建的站点根路径是 `/PerOpt_Good/`（`npm run build`，或由 `.github/workflows/pages.yml` 传入 `--base`）。

Pages 上可直接使用的部分：

- ER15-1400 URDF / STL 三维浏览（`public/urdf`）
- 权重预设与指标 / PD 面板

「启动自动调优」依赖本机 `PerfOpt_v0`（`http://127.0.0.1:8080`）。静态站点只提示这一限制，不会请求公网后端，也不会打包密钥。

合并到 `main` 并启用 Pages 后的地址：`https://zhuyanhe1975-hit.github.io/PerOpt_Good/`
