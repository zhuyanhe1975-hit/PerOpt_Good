import React, { useMemo, useState } from "react";

export type ThemeMode = "dark" | "light";

export type SystemSettings = {
  theme: ThemeMode;
  modelLibraryPath: string;
  paramsStorePath: string;
};

const DEFAULT_SETTINGS: SystemSettings = {
  theme: "dark",
  modelLibraryPath: "/home/yhzhu/LoongEnv/PerfOpt_v0/models",
  paramsStorePath: "/home/yhzhu/LoongEnv/PerfOpt_v0/artifacts",
};

export function getDefaultSystemSettings(): SystemSettings {
  return { ...DEFAULT_SETTINGS };
}

export function loadSystemSettings(): SystemSettings {
  try {
    const raw = localStorage.getItem("loongenv_system_settings_v1");
    if (!raw) return getDefaultSystemSettings();
    const parsed = JSON.parse(raw);
    const s = { ...getDefaultSystemSettings(), ...parsed } as SystemSettings;
    if (s.theme !== "dark" && s.theme !== "light") s.theme = "dark";
    return s;
  } catch {
    return getDefaultSystemSettings();
  }
}

export function saveSystemSettings(s: SystemSettings) {
  localStorage.setItem("loongenv_system_settings_v1", JSON.stringify(s));
}

export function applyTheme(theme: ThemeMode) {
  document.documentElement.dataset.theme = theme;
}

export default function SystemSettingsModal(props: {
  open: boolean;
  initial: SystemSettings;
  onClose: () => void;
  onSave: (next: SystemSettings) => void;
}) {
  const { open, initial, onClose, onSave } = props;
  const [draft, setDraft] = useState<SystemSettings>(initial);

  React.useEffect(() => {
    if (open) setDraft(initial);
  }, [open, initial]);

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(initial), [draft, initial]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-[720px] max-w-[92vw] rounded-xl panel overflow-hidden">
        <div className="panel-header px-5 py-4 flex items-center justify-between">
          <div className="flex flex-col">
            <div className="text-base font-bold">系统配置</div>
            <div className="text-[12px] muted">外观、模型库与参数存储等全局设置</div>
          </div>
          <button
            onClick={onClose}
            className="w-9 h-9 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] hover:bg-[var(--panel)] transition-colors"
            title="关闭"
          >
            <i className="fa-solid fa-xmark" />
          </button>
        </div>

        <div className="p-5 grid grid-cols-2 gap-4">
          <section className="rounded-lg panel-subtle p-4 space-y-3">
            <div className="flex items-center gap-2">
              <i className="fa-solid fa-palette muted" />
              <div className="font-bold">外观风格</div>
            </div>
            <div className="text-[12px] muted leading-relaxed">
              切换浅色/深色主题。主题会影响背景、面板、边框与文本对比度。
            </div>

            <div className="flex gap-2 pt-1">
              <button
                onClick={() => setDraft((d) => ({ ...d, theme: "dark" }))}
                className={`flex-1 py-2 rounded-lg border text-sm font-bold transition-colors ${
                  draft.theme === "dark"
                    ? "border-emerald-500/50 bg-emerald-500/10 text-[var(--accent)]"
                    : "border-[var(--border)] bg-[var(--panel)]"
                }`}
              >
                深色
              </button>
              <button
                onClick={() => setDraft((d) => ({ ...d, theme: "light" }))}
                className={`flex-1 py-2 rounded-lg border text-sm font-bold transition-colors ${
                  draft.theme === "light"
                    ? "border-emerald-500/50 bg-emerald-500/10 text-[var(--accent)]"
                    : "border-[var(--border)] bg-[var(--panel)]"
                }`}
              >
                浅色
              </button>
            </div>
          </section>

          <section className="rounded-lg panel-subtle p-4 space-y-3">
            <div className="flex items-center gap-2">
              <i className="fa-solid fa-database muted" />
              <div className="font-bold">资源路径</div>
            </div>
            <div className="text-[12px] muted leading-relaxed">
              用于团队约定的默认路径。当前版本仅用于 UI 展示与后续对接预留。
            </div>

            <label className="space-y-1">
              <div className="text-[12px] font-bold">模型库目录</div>
              <input
                value={draft.modelLibraryPath}
                onChange={(e) => setDraft((d) => ({ ...d, modelLibraryPath: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--panel)] text-sm mono"
                placeholder="/path/to/models"
              />
            </label>

            <label className="space-y-1">
              <div className="text-[12px] font-bold">参数/日志存储目录</div>
              <input
                value={draft.paramsStorePath}
                onChange={(e) => setDraft((d) => ({ ...d, paramsStorePath: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--panel)] text-sm mono"
                placeholder="/path/to/artifacts"
              />
            </label>
          </section>
        </div>

        <div className="px-5 py-4 border-t border-[var(--border)] flex items-center justify-between bg-[var(--panel)]">
          <button
            onClick={() => setDraft(getDefaultSystemSettings())}
            className="text-sm font-bold muted hover:text-[var(--text)] transition-colors"
          >
            恢复默认
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] text-sm font-bold"
            >
              取消
            </button>
            <button
              onClick={() => onSave(draft)}
              disabled={!dirty}
              className="px-4 py-2 rounded-lg bg-[var(--accent)] text-black font-bold text-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              保存
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

