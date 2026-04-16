# CITL FLEX Troubleshooter v1.0

AI-powered institutional IT troubleshooting app built on the CITL Factbook RAG engine.
Indexed from the FLEX Team OneNote knowledge base. Fully offline. USB-portable.

**Color scheme:** Teal Ops — distinct from the Factbook crimson theme.

---

## Apps in this module

| EXE Target | Description | Entry point |
|------------|-------------|-------------|
| `CITL-FLEX-Troubleshooter` | Full app — all tabs | `flex_troubleshooter_gui.main()` |
| `FLEX-Ask` | RAG query only | `run_query_only()` |
| `FLEX-IT-Diagnostics` | Ping, ports, disk, services | `run_diagnostics_only()` |
| `FLEX-Ticket-Writer` | AI IT ticket generator | `run_ticket_only()` |
| `FLEX-Index-Builder` | Corpus builder/rebuilder | `run_index_builder_only()` |

---

## Tabs

### 1 — Ask / Query
RAG search against the FLEX corpus. Ask any question about procedures, AV setups,
room configurations, or known issues documented in the FLEX OneNote. Streams answers
from the local Ollama LLM. Supports adjustable top-K retrieval.

### 2 — IT Diagnostics
- Ping, traceroute, DNS lookup
- Port checker + common-port scan (RDP, SSH, Ollama, SMB, etc.)
- Disk usage report
- Network interface info
- Running process list (top CPU)
- Ollama service status
- Full system snapshot (one-click runs all checks)
- Save diagnostic report to .txt

### 3 — Ticket Writer
Describe an issue, pick category (AV, Network, Hardware, Software, Account, etc.)
and priority, then let the local LLM generate a structured IT support ticket with:
- Summary, Symptoms, Affected Systems
- Initial Triage Steps
- Escalation Criteria
- Notes / Knowledge Base References

Copy to clipboard or save as .txt.

### 4 — Index Builder
Rebuild or update the FLEX corpus embedding from any PDF, DOCX, or text file.
Configurable chunk size, overlap, and embedding model. Shows corpus stats and
runs the corpus health check from citl_corpus_health.

### 5 — Models
- List installed Ollama models
- Pull new models by name
- Delete models
- Edit and apply the FLEX Modelfile (creates a `flex-troubleshooter` custom model)

### 6 — Settings
- Ollama host URL (test connection)
- Default generation + embedding models
- Default top-K
- Theme selector (teal_ops default — all CITL themes available)

---

## Quick Start

```bash
# 1. Build the corpus from the FLEX OneNote PDF
python flex_builder.py

# 2. Launch the full app
python flex_troubleshooter_gui.py

# Or run a specific mini-app:
python -c "from flex_troubleshooter_gui import run_diagnostics_only; run_diagnostics_only()"
```

Requires [Ollama](https://ollama.ai) running locally with at least one model pulled.

---

## Build EXEs

```bash
# Full app
python build_flex_exe.py

# Specific targets
python build_flex_exe.py --target query
python build_flex_exe.py --target diagnostics
python build_flex_exe.py --target ticket

# All 5 EXEs at once
python build_flex_exe.py --target all
```

EXEs are written to `dist/`. Each is fully standalone (no Python install needed on target machine).

---

## Authors & Contributors

| Name | Role |
|------|------|
| **Abdo Mohammed** | Lead Developer — Factbook AI Engine & RAG Systems |
| **Wahaj Al Obid** | Lead Developer — Academic Advisor v2.0 |
| **Doc McDowell** | Project Lead, CITL AI and Systems Architect |
| **Jerome Anti Porta** | Developer — UI/UX, App Integration |
| **Jonathan Reed** | Developer — LLMOps & Model Management |
| **Peter Anderson** | Developer — AV/IT Operations & Network Tools |
| **Will Cram** | Developer — E-Learning Administrator and Software Architect |
| **William Grainger** | Developer — Technical Writing & Documentation Tools |
| **Mason Jones** | Developer — Staff Toolkit & Field Apps |

> Renton Technical College — Center for Instructional Technology & Learning (CITL)
> Department of IT & Cybersecurity Workforce Development
