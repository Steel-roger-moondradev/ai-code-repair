import { FormEvent, useEffect, useMemo, useState } from "react";

type Status =
  | "queued"
  | "running"
  | "patch_ready"
  | "testing"
  | "needs_human_review"
  | "approved"
  | "pr_created"
  | "failed"
  | "rejected";

type Workflow = {
  workflow_id: string;
  request_id?: string;
  status: Status;
  issue?: { owner: string; repo: string; issue_number: number; title: string; body: string; html_url: string };
  analysis?: {
    summary: string;
    problem_type: string;
    expected_behavior: string;
    acceptance_criteria: string[];
    constraints: string[];
    confidence: number;
  };
  relevant_files?: { path: string; start_line: number; end_line: number; content: string }[];
  proposal?: {
    summary: string;
    assumptions: string[];
    risks: string[];
    changes: { path: string; operation: string; rationale: string; original_content: string; updated_content: string }[];
  };
  validation?: { valid: boolean; errors: string[]; validated_paths: string[]; patch_hash?: string };
  diff?: { diff_text: string; changed_files: string[]; additions: number; deletions: number; patch_hash: string };
  sandbox_result?: { status: string; exit_code?: number; test_summary?: string; stdout?: string; stderr?: string };
  review?: { verdict: string; summary: string; correctness_concerns: string[]; security_concerns: string[] };
  errors: string[];
};

const stages = [
  ["analysis", "Issue analysis"],
  ["evidence", "Evidence map"],
  ["proposal", "Patch proposal"],
  ["sandbox", "Sandbox run"],
  ["review", "Review gate"],
  ["publish", "Pull request"]
];

const statusLabels: Record<Status, string> = {
  queued: "Queued", running: "In flight", patch_ready: "Patch ready", testing: "Testing",
  needs_human_review: "Awaiting approval", approved: "Approved", pr_created: "PR created",
  failed: "Failed", rejected: "Rejected"
};

function Icon({ name }: { name: "spark" | "arrow" | "check" | "lock" | "external" | "pulse" }) {
  const paths = {
    spark: <><path d="m12 2 1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8L12 2Z" /><path d="m19 16 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z" /></>,
    arrow: <><path d="M5 12h13" /><path d="m13 6 6 6-6 6" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    lock: <><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>,
    external: <><path d="M14 5h5v5" /><path d="m19 5-8 8" /><path d="M18 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></>,
    pulse: <path d="M3 12h4l2-7 4 14 2-7h6" />
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "The API returned an unexpected response.");
  return body as T;
}

