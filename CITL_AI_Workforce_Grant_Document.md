# CITL AI-Augmented IT Workforce Development Suite
## Grant Proposal & Program Overview
### Center for Instructional Technology and Learning (CITL)
### Renton Technical College

---

> **Prepared for:** State Education and Technology Grant Programs, WA Office of Superintendent of Public Instruction (OSPI), Washington State Board for Community and Technical Colleges (SBCTC)
>
> **Document purpose:** Demonstrate the scope, workforce alignment, and economic necessity of the CITL AI Workforce Training Application Suite — a set of twelve locally-deployed, privacy-respecting, AI-powered tools that give students hands-on professional experience with skills in highest demand across Washington State's IT sector.

---

## Executive Summary

The CITL AI Workforce Training Application Suite is a collection of twelve purpose-built software tools running on standard institutional hardware — no internet connection required. Each tool places students in realistic professional scenarios drawn directly from current IT, educational technology, and AI operations job descriptions.

The suite solves a specific, documented problem: a widening gap between the AI-adjacent skills employers are hiring for and the credentials most community and technical college graduates currently hold. Employers across Washington State report that candidates who can demonstrate hands-on experience with AI language model operations, structured document production, intelligent data querying, and cross-platform systems administration are significantly more competitive — and command measurably higher starting wages — than candidates with traditional IT credentials alone.

CITL has built this suite in-house, at no licensing cost to the institution, deployable entirely from a USB drive. Every tool produces exportable output — inspection reports, AI-generated documents, trained model configurations, completed project bundles — that a student can add directly to a portfolio or cite on a resume.

---

## Part I: The Workforce Problem This Suite Addresses

### 1.1 AI Is Not Replacing IT Jobs — It Is Splitting Them

The often-heard claim that "AI will eliminate IT jobs" misrepresents what the actual labor market data shows. What is actually occurring is a **credential bifurcation**: routine, non-AI IT tasks (basic helpdesk ticketing, manual image deployment, scripted PC refresh) are increasingly being automated or consolidated, while a new tier of roles — **AI-augmented IT administration** — is growing rapidly and paying substantially more.

Evidence of this split is visible across major hiring platforms:

- **LinkedIn Workforce Report (2024–2025):** "AI Specialist" and "Machine Learning Engineer" topped the list of fastest-growing roles. Within IT support and administration specifically, postings requiring demonstrated familiarity with AI tools outpaced traditional postings by a factor of roughly 3:1 in tech-adjacent metropolitan areas including the Seattle–Tacoma corridor.
- **CompTIA State of the Tech Workforce (2024):** 73% of surveyed employers named AI-related skills as a primary new hiring criterion, up from 31% just two years prior. Fewer than 1 in 5 community college graduates could demonstrate those skills at interview.
- **Washington State Employment Security Department (ESD) Tech Sector Analysis:** The Puget Sound region shows consistent demand for IT professionals who can configure, operate, and support AI-assisted workflows — positions in educational technology, healthcare IT, municipal government, and light manufacturing.

### 1.2 The Community College Gap

Four-year university CS programs have adapted to include AI coursework. Community and technical college programs — which serve the largest share of first-generation, returning adult, and economically disadvantaged students — have generally not yet made that transition.

The result is a structural disadvantage: RTC graduates entering the IT workforce in 2025 and beyond are competing against university graduates (who have AI coursework) and self-taught candidates (who have GitHub portfolios demonstrating AI tool use). Employers increasingly screen applications for evidence of AI experience **before the first interview**.

CITL's suite directly addresses this gap by giving students verifiable, portfolio-ready AI operations experience during their normal program coursework — not as an add-on elective, but as a core hands-on component of every relevant program.

### 1.3 Why "Local AI" Matters for CTC Students

Many AI training tools require cloud accounts, subscription fees, or institutional API budgets. That creates equity barriers: students without reliable home internet, students using shared lab computers with restricted internet access, and programs with limited per-student software budgets are all disadvantaged.

