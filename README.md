# PodPulse — Autonomous Podcast Intelligence, Fact-Checking & Accountability Engine

**PodPulse** is a multi-agent system built with the **Google Agent Development Kit (ADK)** and **Vertex AI (`gemini-2.5-flash` & `gemini-2.5-pro`)**. It ingests podcast episodes (such as *The All-In Podcast*), generates a standardized 1-page executive summary, fact-checks specific quantitative claims using live **Google Search Grounding** with confidence scores, tracks host predictions over time in a persistent **Accountability Ledger**, and delivers briefings via a **Human-in-the-Loop (HitL)** email dispatcher and a shareable **Web UI Dashboard**.

---

## Architecture Overview

```text
[Podcast URL (YouTube / Sample)]
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│ Stage 1: IngestionSpecialistAgent (gemini-2.5-flash)      │
│  • Tool: `fetch_podcast_transcript` (Deep-link timestamps)│
│  • Guardrail: `inspect_content_guardrails` (Model Armor)  │
│  • Memory: `compact_transcript_history` (Sliding Window)  │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│ Stage 2: ExecutiveSummarizerAgent (gemini-2.5-flash)      │
│  • Synthesizes 2-minute takeaways & Host Debate Friction │
│  • Tailors "So What For You" to user role profile        │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│ Stage 3: FactCheckerSpecialistAgent (gemini-2.5-pro)      │
│  • Tool: `verify_claim_web_grounding` (Google Search)    │
│  • Outputs Verdict, Confidence (0-100%), and Citations   │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│ Stage 4: PredictionLedgerAgent (gemini-2.5-flash)         │
│  • Tool: `query_prediction_ledger` (SQLite State)        │
│  • Tool: `record_prediction_async` (Async Non-Blocking)  │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│ Stage 5: DispatchCoordinatorAgent (gemini-2.5-flash)      │
│  • Self-Eval Plugin: `evaluate_briefing_quality_guardrail`│
│  • Human-in-the-Loop Gate (`approval_callback`)          │
│  • Tool: `dispatch_executive_brief_email` (Secret Mgr)   │
└──────────────────────────────────────────────────────────┘
```

---



## Quick Start & Usage

### 1. Install Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the Automated Evaluation Suite
```bash
python3 tests/eval_harness.py
```

### 3. Run the Interactive CLI (with Human-in-the-Loop Gate)
```bash
python3 -m src.main --url sample://all-in-ep-200 --email vakulm@google.com
```

### 4. Launch the Shareable Web UI Dashboard
```bash
python3 -m src.web.app
# Or with uvicorn:
uvicorn src.web.app:app --host 127.0.0.1 --port 8080
```

### 5. Provision Cloud Infrastructure via Terraform
```bash
cd terraform
terraform init
terraform plan -var="project_id=vakul-100"
```
