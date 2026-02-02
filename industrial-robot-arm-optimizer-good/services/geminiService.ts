
import { GoogleGenAI, Type } from "@google/genai";
import { RobotParams, Weights, OptimizationResult, StrategicInsight } from "../types";

export const getStrategicInsight = async (
  currentParams: RobotParams,
  weights: Weights,
  currentMetrics: OptimizationResult,
  history: OptimizationResult[]
): Promise<StrategicInsight | null> => {
  const ai = new GoogleGenAI({ apiKey: process.env.API_KEY });
  
  const prompt = `
    你现在是工业机器人控制系统的“首席架构师”。底层 Optuna 优化器正在负责具体的增益搜索。
    你需要从更高维度分析当前的优化任务。

    【任务上下文】
    - 控制架构: ID (动力学前馈) + PD 反馈
    - 当前权重(目标优先级): ${JSON.stringify(weights)}
    - 最新物理指标 (MuJoCo 1ms): ${JSON.stringify(currentMetrics)}
    - 历史趋势长度: ${history.length} 次迭代

    【你的职责】
    1. 分析目标合理性。
    2. 约束建议。
    3. 策略转向：如果进度停滞，是否应该建议修改权重？
    4. 参数微调。

    返回格式必须包含: analysis, feasibilityScore, constraintSuggestions, parameterStrategy, suggestedParams, suggestedWeights。
    语言：中文。
  `;

  try {
    const response = await ai.models.generateContent({
      model: "gemini-3-pro-preview",
      contents: prompt,
      config: {
        responseMimeType: "application/json",
        responseSchema: {
          type: Type.OBJECT,
          properties: {
            analysis: { type: Type.STRING },
            feasibilityScore: { type: Type.NUMBER },
            constraintSuggestions: { type: Type.ARRAY, items: { type: Type.STRING } },
            parameterStrategy: { type: Type.STRING },
            suggestedParams: {
              type: Type.OBJECT,
              properties: Object.keys(currentParams).reduce((acc: any, key) => {
                acc[key] = {
                  type: Type.OBJECT,
                  properties: {
                    kp: { type: Type.NUMBER },
                    kd: { type: Type.NUMBER }
                  },
                  required: ["kp", "kd"]
                };
                return acc;
              }, {})
            },
            suggestedWeights: {
              type: Type.OBJECT,
              properties: {
                energy: { type: Type.NUMBER },
                precision: { type: Type.NUMBER },
                vibration: { type: Type.NUMBER },
                cycleTime: { type: Type.NUMBER }
              }
            }
          },
          required: ["analysis", "feasibilityScore", "constraintSuggestions", "parameterStrategy", "suggestedParams"]
        }
      }
    });

    return JSON.parse(response.text);
  } catch (error: any) {
    // Mute console error for quota issues
    console.debug("Gemini Strategic Layer paused:", error.message || "Quota limit reached");
    
    return {
      analysis: "由于 AI 架构师配额限制（Quota Exceeded），战略建议功能已进入静默模式。系统将继续使用本地 Optuna TPE 算法进行参数搜索，这不会影响控制性能。",
      feasibilityScore: 0,
      constraintSuggestions: ["等待 API 配额窗口恢复...", "当前环境：本地优化模式"],
      parameterStrategy: "OFFLINE: 继续本地 TPE 采样搜索。",
      suggestedParams: currentParams
    };
  }
};