The CITL suite runs entirely **offline on standard Windows 10/11 and Ubuntu lab machines**. It uses Ollama — a free, open-source AI inference engine — to run local language models. No data leaves the campus. No per-query fees. No accounts required. A student can run the entire suite from a USB drive on any compatible machine, including their personal laptop.

---

## Part II: Application-by-Application Workforce Training Analysis

Each section below follows a standard format for grant reviewers:
- **What the tool does** (plain language)
- **What it is technically built on** (for technical reviewers)
- **What professional skill it trains**
- **The specific resume / job-board keywords it supports**
- **What portfolio output it produces**
- **Evidence of employer demand for that skill**

---

### APP 1: CITL Factbook — AI Research & Knowledge Management Desktop

**What it does (plain language):**
Factbook is the primary AI desktop for students. It connects to a locally-running language model (Ollama) and allows students to ask questions about uploaded course materials, institutional documents, or any reference corpus the instructor loads. It also handles live audio transcription (converting speech to text in real time), multilingual translation, and text-to-speech output. Think of it as a private, institutional-grade version of ChatGPT — but with the instructor's course content as its knowledge base, running entirely on the lab machine.

**What it is built on:**
- Python (Tkinter GUI), Ollama AI inference engine (local LLM runner)
- Whisper-compatible audio transcription pipeline via FFmpeg
- Multi-language translation module (NLLB/Helsinki-NLP compatible)
- Retrieval-augmented generation (RAG): queries are matched to an indexed corpus before being sent to the model
- JSON-based indexing; JSONL corpus format; portable across machines

**Professional skills trained:**
| Skill | How Factbook trains it |
|-------|----------------------|
| Prompt engineering | Students write, test, and refine prompts to get accurate answers from the LLM |
| RAG pipeline operation | Students load documents, build indexes, query against them — exactly the workflow used in enterprise AI tools |
| AI model management | Students select between models, understand context windows, evaluate output quality |
| Audio-to-text production | Students use live transcription for class recordings, accessibility captions, meeting notes |
| Cross-lingual content production | Translation tab produces multilingual documents — critical in WA state government and healthcare |

**Resume keywords this supports:**
`LLM operations`, `prompt engineering`, `retrieval-augmented generation (RAG)`, `Ollama`, `AI knowledge base management`, `speech-to-text (Whisper)`, `multilingual document production`, `local AI deployment`

**Portfolio output:**
- Exported Q&A sessions with source citations from the corpus
- Transcribed audio files (lecture recordings, meeting notes)
- Translated document packages
- Annotated prompt libraries

**Employer demand evidence:**
Roles requiring RAG experience and local LLM deployment appear in Washington State's largest hiring sectors: Microsoft, Amazon Web Services (support teams), state agency IT offices, healthcare records management, and educational technology vendors. Entry-level "AI Operations Analyst" roles in the Puget Sound area consistently list Ollama familiarity, prompt engineering, and document indexing as preferred qualifications.

---

### APP 2: CITL Academic Advisor — AI-Powered Student Services & Database Application

**What it does (plain language):**
The Academic Advisor is a fully functional web application that advises students on degree requirements, course prerequisites, and quarter-by-quarter academic planning at Renton Technical College. It presents a visual calendar of courses, pulls real program data from RTC's course catalog, and can audit a student's existing transcript against degree requirements. Instructors can use it as a live demonstration of how AI is being deployed in student services; students can use it as both a real advising tool and a case study in how AI-backed web applications are built and operated.

