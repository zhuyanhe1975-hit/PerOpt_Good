import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import net from "node:net";
import { spawn } from "node:child_process";

const DEFAULT_URL = process.env.PERFOPT_URL || "http://127.0.0.1:8080";
const DEFAULT_BACKEND_PY =
  process.env.PERFOPT_BACKEND ||
  path.resolve(process.cwd(), "../PerfOpt_v0/scripts/perfopt_http_backend.py");
const DEFAULT_CONDA_ENV = process.env.PERFOPT_CONDA_ENV || "mjwarp_env";

function parseArgs(argv) {
  const args = {
    url: DEFAULT_URL,
    startBackend: false,
    keepBackend: false,
    backendPy: DEFAULT_BACKEND_PY,
    condaEnv: DEFAULT_CONDA_ENV,
    host: "127.0.0.1",
    port: null,
    resume: true,
    studyName: null,
    runs: 3,
    jobs: 8,
    rounds: 3,
    trialsPerRound: 24,
    duration: 5.0,
    pollMs: 800,
    timeoutS: 600,
    out: "artifacts/optimize_smoke_loop.log",
    backendStdout: "artifacts/backend.stdout.log",
  };

  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    const v = argv[i + 1];
    if (!a.startsWith("--")) continue;
    if (v === undefined) throw new Error(`Missing value for ${a}`);
    i++;
    if (a === "--url") args.url = v;
    else if (a === "--start-backend") args.startBackend = v === "1" || v === "true" || v === "yes";
    else if (a === "--keep-backend") args.keepBackend = v === "1" || v === "true" || v === "yes";
    else if (a === "--backend-py") args.backendPy = v;
    else if (a === "--conda-env") args.condaEnv = v;
    else if (a === "--host") args.host = v;
    else if (a === "--port") args.port = Number(v);
    else if (a === "--resume") args.resume = v === "1" || v === "true" || v === "yes";
    else if (a === "--study-name") args.studyName = v;
    else if (a === "--runs") args.runs = Number(v);
    else if (a === "--jobs") args.jobs = Number(v);
    else if (a === "--rounds") args.rounds = Number(v);
    else if (a === "--trials") args.trialsPerRound = Number(v);
    else if (a === "--duration") args.duration = Number(v);
    else if (a === "--poll-ms") args.pollMs = Number(v);
    else if (a === "--timeout-s") args.timeoutS = Number(v);
    else if (a === "--out") args.out = v;
    else throw new Error(`Unknown arg: ${a}`);
  }

  if (!Number.isFinite(args.runs) || args.runs < 1) throw new Error("--runs must be >= 1");
  if (!Number.isFinite(args.jobs) || args.jobs < 1) throw new Error("--jobs must be >= 1");
  if (!Number.isFinite(args.rounds) || args.rounds < 1) throw new Error("--rounds must be >= 1");
  if (!Number.isFinite(args.trialsPerRound) || args.trialsPerRound < 1) throw new Error("--trials must be >= 1");
  if (!Number.isFinite(args.duration) || args.duration <= 0) throw new Error("--duration must be > 0");
  if (!Number.isFinite(args.pollMs) || args.pollMs < 200) throw new Error("--poll-ms must be >= 200");
  if (!Number.isFinite(args.timeoutS) || args.timeoutS < 5) throw new Error("--timeout-s must be >= 5");
  if (args.port !== null && (!Number.isFinite(args.port) || args.port <= 0 || args.port >= 65536)) {
    throw new Error("--port must be 1..65535");
  }
  return args;
}

async function httpJson(url, init) {
  let resp;
  try {
    resp = await fetch(url, init);
  } catch (e) {
    const msg = e?.cause?.code
      ? `${e.cause.code}`
      : e?.message
        ? e.message
        : String(e);
    throw new Error(
      `fetch failed (${msg}) url=${url}. Is the backend running? Try: curl ${new URL("/health", url).toString()}`
    );
  }
  let body;
  try {
    body = await resp.json();
  } catch {
    body = null;
  }
  if (!resp.ok) {
    const msg = body?.error || body?.message || `HTTP_${resp.status}`;
    throw new Error(msg);
  }
  return body;
}

function ensureDir(filePath) {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });
}

function nowIso() {
  return new Date().toISOString();
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function ceilToMultiple(n, k) {
  if (k <= 0) return n;
  return Math.ceil(n / k) * k;
}

async function isPortFree(host, port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once("error", () => resolve(false));
    srv.once("listening", () => srv.close(() => resolve(true)));
    srv.listen(port, host);
  });
}

