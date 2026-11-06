
import React, { useState, useEffect, useCallback, useRef } from 'react';
import SidebarLeft from './components/SidebarLeft';
import RobotVisualizer from './components/RobotVisualizer';
import SidebarRight from './components/SidebarRight';
import { RobotParams, Weights, OptimizationResult, LogEntry, JointInfo, UrdfModel, AssetMap, StrategicInsight, SimulationConfig, BackendStatus } from './types';
import { PerfOptClient } from './services/backendService';
import SystemSettingsModal, { applyTheme, loadSystemSettings, saveSystemSettings, SystemSettings } from './components/SystemSettingsModal';

const INITIAL_WEIGHTS: Weights = {
  energy: 20, precision: 40, vibration: 25, cycleTime: 15
};

const SIM_CONFIG: SimulationConfig = {
  engine: 'MuJoCo',
  timestep: 0.001,
  integrator: 'RK4',
  duration: 3.0,
  torqueLimit: [1000.0, 1000.0, 1000.0, 100.0, 100.0, 100.0],
  velLimits: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
};

const PD_RANGES = {
  kp: [2000.0, 10000.0] as const,
  kd: [0.1, 500.0] as const,
};

const FALLBACK_URDF = `
<?xml version="1.0" ?>
<robot name="ER15_Pro">
  <link name="base_link"><visual><geometry><box size="0.2 0.2 0.1"/></geometry><material name="g"><color rgba="0.2 0.2 0.2 1"/></material></visual></link>
  <link name="l1"><visual><geometry><cylinder length="0.4" radius="0.05"/></geometry></visual></link>
  <link name="l2"><visual><geometry><box size="0.04 0.04 0.4"/></geometry></visual></link>
  <link name="l3"><visual><geometry><box size="0.04 0.04 0.3"/></geometry></visual></link>
  <link name="l4"><visual><geometry><cylinder length="0.1" radius="0.03"/></geometry></visual></link>
  <link name="l5"><visual><geometry><cylinder length="0.1" radius="0.03"/></geometry></visual></link>
  <link name="l6"><visual><geometry><sphere radius="0.05"/></geometry></visual></link>
  <joint name="j1" type="revolute"><parent link="base_link"/><child link="l1"/><axis xyz="0 0 1"/></joint>
  <joint name="j2" type="revolute"><parent link="l1"/><child link="l2"/><axis xyz="0 1 0"/></joint>
  <joint name="j3" type="revolute"><parent link="l2"/><child link="l3"/><axis xyz="0 1 0"/></joint>
  <joint name="j4" type="revolute"><parent link="l3"/><child link="l4"/><axis xyz="1 0 0"/></joint>
  <joint name="j5" type="revolute"><parent link="l4"/><child link="l5"/><axis xyz="0 1 0"/></joint>
  <joint name="j6" type="revolute"><parent link="l5"/><child link="l6"/><axis xyz="0 0 1"/></joint>
</robot>
`;

// VERIFIED_GOOD_CHECKPOINT

function isHostedStaticDemo(): boolean {
  if (typeof window === 'undefined') return false;
  const host = window.location.hostname;
  return host !== 'localhost' && host !== '127.0.0.1' && host !== '::1';
}

const STATIC_DEMO_NOTE =
  '静态演示：可浏览 ER15-1400 模型、切换权重并查看指标面板。「启动自动调优」需要本机 PerfOpt_v0 后端（http://127.0.0.1:8080，MuJoCo/Optuna）。GitHub Pages 不会启动该服务，也不会写入 API 密钥。';

function flatten(obj: any, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  const keyOf = (p: string, k: string) => (p ? `${p}.${k}` : k);

  if (obj === null || obj === undefined) {
    out[prefix || "$"] = String(obj);
    return out;
  }
  if (typeof obj !== "object") {
    out[prefix || "$"] = String(obj);
    return out;
  }
  if (Array.isArray(obj)) {
    out[prefix || "$"] = JSON.stringify(obj);
    return out;
  }
  for (const [k, v] of Object.entries(obj)) {
    const p = keyOf(prefix, k);
    if (v === null || v === undefined) out[p] = String(v);
    else if (typeof v !== "object") out[p] = String(v);
    else if (Array.isArray(v)) out[p] = JSON.stringify(v);
    else Object.assign(out, flatten(v, p));
  }
  return out;
}