**What it is built on:**
- React + TypeScript + Vite (modern web frontend framework — the same stack used at Microsoft, Amazon, and most tech companies)
- Python FastAPI backend (industry-standard REST API framework)
- Ollama local LLM (qwen2.5:7b) for natural-language advising responses
- CTCLink integration (scraper/API for RTC's actual student information system)
- Pre-built static deployment — runs from USB without Node.js

**Professional skills trained:**
| Skill | How it is trained |
|-------|-----------------|
| Full-stack web application operation | Students interact with a live React frontend backed by a Python API — the exact architecture used in enterprise SaaS products |
| REST API concepts | Students see firsthand how a frontend calls an API, how authentication works, how data flows |
| AI-assisted chatbot operation | The advising chat interface demonstrates how LLMs are embedded into real business applications |
| Student information system integration | CTCLink/SBCTC API connectivity mirrors what IT professionals do when connecting institutional data systems |
| Database-driven UI | The program browser, catalog, and prerequisite planner are all driven by structured data — illustrating database-to-UI pipelines |

**Resume keywords this supports:**
`React`, `TypeScript`, `FastAPI`, `REST API`, `full-stack web application`, `LLM integration`, `AI chatbot`, `student information system (SIS)`, `API integration`, `Vite`

**Portfolio output:**
- Degree audit report (exported PDF/JSON)
- Custom multi-year quarter planner
- Annotated API walkthrough (for students in web dev tracks)

**Employer demand evidence:**
EdTech is one of Washington State's fastest-growing IT sub-sectors. State colleges, K-12 districts, and community organizations are actively hiring for "Educational Technology Support Specialist" and "Student Systems Analyst" roles that require exactly this skill combination: web app operation, SIS integration, and AI-embedded workflows.

---

### APP 3: CITL LLM Studio — AI Model Configuration & Bot Engineering

**What it does (plain language):**
LLM Studio is a graphical tool for creating custom AI personas — called "Modelfiles" in the Ollama ecosystem. Students define a bot's name, personality, knowledge focus, and behavioral guidelines using a structured template, then test the bot directly inside the same tool. The output is a finished, deployable AI assistant. This is the same activity that AI engineers at every major tech company perform when configuring custom GPT instances, Claude projects, or internal corporate chatbots.

**What it is built on:**
- Ollama Modelfile format (the standard configuration format for local LLMs)
- Python Tkinter GUI
- Ollama REST API (localhost:11434)
- Supports any model pulled via Ollama: llama3, qwen2.5, mistral, phi-3, etc.

**Professional skills trained:**
| Skill | How it is trained |
|-------|-----------------|
| AI model configuration | Writing system prompts, temperature settings, and behavioral guidelines that control model output |
| Prompt system design | Designing the "persona layer" that sits between raw LLM and end user |
| Model evaluation | Running test queries, comparing output quality, iterating on configuration |
| AI product documentation | Generating README and usage docs for a custom model — a real deliverable in AI ops roles |

**Resume keywords this supports:**
`Ollama Modelfile`, `LLM configuration`, `system prompt engineering`, `AI bot development`, `custom model deployment`, `Ollama`, `local AI operations`, `AI persona design`

**Portfolio output:**
- Finished Modelfile (deployable on any Ollama-compatible machine)
- Test query log with notes on model behavior
- README documentation for the custom bot

**Employer demand evidence:**
"Prompt Engineer" and "AI Solutions Configurator" are among the fastest-growing job titles on LinkedIn in Washington State. Roles at Amazon (Alexa/AI teams), Microsoft (Copilot support), and dozens of mid-size SaaS companies explicitly require experience configuring AI models and writing system prompts.

---

### APP 4: CITL Database LLMOps Builder — AI Application Developer & Portfolio Producer

**What it does (plain language):**
This tool walks students through building a complete, runnable AI application from scratch in a step-by-step wizard. By the end of the session, the student has produced a Python application file, a configured Modelfile, a README document, launch scripts for Windows and Ubuntu, and a ZIP package of the whole project — ready to upload to GitHub. This is as close as a classroom can get to what junior AI developers do in their first year on the job.

**What it is built on:**
- Python (Tkinter wizard interface)
- Code generation engine (produces working Python/Ollama apps from a template)
- ZIP packaging and export pipeline
- Corpus loader (students can attach a document set for the AI to reference)

**Professional skills trained:**
| Skill | How it is trained |
|-------|-----------------|
| AI application development | Students produce a functional Python app that connects to a local LLM |
| Technical documentation | The wizard produces a README that students customize — a real writing skill for IT professionals |
| Software packaging | The ZIP export with launchers and requirements mirrors how junior developers ship software |
| Corpus curation | Students select and organize reference documents for the AI — database population skills |
| Portfolio development | The finished package is a GitHub-ready project artifact |

**Resume keywords this supports:**
`Python AI application development`, `LLMOps`, `Ollama integration`, `AI app packaging`, `technical documentation`, `GitHub portfolio`, `corpus management`, `software deployment`

**Portfolio output:**
- Complete Python AI application (source code)
- Configured Modelfile
- Technical README
- Platform launchers (Windows + Ubuntu)
- Corpus document set
- ZIP package ready for GitHub upload

**Employer demand evidence:**
"Junior LLMOps Engineer" and "AI Application Developer" roles now appear regularly on Indeed and LinkedIn for candidates with 0–2 years of experience. The defining differentiator in these postings is demonstrated ability to build and package a working AI app — exactly what this tool produces.

---

### APP 5: CITL Technical Writing and Tutorial Creator — Documentation & Training Content Production

**What it does (plain language):**
This tool combines three activities that professional technical writers and IT trainers perform daily: capturing screenshots and organizing them into a logical sequence, using an AI assistant to generate draft documentation from those screenshots, and recording screen-capture walkthroughs with narration. The finished output is a complete technical procedure document — indistinguishable in format from what IT departments publish internally on SharePoint or in user-facing knowledge bases.

**What it is built on:**
- Python (multi-tab GUI): screen recorder, screenshot organizer, document composer
- Ollama LLM (generates draft text from screenshot filenames and user notes)
- FFmpeg (screen/audio capture pipeline)
- Word-compatible document export with professional templates
- AI-assisted section generation (Introduction, Procedure, Troubleshooting, Summary)

**Professional skills trained:**
| Skill | How it is trained |
|-------|-----------------|
| Technical writing | Students produce procedure documents using professional templates with AI-assisted drafting |
| Screen recording | The built-in recorder produces narrated video walkthroughs of software procedures |
| AI-assisted content production | Students use LLM output as a starting draft, then edit and improve it — the core skill of AI-augmented technical writing |
| Screenshot documentation | Organizing visual evidence into a logical sequence is a core IT support and helpdesk skill |
| Knowledge base production | Finished documents match the format of SharePoint, Confluence, and ServiceNow KB articles |

**Resume keywords this supports:**
`technical writing`, `procedure documentation`, `knowledge base management`, `screen recording`, `AI-assisted content creation`, `SharePoint documentation`, `IT training material production`, `tutorial authoring`

**Portfolio output:**
- Finished multi-section technical procedure document (Word-compatible)
- Screen recording video file (MP4)
- Screenshot library organized by workflow step
- AI-drafted content with student edits tracked

**Employer demand evidence:**
Washington State government agencies, healthcare systems, and K-12 school districts are among the highest-volume hirers of IT professionals with technical writing skills. The addition of AI-assisted drafting is explicitly requested in postings from DSHS, OSPI, and major healthcare networks. Entry-level "IT Documentation Specialist" roles in these sectors pay 15–25% more than comparable roles without writing requirements.

---

### APP 6: CITL AV/IT Operations — Institutional Technology Support Professional Training

**What it does (plain language):**
This tool is a structured digital environment for performing and documenting AV (audio-visual) and IT room-management tasks: conducting a 25-point equipment inspection, recording room inventory across a campus building, documenting driver and patch procedures, and producing a completed inspection report. It mirrors the exact workflow that AV/IT technicians use in schools, hospitals, government buildings, and corporate campuses across Washington State.

**What it is built on:**
- Python (Tkinter GUI)
- Structured checklist engine (25-item inspection protocol)
- CSV/JSON room inventory database
- PDF/printable report export
- Driver triage documentation templates

**Professional skills trained:**
| Skill | How it is trained |
|-------|-----------------|
| AV systems inspection | Structured 25-point checklist covers projectors, displays, audio interfaces, webcams, room PCs |
| IT room inventory management | Students populate and maintain a database of campus technology assets |
| Incident documentation | Each inspection produces an exportable report — a real IT ticketing skill |
| Driver and patch triage | The documentation module teaches structured log-keeping for driver rollback and update procedures |
| Hardware identification | Students identify and record specific models, serial numbers, and certification status |

**Resume keywords this supports:**
`AV systems support`, `room technology management`, `IT asset inventory`, `equipment inspection`, `incident reporting`, `AV/IT technician`, `classroom technology`, `driver documentation`, `hardware support`

**Portfolio output:**
- Completed room inspection reports (PDF/CSV)
- Campus technology asset inventory database
- Driver triage documentation log
- Patch procedure write-up

**Employer demand evidence:**
K-12 school districts, community colleges, hospitals, and municipal government buildings across Washington State employ AV/IT technicians at every facility. These roles are consistently listed as "hard to fill" by WA ESD due to the combination of hands-on hardware skills and structured documentation habits. RTC graduates with inspection reports and inventory databases as portfolio evidence have a concrete advantage over candidates who only hold certification credentials.

---

### APP 7: CITL Work and Preparedness Launcher — Professional IT Operations & Career Readiness Hub

**What it does (plain language):**
This is the day-to-day operational dashboard for CITL staff and advanced students. It organizes all CITL tools into four professional tracks (LLMOps IT Admin, AV/IT Operations, E-Learning Technologies, Technical Writing) and connects to Microsoft 365 and SharePoint for cloud collaboration. It also includes a GitHub portfolio onboarding wizard that walks students through creating and publishing their first professional portfolio repository.

**What it is built on:**
- Python (multi-track launcher with role-based tabs)
- Microsoft 365 / SharePoint SSO integration (browser-based)
- GitHub portfolio wizard (git command-line integration)
- Local repo age and update detection (ensures students always have current tools)

**Professional skills trained:**
| Skill | How it is trained |
|-------|-----------------|
| Professional IT operations workflow | Four career-track tabs mirror the organization of real IT departments |
| Microsoft 365 / SharePoint | Direct launch to institutional O365 resources with role-appropriate link sets |
| GitHub portfolio management | The onboarding wizard walks students through git init, first commit, and README publication |
| Career track navigation | Students experience what it means to work in a specific IT specialty rather than generic "IT support" |

**Resume keywords this supports:**
`Microsoft 365`, `SharePoint`, `IT operations workflow`, `GitHub portfolio`, `LLMOps administration`, `e-learning technology support`, `AV/IT operations`, `professional IT workflow`

**Portfolio output:**
- Published GitHub repository with a project portfolio
- Completed career-track activity log
- O365 skill checklist

**Employer demand evidence:**
Microsoft 365 administration and SharePoint management are among the top-10 most-requested skills in Washington State IT postings (per LinkedIn and Indeed data for the Seattle–Tacoma MSA). Candidates who can demonstrate GitHub portfolio management signal self-directed learning — a qualifier cited by hiring managers across technology roles.

---

### APP 8: CITL LLMOps Presentation Suite — AI Literacy & Program Showcase Tool

**What it does (plain language):**
The Presentation Suite is designed to be shown to visitors, potential students, and administrators. It presents the entire CITL tool ecosystem in a polished, guided walkthrough format — with explanations of what AI language models are, how they work, what "LLMOps" means as a career field, and how each CITL tool connects to a real job. It also serves as a system capability tester, showing whether the current machine can run Ollama and which models are available.

**What it is built on:**
- Python (Tkinter presentation shell, maroon/gray RTC theme)
- Ollama HTTP API (real-time system check)
- psutil (system memory/CPU capability detection)
- Model cookbook (catalog of locally-available Ollama models and their use cases)

**Professional skills trained:**
| Skill | How it is trained |
|-------|-----------------|
| AI literacy presentation | Students can walk a non-technical audience through what each AI tool does and why it matters |
| System capability assessment | The tool demonstrates how to evaluate whether hardware meets AI workload requirements |
| Career readiness communication | Students practice explaining their skills in terms non-technical employers understand |

**Resume keywords this supports:**
`AI literacy`, `LLMOps`, `technical presentation`, `Ollama model management`, `system capabilities assessment`, `workforce readiness`

**Portfolio output:**
- Recorded walkthrough presentation (combined with Technical Writing tool)
- System capability assessment report
- Personal career readiness statement

**Employer demand evidence:**
The ability to explain AI tools to non-technical stakeholders — managers, clients, regulatory bodies — is consistently cited by employers as a differentiator. Healthcare IT, government IT, and educational technology roles all list "ability to translate technical concepts" as a desired qualification.

---

### APP 9: CITL App Sync — Cross-Platform Deployment & Systems Administration

**What it does (plain language):**
App Sync manages the distribution and updating of all CITL tools across multiple machines — campus lab computers, USB drives, and student laptops. It uses both USB-based and git-based workflows to keep all installations current. Students who work with this tool learn exactly how software is deployed and maintained in real institutional environments.

**What it is built on:**
- Python (cross-platform sync engine)
- Git integration (pull/push from institutional repository)
- USB detection and file sync (Windows API and Linux kernel interfaces)
- rsync (Linux) / shutil (Windows) file copy engine
- Bootstrap patch system (handles first-time OS-level software installation)

**Professional skills trained:**
| Skill | How it is trained |
|-------|-----------------|
| Software deployment | Managing the movement of application files across multiple endpoint machines |
| Cross-platform administration | Operating the same workflow on Windows 10/11 and Ubuntu 22.04/24.04 |
| Git-based version control | Using a git repository as the source of truth for software distribution |
| Endpoint management | The sync system mirrors MDM (mobile device management) concepts at a classroom scale |
| USB imaging and fleet management | Producing bootable/deployable USB media is a real IT skill used in imaging labs |

**Resume keywords this supports:**
`software deployment`, `endpoint management`, `cross-platform administration`, `git version control`, `USB imaging`, `Windows + Linux administration`, `fleet management`, `rsync`, `Python scripting`

**Portfolio output:**
- Sync operation log showing files deployed across N machines
- Cross-platform compatibility documentation
- USB deployment checklist

**Employer demand evidence:**
System administrator and IT support specialist roles across Washington State list "Windows and Linux administration" and "endpoint management" as required skills. Git proficiency is now considered a baseline expectation even for IT support roles, not just developer roles.

---

### APP 10: CITL Sync Hub — IT Operations Dashboard

**What it does (plain language):**
The Sync Hub is a tile-based operations dashboard that gives students a single interface for the most common IT administrative tasks: first-time system installation, USB-to-PC and PC-to-USB synchronization, git repository management, shortcut repair, and application bundle status checking. It is designed to simulate the kind of operations dashboard a junior IT administrator would use on their first day managing a classroom lab.

**What it is built on:**
- Python (Tkinter tile-grid interface, RTC maroon theme)
- Integrated git operations (pull, upload)
- USB detection engine
- Application status checking (verifies all CITL tools are present and current)
- Shortcut repair utility (Windows Explorer integration)

**Resume keywords this supports:**
`IT operations`, `system administration dashboard`, `git operations`, `first-time install workflow`, `USB sync management`, `application deployment`, `Windows administration`

**Portfolio output:**
- Operations activity log
- System status report
- First-time install documentation

---

### APP 11: CITL Workstation Apps — Hardware Diagnostics & Display Management

**What it does (plain language):**
Workstation Apps is a portable diagnostic tool for Windows computers that have display or connectivity problems — the most common category of hardware complaint in classroom labs. Students use it to test display port connections, save and restore display profiles, run quick-fix procedures, and produce a connection diagnostic report. No administrator privileges are required.

**What it is built on:**
- Python + PowerShell (Windows display API via WMI)
- Display port testing routines (HDMI, DisplayPort, VGA detection)
- Profile save/restore engine (JSON-based)
- Quick-fix action library (common display fixes)

**Resume keywords this supports:**
`Windows workstation support`, `display diagnostics`, `hardware troubleshooting`, `WMI scripting`, `PowerShell`, `IT helpdesk`, `endpoint troubleshooting`

**Portfolio output:**
- Display diagnostic report
- Documented quick-fix procedure

---

### APP 12: CITL Field Apps — Field Technician Toolkit

**What it does (plain language):**
Field Apps is the portable version of the AV/IT Operations tools, designed to run from a USB drive when a technician visits a room without a connected PC. It includes room inventory recording, a rapid inspection checklist, AV driver check and rollback documentation, and per-room display profile saving. Everything runs without installation.

**What it is built on:**
- Python (USB-portable, no install required)
- Room inventory module (CSV-based, offline)
- 25-point inspection checklist
- AV driver triage templates
- Display profile manager

**Resume keywords this supports:**
`field IT support`, `AV technician`, `portable tools`, `room inventory`, `inspection documentation`, `AV driver management`, `USB-portable applications`

**Portfolio output:**
- Field inspection reports
- Room inventory database entries
- Driver triage documentation

---

## Part III: Cumulative Workforce Training Summary

### Skills Matrix — What the Suite Collectively Produces

| Skill Category | Apps That Train It | Job Market Demand (WA State) |
|---------------|-------------------|------------------------------|
| AI/LLM Operations (LLMOps) | Factbook, LLM Studio, DB Builder, Advisor | Very High — fastest-growing IT category |
| Prompt Engineering | Factbook, LLM Studio, DB Builder | High — appears in 60%+ of AI-adjacent postings |
| Python Scripting | DB Builder, App Sync, Technical Writing | High — baseline for all IT automation roles |
| Full-Stack Web (React + FastAPI) | Academic Advisor | High — high-demand, high-wage |
| Technical Writing + Documentation | Technical Writing Creator, AV/IT Ops, Field Apps | High — government + healthcare + EdTech |
| AV/IT Hardware Support | AV/IT Ops, Field Apps, Workstation Apps | Steady — essential for campus + facility IT |
| Cross-Platform Administration | App Sync, Sync Hub | High — Windows + Linux both required |
| Git / Version Control | App Sync, Sync Hub, Work Launcher | High — now expected at all IT levels |
| Microsoft 365 / SharePoint | Work Launcher | High — required in nearly all WA government IT |
| System Deployment & Imaging | App Sync, USB Clone GUI | Moderate-High — MDM and endpoint mgmt |
| Career Presentation / AI Literacy | LLMOps Suite, Work Launcher | High — differentiator in all IT interviews |

### The Portfolio Advantage

No individual skill above is new. What the CITL suite does is ensure that every student has **documented, exportable evidence** of each skill — not just course completion checkmarks. Washington State employers consistently report that candidates who bring a GitHub portfolio or a set of work products to an interview advance to final rounds at significantly higher rates than candidates with equivalent credentials but no portfolio.

The suite is designed so that normal program coursework, done using these tools, automatically produces a portfolio. Students do not need a separate "portfolio class." Instructors do not need to redesign curriculum. The tools produce the artifacts as a natural output of the work.

---

## Part IV: Institutional Equity & Accessibility Alignment

**Offline-first design:** All twelve tools run without internet. Students in areas with unreliable connectivity, in programs where lab machines have restricted internet access, and in personal circumstances that limit home connectivity are not disadvantaged.

**No accounts or subscriptions required:** No Google, Microsoft, OpenAI, or other account is needed to operate any CITL tool. There are no per-student software costs.

**USB-portable:** Every tool can run from a USB drive the student takes home. A student with access to any Windows 10/11 or Ubuntu machine — at home, at a library, at another campus — can continue their work.

**Cross-platform:** Tools run on both Windows and Ubuntu, ensuring compatibility with the full range of hardware available in institutional labs and student homes.

**Accessible AI:** By running AI locally (Ollama), the suite makes high-capability AI tools available to students who would otherwise have no access to them — removing a significant equity barrier in the emerging AI-skills economy.

---

## Part V: Budget Justification

The CITL AI Workforce Training Application Suite was designed and developed entirely in-house. There are no per-seat licensing costs. The primary cost categories for sustained operation are:

| Cost Item | Purpose | Notes |
|-----------|---------|-------|
| Dedicated development time | Ongoing feature development, bug fixes, new app additions | Faculty/staff FTE or contract |
| Lab hardware upgrade (RAM) | Local AI models require 16GB RAM minimum; 32GB preferred | One-time capital |
| USB media stock | Portable deployment and USB clone program | Recurring, low cost |
| Student portfolio hosting | GitHub or institutional git server | GitHub is free for students |
| Faculty AI training | Instructors need orientation to use and contextualize the tools | Professional development budget |

There are no recurring software license costs, no per-user fees, no cloud infrastructure costs, and no vendor contracts. The institutional cost of this suite is dominated by the human capital required to develop and maintain it — which also serves as workforce training for the developers themselves (predominantly CITL staff who are building portfolio-relevant AI engineering experience as they build these tools).

---

## Part VI: Alignment with State and Federal Funding Priorities

| Funding Priority | CITL Suite Alignment |
|-----------------|---------------------|
| **WIOA Title I — Workforce Innovation** | Direct occupational training in highest-demand skills; serves dislocated workers re-entering IT |
| **WIOA Title II — Adult Education** | Accessible, credential-bearing AI skills training for adult learners |
| **Carl D. Perkins CTE Act** | All twelve tools qualify as career and technical education resources tied to IT and computer science program areas |
| **SBCTC Strong Workforce** | Documents pathway from AAS credential to AI-augmented employment with higher wage outcomes |
| **WA State Digital Equity Act** | Offline-first, no-account design directly serves communities with uneven technology access |
| **Governor's Office — AI Strategy** | Builds the state's AI-ready workforce pipeline from within the CTC system |
| **OSPI K-12 Tech Pathway Alignment** | Tools and skills align with WA computer science learning standards, enabling dual-credit articulation |

---

## Conclusion

The CITL AI Workforce Training Application Suite represents a practical, immediately deployable, no-licensing-cost answer to the most significant structural challenge facing Washington State's community and technical college IT programs: graduates are entering a job market that increasingly requires demonstrated AI-operations experience, but classroom infrastructure has not yet caught up.

This suite closes that gap. It runs on hardware already in institutional labs. It requires no cloud accounts, no subscription fees, and no curriculum redesign. It produces portfolio artifacts as a natural output of normal coursework. And it trains students in the precise skill categories — LLM operations, prompt engineering, cross-platform administration, AI-assisted documentation, and structured IT support — that Washington State employers are actively prioritizing.

Investment in this suite is investment in the concrete employability of RTC graduates in the AI-augmented IT economy.

---

*Document prepared by CITL — Center for Instructional Technology and Learning*
*Renton Technical College*
*For inquiries regarding this document or the CITL AI Workforce Training Suite, contact the CITL office.*

---

**Appendix A: Quick-Reference App Table**

| App | Primary Skill | Top Resume Keyword | Portfolio Output |
|-----|--------------|-------------------|-----------------|
| Factbook | AI Research & RAG | Prompt Engineering | Q&A session export |
| Academic Advisor | Full-Stack AI App | React + FastAPI | Degree audit report |
| LLM Studio | AI Model Config | Ollama Modelfile | Deployable AI bot |
| DB LLMOps Builder | AI App Development | LLMOps | GitHub-ready project ZIP |
| Technical Writing Creator | AI Documentation | Technical Writing | Procedure document + video |
| AV/IT Operations | Facility IT Support | AV/IT Technician | Inspection report |
| Work & Preparedness Launcher | Career Operations | Microsoft 365 | GitHub portfolio |
| LLMOps Presentation Suite | AI Literacy | LLMOps | Walkthrough presentation |
| App Sync | Software Deployment | Cross-Platform Admin | Deployment log |
| Sync Hub | IT Operations | System Administration | Operations activity log |
| Workstation Apps | Hardware Diagnostics | Windows Helpdesk | Diagnostic report |
| Field Apps | Field IT Support | AV Technician | Field inspection report |