async function pickFreePort(host) {
  for (let i = 0; i < 25; i++) {
    const candidate = 39000 + Math.floor(Math.random() * 2000);
    if (await isPortFree(host, candidate)) return candidate;
  }
  for (let p = 39000; p < 41000; p++) {
    if (await isPortFree(host, p)) return p;
  }
  throw new Error("No free port found in 39000-40999");
}

function startBackend({ backendPy, condaEnv, host, port, stdoutPath }) {
  ensureDir(stdoutPath);
  const out = fs.createWriteStream(stdoutPath, { flags: "a" });
  out.write(`\n==== backend start ${nowIso()} host=${host} port=${port} ====\n`);

  const child = spawn("conda", ["run", "-n", condaEnv, "python", backendPy], {
    env: { ...process.env, PERFOPT_HOST: host, PERFOPT_PORT: String(port) },
    stdio: ["ignore", "pipe", "pipe"],
    detached: true,
  });
  child.stdout?.pipe(out);
  child.stderr?.pipe(out);

  const stop = () => {
    try {
      process.kill(-child.pid, "SIGTERM");
    } catch {}
    setTimeout(() => {
      try {
        process.kill(-child.pid, "SIGKILL");
      } catch {}
    }, 2000);
  };

  return { child, stop, stdoutPath };
}

