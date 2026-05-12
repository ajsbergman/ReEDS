import { useEffect, useState, useRef } from "react";
import {
  setupCheckAllAPI,
  setupFixAPI,
  type SetupStep,
} from "../lib/api";

/* ── helpers ──────────────────────────────────────────────────────────────── */

function stepIcon(status: string) {
  switch (status) {
    case "pass": return "✅";
    case "fail": return "❌";
    case "running": return "⏳";
    case "skip": return "⏭️";
    default: return "⬜";
  }
}

/* ── component ────────────────────────────────────────────────────────────── */

export default function SetupWizard() {
  const [steps, setSteps] = useState<SetupStep[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeStep, setActiveStep] = useState<string | null>(null);
  const [fixing, setFixing] = useState<string | null>(null);
  const [fixMsg, setFixMsg] = useState("");
  const [recheckSpinning, setRecheckSpinning] = useState(false);

  // GAMS license input
  const [licenseText, setLicenseText] = useState("");
  const [licenseSaving, setLicenseSaving] = useState(false);

  // Auto-poll when something is running
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function refresh() {
    setLoading(true);
    setError("");
    setRecheckSpinning(true);
    setupCheckAllAPI()
      .then((s) => {
        setSteps(s);
        // Auto-expand first failing step
        if (!activeStep) {
          const firstFail = s.find((x) => x.status === "fail");
          if (firstFail) setActiveStep(firstFail.id);
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        setLoading(false);
        setTimeout(() => setRecheckSpinning(false), 600);
      });
  }

  useEffect(() => { refresh(); }, []);

  // Poll while any step is "running"
  useEffect(() => {
    const hasRunning = steps.some((s) => s.status === "running");
    if (hasRunning && !pollRef.current) {
      pollRef.current = setInterval(refresh, 5000);
    } else if (!hasRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [steps]);

  async function handleFix(step: SetupStep) {
    if (step.id === "gams_license") return;
    setFixing(step.id);
    setFixMsg("");
    try {
      const res = await setupFixAPI(step.id);
      setFixMsg(res.detail);
      setTimeout(refresh, 2000);
    } catch (e: any) {
      setFixMsg(e.message || "Fix failed");
    } finally {
      setFixing(null);
    }
  }

  async function handleSaveLicense() {
    if (!licenseText.trim()) return;
    setLicenseSaving(true);
    try {
      await setupFixAPI("gams_license", "reeds2", licenseText);
      setLicenseText("");
      refresh();
    } catch {
      // ignore
    } finally {
      setLicenseSaving(false);
    }
  }

  const passCount = steps.filter((s) => s.status === "pass").length;
  const allPass = steps.length > 0 && passCount === steps.length;
  const failCount = steps.filter((s) => s.status === "fail").length;

  return (
    <div className="setup-wizard">
      {/* ── Header ── */}
      <div className="setup-header">
        <h2>🧰 Setup Wizard</h2>
        <p className="setup-subtitle">
          Let's get your computer ready to run ReEDS. We'll check each
          requirement and help you fix anything that's missing.
        </p>

        {/* Progress bar */}
        {steps.length > 0 && (
          <div className="setup-progress">
            <div className="setup-progress-bar">
              <div
                className="setup-progress-fill"
                style={{ width: `${(passCount / steps.length) * 100}%` }}
              />
            </div>
            <span className="setup-progress-label">
              {passCount} / {steps.length} ready
            </span>
          </div>
        )}

        {/* Status banner */}
        {allPass && (
          <div className="setup-all-pass">
            🎉 <strong>All set!</strong> Your environment is ready to run ReEDS.
            Head to <strong>Run ReEDS</strong> to launch your first model run.
          </div>
        )}
        {!allPass && failCount > 0 && (
          <div className="setup-action-needed">
            ⚠️ <strong>{failCount} {failCount === 1 ? "step needs" : "steps need"} attention.</strong>{" "}
            Follow the steps below from top to bottom.
          </div>
        )}

        {/* Re-check All button */}
        <button
          className={`setup-recheck-all ${recheckSpinning ? "spinning" : ""}`}
          onClick={refresh}
          disabled={loading && steps.length === 0}
        >
          <span className="setup-recheck-all-icon">↻</span>
          Re-check All
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {loading && steps.length === 0 && (
        <div className="setup-loading">
          <span className="setup-loading-spinner">⟳</span>
          Checking your environment…
        </div>
      )}

      {/* ── Steps ── */}
      <div className="setup-steps">
        {steps.map((step) => {
          const expanded = activeStep === step.id;
          const isRunning = step.status === "running";
          const isFail = step.status === "fail";

          return (
            <div
              key={step.id}
              className={`setup-step ${step.status} ${expanded ? "expanded" : ""}`}
            >
              {/* Step header */}
              <div
                className="setup-step-header"
                onClick={() => setActiveStep(expanded ? null : step.id)}
              >
                <div className="setup-step-left">
                  <span className="setup-step-icon">{stepIcon(step.status)}</span>
                  <div className="setup-step-info">
                    <span className="setup-step-number">Step {step.order}</span>
                    <span className="setup-step-title">{step.title}</span>
                  </div>
                </div>
                <div className="setup-step-right">
                  {step.status === "pass" && (
                    <span className="setup-badge pass">Ready</span>
                  )}
                  {step.status === "fail" && (
                    <span className="setup-badge fail">Action needed</span>
                  )}
                  {step.status === "running" && (
                    <span className="setup-badge running">Working…</span>
                  )}
                  <span className="setup-chevron">{expanded ? "▾" : "▸"}</span>
                </div>
              </div>

              {/* Step body */}
              {expanded && (
                <div className="setup-step-body">
                  <p className="setup-step-desc">{step.description}</p>

                  {/* Status detail */}
                  <div className={`setup-detail ${step.status}`}>
                    {step.detail}
                  </div>

                  {/* Fix message */}
                  {fixMsg && fixing === null && activeStep === step.id && (
                    <div className="setup-fix-msg">{fixMsg}</div>
                  )}

                  {/* Guide steps */}
                  {(isFail || isRunning) && step.guide_steps && step.guide_steps.length > 0 && (
                    <div className="setup-guide">
                      <strong>📋 How to fix:</strong>
                      <ol>
                        {step.guide_steps.map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ol>
                    </div>
                  )}

                  {/* Guide URL */}
                  {isFail && step.guide_url && (
                    <a
                      href={step.guide_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="setup-link"
                    >
                      📥 Open download page →
                    </a>
                  )}

                  {/* GAMS license paste box */}
                  {step.id === "gams_license" && isFail && (
                    <div className="setup-license-box">
                      <label className="setup-license-label">Paste your GAMS license:</label>
                      <textarea
                        value={licenseText}
                        onChange={(e) => setLicenseText(e.target.value)}
                        placeholder={"12345678\nYour Name\nOrganization\ndc xxxxx xx-xxxxxx\n..."}
                        rows={6}
                      />
                      <button
                        className="setup-fix-btn"
                        onClick={handleSaveLicense}
                        disabled={licenseSaving || !licenseText.trim()}
                      >
                        {licenseSaving ? "Saving…" : "💾 Save License"}
                      </button>
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="setup-actions">
                    {isFail && step.auto_fixable && step.id !== "gams_license" && (
                      <button
                        className="setup-fix-btn"
                        onClick={() => handleFix(step)}
                        disabled={fixing === step.id}
                      >
                        {fixing === step.id ? "⏳ Working…" : "🔧 Fix it automatically"}
                      </button>
                    )}
                    <button className="setup-recheck-btn" onClick={refresh}>
                      ↻ Re-check
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Tips ── */}
      {!allPass && steps.length > 0 && (
        <div className="setup-tips">
          <strong>💡 Tips for beginners:</strong>
          <ul>
            <li>Work through the steps <strong>from top to bottom</strong> — later steps depend on earlier ones</li>
            <li>After installing something, click <strong>Re-check All</strong> at the top to verify</li>
            <li>Steps with a <strong>"Fix it automatically"</strong> button can be done with one click</li>
            <li>Most installs require you to <strong>open a new terminal</strong> for PATH changes to take effect</li>
            <li>Stuck? Switch to the <strong>Chat</strong> tab and ask the AI assistant for help!</li>
          </ul>
        </div>
      )}
    </div>
  );
}
