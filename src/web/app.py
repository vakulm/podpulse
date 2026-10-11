"""PodPulse Shareable Web UI Dashboard, Episode Archive, Prediction Leaderboard & Subscriptions.

Security Hardening (per mandatory-secure-web-skills):
- All untrusted database and user values are strictly HTML-escaped (`html.escape`) prior to rendering to prevent XSS.
- All database queries use parameterized SQLite placeholders (`?`) to prevent SQL injection.
- Input payloads are validated via strict Pydantic schemas.
- Local test server binds strictly to `127.0.0.1` (never `0.0.0.0`).
"""

import asyncio
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import sqlite3
from typing import Any, List, Optional
from urllib.parse import parse_qs, urlparse
from config import DATABASE_PATH
from src.agents.orchestrator import PodPulseCoordinator
from src.tools.memory_tools import (
    LedgerQueryInput,
    SubscriberInput,
    add_newsletter_subscriber,
    initialize_memory_database,
    query_prediction_ledger,
)

try:
    from fastapi import FastAPI, Form, HTTPException
    from fastapi.responses import HTMLResponse

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


# =====================================================================
# 1. DATABASE ARCHIVE HELPERS (Parameterized SQL)
# =====================================================================


def fetch_archived_episodes(db_path: str = DATABASE_PATH) -> List[dict]:
    """Retrieves all analyzed podcast episodes from the persistent SQLite archive."""
    initialize_memory_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM episodes ORDER BY created_at DESC LIMIT 20")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_single_episode(
    episode_id: str, db_path: str = DATABASE_PATH
) -> Optional[dict]:
    """Retrieves a single episode briefing by ID using parameterized SQL."""
    initialize_memory_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM episodes WHERE episode_id = ?", (episode_id.strip(),)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def fetch_subscriber_count(db_path: str = DATABASE_PATH) -> int:
    """Returns count of active email newsletter subscribers."""
    initialize_memory_database(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM subscribers WHERE active = 1")
    count = cursor.fetchone()[0]
    conn.close()
    return int(count)


# =====================================================================
# 2. SECURE HTML RENDERER (Strict Output Encoding via html.escape)
# =====================================================================


def render_dashboard_html(
    episodes: List[dict],
    predictions: List[dict],
    subscriber_count: int,
    banner_message: Optional[str] = None,
) -> str:
    """Renders the PodPulse web interface with strict HTML escaping on all dynamic fields."""
    banner_html = ""
    if banner_message:
        safe_msg = html.escape(banner_message)
        banner_html = f"""
        <div class="bg-emerald-900/60 border border-emerald-500 text-emerald-100 px-4 py-3 rounded-lg mb-6">
            <strong>Notice:</strong> {safe_msg}
        </div>
        """

    episodes_html_parts: List[str] = []
    for ep in episodes:
        ep_id = html.escape(str(ep.get("episode_id", "")))
        title = html.escape(str(ep.get("title", "")))
        created = html.escape(str(ep.get("created_at", ""))[:19].replace("T", " "))
        brief = html.escape(str(ep.get("formatted_brief", "")))
        episodes_html_parts.append(f"""
        <div class="bg-slate-800 border border-slate-700 rounded-xl p-6 mb-6 shadow-lg">
            <div class="flex justify-between items-center mb-4">
                <div>
                    <h3 class="text-xl font-bold text-white">{title}</h3>
                    <span class="text-xs text-slate-400">Analyzed: {created} UTC</span>
                </div>
                <a href="/episodes/{ep_id}" class="text-sm bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded-md font-medium">
                    Shareable Link &rarr;
                </a>
            </div>
            <pre class="bg-slate-950 text-slate-200 p-4 rounded-lg text-xs overflow-x-auto font-mono leading-relaxed border border-slate-800">{brief}</pre>
        </div>
        """)

    episodes_section = (
        "\n".join(episodes_html_parts)
        if episodes_html_parts
        else '<p class="text-slate-400">No episodes analyzed yet. Run an analysis above!</p>'
    )

    pred_rows: List[str] = []
    for p in predictions:
        speaker = html.escape(str(p.get("speaker_name", "")))
        text = html.escape(str(p.get("prediction_text", "")))
        horizon = html.escape(str(p.get("target_horizon", "")))
        ep_id = html.escape(str(p.get("episode_id", "")))
        status = html.escape(str(p.get("status", "PENDING")))
        badge_color = (
            "bg-emerald-600/30 text-emerald-300 border-emerald-500"
            if "TRUE" in status
            else "bg-amber-600/30 text-amber-300 border-amber-500"
        )
        pred_rows.append(f"""
        <tr class="border-b border-slate-800">
            <td class="py-3 px-4 font-semibold text-white">{speaker}</td>
            <td class="py-3 px-4 text-slate-300">{text}</td>
            <td class="py-3 px-4 text-slate-400 text-sm">{horizon}</td>
            <td class="py-3 px-4 text-slate-400 text-sm">{ep_id}</td>
            <td class="py-3 px-4">
                <span class="text-xs px-2.5 py-1 rounded-full border {badge_color}">{status}</span>
            </td>
        </tr>
        """)

    predictions_table = "\n".join(pred_rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PodPulse — Podcast Intelligence & Fact-Checking Engine</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen font-sans">
    <div class="max-w-6xl mx-auto px-6 py-8">
        <!-- Header -->
        <header class="border-b border-slate-800 pb-6 mb-8 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
            <div>
                <div class="flex items-center gap-3">
                    <span class="bg-blue-600 text-white text-xs font-bold px-2.5 py-1 rounded uppercase tracking-wider">ADK Multi-Agent</span>
                    <span class="bg-purple-600/30 border border-purple-500 text-purple-300 text-xs px-2.5 py-1 rounded">Model Armor Active</span>
                    <span class="bg-emerald-600/30 border border-emerald-500 text-emerald-300 text-xs px-2.5 py-1 rounded">{subscriber_count} Active Subscribers</span>
                </div>
                <h1 class="text-3xl font-extrabold text-white mt-2"><a href="/">PodPulse Intelligence Engine</a></h1>
                <p class="text-slate-400 text-sm mt-1">1-Page Podcast Briefs, Google Search Fact-Checking, and Host Prediction Accountability</p>
            </div>
        </header>

        {banner_html}

        <!-- Top Grid: Run Episode + Subscribe -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-10">
            <!-- On-Demand Episode Analyzer -->
            <div class="bg-slate-800/80 border border-slate-700 rounded-xl p-6">
                <h2 class="text-lg font-bold text-white mb-2">1. Analyze Podcast Episode</h2>
                <p class="text-xs text-slate-400 mb-4">Runs the 5-agent ADK pipeline (Flash ingestion + Pro Search fact-checking).</p>
                <form action="/analyze" method="post" class="space-y-3">
                    <div>
                        <label class="block text-xs text-slate-300 mb-1">YouTube Podcast URL or Sample Key</label>
                        <input type="text" name="video_url" value="sample://all-in-ep-200" required
                            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                    </div>
                    <div>
                        <label class="block text-xs text-slate-300 mb-1">Tailor "So What" For Role</label>
                        <input type="text" name="user_role" value="Enterprise AI & Cloud Leader" required
                            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                    </div>
                    <div>
                        <label class="block text-xs text-slate-300 mb-1">Optional: Dispatch Approved Brief to Email</label>
                        <input type="email" name="recipient_email" placeholder="you@company.com"
                            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                    </div>
                    <button type="submit" class="w-full bg-blue-600 hover:bg-blue-500 text-white font-semibold py-2 px-4 rounded-lg text-sm transition">
                        Run 5-Agent Intelligence Pipeline
                    </button>
                </form>
            </div>

            <!-- Newsletter Subscription Box -->
            <div class="bg-slate-800/80 border border-slate-700 rounded-xl p-6">
                <h2 class="text-lg font-bold text-white mb-2">2. Subscribe to Standardized Email Briefs</h2>
                <p class="text-xs text-slate-400 mb-4">Get the 1-page plain-text summary and fact-check scorecard delivered automatically.</p>
                <form action="/subscribe" method="post" class="space-y-3">
                    <div>
                        <label class="block text-xs text-slate-300 mb-1">Your Email Address</label>
                        <input type="email" name="email" placeholder="colleague@google.com" required
                            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                    </div>
                    <div>
                        <label class="block text-xs text-slate-300 mb-1">Your Focus / Role Profile</label>
                        <select name="focus_area" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                            <option value="Enterprise AI & Cloud Leader">Enterprise AI & Cloud Leader</option>
                            <option value="Tech & Macro Investor">Tech & Macro Investor</option>
                            <option value="B2B SaaS Founder / Executive">B2B SaaS Founder / Executive</option>
                        </select>
                    </div>
                    <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-semibold py-2 px-4 rounded-lg text-sm transition mt-4">
                        Subscribe to PodPulse Briefings
                    </button>
                </form>
            </div>
        </div>

        <!-- Prediction & Accountability Ledger -->
        <section class="mb-10">
            <h2 class="text-2xl font-bold text-white mb-4">Host Prediction & Accountability Ledger</h2>
            <div class="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden shadow-lg">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="bg-slate-950 border-b border-slate-700 text-xs uppercase text-slate-400">
                            <th class="py-3 px-4">Speaker</th>
                            <th class="py-3 px-4">Prediction / Forecast</th>
                            <th class="py-3 px-4">Target Horizon</th>
                            <th class="py-3 px-4">Episode</th>
                            <th class="py-3 px-4">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {predictions_table}
                    </tbody>
                </table>
            </div>
        </section>

        <!-- Past Episode Summaries Archive -->
        <section>
            <h2 class="text-2xl font-bold text-white mb-4">Archived Episode Briefings (Shareable)</h2>
            {episodes_section}
        </section>
    </div>
</body>
</html>"""


# =====================================================================
# 3. FASTAPI WEB & API ROUTES (Cloud Run Production Entrypoint)
# =====================================================================

if FASTAPI_AVAILABLE:
    app = FastAPI(
        title="PodPulse Intelligence & Fact-Checking Engine",
        description="Multi-Agent Podcast Summarizer, Grounded Fact-Checker, and Accountability Ledger",
        version="1.0.0",
    )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_home() -> Any:
        episodes = fetch_archived_episodes()
        ledger = query_prediction_ledger(LedgerQueryInput(limit=15))
        preds = [p.model_dump() for p in ledger.predictions]
        sub_count = fetch_subscriber_count()
        return HTMLResponse(
            content=render_dashboard_html(episodes, preds, sub_count)
        )

    @app.get("/episodes/{episode_id}", response_class=HTMLResponse)
    async def view_shareable_episode(episode_id: str) -> Any:
        ep = fetch_single_episode(episode_id)
        if not ep:
            raise HTTPException(
                status_code=404, detail="Episode briefing not found."
            )
        ledger = query_prediction_ledger(LedgerQueryInput(limit=10))
        preds = [p.model_dump() for p in ledger.predictions]
        sub_count = fetch_subscriber_count()
        return HTMLResponse(
            content=render_dashboard_html(
                [ep],
                preds,
                sub_count,
                banner_message=f"Viewing shareable permalink for episode '{episode_id}'.",
            )
        )

    @app.post("/subscribe", response_class=HTMLResponse)
    async def handle_web_subscription(
        email: str = Form(...),
        focus_area: str = Form("Enterprise AI & Cloud Leader"),
    ) -> Any:
        res = add_newsletter_subscriber(
            SubscriberInput(email=email, focus_area=focus_area)
        )
        episodes = fetch_archived_episodes()
        ledger = query_prediction_ledger(LedgerQueryInput(limit=15))
        preds = [p.model_dump() for p in ledger.predictions]
        sub_count = fetch_subscriber_count()
        msg = res.message if res.success else f"Error: {res.error_message}"
        return HTMLResponse(
            content=render_dashboard_html(
                episodes, preds, sub_count, banner_message=msg
            )
        )

    @app.post("/analyze", response_class=HTMLResponse)
    async def handle_web_analyze(
        video_url: str = Form(...),
        user_role: str = Form("Enterprise AI & Cloud Leader"),
        recipient_email: Optional[str] = Form(None),
    ) -> Any:
        coordinator = PodPulseCoordinator()
        clean_email = recipient_email.strip() if recipient_email else None
        result = await coordinator.run_episode_pipeline(
            video_url=video_url,
            user_role=user_role,
            recipient_email=clean_email,
            approval_callback=(lambda _brief: True) if clean_email else None,
        )
        episodes = fetch_archived_episodes()
        ledger = query_prediction_ledger(LedgerQueryInput(limit=15))
        preds = [p.model_dump() for p in ledger.predictions]
        sub_count = fetch_subscriber_count()
        msg = (
            f"Successfully analyzed '{result.episode_id}'!"
            if result.success
            else f"Pipeline blocked/failed: {result.error_message}"
        )
        return HTMLResponse(
            content=render_dashboard_html(
                episodes, preds, sub_count, banner_message=msg
            )
        )

    @app.get("/api/health")
    async def health_check() -> dict:
        return {"status": "healthy", "service": "podpulse-intelligence-agent"}


# =====================================================================
# 4. BUILT-IN LOCAL HTTP SERVER (Binds strictly to 127.0.0.1)
# =====================================================================


class LocalDashboardHandler(BaseHTTPRequestHandler):
    """Zero-dependency HTTP handler for local browser preview on 127.0.0.1."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        episodes = fetch_archived_episodes()
        ledger = query_prediction_ledger(LedgerQueryInput(limit=15))
        preds = [p.model_dump() for p in ledger.predictions]
        sub_count = fetch_subscriber_count()

        if parsed.path.startswith("/episodes/"):
            ep_id = parsed.path.replace("/episodes/", "").strip("/")
            ep = fetch_single_episode(ep_id)
            body = render_dashboard_html(
                [ep] if ep else [],
                preds,
                sub_count,
                banner_message=f"Shareable view for episode '{ep_id}'",
            )
        else:
            body = render_dashboard_html(episodes, preds, sub_count)

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8")
        form = parse_qs(raw_body)
        banner = ""

        if self.path == "/subscribe":
            email = form.get("email", [""])[0]
            focus = form.get("focus_area", ["Enterprise AI & Cloud Leader"])[0]
            res = add_newsletter_subscriber(
                SubscriberInput(email=email, focus_area=focus)
            )
            banner = res.message if res.success else str(res.error_message)
        elif self.path == "/analyze":
            url = form.get("video_url", ["sample://all-in-ep-200"])[0]
            role = form.get("user_role", ["Enterprise AI & Cloud Leader"])[0]
            email = form.get("recipient_email", [""])[0].strip() or None
            coordinator = PodPulseCoordinator()
            res = asyncio.run(
                coordinator.run_episode_pipeline(
                    video_url=url,
                    user_role=role,
                    recipient_email=email,
                    approval_callback=(lambda _b: True) if email else None,
                )
            )
            banner = (
                f"Analyzed episode '{res.episode_id}'!"
                if res.success
                else f"Error: {res.error_message}"
            )

        episodes = fetch_archived_episodes()
        ledger = query_prediction_ledger(LedgerQueryInput(limit=15))
        preds = [p.model_dump() for p in ledger.predictions]
        sub_count = fetch_subscriber_count()
        body = render_dashboard_html(
            episodes, preds, sub_count, banner_message=banner
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


if __name__ == "__main__":
    import os

    port = int(os.getenv("PORT", "8085"))
    server = HTTPServer(("127.0.0.1", port), LocalDashboardHandler)
    print(f"PodPulse Web Dashboard running at http://127.0.0.1:{port}", flush=True)
    server.serve_forever()
