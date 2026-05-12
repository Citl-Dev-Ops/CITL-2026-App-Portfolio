# CITL Work Ticketing System

This app is a CITL-style dark GUI that combines:
- local ticket database (`SQLite`)
- service ticket lifecycle operations (`new`, `in_progress`, `pending`, `resolved`, `closed`)
- intake QA to catch unreliable email-trigger payloads before they become bad tickets
- FlowFX-based Power Automate JSON generation for Microsoft Lists + Teams + Outlook + Planner workflows
- Flow Run Import parser to extract root-cause failing action from run-history payload JSON
- packet diagnostics to classify Microsoft failures (permissions/licensing/connection/schema/throttling/timeout)
- local operation catalog DB for connector operation IDs, required params, and verified sample commands
- local error-catalog DB with deterministic/ambiguous diagnosis signaling
- prototype/live environment profile switching for safer pre-live testing
- local webhook observer + remote probe logging for packet inspection without storing tenant credentials
- connection preflight checks for Graph/Outlook/SharePoint reachability and permission visibility
- CI-style FlowFX validator pack (single-file and batch validation with JSON report output)

## Launch

On Windows:

```cmd
RUN_WORK_TICKETING_SYSTEM_WINDOWS.cmd
```

Or directly:

```powershell
python .\powerflow_builder\citl_work_ticketing_gui.py
```

Build Windows executable:

```powershell
powershell -ExecutionPolicy Bypass -File .\powerflow_builder\build_ticketing_automation_exe.ps1 -Clean
```

Run Windows executable:

```cmd
RUN_WORK_TICKETING_SYSTEM_WINDOWS_EXE.cmd
```

Build Ubuntu/Linux binary (run on Ubuntu host):

```bash
bash powerflow_builder/build_ticketing_automation_bin.sh
```

Run Ubuntu/Linux binary:

```bash
bash RUN_WORK_TICKETING_SYSTEM_UBUNTU.sh
```

## Data Location

- DB: `documents/ticketing_system/citl_ticketing.db`
- Exports: `documents/ticketing_system/exports`

## Why Intake QA Exists

Office 365 email triggers can skip or duplicate events in edge cases, especially when mail is moved between folders or when attachments are involved. This app's Intake QA tab adds guardrails (confidence scoring, allowlist domain checks, auto-reply filtering) so low-trust payloads are reviewed before ticket creation.

## Diagnostics Coverage

The `Packet Diagnostics` tab helps explain generic errors by mapping packet text to likely root causes:
- permissions / conditional access denials (`401/403`, `AADSTS*`, mailbox rights)
- licensing mismatches (`DirectApiAuthorizationRequired`, premium connector issues)
- broken connection references (`InvalidConnection`)
- schema/expression faults (`InvalidTemplate`, `TriggerInputSchemaMismatch`, etc.)
- throttling/quota and timeout patterns

Each diagnostic output now includes:
- matched catalog definitions with evidence and recommended actions
- `determinism` (`deterministic`, `ambiguous`, `probable`, `low_confidence`)
- connector permission checklist guidance
- root-cause flow-run import support (`Flow Run Import` tab) to reduce generic ActionFailed ambiguity

## Flow Builder Output

The `Flow Builder` tab emits:
- `FlowFX` script (editable)
- compiled Power Automate JSON definition (copy/import ready)
- validator-pack report (`Validate FlowFX Pack` / `Batch Validate Files`)

Use this as a controlled stopgap instead of hand-editing JSON in Copilot-assisted sessions.

## Connection Preflight

The `Connection Preflight` tab supports two safe modes:
- paste an access token (in-memory only) and run checks
- use device-code sign-in (public client app) and poll token manually

Checks include:
- delegated Graph identity (`/me`)
- mailbox settings access
- mailbox folder visibility (`/me/mailFolders/{folder}`)
- SharePoint site lookup by path
- SharePoint list enumeration and target-list verification

## Webhook Observation Mode

The `Webhook Monitor` tab supports:
- local observer endpoint (safe default bind: `127.0.0.1`)
- optional all-interface bind (`0.0.0.0`) with token prompt
- token validation (`X-CITL-Token`)
- strict path check (mismatch returns `404`)
- persisted packet/event log in SQLite for post-run analysis

This mode is for prototyping and diagnostics, not credentialed production sync.
