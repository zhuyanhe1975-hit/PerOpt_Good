
import React, { useRef, useState } from 'react';
import { RobotParams, Weights, JointInfo, AssetMap } from '../types';
import loongenvLogo from '../loongenv-logo.png';

interface SidebarLeftProps {
  params: RobotParams;
  liveParams: RobotParams | null;
  joints: JointInfo[];
  weights: Weights;
  onWeightChange: (key: keyof Weights, val: number) => void;
  onOptimize: () => void;
  isOptimizing: boolean;
  isPaused: boolean;
  onTogglePause: () => void;
  onStop: () => void;
  onUrdfLoad: (content: string) => void;
  assets: AssetMap;
  onAssetsUpload: (newAssets: AssetMap) => void;
  maxRounds: number;
  setMaxRounds: (val: number) => void;
  totalTrials: number;
  setTotalTrials: (val: number) => void;
  simDuration: number;
  setSimDuration: (val: number) => void;
  currentTrial: number;
  jobProgress: { done: number; total: number } | null;
  resumeOptimization: boolean;
  setResumeOptimization: (val: boolean) => void;
  presetMeta: { preset: string; path?: string; sha256?: string; mtime?: number } | null;
  // AI 与并行设置
  useAIStrategy: boolean;
  setUseAIStrategy: (val: boolean) => void;
  parallelWorkers: number;
  setParallelWorkers: (val: number) => void;
}

