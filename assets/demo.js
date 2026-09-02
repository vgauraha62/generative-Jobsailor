(() => {
  const DEMO = true;
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  const MOCK = {
    status: {
      budget: { day: today, calls_used: 7, daily_limit: 19, timezone: "Asia/Kolkata", reset_at: today + "T00:00:00+05:30", next_reset_at: today + "T00:00:00+05:30", last_call_at: now.toISOString() },
      curation_budget: { day: today, calls_used: 12, daily_limit: 50, threshold: 0.5, timezone: "Asia/Kolkata", reset_at: today + "T00:00:00+05:30", next_reset_at: today + "T00:00:00+05:30", last_call_at: now.toISOString() },
      rag_budget: { day: today, calls_used: 4, daily_limit: 50, timezone: "Asia/Kolkata", reset_at: today + "T00:00:00+05:30", next_reset_at: today + "T00:00:00+05:30", last_call_at: now.toISOString() },
      budgets: {
        gemini: { day: today, calls_used: 7, daily_limit: 19, timezone: "Asia/Kolkata", reset_at: today + "T00:00:00+05:30", next_reset_at: today + "T00:00:00+05:30", last_call_at: now.toISOString() },
        curation: { day: today, calls_used: 12, daily_limit: 50, timezone: "Asia/Kolkata", reset_at: today + "T00:00:00+05:30", next_reset_at: today + "T00:00:00+05:30", last_call_at: now.toISOString() },
        rag: { day: today, calls_used: 4, daily_limit: 50, timezone: "Asia/Kolkata", reset_at: today + "T00:00:00+05:30", next_reset_at: today + "T00:00:00+05:30", last_call_at: now.toISOString() }
      },
      timezone: { name: "Asia/Kolkata", locked: true, locked_at: today + "T00:00:00+05:30" },
      curation_trace: { changed_total: 3, uploaded_total: 2, runs_with_curation: 2, day: today },
      upload_screenshots: [],
      all_screenshots_total: 3,
      active_resume: { sha: "a1b2c3d", active_pdf: "resumes/curated/demo.pdf" },
      rolling_5: [
        { run_id: "20260829_153446", by_status: { applied: 2, skipped: 8, failed: 1, review: 1 }, summary: { by_status: { applied: 2, skipped: 8, failed: 1, review: 1 }, by_job_type: { python: { applied: 1, failed: 1 }, "ai-ml": { applied: 1 } }, by_upload_status: { uploaded: 2, skipped: 1 }, curation_score_histogram: { "0.0-0.2": 1, "0.2-0.4": 2, "0.4-0.6": 3, "0.6-0.8": 4, "0.8-1.0": 2 }, applied_rate_curated: 0.42, applied_rate_kept: 0.18, applied_rate_delta_curated_vs_kept: 0.24, curation_performed: 5, curation_skipped_high_score: 3, avg_curation_score: 0.61 } },
        { run_id: "20260828_203103", by_status: { applied: 1, skipped: 5, failed: 2 }, summary: { by_status: { applied: 1, skipped: 5, failed: 2 }, by_job_type: { python: { applied: 1, failed: 1 } }, by_upload_status: { uploaded: 1 }, curation_score_histogram: { "0.0-0.2": 0, "0.2-0.4": 1, "0.4-0.6": 2, "0.6-0.8": 3, "0.8-1.0": 2 }, applied_rate_curated: 0.35, applied_rate_kept: 0.15, applied_rate_delta_curated_vs_kept: 0.2, curation_performed: 3, avg_curation_score: 0.58 } }
      ],
      ledger: { total_urls: 142, by_status: { applied: 12, skipped: 98, failed: 18, review: 14 } },
      profile_sentinels: [],
      dry_run_default: true,
      run_state: { running: false, live: false },
      gemini_health: { ok: true, last_checked: now.toISOString(), error: null },
      is_admin: false,
      needs_credentials: false,
      admin_users: []
    },
    config: { search: { slugs: ["python-jobs", "ai-ml-jobs", "data-scientist-jobs"], per_type_jobs: 20, max_jobs_global: 50, max_pages_per_type: 5, max_run_types: 3 }, browser: { profile_path: "", binary: "" }, apply: { dry_run: true }, gemini: { model: "gemini-2.5-flash", daily_call_limit: 19 }, resume_curation: { match_threshold: 0.5, gemini_daily_limit: 50 }, rag: { daily_call_limit: 50 } },
    timezone: { timezone: "Asia/Kolkata", locked: true, locked_at: today + "T00:00:00+05:30" },
    reports: [
      { run_id: "20260829_153446", kind: "visit", filename: "visit_20260829_153446.json", modified_at: Date.now() / 1000 - 3600 },
      { run_id: "20260829_153446", kind: "capture", filename: "capture_20260829_153446.json", modified_at: Date.now() / 1000 - 3700 },
      { run_id: "20260828_203103", kind: "visit", filename: "visit_20260828_203103.json", modified_at: Date.now() / 1000 - 86400 },
      { run_id: "20260828_203103", kind: "capture", filename: "capture_20260828_203103.json", modified_at: Date.now() / 1000 - 86500 }
    ],
    screenshots: { items: [], total: 0, pages: 1, page: 0, limit: 3 },
    credentials: { config: { search: { slugs: ["python-jobs", "ai-ml-jobs"] }, browser: { profile_path: "/home/demo/Profiles/naukrijobs" }, gemini: { model: "gemini-2.5-flash" } }, profile: { resume_facts: { name: "Demo User", email: "demo@example.com", phone: "9876543210", highest_qualification: "MTech AI and ML", institution: "Demo University", total_experience_years: "3", relevant_experience_years: "2", current_location: "Bengaluru", skills: "Python, ML, Docker" }, user_preferences: { current_ctc_lpa: "12", expected_ctc_lpa: "18", notice_period_days: "30", willing_to_relocate: true, work_authorization: "Indian citizen", passport_valid: true } } },
    ragStats: { chunks: 42, qa_cached: 18 },
    visitReports: {
      "20260829_153446": { run_id: "20260829_153446", started_at: today + "T09:00:00", summary: { by_status: { applied: 2, skipped: 8, failed: 1 }, by_job_type: { python: { applied: 1, failed: 1 } }, curation_performed: 5, curation_skipped_high_score: 3, avg_curation_score: 0.61, applied_rate_curated: 0.42, applied_rate_kept: 0.18, applied_rate_delta_curated_vs_kept: 0.24, by_upload_status: { uploaded: 2 }, curation_score_histogram: { "0.0-0.2": 1, "0.2-0.4": 2, "0.4-0.6": 3, "0.6-0.8": 4, "0.8-1.0": 2 } }, results: [{ url: "https://www.naukri.com/job-listings-demo-python-engineer-bengaluru-1-to-3-years-123", job_type: "python", status: "applied", curation_score: 0.82, curation_performed: true, upload_status: "uploaded", reason: "chat_widget" }, { url: "https://www.naukri.com/job-listings-demo-ai-engineer-bengaluru-2-to-5-years-456", job_type: "ai-ml", status: "skipped", curation_score: 0.31, curation_performed: false, upload_status: "skipped", reason: "already_applied" }, { url: "https://www.naukri.com/job-listings-demo-data-scientist-bengaluru-3-to-6-years-789", job_type: "python", status: "failed", curation_score: 0.64, curation_performed: true, upload_status: "uploaded", reason: "no form fields" }], gemini_calls_total: 6 },
      "20260828_203103": { run_id: "20260828_203103", started_at: "2026-08-28T10:00:00", summary: { by_status: { applied: 1, skipped: 5, failed: 2 }, by_job_type: { python: { applied: 1 } }, curation_performed: 3, avg_curation_score: 0.58, applied_rate_curated: 0.35, applied_rate_kept: 0.15, applied_rate_delta_curated_vs_kept: 0.2, by_upload_status: { uploaded: 1 }, curation_score_histogram: { "0.0-0.2": 0, "0.2-0.4": 1, "0.4-0.6": 2, "0.6-0.8": 3, "0.8-1.0": 2 } }, results: [{ url: "https://www.naukri.com/job-listings-demo-backend-bengaluru-2-to-4-years-999", job_type: "python", status: "applied", curation_score: 0.77, curation_performed: true, upload_status: "uploaded", reason: "chat_widget" }], gemini_calls_total: 4 }
    },
    captureReports: {
      "20260829_153446": { run_id: "20260829_153446", started_at: today + "T09:00:00", job_types: { "python-jobs": { pages_scraped: 2, pages_stopped_reason: "job_limit", total_links_captured: 24, net_new_actionable_urls: 14 }, "ai-ml-jobs": { pages_scraped: 1, pages_stopped_reason: "no_more_pages", total_links_captured: 12, net_new_actionable_urls: 8 } }, totals: { total_links: 36, net_new: 22 } },
      "20260828_203103": { run_id: "20260828_203103", started_at: "2026-08-28T10:00:00", job_types: { "python-jobs": { pages_scraped: 3, pages_stopped_reason: "job_limit", total_links_captured: 32, net_new_actionable_urls: 18 } }, totals: { total_links: 32, net_new: 18 } }
    }
  };

  const demoResponses = {
    ragQuery: (body) => {
      const q = (body.query || "").toLowerCase();
      if (q.includes("skill")) return { answer: "**Core Skills:** Python, FastAPI, Selenium, Gemini AI, RAG (Hybrid Dense+BM25), Docker, PostgreSQL. Tools: Firefox/Geckodriver, Chart.js.", chunks: [{ content: "Python, FastAPI, Selenium WebDriver for Naukri automation. Gemini 2.5 Flash for Q&A. Hybrid RAG with dense embeddings.", title: "Resume — Skills", category: "skills" }], route: "SINGLE_DOC", domain: "resume", verified: true, cached: "L2", latency_ms: 4 };
      if (q.includes("ctc") || q.includes("notice") || q.includes("location")) return { answer: "Current CTC: **12 LPA**, Expected: **18 LPA**, Notice: **30 days**, Location: **Bengaluru**, Relocate: **Yes**.", chunks: [{ content: "Current CTC 12 LPA, Expected 18 LPA, 30 days notice period, Bengaluru base, willing to relocate.", title: "Preferences", category: "preferences" }], route: "SINGLE_DOC", domain: "resume", verified: true, cached: "direct", latency_ms: 2 };
      if (q.includes("fail") || q.includes("application")) return { answer: "Recent audit: **2 applied, 8 skipped (already_applied/visited), 1 failed (no form fields)**. Avg curation score **0.61**. Curated rate **0.42** vs kept **0.18**.", chunks: [{ content: "Visit summary: 2 applied, 8 skipped, 1 failed. Curated 5 at 0.61 avg.", title: "Visit Report 20260829_153446", category: "reports" }], route: "SINGLE_DOC", domain: "reports", verified: true, cached: "L2", latency_ms: 3 };
      return { answer: `Demo RAG response to: **${body.query}**\n\nThis is a static GitHub Pages demo — no Gemini API calls. In production this uses hybrid Dense+BM25 retrieval with L1/L2 caching (${MOCK.ragStats.chunks} chunks indexed).`, chunks: [{ content: "Demo chunk — replace with indexed resume facts in production.", title: "Demo Source", category: "demo" }], route: "SINGLE_DOC", domain: "resume", verified: true, cached: "L1", latency_ms: 1 };
    }
  };

  const origFetch = window.fetch.bind(window);
  window.fetch = async (url, opts = {}) => {
    const u = typeof url === "string" ? url : url.url;
    const method = (opts.method || "GET").toUpperCase();
    const isApi = u.includes("/api/");
    if (!isApi) return origFetch(url, opts);
    const path = u.split("?")[0];
    const jsonOk = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

    if (path.endsWith("/api/status") && method === "GET") return jsonOk(MOCK.status);
    if (path.endsWith("/api/config") && method === "GET") return jsonOk(MOCK.config);
    if (path.endsWith("/api/timezone") && method === "GET") return jsonOk(MOCK.timezone);
    if (path.endsWith("/api/reports") && method === "GET") return jsonOk({ reports: MOCK.reports });
    if (path.includes("/api/reports/") && method === "GET") {
      const parts = path.split("/api/reports/")[1].split("/");
      const kind = parts[0], runId = parts[1];
      const data = kind === "capture" ? MOCK.captureReports[runId] : kind === "visit" ? MOCK.visitReports[runId] : null;
      if (data) return jsonOk(data);
      return jsonOk({ detail: "report not found" }, 404);
    }
    if (path.includes("/api/screenshots") && method === "GET") {
      if (path.includes("/file/")) return jsonOk({ detail: "No screenshots in demo" }, 404);
      return jsonOk(MOCK.screenshots);
    }
    if (path.endsWith("/api/credentials") && method === "GET") return jsonOk(MOCK.credentials);
    if (path.endsWith("/api/rag/stats") && method === "GET") return jsonOk(MOCK.ragStats);
    if (path.endsWith("/api/profile") && method === "GET") return jsonOk({ profile: MOCK.credentials.profile, sentinels: [] });
    if (path.endsWith("/api/budget/raw") && method === "GET") return jsonOk({ gemini: MOCK.status.budget, curation: MOCK.status.curation_budget, rag: MOCK.status.rag_budget, limits: { gemini: 19, curation: 50, rag: 50 } });

    if (method === "POST") {
      if (path.endsWith("/api/rag/query")) {
        let body = {}; try { body = JSON.parse(opts.body || "{}"); } catch {}
        return jsonOk(demoResponses.ragQuery(body));
      }
      if (path.endsWith("/api/run")) return jsonOk({ detail: "Demo mode — runs disabled on GitHub Pages. Clone locally and run apply_jobs.py." }, 403);
      if (path.endsWith("/api/run/stop")) return jsonOk({ detail: "No run to stop in demo" }, 400);
      if (path.endsWith("/api/credentials")) return jsonOk({ detail: "Demo — credentials not saved (static site). Configure locally via .env + candidate_profile.json." }, 403);
      if (path.endsWith("/api/credentials/resume")) return jsonOk({ detail: "Demo — resume upload disabled. Run locally." }, 403);
      if (path.includes("/api/timezone")) return jsonOk({ detail: "Demo — timezone locked to Asia/Kolkata." }, 403);
      if (path.endsWith("/api/signup") || path.endsWith("/api/delete") || path.endsWith("/api/export") || path.endsWith("/api/rag/reindex") || path.includes("/api/curation")) {
        return jsonOk({ detail: "Demo mode — this action is disabled on the static preview." }, 403);
      }
    }
    return jsonOk({ detail: "Demo — endpoint not available on GitHub Pages" }, 404);
  };

  window.DEMO_BANNER_HTML = `<div class="alert success" role="alert" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px"><span>📄 Demo — static preview on GitHub Pages. Runs, uploads & Gemini calls are disabled.</span><a href="https://github.com/GoliathReaper/JobSailor" target="_blank" rel="noopener" class="btn" style="margin-left:auto">View Source ↗</a></div>`;

  document.addEventListener("DOMContentLoaded", () => {
    const firstMain = document.querySelector("main");
    if (firstMain && !document.getElementById("demo-banner")) {
      const b = document.createElement("div");
      b.id = "demo-banner";
      b.innerHTML = window.DEMO_BANNER_HTML;
      const h1 = firstMain.querySelector("h1");
      if (h1) h1.insertAdjacentElement("afterend", b);
      else firstMain.prepend(b);
    }
    document.querySelectorAll('form[action="/logout"]').forEach(f => {
      f.addEventListener("submit", e => { e.preventDefault(); location.href = "login.html"; });
    });
  });
})();
