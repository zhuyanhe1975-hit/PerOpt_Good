import React, { useMemo, useState } from "react";
import { OptimizationResult, RobotParams, Weights, StrategicInsight } from "../types";

interface SidebarRightProps {
  metrics: OptimizationResult;
  weights: Weights;
  strategicHistory: StrategicInsight[];
  params: RobotParams;
  liveParams: RobotParams | null;
}

const SidebarRight: React.FC<SidebarRightProps> = ({ metrics, weights, strategicHistory, params, liveParams }) => {
  const latestInsight = strategicHistory[0];
  const [pdPanelMode, setPdPanelMode] = useState<"six" | "all" | "collapsed">("six");

  const jointKeys = useMemo(() => Object.keys(params), [params]);
  const visibleJoints =
    pdPanelMode === "collapsed" ? [] : pdPanelMode === "all" ? jointKeys : jointKeys.slice(0, 6);

  const handlePdPanelToggle = () => {
    if (pdPanelMode === "collapsed") {
      setPdPanelMode("six");
      return;
    }
    if (pdPanelMode === "six") {
      setPdPanelMode(jointKeys.length > 6 ? "all" : "collapsed");
      return;
    }
    setPdPanelMode("collapsed");
  };

  const pdPanelToggleLabel =
    pdPanelMode === "collapsed"
      ? `展开 ${Math.min(6, jointKeys.length)} 轴`
      : pdPanelMode === "six"
        ? jointKeys.length > 6
          ? `展开全部 ${jointKeys.length} 轴`
          : "折叠"
        : "折叠";

  const totalScore = useMemo(() => {
    const sum = weights.energy + weights.precision + weights.vibration + weights.cycleTime;
    const wn =
      sum > 0
        ? {
            energy: weights.energy / sum,
            precision: weights.precision / sum,
            vibration: weights.vibration / sum,
            cycleTime: weights.cycleTime / sum,
          }
        : { energy: 0.25, precision: 0.25, vibration: 0.25, cycleTime: 0.25 };
    const precisionMm = (metrics.tcpErrorMean ?? metrics.precision) * 1000;
    return wn.precision * precisionMm + wn.vibration * metrics.vibration + wn.energy * metrics.energy + wn.cycleTime * metrics.cycleTime;
  }, [metrics, weights]);

  return (
    <div
      className="w-[420px] flex-shrink-0 border-l border-[var(--border)] flex flex-col h-screen overflow-hidden select-none"
      style={{ background: "var(--panel)" }}
    >
      <div className="p-4 overflow-y-auto flex-grow flex flex-col gap-5 scrollbar-thin">
        <h2 className="text-[12px] font-bold muted uppercase tracking-widest flex items-center justify-between">
          <span>
            <i className="fa-solid fa-gauge-high mr-2"></i> 状态面板
          </span>
          <span className="text-[var(--accent)] mono text-[11px] bg-emerald-500/10 px-2 py-1 rounded border border-emerald-500/20">
            {metrics.solverStatus || "UNKNOWN"}
          </span>
        </h2>

        <div className="grid grid-cols-2 gap-3">
          <MetricCard label="能耗" value={metrics.energy.toFixed(2)} unit="kWh" />
          <MetricCard label="精度" value={(((metrics.tcpErrorMean ?? metrics.precision) * 1000)).toFixed(2)} unit="mm" />
          <MetricCard label="振动" value={metrics.vibration.toFixed(3)} unit="-" />
          <MetricCard label="节拍" value={metrics.cycleTime.toFixed(2)} unit="s" />
          <MetricCard label="总分" value={totalScore.toFixed(2)} unit="score" accent />
          <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3 flex flex-col justify-between">
            <span className="text-[12px] muted font-bold uppercase tracking-widest">Trial</span>
            <div className="flex items-baseline gap-1">
              <span className="text-xl mono font-bold">{metrics.trialCount || 0}</span>
              <span className="text-[12px] muted">#</span>
            </div>
          </div>
        </div>

        {/* PD 最优参数监控（搬到右侧） */}
        <section className="rounded-lg panel-subtle p-3 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-[12px] font-bold muted uppercase tracking-widest flex items-center gap-2">
              <i className="fa-solid fa-sliders"></i> PD 最优参数监控
            </h3>
            <button onClick={handlePdPanelToggle} className="text-[12px] text-[var(--accent)] font-bold tracking-widest">
              {pdPanelToggleLabel}
            </button>
          </div>

          <div className="grid grid-cols-1 gap-2">
            {visibleJoints.map((name) => {
              const base = params[name];
              const live = liveParams ? liveParams[name] : null;
              return (
                <div
                  key={name}
                  className={`px-3 py-2.5 rounded-lg border transition-all ${
                    live ? "bg-emerald-500/10 border-emerald-500/30" : "bg-[var(--panel)] border-[var(--border)]"
                  }`}
                >
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-[12px] mono font-bold">{name}</span>
                    {live && <span className="w-2 h-2 bg-[var(--accent)] rounded-full animate-pulse" />}
                  </div>

                  <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                    <div className="space-y-1">
                      <div className="flex justify-between text-[11px] font-bold uppercase muted">
                        <span>Kp</span>
                        <span className="mono text-[var(--text)]">{(base?.kp ?? 0).toFixed(0)}</span>
                      </div>
                      <div className="h-1.5 w-full rounded-full relative overflow-hidden border border-[var(--border)] bg-[var(--panel-2)]">
                        <div className="absolute inset-y-0 w-px bg-[var(--border)] left-1/2" />
                        {live && (
                          <div
                            className="absolute inset-y-0 w-2 bg-[var(--accent)] shadow-[0_0_10px_rgba(16,185,129,0.55)] transition-all duration-300"
                            style={{ left: `${Math.max(2, Math.min(95, 50 + ((live.kp / base.kp - 1) * 60)))}%` }}
                          />
                        )}
                      </div>
                    </div>
                    <div className="space-y-1">
                      <div className="flex justify-between text-[11px] font-bold uppercase muted">
                        <span>Kd</span>
                        <span className="mono text-[var(--text)]">{(base?.kd ?? 0).toFixed(1)}</span>
                      </div>
                      <div className="h-1.5 w-full rounded-full relative overflow-hidden border border-[var(--border)] bg-[var(--panel-2)]">
                        <div className="absolute inset-y-0 w-px bg-[var(--border)] left-1/2" />
                        {live && (
                          <div
                            className="absolute inset-y-0 w-2 bg-amber-500 shadow-[0_0_10px_rgba(245,158,11,0.55)] transition-all duration-300"
                            style={{ left: `${Math.max(2, Math.min(95, 50 + ((live.kd / base.kd - 1) * 60)))}%` }}
                          />
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}

            {visibleJoints.length === 0 && (
              <div className="text-[12px] muted text-center py-6">已折叠</div>
            )}
          </div>
        </section>

        {latestInsight && (
          <section className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-4 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-[12px] font-bold text-amber-600 uppercase tracking-widest flex items-center gap-2">
                <i className="fa-solid fa-brain"></i> 战略架构师评估
              </h3>
              <div className="flex flex-col items-end">
                <span className="text-[12px] muted font-bold uppercase">可行性</span>
                <span className={`text-xl mono font-bold ${latestInsight.feasibilityScore > 70 ? "text-[var(--accent)]" : "text-amber-600"}`}>
                  {latestInsight.feasibilityScore}%
                </span>
              </div>
            </div>

            <div className="text-[13px] leading-relaxed bg-black/10 p-3 rounded-md border border-[var(--border)]">
              {latestInsight.analysis}
            </div>

            <div className="space-y-2">
              <span className="text-[12px] muted uppercase font-bold">建议</span>
              <ul className="space-y-1">
                {latestInsight.constraintSuggestions.map((s, i) => (
                  <li key={i} className="text-[13px] flex items-start gap-2">
                    <span className="text-amber-600 mt-0.5">•</span>
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          </section>
        )}
      </div>

      <section className="h-[28%] border-t border-[var(--border)] flex flex-col overflow-hidden panel-header">
        <header className="p-3 border-b border-[var(--border)] flex items-center justify-between">
          <h3 className="text-[12px] font-bold text-[var(--accent)] uppercase tracking-widest flex items-center gap-2">
            <i className="fa-solid fa-list-check"></i> 策略演进
          </h3>
          <span className="text-[12px] muted mono">记录: {strategicHistory.length}</span>
        </header>

        <div className="flex-grow overflow-y-auto p-3 space-y-4 scrollbar-thin bg-[var(--panel-3)] text-[12px]">
          {strategicHistory.map((entry, idx) => (
            <div key={idx} className="border-l-2 border-emerald-500/20 pl-3 py-1">
              <div className="text-[var(--accent)] font-bold mb-1">架构师更新 #{strategicHistory.length - idx}</div>
              <div className="muted italic mb-2">"{entry.parameterStrategy}"</div>
              {entry.suggestedWeights && (
                <div className="bg-[var(--panel)] p-2 rounded text-[12px] muted border border-[var(--border)]">
                  建议权重调整: 能耗:{entry.suggestedWeights.energy}% | 精度:{entry.suggestedWeights.precision}%
                </div>
              )}
            </div>
          ))}
          {strategicHistory.length === 0 && <div className="muted text-center py-6">暂无记录</div>}
        </div>
      </section>
    </div>
  );
};

const MetricCard: React.FC<{ label: string; value: string; unit: string; accent?: boolean }> = ({ label, value, unit, accent }) => (
  <div className="bg-[var(--panel-2)] border border-[var(--border)] p-3 rounded-lg hover:opacity-95 transition-opacity">
    <span className="text-[12px] muted uppercase font-bold block mb-1">{label}</span>
    <div className="flex items-baseline gap-1">
      <span className={`text-xl mono font-bold ${accent ? "text-[var(--accent)]" : ""}`}>{value}</span>
      <span className="text-[12px] muted">{unit}</span>
    </div>
  </div>
);

export default SidebarRight;