async function main() {
  const args = parseArgs(process.argv);
  ensureDir(args.out);

  const logStream = fs.createWriteStream(args.out, { flags: "a" });
  const log = (obj) => {
    logStream.write(JSON.stringify({ ts: nowIso(), ...obj }) + "\n");
  };

  console.log(`PerfOpt backend smoke loop`);
  console.log(`- url: ${args.url}`);
  console.log(`- runs: ${args.runs}`);
  console.log(`- jobs: ${args.jobs}`);
  console.log(`- rounds: ${args.rounds}`);
  console.log(`- trials/round: ${args.trialsPerRound}`);
  console.log(`- duration: ${args.duration}s`);
  console.log(`- out: ${args.out}`);
  console.log(`- start-backend: ${args.startBackend ? "yes" : "no"}`);

  let backendProc = null;
  let url = args.url;
  let studyName = args.studyName || "er15_default";

  if (args.startBackend) {
    const host = args.host || "127.0.0.1";
    const port = args.port ?? (await pickFreePort(host));
    if (!(await isPortFree(host, port))) throw new Error(`Port not free: ${host}:${port}`);
    url = `http://${host}:${port}`;

    console.log(`- backend-py: ${args.backendPy}`);
    console.log(`- conda-env: ${args.condaEnv}`);
    console.log(`- backend-url: ${url}`);
    console.log(`- backend-stdout: ${args.backendStdout}`);

    // Avoid colliding with an existing long-running manual backend using the same sqlite storage.
    // This keeps smoke tests isolated even if another server is optimizing 'er15_default' in parallel.
    if (!args.studyName) {
      studyName = `smoke_${port}_${Date.now().toString(36)}`;
    }
    console.log(`- study-name: ${studyName}`);

    backendProc = startBackend({
      backendPy: args.backendPy,
      condaEnv: args.condaEnv,
      host,
      port,
      stdoutPath: args.backendStdout,
    });

    const cleanup = () => {
      if (backendProc && !args.keepBackend) backendProc.stop();
    };
    process.on("SIGINT", () => {
      cleanup();
      process.exit(130);
    });
    process.on("SIGTERM", () => {
      cleanup();
      process.exit(143);
    });
    process.on("exit", cleanup);
  }

  // Give the backend a moment to come up (esp. conda cold start).
  let health = null;
  const healthUrl = `${url}/health`;
  for (let i = 0; i < 120; i++) {
    try {
      health = await httpJson(healthUrl, { method: "GET" });
      break;
    } catch (e) {
      if (backendProc?.child && backendProc.child.exitCode !== null) {
        throw new Error(`Backend exited early (code=${backendProc.child.exitCode}). Check ${backendProc.stdoutPath}`);
      }
      if (i === 119) throw e;
      await sleep(250);
    }
  }
  if (!health?.ok) throw new Error(`Backend health not ok: ${JSON.stringify(health)}`);
  log({ type: "health", url, health });

  const trialsPerRound = ceilToMultiple(args.trialsPerRound, args.jobs);
  const trialsTotal = trialsPerRound * args.rounds;

  const basePayload = {
    weights: { energy: 20, precision: 40, vibration: 25, cycleTime: 15 },
    config: {
      engine: "MuJoCo",
      timestep: 0.001,
      integrator: "RK4",
      duration: args.duration,
      torqueLimit: [1000.0, 1000.0, 1000.0, 100.0, 100.0, 100.0],
      velLimits: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
      torque_limit: [1000.0, 1000.0, 1000.0, 100.0, 100.0, 100.0],
      vel_limits: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
    },
    kp_range: [2000.0, 10000.0],
    kd_range: [0.1, 500.0],
    jobs: args.jobs,
    trials: trialsTotal,
    traj: "cosine_pos",
    resume: args.resume,
    study_name: studyName,
  };

  for (let runIdx = 1; runIdx <= args.runs; runIdx++) {
    console.log(`\nRun ${runIdx}/${args.runs} start...`);
    log({ type: "run.start", run: runIdx, payload: basePayload });

    const start = await httpJson(`${url}/optimize/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(basePayload),
    });
    if (!start?.ok || !start?.job_id) throw new Error(`start failed: ${JSON.stringify(start)}`);
    const jobId = start.job_id;
    console.log(`- job_id: ${jobId} (trials=${trialsTotal}, jobs=${args.jobs})`);
    log({ type: "run.job", run: runIdx, job_id: jobId, trialsTotal, trialsPerRound });

    const t0 = Date.now();
    let lastTrialLogged = null;
    let lastProgress = null;
    let lastState = "UNKNOWN";

    while (true) {
      if ((Date.now() - t0) / 1000 > args.timeoutS) {
        console.log(`- timeout (${args.timeoutS}s). sending stop...`);
        log({ type: "run.timeout", run: runIdx, job_id: jobId });
        await httpJson(`${url}/optimize/stop`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: jobId }),
        });
        break;
      }

      const st = await httpJson(`${url}/optimize/status?job_id=${encodeURIComponent(jobId)}`, { method: "GET" });
      const job = st?.job;
      const snap = job?.snapshot || {};
      const state = String(job?.state || "UNKNOWN");
      lastState = state;
      const progress = snap?.progress || null;
      const best = snap?.best || null;
      const recent = Array.isArray(snap?.recent_trials) ? snap.recent_trials : [];

      if (progress && typeof progress.done === "number" && typeof progress.total === "number") {
        const p = `${progress.done}/${progress.total}`;
        if (p !== lastProgress) {
          lastProgress = p;
          process.stdout.write(`\r- state=${state} progress=${p}   `);
        }
      }

      if (recent.length) {
        const last = recent[recent.length - 1];
        const trial = last?.trial ?? null;
        if (trial !== null && trial !== lastTrialLogged) {
          lastTrialLogged = trial;
          log({ type: "trial", run: runIdx, job_id: jobId, trial, metrics: last.metrics, params: last.params, backend: last.backend, elapsed_s: last.elapsed_s });
        }
      }

      if (best?.trial !== undefined) {
        log({ type: "best", run: runIdx, job_id: jobId, best });
      }

      if (state === "FINISHED" || state === "STOPPED" || state === "ERROR") {
        const prog = progress && typeof progress.done === "number" && typeof progress.total === "number" ? `${progress.done}/${progress.total}` : "n/a";
        process.stdout.write("\n");
        console.log(`- final: job_id=${jobId} state=${state} progress=${prog}`);
        if (state === "ERROR") console.log(`- ERROR: ${job?.error || "unknown"}`);
        log({ type: "run.end", run: runIdx, job_id: jobId, state, error: job?.error || null, best });
        break;
      }

      await sleep(args.pollMs);
    }

    // Defensive: if we exited the loop without a terminal state (shouldn't happen), show it.
    if (lastState !== "FINISHED" && lastState !== "STOPPED" && lastState !== "ERROR") {
      console.log(`- note: run exited without terminal state (state=${lastState})`);
    }
  }

  log({ type: "smoke.done", runs: args.runs });
  logStream.end();
  console.log(`\nDone. Log appended to ${args.out}`);
  if (backendProc && !args.keepBackend) {
    console.log(`Stopping backend...`);
    backendProc.stop();
  } else if (backendProc && args.keepBackend) {
    console.log(`Backend left running (keep-backend=yes).`);
  }
}

main().catch((err) => {
  console.error(`\nSMOKE FAILED: ${err?.message || String(err)}`);
  process.exit(1);
});
