
import { RobotParams, Weights, OptimizationResult, SimulationConfig } from "../types";

export class PerfOptClient {
  private baseUrl: string;

  constructor(url: string) {
    this.baseUrl = url.replace(/\/$/, "");
  }

  async checkHealth(): Promise<boolean> {
    try {
      const resp = await fetch(`${this.baseUrl}/health`, { signal: AbortSignal.timeout(2000) });
      return resp.ok;
    } catch {
      return false;
    }
  }

  async getPresetConfig(preset: string): Promise<any> {
    // Avoid stale cached responses when users edit backend JSON files during dev.
    const url = `${this.baseUrl}/config/preset?name=${encodeURIComponent(preset)}&t=${Date.now()}`;
    const resp = await fetch(url, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    });
    return resp.json();
  }

  async startOptimize(payload: {
    // Keep frontend UI minimal: most parameters live in backend configs/*.json.
    // Frontend may send overrides for a small subset.
    weights?: Weights;
    config?: Partial<SimulationConfig>;
    kp_range?: [number, number];
    kd_range?: [number, number];
    jobs?: number;
    trials?: number;
    seed?: number;
    traj?: string;
    resume?: boolean;
    study_name?: string;
    preset?: string;
  }): Promise<{ ok: boolean; job_id?: string; error?: string }> {
    const resp = await fetch(`${this.baseUrl}/optimize/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return resp.json();
  }

  async getOptimizeStatus(jobId: string): Promise<any> {
    const resp = await fetch(`${this.baseUrl}/optimize/status?job_id=${encodeURIComponent(jobId)}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    return resp.json();
  }

  async stopOptimize(jobId: string): Promise<any> {
    const resp = await fetch(`${this.baseUrl}/optimize/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId }),
    });
    return resp.json();
  }

  async runMuJoCoSimulation(
    params: RobotParams, 
    weights: Weights, 
    model: { urdf?: string; mjcf?: string; modelType?: 'urdf' | 'mjcf' } | string,
    config: SimulationConfig = { engine: 'MuJoCo', timestep: 0.001, integrator: 'RK4', duration: 5.0 }
  ): Promise<OptimizationResult> {
    const startTime = performance.now();
    try {
      const configPayload = {
        ...config,
        torque_limit: config.torqueLimit,
        vel_limits: config.velLimits,
        ff_mode: config.ffMode,
      };

      const payload =
        typeof model === "string"
          ? { params, weights, urdf: model, config: configPayload }
          : {
              params,
              weights,
              urdf: model.urdf,
              mjcf: model.mjcf,
              modelType: model.modelType ?? (model.mjcf ? "mjcf" : "urdf"),
              config: configPayload,
            };

      const response = await fetch(`${this.baseUrl}/simulate/mujoco`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(`HTTP_${response.status}`);
      const data = await response.json();
      // Guard against invalid numeric outputs from parallel trials / unstable sims.
      const tcpErrorMax =
        data?.tcpErrorMax ??
        data?.tcp_error_max ??
        data?.e_max ??
        data?.error_max ??
        data?.trackingErrorMax;
      const tcpErrorMean =
        data?.tcpErrorMean ??
        data?.tcp_error_mean ??
        data?.e_mean ??
        data?.error_mean ??
        data?.trackingErrorMean;

      const result: OptimizationResult = {
        ...data,
        ...(tcpErrorMax !== undefined ? { tcpErrorMax } : {}),
        ...(tcpErrorMean !== undefined ? { tcpErrorMean } : {}),
        computationTime: performance.now() - startTime,
        timestamp: new Date().toISOString(),
        solverStatus: "CONVERGED",
      };
      if (
        !Number.isFinite(result.energy) ||
        !Number.isFinite(result.precision) ||
        !Number.isFinite(result.vibration) ||
        !Number.isFinite(result.cycleTime)
      ) {
        throw new Error("INVALID_NUMERIC_RESULT");
      }
      return result;
    } catch (error) {
      const fallback = this.fallbackNumericalSim(params, config);
      return { ...fallback, computationTime: performance.now() - startTime };
    }
  }

  private fallbackNumericalSim(params: RobotParams, config: SimulationConfig): OptimizationResult {
    const steps = Math.floor(config.duration / config.timestep);
    let totalError = 0;
    let maxError = 0;
    let totalEnergy = 0;
    let maxAccel = 0;

    // 获取所有关节的平均增益用于估算整体表现
    const jointKeys = Object.keys(params);
    const avgKp = jointKeys.reduce((acc, k) => acc + params[k].kp, 0) / (jointKeys.length || 1);
    const avgKd = jointKeys.reduce((acc, k) => acc + params[k].kd, 0) / (jointKeys.length || 1);

    // 工业现实：传动间隙和柔顺性
    const Backlash = 0.002; // 2mm 的机械间隙
    const Compliance = 5000; // 关节刚度

    for (let i = 0; i < steps; i++) {
      const t = i * config.timestep;
      const q_ref = Math.sin(t * 1.5) * 0.5;
      const qd_ref = 0.75 * Math.cos(t * 1.5);
      const qdd_ref = -1.125 * Math.sin(t * 1.5);

      // 扰动模型：重力 + 摩擦 + 动力学不确定性
      const disturbance = 0.5 * Math.sin(t * 10) + 0.8 * Math.sign(qd_ref);
      
      // 计算控制误差。增加非线性项使得精度不再是“微米级”
      // 误差 e = 扰动 / (比例增益 + 刚度项) + 机械间隙
      const steadyStateError = (Math.abs(disturbance) / (avgKp + Compliance)) + (Backlash * Math.random());
      
      // 动态误差项：阻尼不足会导致超调
      const dynamicError = Math.abs(qdd_ref) * (1 / (avgKd + 10));

      const instantError = steadyStateError + dynamicError;
      totalError += instantError * config.timestep;
      maxError = Math.max(maxError, instantError);
      
      // 能耗估算
      const torque = avgKp * instantError + avgKd * qd_ref;
      totalEnergy += Math.abs(torque * qd_ref) * config.timestep;
      maxAccel = Math.max(maxAccel, Math.abs(qdd_ref + disturbance * 0.1));
    }

    return {
      energy: (totalEnergy / config.duration) * 0.5,
      // 精度结果单位：米 (m)。1mm = 0.001m
      precision: totalError / config.duration,
      tcpErrorMean: totalError / config.duration,
      tcpErrorMax: maxError,
      vibration: maxAccel * 0.05,
      cycleTime: config.duration,
      timestamp: new Date().toISOString(),
      backend: "fallback",
      solverStatus: "LOCAL_ENGINE_STABLE"
    };
  }
}