function App() {
  const [issueUrl, setIssueUrl] = useState("https://github.com/Steel-roger-moondradev/patchpilot-demo-target/issues/1");
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"overview" | "diff" | "evidence">("overview");
  const [toast, setToast] = useState("");

  useEffect(() => {
    if (!workflow || ["pr_created", "failed", "rejected", "patch_ready"].includes(workflow.status)) return;
    const timer = window.setInterval(async () => {
      try { setWorkflow(await api<Workflow>(`/api/v1/workflows/${workflow.workflow_id}`)); } catch { /* keep current state */ }
    }, 2200);
    return () => window.clearInterval(timer);
  }, [workflow]);

  const completedStages = useMemo(() => {
    if (!workflow) return 0;
    if (workflow.status === "pr_created") return 6;
    if (workflow.review) return 5;
    if (workflow.sandbox_result) return 4;
    if (workflow.proposal) return 3;
    if (workflow.relevant_files?.length) return 2;
    if (workflow.analysis) return 1;
    return 0;
  }, [workflow]);

  async function startWorkflow(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setWorkflow(null);
    try {
      const result = await api<Workflow>("/api/v1/workflows", {
        method: "POST",
        body: JSON.stringify({ issue_url: issueUrl, idempotency_key: `console-${Date.now()}` })
      });
      setWorkflow(result);
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to start workflow."); }
    finally { setBusy(false); }
  }

  async function approve() {
    if (!workflow?.validation?.patch_hash) return;
    setBusy(true); setError("");
    try {
      const result = await api<{ branch: string; number: number; url: string }>(`/api/v1/workflows/${workflow.workflow_id}/approve`, {
        method: "POST",
        body: JSON.stringify({ workflow_id: workflow.workflow_id, expected_patch_hash: workflow.validation.patch_hash })
      });
      setWorkflow({ ...workflow, status: "pr_created" });
      setToast(`Pull request #${result.number} created`);
      window.setTimeout(() => setToast(""), 5000);
      window.open(result.url, "_blank", "noopener,noreferrer");
    } catch (err) { setError(err instanceof Error ? err.message : "Approval failed."); }
    finally { setBusy(false); }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/"><span className="brand-mark"><Icon name="spark" /></span><span>patch<span>pilot</span></span></a>
        <div className="topbar-right"><span className="live-dot" /> <span>ENGINE ONLINE</span><span className="divider" /><span className="version">MVP / 16</span></div>
      </header>
      <main className="main">
        <section className="hero">
          <div className="eyebrow"><span className="eyebrow-line" /> AUTONOMOUS PATCH OPERATIONS</div>
          <h1>From issue to <em>ship-ready</em><br />in one controlled flight.</h1>
          <p className="hero-copy">PatchPilot turns a GitHub issue into a tested, reviewable pull request—without touching your default branch.</p>
        </section>

        <section className="launch-grid">
          <div className="launch-card">
            <div className="card-kicker"><span className="kicker-number">01</span> LAUNCH A WORKFLOW</div>
            <form onSubmit={startWorkflow}>
              <label htmlFor="issue-url">GitHub issue URL</label>
              <div className="input-row">
                <span className="input-prefix">github.com /</span>
                <input id="issue-url" value={issueUrl} onChange={(e) => setIssueUrl(e.target.value)} placeholder="owner/repository/issues/123" required />
                <button className="launch-button" disabled={busy} type="submit">{busy ? "Processing" : "Analyze issue"} <Icon name="arrow" /></button>
              </div>
            </form>
            <div className="launch-note"><Icon name="lock" /> Runs in an isolated Docker sandbox <span>·</span> Human approval required before publish</div>
          </div>
          <div className="signal-card">
            <div className="signal-top"><span className="signal-label">SYSTEM SIGNAL</span><span className="signal-live">● LIVE</span></div>
            <div className="signal-chart"><div className="chart-grid" /><svg viewBox="0 0 340 100" preserveAspectRatio="none"><path d="M0 76 C20 76 18 54 37 60 S60 84 77 55 S100 68 116 49 S139 38 155 51 S176 22 194 38 S215 65 231 48 S254 40 270 45 S290 20 307 30 S325 24 340 10" /></svg></div>
            <div className="signal-bottom"><span>PIPELINE INTEGRITY</span><strong>99.8%</strong></div>
          </div>
        </section>

        {error && <div className="error-banner"><strong>Workflow paused</strong><span>{error}</span></div>}

        {workflow ? <WorkflowView workflow={workflow} completedStages={completedStages} activeTab={activeTab} setActiveTab={setActiveTab} approve={approve} busy={busy} /> : (
          <section className="empty-state"><div className="empty-orbit"><Icon name="spark" /></div><h2>Your next safe change starts here.</h2><p>Paste an issue above to map the repository, generate a minimal patch, and watch the evidence accumulate.</p></section>
        )}
      </main>
      {toast && <div className="toast"><span className="toast-check"><Icon name="check" /></span>{toast}</div>}
      <footer><span>PATCHPILOT</span><span>SAFE BY DEFAULT / EVIDENCE FIRST</span><span>© 2026</span></footer>
    </div>
  );
}

function WorkflowView({ workflow, completedStages, activeTab, setActiveTab, approve, busy }: { workflow: Workflow; completedStages: number; activeTab: string; setActiveTab: (tab: "overview" | "diff" | "evidence") => void; approve: () => void; busy: boolean }) {
  const ready = workflow.status === "patch_ready" && workflow.review?.verdict === "approved";
  return <section className="workflow-area">
    <div className="workflow-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> ACTIVE FLIGHT</div><h2>{workflow.issue?.title || "Workflow in progress"}</h2><a href={workflow.issue?.html_url} target="_blank" rel="noreferrer">{workflow.issue?.owner}/{workflow.issue?.repo} <Icon name="external" /></a></div><StatusPill status={workflow.status} /></div>
    <div className="stage-rail">{stages.map(([key, label], index) => <div className={`stage ${index < completedStages ? "done" : index === completedStages ? "current" : ""}`} key={key}><div className="stage-marker">{index < completedStages ? <Icon name="check" /> : <span>0{index + 1}</span>}</div><span>{label}</span>{index < stages.length - 1 && <div className="stage-connector" />}</div>)}</div>
    <div className="tabs"><button className={activeTab === "overview" ? "active" : ""} onClick={() => setActiveTab("overview")}>Flight overview</button><button className={activeTab === "diff" ? "active" : ""} onClick={() => setActiveTab("diff")}>Patch preview {workflow.diff && <b>{workflow.diff.additions + workflow.diff.deletions}</b>}</button><button className={activeTab === "evidence" ? "active" : ""} onClick={() => setActiveTab("evidence")}>Evidence log</button></div>
    {activeTab === "overview" && <Overview workflow={workflow} />}
    {activeTab === "diff" && <DiffView workflow={workflow} />}
    {activeTab === "evidence" && <EvidenceView workflow={workflow} />}
    {ready && <div className="approval-bar"><div><div className="approval-icon"><Icon name="lock" /></div><div><strong>Ready for human approval</strong><p>All checks passed. Review the patch before publishing to GitHub.</p></div></div><button className="approve-button" onClick={approve} disabled={busy}>{busy ? "Publishing..." : "Approve & create PR"} <Icon name="arrow" /></button></div>}
  </section>;
}

function StatusPill({ status }: { status: Status }) { return <span className={`status-pill ${status}`}><span />{statusLabels[status]}</span>; }

function Overview({ workflow }: { workflow: Workflow }) {
  return <div className="overview-grid"><article className="panel analysis-panel"><PanelTitle label="ANALYSIS" index="01" /><h3>{workflow.analysis?.summary || "Reading the issue..."}</h3><p>{workflow.analysis?.expected_behavior || "PatchPilot is gathering context from the issue and repository."}</p>{workflow.analysis && <div className="criteria"><strong>ACCEPTANCE CRITERIA</strong>{workflow.analysis.acceptance_criteria.map((item) => <div key={item}><Icon name="check" />{item}</div>)}</div>}</article><article className="panel metrics-panel"><PanelTitle label="RUN METRICS" index="02" /><div className="metrics"><Metric value={workflow.validation?.valid ? "PASS" : "—"} label="VALIDATION" tone="green" /><Metric value={workflow.sandbox_result?.status === "passed" ? "PASS" : "—"} label="SANDBOX" tone="green" /><Metric value={workflow.review?.verdict === "approved" ? "PASS" : "—"} label="REVIEW GATE" tone="green" /></div><div className="repo-line"><span className="repo-avatar">GH</span><span>{workflow.issue?.owner}/{workflow.issue?.repo}</span><span className="repo-branch">main</span></div></article><article className="panel files-panel"><PanelTitle label="FILES IN SCOPE" index="03" /><div className="file-list">{(workflow.relevant_files || []).map((file) => <div className="file-row" key={file.path}><span className="file-icon">PY</span><code>{file.path}</code><span className="file-lines">L{file.start_line}–{file.end_line}</span></div>)}</div></article></div>;
}

function PanelTitle({ label, index }: { label: string; index: string }) { return <div className="panel-title"><span>{index}</span>{label}<i /></div>; }
function Metric({ value, label, tone }: { value: string; label: string; tone: string }) { return <div className="metric"><strong className={tone}>{value}</strong><span>{label}</span></div>; }
function DiffView({ workflow }: { workflow: Workflow }) { return <div className="panel diff-panel"><PanelTitle label="PROPOSED PATCH" index="01" /><div className="diff-meta"><span>{workflow.diff?.changed_files?.[0] || workflow.proposal?.changes?.[0]?.path || "Waiting for patch..."}</span><span className="add">+{workflow.diff?.additions || 0}</span><span className="remove">−{workflow.diff?.deletions || 0}</span></div><pre className="diff-code">{(workflow.diff?.diff_text || "Patch preview will appear once the proposal is ready.").split("\n").map((line, i) => <span className={line.startsWith("+") ? "line-add" : line.startsWith("-") ? "line-remove" : ""} key={`${line}-${i}`}>{line || " "}</span>)}</pre></div>; }
function EvidenceView({ workflow }: { workflow: Workflow }) { return <div className="evidence-grid"><article className="panel"><PanelTitle label="SANDBOX RESULT" index="01" /><div className="evidence-status"><span className={workflow.sandbox_result?.status === "passed" ? "pass-dot" : ""} />{workflow.sandbox_result?.status || "Pending"}</div><pre>{workflow.sandbox_result?.test_summary || "Awaiting isolated test execution."}</pre></article><article className="panel"><PanelTitle label="REVIEWER NOTES" index="02" /><p className="review-copy">{workflow.review?.summary || "The reviewer will summarize correctness, security, and maintainability evidence here."}</p>{workflow.validation?.patch_hash && <div className="hash"><span>PATCH HASH</span><code>{workflow.validation.patch_hash}</code></div>}</article></div>; }

export default App;