function diffKeys(prevObj: any, nextObj: any) {
  const a = flatten(prevObj);
  const b = flatten(nextObj);
  const keys = Array.from(new Set([...Object.keys(a), ...Object.keys(b)])).sort();
  const changes: Array<{ key: string; from: string; to: string }> = [];
  for (const k of keys) {
    const av = a[k];
    const bv = b[k];
    if (av !== bv) changes.push({ key: k, from: av ?? "(unset)", to: bv ?? "(unset)" });
  }
  return changes;
}

const App: React.FC = () => {
  const [params, setParams] = useState<RobotParams>({});
  const [liveParams, setLiveParams] = useState<RobotParams | null>(null);
  const [joints, setJoints] = useState<JointInfo[]>([]);
  const [urdfModel, setUrdfModel] = useState<UrdfModel | null>(null);
  const [assets, setAssets] = useState<AssetMap>({});
  const [weights, setWeights] = useState<Weights>(INITIAL_WEIGHTS);
  const [backendStatus, setBackendStatus] = useState<BackendStatus>({ connected: false, url: "http://127.0.0.1:8080" });
  const [lastSim, setLastSim] = useState<{ backend: string; elapsedS?: number } | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobProgress, setJobProgress] = useState<{ done: number; total: number } | null>(null);
  
  const [metrics, setMetrics] = useState<OptimizationResult>({
    energy: 2.15,
    precision: 0.005,
    tcpErrorMean: 0.005,
    tcpErrorMax: 0.005,
    vibration: 0.65,
    cycleTime: 3.50,
    timestamp: new Date().toISOString(),
    solverStatus: "IDLE"
  });
  
  const [history, setHistory] = useState<OptimizationResult[]>([]);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([
    { id: 'checkpoint', time: new Date().toLocaleTimeString(), type: 'success', message: 'System Initialized: Verified Good Checkpoint v1.0.0' }
  ]);
  const [strategicHistory, setStrategicHistory] = useState<StrategicInsight[]>([]);
  const [maxRounds, setMaxRounds] = useState(5);
  const [currentRound, setCurrentRound] = useState(0);
  const [currentTrial, setCurrentTrial] = useState(0);

  // 配置：AI 闭环与并行度
  const [useAIStrategy, setUseAIStrategy] = useState(false);
  const [parallelWorkers, setParallelWorkers] = useState(8);
  const [simDuration, setSimDuration] = useState(5.0);
  const [totalTrials, setTotalTrials] = useState(24);
  const [resumeOptimization, setResumeOptimization] = useState(false);

  const [systemSettings, setSystemSettings] = useState<SystemSettings>(() => loadSystemSettings());
  const [settingsOpen, setSettingsOpen] = useState(false);

  const stopRef = useRef(false);
  const pauseRef = useRef(false);
  const lastTrialLogRef = useRef<number | null>(null);
  const lastBestTrialRef = useRef<number | null>(null);
  const liveFlashTimeoutRef = useRef<number | null>(null);
  const lastPresetRef = useRef<{ preset: string; sha256?: string; config?: any } | null>(null);
  const [presetMeta, setPresetMeta] = useState<{ preset: string; path?: string; sha256?: string; mtime?: number } | null>(null);
  // Use IPv4 loopback explicitly; some browsers prefer IPv6 (::1) for "localhost",
  // while a minimal Python server may bind only to IPv4 (0.0.0.0/127.0.0.1).
  const backendClient = useRef(new PerfOptClient("http://127.0.0.1:8080"));
  const lastBackendConnectedRef = useRef<boolean | null>(null);
  const hostedStaticDemo = isHostedStaticDemo();

  const addLog = useCallback((message: string, type: LogEntry['type'] = 'info') => {
    setLogs(prev => [{ id: Math.random().toString(36).substr(2, 9), time: new Date().toLocaleTimeString(), type, message }, ...prev].slice(0, 50));
  }, []);

  const refreshPresetAndSyncUI = useCallback(async (presetName: string) => {
    const presetResp = await backendClient.current.getPresetConfig(presetName);
    if (!presetResp?.ok) {
      addLog(`Failed to load backend preset: ${presetResp?.error || "unknown"}`, "warning");
      return null;
    }

    const cfg = presetResp.config || {};
    const sha = presetResp.sha256 ? String(presetResp.sha256).slice(0, 12) : "unknown";
    const path = presetResp.path ? String(presetResp.path) : undefined;
    const mtime = typeof presetResp.mtime === "number" ? presetResp.mtime : undefined;
    setPresetMeta({ preset: String(presetResp.preset || presetName), path, sha256: presetResp.sha256, mtime });
    addLog(
      `Backend preset loaded: ${presetResp.preset} @ ${sha}${path ? ` | ${path}` : ""}`,
      "success"
    );

    const uiRounds = Number(cfg?.ui?.rounds ?? cfg?.rounds ?? NaN);
    const uiTrialsPerRound = Number(cfg?.ui?.trials_per_round ?? cfg?.ui?.trialsPerRound ?? cfg?.trials_per_round ?? NaN);
    const jobs = Number(cfg?.jobs ?? NaN);
    const trialsTotal = Number(cfg?.trials ?? NaN);

    if (cfg.weights) setWeights((prev) => ({ ...prev, ...cfg.weights }));
    if (Number.isFinite(jobs)) setParallelWorkers(jobs);
    if (Number.isFinite(uiRounds)) setMaxRounds(Math.max(1, Math.floor(uiRounds)));
    if (Number.isFinite(uiTrialsPerRound)) setTotalTrials(Math.max(4, Math.floor(uiTrialsPerRound)));

    // Effective duration: if cycles/freq exist, duration becomes cycles/freq on backend; reflect it.
    const freq = Number(cfg?.config?.sine_freq_hz ?? cfg?.config?.sineFreqHz ?? NaN);
    const cycles = Number(cfg?.config?.sine_cycles ?? cfg?.config?.sineCycles ?? NaN);
    const durCfg = Number(cfg?.config?.duration ?? NaN);
    if (Number.isFinite(cycles) && cycles > 0 && Number.isFinite(freq) && freq > 0) {
      setSimDuration(cycles * (1.0 / freq));
    } else if (Number.isFinite(durCfg)) {
      setSimDuration(durCfg);
    }

    const important = {
      study_name: cfg.study_name,
      resume: cfg.resume,
      jobs: cfg.jobs,
      trials: cfg.trials,
      rounds: cfg?.ui?.rounds ?? cfg?.rounds,
      trials_per_round: cfg?.ui?.trials_per_round ?? cfg?.trials_per_round,
      kp_range: cfg.kp_range,
      kd_range: cfg.kd_range,
      traj: cfg?.config?.traj,
      timestep: cfg?.config?.timestep ?? cfg?.config?.dt,
      integrator: cfg?.config?.integrator,
      ff_mode: cfg?.config?.ff_mode,
      sine_freq_hz: cfg?.config?.sine_freq_hz,
      sine_amp_scale: cfg?.config?.sine_amp_scale,
      sine_cycles: cfg?.config?.sine_cycles,
      torque_limit: cfg?.config?.torque_limit,
      vel_limits: cfg?.config?.vel_limits,
    };
    addLog(`Preset key params: ${JSON.stringify(important)}`, "info");

    if (lastPresetRef.current && lastPresetRef.current.preset === presetName) {
      const prevCfg = lastPresetRef.current.config;
      const changes = diffKeys(prevCfg, cfg);
      if (changes.length) {
        addLog(`Preset changed since last run: ${changes.length} items`, "warning");
        const focus = [
          "study_name",
          "resume",
          "jobs",
          "trials",
          "ui.rounds",
          "ui.trials_per_round",
          "kp_range",
          "kd_range",
          "config.timestep",
          "config.dt",
          "config.integrator",
          "config.traj",
          "config.ff_mode",
          "config.sine_freq_hz",
          "config.sine_amp_scale",
          "config.sine_cycles",
          "config.torque_limit",
          "config.vel_limits",
        ];
        const focused = changes.filter((c) => focus.includes(c.key));
        const list = (focused.length ? focused : changes).slice(0, 12);
        for (const c of list) addLog(`Changed ${c.key}: ${c.from} -> ${c.to}`, "warning");
        if (changes.length > list.length) addLog(`...and ${changes.length - list.length} more`, "warning");
      }
    }
    lastPresetRef.current = { preset: presetName, sha256: presetResp.sha256, config: cfg };

    if (Number.isFinite(trialsTotal) && Number.isFinite(uiRounds) && Number.isFinite(uiTrialsPerRound)) {
      const expected = Math.max(1, Math.floor(uiRounds)) * Math.max(1, Math.floor(uiTrialsPerRound));
      if (expected !== trialsTotal) addLog(`Preset mismatch: ui.rounds*trials_per_round=${expected} != trials=${trialsTotal}`, "warning");
    }

    return cfg;
  }, [addLog]);

  useEffect(() => {
    applyTheme(systemSettings.theme);
  }, [systemSettings.theme]);

  const parseUrdf = useCallback((xmlString: string, modelName = "ER15 Robot") => {
    try {
      const parser = new DOMParser();
      const xmlDoc = parser.parseFromString(xmlString, "text/xml");
      const jointElements = xmlDoc.getElementsByTagName("joint");
      const foundJoints: JointInfo[] = [];
      const initialControlParams: RobotParams = {};

      for (let i = 0; i < jointElements.length; i++) {
        const joint = jointElements[i];
        const type = joint.getAttribute("type");
        if (type === "revolute" || type === "continuous") {
          const name = joint.getAttribute("name") || `joint_${i+1}`;
          foundJoints.push({ name, type, lower: -180, upper: 180, value: 0 });
          initialControlParams[name] = { kp: 4000, kd: 120 };
        }
      }
      setUrdfModel({ name: modelName, content: xmlString, joints: foundJoints });
      setJoints(foundJoints);
      setParams(initialControlParams);
      return true;
    } catch (e) {
      addLog("URDF 解析失败", "error");
      return false;
    }
  }, [addLog]);

  useEffect(() => {
    const autoLoad = async () => {
      try {
        const response = await fetch(`${import.meta.env.BASE_URL}urdf/robot.urdf`);
        const text = response.ok ? await response.text() : '';
        const urdfOk = text.includes('<robot');
        parseUrdf(urdfOk ? text : FALLBACK_URDF, urdfOk ? "Industrial Workspace" : "Fallback ER15 Engine");
      } catch {
        parseUrdf(FALLBACK_URDF, "Fallback ER15 Engine");
      }
    };
    autoLoad();
  }, [parseUrdf]);

  useEffect(() => {
    if (hostedStaticDemo) {
      setBackendStatus((prev) => ({ ...prev, connected: false }));
      addLog(STATIC_DEMO_NOTE, 'warning');
      return;
    }

    let mounted = true;
    const url = backendStatus.url;

    const poll = async () => {
      const ok = await backendClient.current.checkHealth();
      if (!mounted) return;

      setBackendStatus((prev) => ({ ...prev, url, connected: ok }));

      if (lastBackendConnectedRef.current === null || lastBackendConnectedRef.current !== ok) {
        lastBackendConnectedRef.current = ok;
        addLog(ok ? `Backend connected: ${url}` : `Backend disconnected: ${url}`, ok ? "success" : "warning");
        if (ok) {
          // Sync UI with backend config on connect.
          refreshPresetAndSyncUI("default").catch(() => {});
        }
      }
    };

    poll();
    const id = window.setInterval(poll, 4000);
    return () => {
      mounted = false;
      window.clearInterval(id);
    };
  }, [addLog, backendStatus.url, hostedStaticDemo, refreshPresetAndSyncUI]);

  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

  const makeObjective = useCallback((result: OptimizationResult, w: Weights) => {
    const sum = w.energy + w.precision + w.vibration + w.cycleTime;
    const wn = sum > 0 ? { energy: w.energy / sum, precision: w.precision / sum, vibration: w.vibration / sum, cycleTime: w.cycleTime / sum } : { energy: 0.25, precision: 0.25, vibration: 0.25, cycleTime: 0.25 };
    const precisionMm = result.precision * 1000;
    return (
      wn.precision * precisionMm +
      wn.vibration * result.vibration +
      wn.energy * result.energy +
      wn.cycleTime * result.cycleTime
    );
  }, []);

  const runOptimization = async () => {
    if (isOptimizing || !urdfModel) return;
    if (hostedStaticDemo) {
      addLog(STATIC_DEMO_NOTE, 'warning');
      return;
    }
    if (!backendStatus.connected) {
      addLog(`Backend OFFLINE (${backendStatus.url}). 三维浏览仍然可用；自动调优需要先在本机启动 PerfOpt_v0。`, 'warning');
      return;
    }
    
    stopRef.current = false;
    pauseRef.current = false;
    lastTrialLogRef.current = null;
    lastBestTrialRef.current = null;
    if (liveFlashTimeoutRef.current) {
      window.clearTimeout(liveFlashTimeoutRef.current);
      liveFlashTimeoutRef.current = null;
    }
    setIsOptimizing(true);
    setIsPaused(false);
    setStrategicHistory([]);
    addLog(`Optuna Engine: Started with ${parallelWorkers} Parallel Workers | Trials/Round: ${totalTrials} | Sim: ${simDuration.toFixed(1)}s`, "success");
    if (useAIStrategy) addLog("Strategic Layer: AI Feedback Loop ENABLED", "warning");
    addLog(backendStatus.connected ? `Backend: ONLINE (${backendStatus.url})` : `Backend: OFFLINE (fallback sim)`, backendStatus.connected ? "success" : "warning");

    try {
      const jobs = Math.max(1, parallelWorkers);
      // Keep each round aligned to the process pool to avoid under-utilization.
      const trialsPerRound = Math.max(4, Math.ceil(totalTrials / jobs) * jobs);
      const trialsTotal = Math.max(4, maxRounds * trialsPerRound);

      const presetName = "default";
      try {
        const cfg = await refreshPresetAndSyncUI(presetName);
        if (cfg && typeof cfg.resume === "boolean" && cfg.resume !== resumeOptimization) {
          addLog(`Override resume: ${cfg.resume} -> ${resumeOptimization}`, "warning");
        }
      } catch (e) {
        addLog(`Preset read failed: ${(e as Error).message}`, "warning");
      }

      const startResp = await backendClient.current.startOptimize({
        preset: "default",
        resume: resumeOptimization,
        // Keep UI simple: advanced knobs are in backend configs/*.json (preset).
      });

      if (!startResp?.ok || !startResp.job_id) {
        throw new Error(startResp?.error || "Failed to start backend optimization job");
      }

      setJobId(startResp.job_id);
      setJobProgress({ done: 0, total: trialsTotal });
      addLog(`Backend job started: ${startResp.job_id} | Trials: ${trialsTotal} | Jobs: ${jobs}`, "success");

      // Poll until finished/stopped/error.
      while (!stopRef.current) {
        if (pauseRef.current) {
          await new Promise((r) => setTimeout(r, 200));
          continue;
        }
        const st = await backendClient.current.getOptimizeStatus(startResp.job_id);
        if (!st?.ok || !st?.job) throw new Error("Invalid status response");

        const job = st.job;
        const state = String(job.state || "UNKNOWN");
        const snap = job.snapshot || {};
        const progress = snap.progress || null;
        if (progress && typeof progress.done === "number" && typeof progress.total === "number") {
          setJobProgress({ done: progress.done, total: progress.total });
          setCurrentRound(Math.floor(progress.done / trialsPerRound) + 1);
          setCurrentTrial((progress.done % trialsPerRound) || 0);
        }

        const best = snap.best;
        if (best?.params && best?.metrics) {
          const m = best.metrics || {};
          const bestTrial = typeof best.trial === "number" ? best.trial : Number(best.trial ?? 0);
          const result: OptimizationResult = {
            energy: Number(m.energy || 0),
            precision: Number(m.rmse || 0),
            tcpErrorMean: Number(m.rmse || 0),
            tcpErrorMax: Number(m.e_max || 0),
            vibration: Number(m.vib_energy || 0),
            cycleTime: Number(m.cycle_time || simDuration),
            timestamp: new Date().toISOString(),
            solverStatus: state,
            optimizedParams: best.params,
            trialCount: Number.isFinite(bestTrial) ? bestTrial : 0,
            backend: String(best.backend || "perfopt_v0"),
            elapsed_s: typeof best.elapsed_s === "number" ? best.elapsed_s : undefined,
          };
          if (Number.isFinite(bestTrial) && bestTrial !== lastBestTrialRef.current) {
            lastBestTrialRef.current = bestTrial;
            setMetrics(result);
            setParams(best.params);

            // Flash PD panel to show convergence steps (best-so-far updates).
            setLiveParams(best.params);
            if (liveFlashTimeoutRef.current) window.clearTimeout(liveFlashTimeoutRef.current);
            liveFlashTimeoutRef.current = window.setTimeout(() => setLiveParams(null), 900);

            if (result.elapsed_s !== undefined) setLastSim({ backend: result.backend || "perfopt_v0", elapsedS: result.elapsed_s });
            addLog(`Best updated @ Trial #${bestTrial}`, "success");
          }
        }

        const recent = Array.isArray(snap.recent_trials) ? snap.recent_trials : [];
        if (recent.length) {
          // Log only the last item to avoid flooding.
          const last = recent[recent.length - 1];
          const t = typeof last.trial === "number" ? last.trial : Number(last.trial ?? NaN);
          if (Number.isFinite(t) && lastTrialLogRef.current === t) {
            // no-op
          } else {
            if (Number.isFinite(t)) lastTrialLogRef.current = t;
          const m = last.metrics || {};
          const precStr = ((Number(m.rmse || 0)) * 1000).toFixed(2);
          const backend = String(last.backend || "perfopt_v0");
          const elapsedS = typeof last.elapsed_s === "number" ? last.elapsed_s : undefined;
          addLog(
            `Trial #${last.trial}: Error ${precStr}mm | Vib: ${Number(m.vib_energy || 0).toFixed(3)} | ${backend}${elapsedS !== undefined ? ` ${elapsedS.toFixed(3)}s` : ""}`,
            "info"
          );
          }
        }

        if (state === "FINISHED" || state === "STOPPED" || state === "ERROR") {
          if (state === "ERROR") addLog(`Backend job error: ${job.error || "unknown"}`, "error");
          break;
        }

        await new Promise((r) => setTimeout(r, 800));
      }
    } catch (err) {
      addLog("Pipeline Error: " + (err as Error).message, "error");
    } finally {
      setIsOptimizing(false);
      setIsPaused(false);
      setCurrentRound(0);
      setCurrentTrial(0);
      setLiveParams(null);
      setJobId(null);
      setJobProgress(null);
      addLog(stopRef.current ? "Pipeline: EMERGENCY STOPPED" : "Pipeline: FINISHED", stopRef.current ? "warning" : "success");
      stopRef.current = false;
    }
  };

  const handleStop = () => {
    stopRef.current = true;
    pauseRef.current = false;
    setIsPaused(false);
    if (jobId) {
      backendClient.current.stopOptimize(jobId).catch(() => {});
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden app-root">
      <SidebarLeft 
        params={params} liveParams={liveParams} joints={joints} weights={weights} 
        onWeightChange={(k, v) => setWeights(prev => ({ ...prev, [k]: v }))}
        onOptimize={runOptimization} isOptimizing={isOptimizing}
        isPaused={isPaused} onTogglePause={() => { pauseRef.current = !isPaused; setIsPaused(!isPaused); }} onStop={handleStop}
        onUrdfLoad={parseUrdf} assets={assets} onAssetsUpload={(a) => setAssets(prev => ({ ...prev, ...a }))}
        maxRounds={maxRounds} setMaxRounds={setMaxRounds}
        totalTrials={totalTrials} setTotalTrials={setTotalTrials}
        simDuration={simDuration} setSimDuration={setSimDuration}
        currentTrial={currentTrial}
        useAIStrategy={useAIStrategy} setUseAIStrategy={setUseAIStrategy}
        parallelWorkers={parallelWorkers} setParallelWorkers={setParallelWorkers}
        jobProgress={jobProgress}
        resumeOptimization={resumeOptimization}
        setResumeOptimization={setResumeOptimization}
        presetMeta={presetMeta}
      />
      
      <main className="flex-grow flex flex-col min-w-0">
        <header className="h-14 border-b border-[var(--border)] flex items-center justify-between px-6 panel-header backdrop-blur-md z-10">
           <div className="flex items-center gap-6">
              <div className="flex flex-col">
                <span className="text-[12px] muted font-bold uppercase tracking-tighter">搜索引擎</span>
                <span className="text-sm text-[var(--accent)] mono">{`Optuna ${parallelWorkers}x Workers`}</span>
              </div>
              <div className="h-6 w-px bg-[var(--border)]" />
              <div className="flex flex-col">
                <span className="text-[12px] muted font-bold uppercase tracking-tighter">策略层</span>
                <span className={`text-xs mono ${useAIStrategy ? 'text-amber-500' : 'muted-2'}`}>
                  {useAIStrategy ? 'Gemini-3-Pro' : 'OFFLINE (TPE ONLY)'}
                </span>
              </div>
           </div>
            <div className="flex items-center gap-4">
              <button
                onClick={() => setSettingsOpen(true)}
                className="text-[12px] font-mono px-3 py-1 rounded bg-[var(--panel)] border border-[var(--border)] flex items-center gap-2 hover:bg-[var(--panel-2)] transition-colors"
                title="系统配置"
              >
                <i className="fa-solid fa-gear muted" />
                <span className="muted">系统配置</span>
              </button>
              <span
                title={backendStatus.connected ? `Backend ONLINE: ${backendStatus.url}` : `Backend OFFLINE: ${backendStatus.url}`}
                className={`text-[12px] mono px-3 py-1 rounded bg-[var(--panel)] border border-[var(--border)] flex items-center gap-2 ${
                  backendStatus.connected ? 'text-[var(--accent)]' : 'text-rose-500'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${backendStatus.connected ? 'bg-[var(--accent)]' : 'bg-rose-500'}`} />
                {backendStatus.connected ? 'BACKEND_ON' : 'BACKEND_OFF'}
                {backendStatus.connected && lastSim?.elapsedS !== undefined && (
                  <span className="text-[11px] muted">{`${lastSim.backend} ${lastSim.elapsedS.toFixed(3)}s`}</span>
                )}
              </span>
              <span className={`text-[12px] mono px-3 py-1 rounded bg-[var(--panel)] border border-[var(--border)] ${isOptimizing ? 'text-[var(--accent)]' : 'muted-2'}`}>
                {isOptimizing
                  ? `R${currentRound}.T${currentTrial}_RUNNING${jobProgress ? ` ${jobProgress.done}/${jobProgress.total}` : ""}`
                  : 'SYSTEM_IDLE'}
              </span>
            </div>
        </header>

        {hostedStaticDemo && (
          <div className="px-6 py-2 text-[12px] leading-relaxed border-b border-[var(--warning)] bg-[var(--panel-2)]">
            {STATIC_DEMO_NOTE}
          </div>
        )}

        <div className="flex-grow relative" style={{ background: "var(--bg)" }}>
           <RobotVisualizer urdfContent={urdfModel?.content || null} metrics={metrics} assets={assets} isOptimizing={isOptimizing && !isPaused} basePath={`${import.meta.env.BASE_URL}urdf`} />
           <div className="absolute bottom-6 left-6 p-4 rounded-xl backdrop-blur-lg panel-subtle">
              <div className="text-[12px] muted mb-2 font-bold uppercase tracking-wider">TCP 误差 (全局最优 Max / Mean)</div>
              <div className="space-y-1">
                <div className="flex items-baseline gap-2">
                  <span className="text-[11px] muted font-bold uppercase w-12">Max</span>
                  <span className="text-2xl mono font-bold">{(((metrics.tcpErrorMax ?? metrics.precision) * 1000)).toFixed(2)}</span>
                  <span className="text-[12px] text-[var(--accent)]">mm</span>
                </div>
                <div className="flex items-baseline gap-2">
                  <span className="text-[11px] muted font-bold uppercase w-12">Mean</span>
                  <span className="text-2xl mono font-bold">{(((metrics.tcpErrorMean ?? metrics.precision) * 1000)).toFixed(2)}</span>
                  <span className="text-[12px] text-[var(--accent)]">mm</span>
                </div>
              </div>
           </div>
        </div>

        <div className="h-40 border-t border-[var(--border)] p-4 panel-header">
            <div className="h-full overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--panel)] p-3 mono text-[12px] flex flex-col-reverse scrollbar-thin">
                {logs.map(log => (
                    <div key={log.id} className="flex gap-4 py-0.5 border-l border-transparent hover:border-zinc-800 pl-2">
                        <span className="muted-2 min-w-[74px]">{log.time}</span>
                        <span className={`${log.type === 'success' ? 'text-[var(--accent)]' : log.type === 'error' ? 'text-rose-600' : log.type === 'warning' ? 'text-amber-600' : 'muted'}`}>
                          [{log.type.toUpperCase()}] {log.message}
                        </span>
                    </div>
                ))}
            </div>
        </div>
      </main>
      
      <SidebarRight metrics={metrics} weights={weights} strategicHistory={strategicHistory} params={params} liveParams={liveParams} />

      <SystemSettingsModal
        open={settingsOpen}
        initial={systemSettings}
        onClose={() => setSettingsOpen(false)}
        onSave={(next) => {
          setSystemSettings(next);
          saveSystemSettings(next);
          applyTheme(next.theme);
          addLog(`System settings saved: theme=${next.theme}`, "success");
          setSettingsOpen(false);
        }}
      />
    </div>
  );
};

export default App;
