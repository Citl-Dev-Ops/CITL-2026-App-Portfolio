# Stopgap + Long-Term Architecture Notes (April 29, 2026)

This document captures official references for building a safer Microsoft-centric automation stack while reducing JSON breakage risk.

## 1) Keep Power Automate, but make it code-safe

- Use **solution-aware flows** and manage them through Dataverse APIs and/or PAC CLI.
- Treat flow definitions as versioned artifacts, not manual UI-only edits.

Official references:
- Cloud flows with code (Dataverse workflow `clientdata`, connectionReferences):  
  https://learn.microsoft.com/en-us/power-automate/manage-flows-with-code
- PAC CLI intro:  
  https://learn.microsoft.com/en-us/power-platform/developer/cli/introduction
- PAC `solution` commands (`unpack`, `pack`, `sync`, etc.):  
  https://learn.microsoft.com/en-us/power-platform/developer/cli/reference/solution
- PAC `auth` commands:  
  https://learn.microsoft.com/en-us/power-platform/developer/cli/reference/auth

## 2) Reduce expression/JSON failures at build time

- Use expression cookbook patterns and compile-time validation before deploy.
- Add lint-like gates for duplicate action names, bad expression refs, and required fields.

Official references:
- Expression cookbook:  
  https://learn.microsoft.com/en-us/power-automate/expression-cookbook
- Cloud flow error reference:  
  https://learn.microsoft.com/en-us/power-automate/error-reference

## 3) Address known inbox-trigger instability

- For Outlook triggers, ensure folder targeting is correct.
- Avoid relying on moved-message semantics.
- Be careful with attachment-heavy triggers and shared mailbox edge cases.

Official references:
- Office 365 Outlook connector known trigger limitations:  
  https://learn.microsoft.com/en-us/connectors/office365/
- Email-trigger design guidance:  
  https://learn.microsoft.com/en-us/power-automate/email-triggers

## 4) Admin/API operations for environment oversight

- Use supported connectors/APIs, avoid unsupported direct dependency on `api.flow.microsoft.com`.
- Use Management/Admin connectors for inventory and diagnostics.

Official references:
- Power Automate Management connector:  
  https://learn.microsoft.com/en-us/connectors/flowmanagement/
- Power Automate for Admins connector:  
  https://learn.microsoft.com/en-us/connectors/microsoftflowforadmins/

## 5) Improve error interpretation and retry behavior

- Use official cloud-flow error reference as canonical code map.
- Follow robust run-after and retry/error-branch patterns.
- For SharePoint-heavy workloads, honor `Retry-After` for both `429` and `503`.

Official references:
- Cloud flow error code reference:  
  https://learn.microsoft.com/en-us/power-automate/error-reference
- Error-handling guidance:  
  https://learn.microsoft.com/en-us/power-automate/guidance/coding-guidelines/error-handling
- SharePoint throttling/blocking guidance:  
  https://learn.microsoft.com/en-us/sharepoint/dev/general-development/how-to-avoid-getting-throttled-or-blocked-in-sharepoint-online

## 6) Optional external stopgaps (if needed)

If you need a temporary external automation orchestrator while hardening MS flows:

- n8n docs: https://docs.n8n.io/
- Activepieces docs: https://www.activepieces.com/docs
- Node-RED docs: https://nodered.org/docs/

These can serve as sidecar orchestration layers, but primary institutional ticket records should remain in Microsoft Lists/Dataverse/SharePoint where governance and access controls already exist.

## 7) Connection preflight references (Graph + O365)

Use these for safe, explicit connectivity and permission probing from the CITL app:

- Device code grant flow (no embedded user password handling):  
  https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code
- `GET /me` (delegated identity sanity check):  
  https://learn.microsoft.com/en-us/graph/api/user-get?view=graph-rest-1.0
- `GET /me/mailFolders/{id}` (mailbox folder visibility):  
  https://learn.microsoft.com/en-us/graph/api/mailfolder-get?view=graph-rest-1.0
- `GET /sites/{hostname}:/{relative-path}` (site lookup by path):  
  https://learn.microsoft.com/en-us/graph/api/site-getbypath?view=graph-rest-1.0
- `GET /sites/{site-id}/lists` (list enumeration):  
  https://learn.microsoft.com/en-us/graph/api/list-list?view=graph-rest-1.0