const SidebarLeft: React.FC<SidebarLeftProps> = ({ 
  params, liveParams, weights, onWeightChange, onOptimize, isOptimizing, 
  isPaused, onTogglePause, onStop, onAssetsUpload, currentTrial,
  maxRounds, setMaxRounds, totalTrials, setTotalTrials, simDuration, setSimDuration,
  useAIStrategy, setUseAIStrategy, parallelWorkers, setParallelWorkers, jobProgress,
  resumeOptimization, setResumeOptimization,
  presetMeta
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [activePresetId, setActivePresetId] = useState<string | null>(null);

  const presets = [
    { id: 'quick', name: '节拍', icon: 'fa-bolt', w: { energy: 10, precision: 20, vibration: 10, cycleTime: 60 } },
    { id: 'true', name: '精度', icon: 'fa-crosshairs', w: { energy: 10, precision: 70, vibration: 10, cycleTime: 10 } },
    { id: 'stable', name: '稳定性', icon: 'fa-wave-square', w: { energy: 10, precision: 20, vibration: 60, cycleTime: 10 } }
  ];

  const handleWeightChange = (key: keyof Weights, val: number) => {
    setActivePresetId(null);
    onWeightChange(key, val);
  };

  const applyPreset = (presetId: string) => {
    const preset = presets.find((p) => p.id === presetId);
    if (!preset) return;
    setActivePresetId(presetId);
    Object.entries(preset.w).forEach(([k, v]) => onWeightChange(k as keyof Weights, v));
  };

  return (
    <div className="w-80 flex-shrink-0 border-r border-[var(--border)] flex flex-col h-screen overflow-hidden select-none" style={{ background: "var(--panel)" }}>
      <div className="p-4 flex items-center gap-3 panel-header">
        <div className="w-10 h-10 rounded-lg overflow-hidden border border-[var(--border)] bg-[var(--panel-2)] flex items-center justify-center">
          <img src={loongenvLogo} alt="LoongEnv" className="w-full h-full object-contain p-1.5" />
        </div>
        <div className="flex-grow">
          <div className="flex items-center gap-2">
            <h1 className="text-[15px] font-bold tracking-tight">工业机器人正向设计平台</h1>
            <span className="text-[11px] bg-emerald-500/15 text-[var(--accent)] px-1.5 py-0.5 rounded border border-emerald-500/25 font-bold tracking-tighter">LoongEnv</span>
          </div>
          <p className="text-[12px] muted uppercase tracking-widest font-semibold">交互 / 配置 / 可视化</p>
        </div>
      </div>

      <div className="flex-grow overflow-y-auto p-4 space-y-5 scrollbar-thin">
        {/* 任务与执行 */}
        <section className="rounded-lg panel-subtle p-3 space-y-4">
          <h2 className="text-[12px] font-bold muted uppercase tracking-widest flex items-center gap-2">
            <i className="fa-solid fa-gears text-[12px]"></i> 执行编排
          </h2>
          
          <div className="flex items-center justify-between group">
             <div className="flex flex-col">
                <span className="text-[12px] font-bold">AI 闭环优化</span>
                <span className="text-[12px] muted uppercase">Gemini Strategic Layer</span>
             </div>
             <button 
                onClick={() => setUseAIStrategy(!useAIStrategy)}
                disabled={isOptimizing}
                className={`relative w-8 h-4 rounded-full transition-colors ${useAIStrategy ? 'bg-amber-600' : 'bg-zinc-800'} ${isOptimizing ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
             >
                <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${useAIStrategy ? 'left-4.5 shadow-[0_0_5px_rgba(255,255,255,0.5)]' : 'left-0.5'}`} />
             </button>
          </div>

          <div className="space-y-2">
             <div className="flex justify-between items-center">
                <div className="flex flex-col">
                  <span className="text-[12px] font-bold">并行进程数</span>
                  <span className="text-[12px] muted uppercase">Optuna Multi-Process</span>
                </div>
                <span className="text-sm mono text-[var(--accent)]">{parallelWorkers}</span>
             </div>
             <input 
                type="range" min="1" max="8" value={parallelWorkers} 
                disabled={true}
                onChange={(e) => setParallelWorkers(parseInt(e.target.value))}
                className="w-full h-1 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-emerald-500 disabled:opacity-50"
             />
          </div>

          <div className="grid grid-cols-2 gap-2 pt-2 border-t border-zinc-800/60">
            <label className="bg-[var(--panel)] border border-[var(--border)] rounded-lg p-2.5 flex flex-col gap-1">
              <span className="text-[12px] muted font-bold uppercase tracking-widest">优化轮数</span>
              <input
                type="number"
                min={1}
                max={50}
                disabled={true}
                value={maxRounds}
                onChange={(e) => setMaxRounds(Math.max(1, Math.min(50, parseInt(e.target.value || '1', 10))))}
                className="bg-transparent outline-none text-base mono"
              />
            </label>
            <label className="bg-[var(--panel)] border border-[var(--border)] rounded-lg p-2.5 flex flex-col gap-1">
              <span className="text-[12px] muted font-bold uppercase tracking-widest">每轮试炼数</span>
              <input
                type="number"
                min={4}
                max={200}
                step={1}
                disabled={true}
                value={totalTrials}
                onChange={(e) => setTotalTrials(Math.max(4, Math.min(200, parseInt(e.target.value || '4', 10))))}
                className="bg-transparent outline-none text-base mono"
              />
            </label>
            <div className="col-span-2 bg-[var(--panel)] border border-[var(--border)] rounded-lg p-2.5 space-y-2">
              <div className="flex justify-between items-baseline">
                <div className="flex flex-col">
                  <span className="text-[12px] muted font-bold uppercase tracking-widest">仿真时长</span>
                  <span className="text-[12px] muted">每个 Trial 的模拟时间</span>
                </div>
                <span className="text-base mono text-[var(--accent)]">{simDuration.toFixed(1)}s</span>
              </div>
              <input
                type="range"
                min="1"
                max="15"
                step="0.5"
                disabled={true}
                value={simDuration}
                onChange={(e) => setSimDuration(parseFloat(e.target.value))}
                className="w-full h-1 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-emerald-500 disabled:opacity-50"
              />
            </div>
          </div>

          <div className="text-[12px] muted border-t border-[var(--border)] pt-3 leading-relaxed space-y-1">
            <div>
              参数由后端配置文件提供：<span className="mono">PerfOpt_v0/configs/{presetMeta?.preset || "default"}.json</span>（高级用户直接编辑）。
            </div>
            {presetMeta?.path && (
              <div className="mono text-[11px] muted-2 break-all">
                {presetMeta.path}{presetMeta.sha256 ? ` @ ${String(presetMeta.sha256).slice(0, 12)}` : ""}
              </div>
            )}
          </div>
        </section>

        {/* 优化目标 */}
        <section className="rounded-lg panel-subtle p-3 space-y-4">
          <h2 className="text-[12px] font-bold muted uppercase tracking-widest flex items-center gap-2">
            <i className="fa-solid fa-layer-group text-[12px]"></i> 优化目标权重 (精度 / 振动 / 节拍 / 能耗)
          </h2>

          {/* 预设模式 */}
          <div className="grid grid-cols-3 gap-2">
              {presets.map(p => (
                <button
                  key={p.id}
                  onClick={() => applyPreset(p.id)}
                  className={`relative flex flex-col items-center gap-1.5 p-2.5 rounded border transition-colors ${
                    activePresetId === p.id
                      ? 'border-amber-500/50 bg-amber-500/10'
                      : 'border-[var(--border)] bg-[var(--panel)] hover:bg-[var(--panel-2)]'
                  }`}
                >
                  <span
                    className={`absolute top-1 right-1 text-[11px] ${
                      activePresetId === p.id ? 'text-amber-500 drop-shadow-[0_0_6px_rgba(245,158,11,0.8)]' : 'muted-2'
                    }`}
                    title={activePresetId === p.id ? '已选择' : '未选择'}
                  >
                    <i className="fa-solid fa-lightbulb"></i>
                  </span>
                  <i className={`fa-solid ${p.icon} text-[14px] ${activePresetId === p.id ? 'text-amber-500' : 'muted'}`}></i>
                  <span className="text-[12px] font-bold">{p.name}</span>
                </button>
              ))}
          </div>

          <div className="space-y-4 px-1">
             {Object.entries(weights).map(([key, val]) => (
               <div key={key} className="space-y-1.5">
                 <div className="flex justify-between text-[12px] font-bold tracking-tight">
                   <span className="muted">{
                     key === 'precision' ? '精度' :
                     key === 'vibration' ? '振动' :
                     key === 'cycleTime' ? '节拍' :
                     '能耗'
                   }</span>
                   <span className="text-[var(--accent)] mono">{val}%</span>
                 </div>
                 <div className="relative h-1 w-full bg-zinc-800/50 rounded-full">
                    <div className="absolute top-0 left-0 h-full bg-emerald-500 transition-all duration-300" style={{ width: `${val}%` }} />
                    <input
                      type="range"
                      min="0"
                      max="100"
                      value={val}
                      disabled={true}
                      onChange={(e) => handleWeightChange(key as keyof Weights, parseInt(e.target.value))}
                      className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10 disabled:cursor-not-allowed"
                    />
                 </div>
               </div>
             ))}
          </div>
        </section>
      </div>

      <div className="p-4 border-t border-[var(--border)] flex flex-col gap-2" style={{ background: "var(--panel)" }}>
        {!isOptimizing ? (
          <>
            <label className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2">
              <div className="flex flex-col">
                <span className="text-[12px] font-bold">接续优化</span>
                <span className="text-[12px] muted">在同一 study 上继续（否则从头开始）</span>
              </div>
              <button
                type="button"
                onClick={() => setResumeOptimization(!resumeOptimization)}
                className={`relative w-10 h-5 rounded-full transition-colors ${
                  resumeOptimization ? "bg-emerald-600" : "bg-zinc-700"
                }`}
                title={resumeOptimization ? "已开启" : "已关闭"}
              >
                <div
                  className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-all ${
                    resumeOptimization ? "left-5" : "left-0.5"
                  }`}
                />
              </button>
            </label>

            <button onClick={onOptimize} className="w-full py-3 rounded-lg font-bold text-[12px] tracking-widest bg-emerald-600 hover:bg-emerald-500 text-white shadow-[0_4px_15px_rgba(16,185,129,0.18)]">
              启动自动调优
            </button>
          </>
        ) : (
          <div className="flex gap-2">
            <button onClick={onTogglePause} className={`flex-1 py-3 rounded-lg font-bold text-[12px] border transition-all ${isPaused ? 'bg-amber-600 border-amber-500' : 'bg-[var(--panel-2)] border-[var(--border)]'}`}>
              <i className={`fa-solid ${isPaused ? 'fa-play' : 'fa-pause'} mr-2`}></i>{isPaused ? "继续" : "暂停"}
            </button>
            <button onClick={onStop} className="flex-1 py-3 rounded-lg font-bold text-[12px] bg-rose-900/15 text-rose-600 border border-rose-900/20 hover:bg-rose-900/25 transition-all">
              <i className="fa-solid fa-stop mr-2"></i>停止
            </button>
          </div>
        )}

        {isOptimizing && jobProgress && jobProgress.total > 0 && (
          <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3 space-y-2">
            <div className="flex items-center justify-between text-[12px]">
              <span className="muted font-bold uppercase tracking-widest">优化进度</span>
              <span className="mono font-bold text-[var(--accent)]">
                {Math.min(100, Math.max(0, (jobProgress.done / jobProgress.total) * 100)).toFixed(1)}%
              </span>
            </div>
            <div className="h-2 w-full rounded-full overflow-hidden border border-[var(--border)] bg-[var(--panel)]">
              <div
                className="h-full bg-[var(--accent)] transition-all duration-300"
                style={{ width: `${Math.min(100, Math.max(0, (jobProgress.done / jobProgress.total) * 100))}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-[12px] mono muted">
              <span>
                {jobProgress.done}/{jobProgress.total} trials
              </span>
              <span className={isPaused ? "text-amber-600 font-bold" : "muted"}>
                {isPaused ? "已暂停" : "运行中"}
              </span>
            </div>
          </div>
        )}

        <div className="flex justify-between text-[11px] muted mono px-1">
          <span>PARALLEL_WORKERS: {parallelWorkers}</span>
          <span>SYSTEM_READY</span>
        </div>
      </div>
    </div>
  );
};

export default SidebarLeft;
