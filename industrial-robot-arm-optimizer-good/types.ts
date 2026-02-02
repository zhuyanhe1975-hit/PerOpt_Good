
export interface JointInfo {
  name: string;
  type: string;
  lower: number;
  upper: number;
  value: number;
}

export interface ControlGains {
  kp: number;
  kd: number;
}

export interface RobotParams {
  [jointName: string]: ControlGains;
}

export interface SimulationConfig {
  engine: 'MuJoCo';
  timestep: number; // 0.001
  integrator: 'RK4' | 'Euler';
  duration: number; // 仿真总时长
  ffMode?: 'no' | 'ref' | 'meas' | 'ideal';
  torqueLimit?: number[]; // N·m, per joint
  velLimits?: number[]; // rad/s, per joint
}

export interface Weights {
  energy: number;
  precision: number;
  vibration: number;
  cycleTime: number;
}

export interface OptimizationResult {
  energy: number;
  precision: number;
  vibration: number;
  cycleTime: number;
  timestamp: string;
  optimizedParams?: RobotParams;
  // Optional detailed TCP error stats (meters)
  tcpErrorMax?: number;
  tcpErrorMean?: number;
  computationTime?: number;
  backend?: string;
  elapsed_s?: number;
  config?: unknown;
  solverStatus?: string;
  trialCount?: number; // Optuna 运行的尝试次数
}

export interface LogEntry {
  id: string;
  time: string;
  type: 'info' | 'success' | 'warning' | 'error';
  message: string;
}

export interface BackendStatus {
  connected: boolean;
  url: string;
  version?: string;
}

export interface UrdfModel {
  name: string;
  content: string;
  joints: JointInfo[];
}

export interface AssetMap {
  [filename: string]: string;
}

export interface StrategicInsight {
  analysis: string;
  feasibilityScore: number; // 目标合理性评分 (0-100)
  constraintSuggestions: string[];
  parameterStrategy: string;
  suggestedParams: RobotParams;
  suggestedWeights?: Weights;
}
