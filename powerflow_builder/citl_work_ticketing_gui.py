#!/usr/bin/env python3
"""
CITL Work Ticketing System

Dark-mode, notebook-style GUI inspired by CITL Workstation Apps, expanded for:
- Service ticket lifecycle tracking
- Historical ticket storage in SQLite
- Intake QA for unreliable email scrape payloads
- FlowFX -> Power Automate JSON compilation
"""

from __future__ import annotations

import csv
from datetime import datetime
import html
import json
import os
from pathlib import Path
import queue
import re
import sqlite3
import threading
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple


def _configure_tk_runtime() -> None:
    # Some portable/venv setups lose Tcl/Tk lookup paths; repair before importing tkinter.
    tcl_env = os.environ.get("TCL_LIBRARY", "").strip()
    tk_env = os.environ.get("TK_LIBRARY", "").strip()
    if tcl_env and tk_env:
        return
    candidates = [
        Path(sys.base_prefix),
        Path(sys.prefix),
        Path(sys.executable).resolve().parent.parent,
        Path(sys.executable).resolve().parent,
    ]
    for root in candidates:
        tcl_dir = root / "tcl" / "tcl8.6"
        tk_dir = root / "tcl" / "tk8.6"
        if tcl_dir.exists() and not os.environ.get("TCL_LIBRARY"):
            os.environ["TCL_LIBRARY"] = str(tcl_dir)
        if tk_dir.exists() and not os.environ.get("TK_LIBRARY"):
            os.environ["TK_LIBRARY"] = str(tk_dir)
        if os.environ.get("TCL_LIBRARY") and os.environ.get("TK_LIBRARY"):
            return


_configure_tk_runtime()

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ImportError:
    sys.exit("tkinter is required.")

try:
    from .flowfx_compiler import FlowFxError, compile_flowfx_text, pretty_print_help
    from .flowfx_validator_pack import run_validator_pack, validate_flowfx_text
    from .ops_assistant import (
        analyze_flow_run_payload,
        begin_device_code,
        graph_list_mail_messages,
        poll_device_token,
        run_graph_preflight,
        servicedesk_list_requests,
        sharepoint_list_item_create,
        sharepoint_list_item_delete,
        sharepoint_list_item_get,
        sharepoint_list_item_update,
        sharepoint_list_item_upsert_by_field,
        sharepoint_list_items_list,
        sharepoint_resolve_list,
        sharepoint_resolve_site,
    )
except ImportError:
    try:
        from powerflow_builder.flowfx_compiler import FlowFxError, compile_flowfx_text, pretty_print_help
        from powerflow_builder.flowfx_validator_pack import run_validator_pack, validate_flowfx_text
        from powerflow_builder.ops_assistant import (
            analyze_flow_run_payload,
            begin_device_code,
            graph_list_mail_messages,
            poll_device_token,
            run_graph_preflight,
            servicedesk_list_requests,
            sharepoint_list_item_create,
            sharepoint_list_item_delete,
            sharepoint_list_item_get,
            sharepoint_list_item_update,
            sharepoint_list_item_upsert_by_field,
            sharepoint_list_items_list,
            sharepoint_resolve_list,
            sharepoint_resolve_site,
        )
    except ImportError:
        from flowfx_compiler import FlowFxError, compile_flowfx_text, pretty_print_help
        from flowfx_validator_pack import run_validator_pack, validate_flowfx_text
        from ops_assistant import (
            analyze_flow_run_payload,
            begin_device_code,
            graph_list_mail_messages,
            poll_device_token,
            run_graph_preflight,
            servicedesk_list_requests,
            sharepoint_list_item_create,
            sharepoint_list_item_delete,
            sharepoint_list_item_get,
            sharepoint_list_item_update,
            sharepoint_list_item_upsert_by_field,
            sharepoint_list_items_list,
            sharepoint_resolve_list,
            sharepoint_resolve_site,
        )


APP_NAME = "CITL Work Ticketing System"
APP_VERSION = "v0.3"
SAFE_MODE_NOTE = (
    "Safe Observation Mode: this app does not store Office 365 credentials. "
    "Use packet imports, webhook observation, and catalog diagnostics first."
)

RTC_ORG = {
    "tenant": "rtc.edu",
    "sharepoint_hostname": "rtcedu.sharepoint.com",
    "sharepoint_site_path": "teams/TheFLEXTeam",
    "sharepoint_site_url": "https://rtcedu.sharepoint.com/teams/TheFLEXTeam",
    "sharepoint_site_prototype_url": "https://rtcedu.sharepoint.com/teams/TheFLEXTeam",
    "default_list": "Test Ticketing Planner",
    "dispatch_email": "flex@rtc.edu",
    "team_id": "",
    "channel_id": "",
    "planner_group_id": "",
    "planner_plan_id": "",
    "flow_name_prefix": "CITL-FLEX Ticketing",
}
SEVERITY_RANK = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "info": 0,
}

_HERE = Path(__file__).resolve().parent
REPO = _HERE.parent
DATA_DIR = REPO / "documents" / "ticketing_system"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "citl_ticketing.db"

ENVS_PATH = DATA_DIR / "environments.json"

for _d in (DATA_DIR, EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# Palette copied from existing CITL Work GUI family.
C = {
    "bg": "#0D1B2A",
    "panel": "#112236",
    "panel_alt": "#162B40",
    "notebk": "#0C1A2C",
    "card_sel": "#1E4060",
    "text": "#D4E4F5",
    "muted": "#7A9BBE",
    "faint": "#3E5A78",
    "accent": "#3A8FD4",
    "gold": "#E89820",
    "btn": "#1A3550",
    "btn_hi": "#235272",
    "btn_acc": "#1A4A7A",
    "btn_gold": "#5A3A00",
    "line": "#1D3050",
    "good": "#1E5C30",
    "warn": "#7A4500",
    "err": "#5C1A1A",
}
FONT = "Segoe UI" if sys.platform == "win32" else "Ubuntu"

OP_CATALOG_SEED: List[Dict[str, Any]] = [
    {
        "connector": "Office 365 Outlook",
        "api_name": "shared_office365",
        "operation_id": "SendEmailV2",
        "command_alias": "EMAIL",
        "required_params": ["to", "subject", "body"],
        "sample_flowfx": 'EMAIL NotifyDispatcher to="flex@rtc.edu" subject="Ticket Update" body="Status update text"',
        "source_url": "https://learn.microsoft.com/en-us/connectors/office365/",
        "last_verified": "2026-04-29",
    },
    {
        "connector": "SharePoint",
        "api_name": "shared_sharepointonline",
        "operation_id": "PostItem",
        "command_alias": "SHAREPOINT_CREATE_ITEM",
        "required_params": ["site", "list", "item"],
        "sample_flowfx": 'SHAREPOINT_CREATE_ITEM CreateListItem site="https://rtcedu.sharepoint.com/teams/TheFLEXTeam" list="Test Ticketing Planner" item=\'{"Title":"Projector broken"}\'',
        "source_url": "https://learn.microsoft.com/en-us/connectors/sharepoint/",
        "last_verified": "2026-04-29",
    },
    {
        "connector": "SharePoint",
        "api_name": "shared_sharepointonline",
        "operation_id": "GetOnNewItems",
        "command_alias": "TRIGGER SHAREPOINT_NEW_ITEM",
        "required_params": ["site", "list"],
        "sample_flowfx": 'TRIGGER SHAREPOINT_NEW_ITEM site="https://rtcedu.sharepoint.com/teams/TheFLEXTeam" list="Test Ticketing Planner"',
        "source_url": "https://learn.microsoft.com/en-us/connectors/sharepoint/",
        "last_verified": "2026-04-29",
    },
    {
        "connector": "Microsoft Teams",
        "api_name": "shared_teams",
        "operation_id": "PostMessageToChannelV3",
        "command_alias": "TEAMS_POST",
        "required_params": ["team_id", "channel_id", "message"],
        "sample_flowfx": 'TEAMS_POST NotifyIT team_id="TEAM_ID" channel_id="CHANNEL_ID" message="New RTC ticket received"',
        "source_url": "https://learn.microsoft.com/en-us/connectors/teams/?tabs=text1",
        "last_verified": "2026-04-29",
    },
    {
        "connector": "Planner",
        "api_name": "shared_planner",
        "operation_id": "CreateTask_V3",
        "command_alias": "PLANNER_CREATE_TASK",
        "required_params": ["group_id", "plan_id", "title"],
        "sample_flowfx": 'PLANNER_CREATE_TASK CreateTask group_id="GROUP_ID" plan_id="PLAN_ID" title="Ticket follow-up"',
        "source_url": "https://learn.microsoft.com/en-gb/connectors/planner/",
        "last_verified": "2026-04-29",
    },
    {
        "connector": "Standard approvals",
        "api_name": "shared_approvals",
        "operation_id": "StartAndWaitForAnApproval",
        "command_alias": "APPROVAL",
        "required_params": ["assigned_to", "title"],
        "sample_flowfx": 'APPROVAL ManagerApproval assigned_to="manager@contoso.edu" title="Approve ticket escalation"',
        "source_url": "https://learn.microsoft.com/en-us/connectors/approvals/",
        "last_verified": "2026-04-29",
    },
    {
        "connector": "Office 365 Outlook",
        "api_name": "shared_office365",
        "operation_id": "OnNewEmailV3",
        "command_alias": "Trigger (Power Automate Designer)",
        "required_params": ["folderPath (recommended)"],
        "sample_flowfx": "Use trigger in designer and filter by folder/from/subject to reduce false positives.",
        "source_url": "https://learn.microsoft.com/en-us/connectors/office365/",
        "last_verified": "2026-04-29",
    },
]

ERROR_CATALOG_SEED: List[Dict[str, Any]] = [
    {
        "product": "Power Automate Cloud Flow",
        "code": "InvalidTemplate",
        "aliases": ["invalidtemplate"],
        "pattern": r"invalidtemplate",
        "category": "definition_schema",
        "severity": "high",
        "summary": "Flow definition contains invalid template/expression structure.",
        "recommendations": [
            "Check expression syntax and action references.",
            "Validate action names in expressions (case-sensitive).",
            "Regenerate JSON with FlowFX compiler to avoid hand-edited structure faults.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "FlowCheckerError",
        "aliases": ["flowcheckererror"],
        "pattern": r"flowcheckererror",
        "category": "definition_schema",
        "severity": "high",
        "summary": "Flow checker found required field/connection/validation issues.",
        "recommendations": [
            "Open checker results and resolve each listed field.",
            "Verify every connector action has an attached connection.",
            "Ensure trigger inputs are fully configured.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "DuplicateActionName",
        "aliases": ["duplicateactionname"],
        "pattern": r"duplicateactionname",
        "category": "definition_schema",
        "severity": "high",
        "summary": "Two or more actions share the same internal action name.",
        "recommendations": [
            "Rename duplicate actions in the same scope.",
            "Update all expression references after rename.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "MissingRequiredProperty",
        "aliases": ["missingrequiredproperty"],
        "pattern": r"missingrequiredproperty",
        "category": "definition_schema",
        "severity": "high",
        "summary": "Required action/trigger field is missing.",
        "recommendations": [
            "Fill all required fields marked by connector action design.",
            "Verify solution environment variables are mapped in target environment.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "ExpressionEvaluationFailed",
        "aliases": ["expressionevaluationfailed"],
        "pattern": r"expressionevaluationfailed",
        "category": "runtime_expression",
        "severity": "high",
        "summary": "Expression failed at runtime due to null/type mismatch.",
        "recommendations": [
            "Use null-safe navigation and coalesce fallbacks.",
            "Validate input types before casting (int/float/json).",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "ContentConversionFailed",
        "aliases": ["contentconversionfailed"],
        "pattern": r"contentconversionfailed",
        "category": "runtime_expression",
        "severity": "high",
        "summary": "Data type conversion failed between actions.",
        "recommendations": [
            "Compare runtime input type to connector expected type.",
            "Normalize with string/int/float/bool/json conversion functions.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "InvalidConnection",
        "aliases": ["invalidconnection"],
        "pattern": r"invalidconnection",
        "category": "connection_reference",
        "severity": "critical",
        "summary": "Connection reference is broken, deleted, or expired.",
        "recommendations": [
            "Rebind or recreate connection reference in the flow/solution.",
            "Repair connection and rerun validation test.",
            "Prefer service principal connections where supported.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "ConnectionNotConfigured",
        "aliases": ["connectionnotconfigured"],
        "pattern": r"connectionnotconfigured",
        "category": "connection_reference",
        "severity": "critical",
        "summary": "Connector action has no selected connection.",
        "recommendations": [
            "Select connection for each unresolved connector action.",
            "Map connection references after import in every target environment.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "ConnectionAuthorizationFailed",
        "aliases": ["connectionauthorizationfailed"],
        "pattern": r"connectionauthorizationfailed",
        "category": "connection_auth",
        "severity": "critical",
        "summary": "Connection exists but stored credentials/token is invalid.",
        "recommendations": [
            "Repair connection (interactive sign-in) and rerun.",
            "Check Entra sign-in logs for CA/MFA/consent blocks.",
            "Rotate service principal secret/certificate if used.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "Unauthorized (401)",
        "aliases": ["unauthorized", "401"],
        "pattern": r"\b401\b|unauthorized",
        "category": "permissions_auth",
        "severity": "critical",
        "summary": "Authentication token invalid/expired or not accepted.",
        "recommendations": [
            "Reauthenticate connection and check token refresh behavior.",
            "Validate caller/owner licensing and connector entitlement.",
            "Review conditional access and tenant restrictions.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "Forbidden (403)",
        "aliases": ["forbidden", "403"],
        "pattern": r"\b403\b|forbidden",
        "category": "permissions_auth",
        "severity": "critical",
        "summary": "Authenticated identity lacks permission for target operation.",
        "recommendations": [
            "Validate DLP policy and connector action allowlist.",
            "Verify SharePoint/Teams/Dataverse rights for connection identity.",
            "Check if premium connector usage requires upgraded license.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "ActionFailed",
        "aliases": ["actionfailed"],
        "pattern": r"actionfailed",
        "category": "downstream_api",
        "severity": "high",
        "summary": "Action wrapper failed; inspect downstream API payload/error details.",
        "recommendations": [
            "Open run history and inspect failed action outputs/body.",
            "Classify by underlying HTTP/error code and remediate accordingly.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "BadRequest (400)",
        "aliases": ["badrequest", "400"],
        "pattern": r"\b400\b|badrequest",
        "category": "downstream_api",
        "severity": "high",
        "summary": "Malformed or invalid request sent to connector API.",
        "recommendations": [
            "Compare sent inputs with connector schema field names/types.",
            "Check for missing required properties and invalid characters.",
            "Trim/truncate oversized text fields for SharePoint list columns.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "NotFound (404)",
        "aliases": ["notfound", "404"],
        "pattern": r"\b404\b|notfound",
        "category": "resource_resolution",
        "severity": "high",
        "summary": "Referenced resource was missing/renamed/deleted.",
        "recommendations": [
            "Revalidate site/list/library/folder IDs and names.",
            "Replace hardcoded resource IDs with dynamic lookup where possible.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "TriggerConditionNotMet",
        "aliases": ["triggerconditionnotmet"],
        "pattern": r"triggerconditionnotmet",
        "category": "trigger_filtering",
        "severity": "medium",
        "summary": "Trigger payload did not satisfy configured trigger condition.",
        "recommendations": [
            "Inspect trigger raw payload and validate field paths.",
            "Temporarily disable condition and retest with known payload.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "ActionTimedOut",
        "aliases": ["actiontimedout"],
        "pattern": r"actiontimedout",
        "category": "timeout",
        "severity": "high",
        "summary": "Action exceeded its configured runtime timeout.",
        "recommendations": [
            "Increase timeout where appropriate.",
            "Reduce payload size and move large file fetch to separate actions.",
            "Use retry policy for transient upstream delays.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "OperationTimedOut",
        "aliases": ["operationtimedout"],
        "pattern": r"operationtimedout",
        "category": "timeout",
        "severity": "high",
        "summary": "Long-running operation/webhook/approval exceeded max wait.",
        "recommendations": [
            "Set explicit timeout and run-after timeout branch handling.",
            "Split long-running process into relay or child-flow pattern.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "WorkflowRunActionRepetitionQuotaExceeded",
        "aliases": ["workflowrunactionrepetitionquotaexceeded"],
        "pattern": r"workflowrunactionrepetitionquotaexceeded",
        "category": "throttling_quota",
        "severity": "high",
        "summary": "Apply-to-each iteration quota exceeded.",
        "recommendations": [
            "Filter data before loops (OData filters/$top).",
            "Batch or partition workload across multiple runs.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "FlowRunQuotaExceeded",
        "aliases": ["flowrunquotaexceeded"],
        "pattern": r"flowrunquotaexceeded",
        "category": "throttling_quota",
        "severity": "high",
        "summary": "Daily action quota exceeded by user/flow tier limits.",
        "recommendations": [
            "Optimize action counts and reduce loop-heavy design.",
            "Evaluate premium/process licensing for sustained volume.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Cloud Flow",
        "code": "DirectApiAuthorizationRequired",
        "aliases": ["directapiauthorizationrequired"],
        "pattern": r"directapiauthorizationrequired",
        "category": "licensing",
        "severity": "critical",
        "summary": "Caller lacks required premium connector entitlement.",
        "recommendations": [
            "Assign required premium/process license to calling identity.",
            "Verify flow owner and trigger caller licensing alignment.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Power Automate Trigger",
        "code": "TriggerInputSchemaMismatch",
        "aliases": ["triggerinputschemamismatch"],
        "pattern": r"triggerinputschemamismatch",
        "category": "trigger_schema",
        "severity": "high",
        "summary": "Incoming trigger body did not match trigger schema definition.",
        "recommendations": [
            "Compare incoming payload against trigger schema exactly.",
            "Regenerate schema from latest producer payload and redeploy.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Microsoft Entra / Power Automate Connections",
        "code": "AADSTS53003",
        "aliases": ["aadsts53003"],
        "pattern": r"aadsts53003",
        "category": "conditional_access",
        "severity": "critical",
        "summary": "Token issuance blocked by Conditional Access policy.",
        "recommendations": [
            "Review Entra sign-in logs for policy causing block.",
            "Align CA policy scope for Power Automate and downstream services.",
            "Check Terms of Use grant controls and interactive consent requirements.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/troubleshoot/power-platform/power-automate/administration/conditional-access-and-multi-factor-authentication-in-flow",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Microsoft Entra / Power Automate Connections",
        "code": "AADSTS50158",
        "aliases": ["aadsts50158"],
        "pattern": r"aadsts50158",
        "category": "conditional_access",
        "severity": "critical",
        "summary": "External security challenge / Terms-of-Use requirement not satisfied.",
        "recommendations": [
            "Require interactive sign-in to satisfy ToU challenge.",
            "Repair or recreate broken connections after policy acceptance.",
            "Exclude service accounts from ToU grant controls where policy allows.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/troubleshoot/power-platform/power-automate/administration/conditional-access-and-multi-factor-authentication-in-flow",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Office 365 Outlook Connector",
        "code": "Specified object was not found in the store",
        "aliases": ["specified object was not found in the store"],
        "pattern": r"specified object was not found in the store",
        "category": "mailbox_folder_resolution",
        "severity": "high",
        "summary": "Mailbox/folder object resolution failure in Outlook connector.",
        "recommendations": [
            "Verify mailbox membership/full access for trigger identity.",
            "Confirm exact folder path/ID in trigger configuration.",
            "Repair/recreate Office 365 connection.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/connectors/office365/",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Office 365 Outlook Connector",
        "code": "Trigger behavior when an email folder is changed",
        "aliases": ["trigger will only check for emails inside folder", "moving an email to another folder"],
        "pattern": r"trigger will only check for emails inside folder|moving an email to another folder",
        "category": "trigger_folder_behavior",
        "severity": "medium",
        "summary": "Email moved between folders can be skipped by trigger design.",
        "recommendations": [
            "Point trigger to final destination folder where messages arrive.",
            "Avoid dependence on move-after-receive semantics for critical intake.",
            "Use additional reconciliation checks for missed messages.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/connectors/office365/",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Office 365 Outlook Connector",
        "code": "Trigger timeout with attachments",
        "aliases": ["include attachments", "attachments array is empty", "connector can timeout while downloading"],
        "pattern": r"include attachments|timeout while downloading",
        "category": "attachment_trigger_timeout",
        "severity": "high",
        "summary": "Attachment-heavy trigger execution timed out or produced partial data.",
        "recommendations": [
            "Set Include Attachments to No at trigger.",
            "Retrieve attachments with Get Attachment action downstream.",
            "Keep mailbox and flow region aligned where possible.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/connectors/office365/",
        "last_verified": "2026-04-29",
    },
    {
        "product": "SharePoint Connector",
        "code": "List view threshold exceeded",
        "aliases": ["list view threshold", "limit columns by view", "threshold issues"],
        "pattern": r"list view threshold|threshold issues|limit columns by view",
        "category": "sharepoint_threshold",
        "severity": "high",
        "summary": "SharePoint list query exceeded threshold or lookup constraints.",
        "recommendations": [
            "Filter and index columns; reduce returned rows/lookup fields.",
            "Use Limit Columns by View and targeted queries.",
            "Split high-volume retrieval into paged windows.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/connectors/sharepoint/",
        "last_verified": "2026-04-29",
    },
    {
        "product": "Platform/Connector",
        "code": "TooManyRequests (429)",
        "aliases": ["429", "too many requests", "rate limit is exceeded"],
        "pattern": r"\b429\b|too many requests|rate limit is exceeded",
        "category": "throttling_quota",
        "severity": "high",
        "summary": "Connector/platform throttling limit hit.",
        "recommendations": [
            "Reduce request burst and apply backoff/retry policy.",
            "Batch actions and reduce high-frequency polling.",
            "Respect connector-specific API throughput limits.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/power-automate/guidance/coding-guidelines/understand-limits",
        "last_verified": "2026-04-29",
    },
    {
        "product": "SharePoint Online",
        "code": "Server Too Busy (503)",
        "aliases": ["503", "server too busy", "service unavailable"],
        "pattern": r"(server too busy|service unavailable|http 503)",
        "category": "throttling_or_service_load",
        "severity": "high",
        "summary": "SharePoint service is overloaded or request pattern is being blocked.",
        "recommendations": [
            "Respect Retry-After exactly; aggressive retries can prolong blocking.",
            "Lower concurrent request fan-out and reduce payload sizes.",
            "Move large batches to off-peak windows where possible.",
        ],
        "source_url": "https://learn.microsoft.com/en-us/sharepoint/dev/general-development/how-to-avoid-getting-throttled-or-blocked-in-sharepoint-online",
        "last_verified": "2026-04-29",
    },
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def extract_email(value: str) -> str:
    if not value:
        return ""
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value)
    return m.group(0).lower() if m else value.strip().lower()


def deep_get(payload: Dict[str, Any], *candidates: str) -> Any:
    for key in candidates:
        parts = key.split(".")
        cur: Any = payload
        ok = True
        for part in parts:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok:
            return cur
    return None


def _decode_sharepoint_internal_name(value: str) -> str:
    text = str(value or "")
    def repl(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)
    return re.sub(r"_x([0-9A-Fa-f]{4})_", repl, text)


def normalize_field_name(name: str) -> str:
    text = _decode_sharepoint_internal_name(str(name or "")).strip().lower()
    text = text.replace("_", " ")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def first_non_empty(mapping: Dict[str, Any], candidates: List[str]) -> str:
    lower_map = {str(k).strip().lower(): v for k, v in mapping.items()}
    norm_map: Dict[str, Any] = {}
    for key, value in mapping.items():
        norm = normalize_field_name(str(key or ""))
        if norm and norm not in norm_map:
            norm_map[norm] = value
    for name in candidates:
        key = str(name or "").strip().lower()
        if not key:
            continue
        value = None
        if key in lower_map:
            value = lower_map[key]
        else:
            norm = normalize_field_name(key)
            if norm in norm_map:
                value = norm_map[norm]
        if value is not None:
            text = str(value if value is not None else "").strip()
            if text:
                return text
    return ""


def normalize_status(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw in {"new", "open", "created"}:
        return "new"
    if raw in {"in progress", "in_progress", "working", "assigned"}:
        return "in_progress"
    if raw in {"pending", "on hold", "awaiting info", "awaiting user"}:
        return "pending"
    if raw in {"resolved", "done", "complete"}:
        return "resolved"
    if raw in {"closed", "cancelled", "canceled"}:
        return "closed"
    return "pending"


def normalize_priority(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw in {"critical", "urgent", "sev1", "p1"}:
        return "critical"
    if raw in {"high", "sev2", "p2"}:
        return "high"
    if raw in {"medium", "normal", "moderate", "sev3", "p3"}:
        return "medium"
    if raw in {"low", "minor", "sev4", "p4"}:
        return "low"
    return "medium"


def coerce_timestamp(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    iso_try = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_try)
        return dt.isoformat(timespec="seconds")
    except Exception:
        pass
    patterns = [
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%m/%d/%Y %I:%M %p",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
    ]
    for pattern in patterns:
        try:
            dt = datetime.strptime(raw, pattern)
            return dt.isoformat(timespec="seconds")
        except Exception:
            continue
    return ""


class TicketStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                requester_name TEXT,
                requester_email TEXT,
                institution_unit TEXT,
                subject TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                priority TEXT NOT NULL DEFAULT 'medium',
                assigned_to TEXT,
                channel TEXT,
                external_ref TEXT,
                intake_confidence REAL NOT NULL DEFAULT 1.0
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                note TEXT NOT NULL,
                actor TEXT,
                FOREIGN KEY(ticket_id) REFERENCES tickets(id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS operation_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                connector TEXT NOT NULL,
                api_name TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                command_alias TEXT NOT NULL,
                required_params_json TEXT NOT NULL,
                sample_flowfx TEXT NOT NULL,
                source_url TEXT NOT NULL,
                last_verified TEXT NOT NULL,
                UNIQUE(connector, operation_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS error_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product TEXT NOT NULL,
                code TEXT NOT NULL,
                aliases_json TEXT NOT NULL,
                pattern TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                summary TEXT NOT NULL,
                recommendations_json TEXT NOT NULL,
                source_url TEXT NOT NULL,
                last_verified TEXT NOT NULL,
                UNIQUE(product, code)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                source_label TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                remote_addr TEXT,
                headers_json TEXT NOT NULL,
                body_text TEXT NOT NULL,
                status_code INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS flow_run_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                source_label TEXT NOT NULL,
                summary TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                analysis_json TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS connection_preflight_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL,
                config_json TEXT NOT NULL,
                result_json TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT ''
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_book_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                ticket_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                UNIQUE(book_id, ticket_id),
                FOREIGN KEY(book_id) REFERENCES ticket_books(id),
                FOREIGN KEY(ticket_id) REFERENCES tickets(id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS db_sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL,
                details_json TEXT NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_updated ON tickets(updated_at)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_ticket_id ON ticket_events(ticket_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_webhook_created ON webhook_events(created_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_flow_run_imports_created ON flow_run_imports(created_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_preflight_created ON connection_preflight_runs(created_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_book_items_book_id ON ticket_book_items(book_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_book_items_ticket_id ON ticket_book_items(ticket_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_db_sync_created ON db_sync_runs(created_at)"
        )
        self.conn.commit()
        self._seed_operation_catalog()
        self._seed_error_catalog()
        self._ensure_default_ticket_books()

    def _seed_operation_catalog(self) -> None:
        cur = self.conn.cursor()
        for row in OP_CATALOG_SEED:
            cur.execute(
                """
                INSERT OR REPLACE INTO operation_catalog (
                    id, connector, api_name, operation_id, command_alias, required_params_json,
                    sample_flowfx, source_url, last_verified
                )
                VALUES (
                    (SELECT id FROM operation_catalog WHERE connector = ? AND operation_id = ?),
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    row["connector"],
                    row["operation_id"],
                    row["connector"],
                    row["api_name"],
                    row["operation_id"],
                    row["command_alias"],
                    json.dumps(row["required_params"]),
                    row["sample_flowfx"],
                    row["source_url"],
                    row["last_verified"],
                ),
            )
        self.conn.commit()

    def _seed_error_catalog(self) -> None:
        cur = self.conn.cursor()
        for row in ERROR_CATALOG_SEED:
            cur.execute(
                """
                INSERT OR REPLACE INTO error_catalog (
                    id, product, code, aliases_json, pattern, category, severity,
                    summary, recommendations_json, source_url, last_verified
                )
                VALUES (
                    (SELECT id FROM error_catalog WHERE product = ? AND code = ?),
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    row["product"],
                    row["code"],
                    row["product"],
                    row["code"],
                    json.dumps(row["aliases"]),
                    row["pattern"],
                    row["category"],
                    row["severity"],
                    row["summary"],
                    json.dumps(row["recommendations"]),
                    row["source_url"],
                    row["last_verified"],
                ),
            )
        self.conn.commit()

    def _ensure_default_ticket_books(self) -> None:
        defaults = [
            ("General Intake", "Default work queue for newly created tickets."),
            ("Escalations", "Critical/high-priority tickets requiring rapid handling."),
            ("Faculty Support", "Faculty-facing support and classroom issues."),
            ("Student Support", "Learner-facing issues and access requests."),
        ]
        ts = now_iso()
        cur = self.conn.cursor()
        for name, desc in defaults:
            cur.execute(
                """
                INSERT OR IGNORE INTO ticket_books (created_at, updated_at, name, description)
                VALUES (?, ?, ?, ?)
                """,
                (ts, ts, name, desc),
            )
        self.conn.commit()

    def create_ticket(self, record: Dict[str, Any], note: str, actor: str = "system") -> int:
        created = now_iso()
        updated = created
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO tickets (
                created_at, updated_at, source, requester_name, requester_email,
                institution_unit, subject, description, status, priority, assigned_to,
                channel, external_ref, intake_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created,
                updated,
                record.get("source", "manual"),
                record.get("requester_name", ""),
                record.get("requester_email", ""),
                record.get("institution_unit", ""),
                record.get("subject", "").strip() or "Untitled Ticket",
                record.get("description", ""),
                record.get("status", "new"),
                record.get("priority", "medium"),
                record.get("assigned_to", ""),
                record.get("channel", ""),
                record.get("external_ref", ""),
                float(record.get("intake_confidence", 1.0)),
            ),
        )
        ticket_id = int(cur.lastrowid)
        self._add_event(ticket_id, "create", note or "Ticket created.", actor=actor, commit=False)
        self.conn.commit()
        return ticket_id

    def update_ticket(
        self, ticket_id: int, record: Dict[str, Any], note: str, actor: str = "system"
    ) -> None:
        updated = now_iso()
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE tickets
            SET
                updated_at = ?,
                requester_name = ?,
                requester_email = ?,
                institution_unit = ?,
                subject = ?,
                description = ?,
                status = ?,
                priority = ?,
                assigned_to = ?,
                source = ?,
                channel = ?,
                external_ref = ?,
                intake_confidence = ?
            WHERE id = ?
            """,
            (
                updated,
                record.get("requester_name", ""),
                record.get("requester_email", ""),
                record.get("institution_unit", ""),
                record.get("subject", "").strip() or "Untitled Ticket",
                record.get("description", ""),
                record.get("status", "new"),
                record.get("priority", "medium"),
                record.get("assigned_to", ""),
                record.get("source", "manual"),
                record.get("channel", ""),
                record.get("external_ref", ""),
                float(record.get("intake_confidence", 1.0)),
                ticket_id,
            ),
        )
        self._add_event(
            ticket_id,
            "update",
            note or "Ticket updated.",
            actor=actor,
            commit=False,
        )
        self.conn.commit()

    def close_ticket(self, ticket_id: int, note: str, actor: str = "system") -> None:
        self.conn.execute(
            "UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?",
            ("closed", now_iso(), ticket_id),
        )
        self._add_event(ticket_id, "close", note or "Ticket closed.", actor=actor, commit=False)
        self.conn.commit()

    def _add_event(
        self, ticket_id: int, event_type: str, note: str, actor: str, commit: bool = True
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO ticket_events (ticket_id, created_at, event_type, note, actor)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ticket_id, now_iso(), event_type, note, actor),
        )
        if commit:
            self.conn.commit()

    def list_tickets(self, status_filter: str = "all") -> List[sqlite3.Row]:
        if status_filter == "all":
            cur = self.conn.execute(
                "SELECT * FROM tickets ORDER BY datetime(updated_at) DESC, id DESC"
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM tickets WHERE status = ? ORDER BY datetime(updated_at) DESC, id DESC",
                (status_filter,),
            )
        return list(cur.fetchall())

    def search_tickets(self, query: str) -> List[sqlite3.Row]:
        q = f"%{query.lower()}%"
        cur = self.conn.execute(
            """
            SELECT * FROM tickets
            WHERE lower(subject) LIKE ? OR lower(description) LIKE ? OR lower(requester_email) LIKE ?
            ORDER BY datetime(updated_at) DESC, id DESC
            """,
            (q, q, q),
        )
        return list(cur.fetchall())

    def get_ticket(self, ticket_id: int) -> Optional[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        return cur.fetchone()

    def find_ticket_by_external_ref(self, source: str, external_ref: str) -> Optional[sqlite3.Row]:
        src = (source or "").strip().lower()
        ref = (external_ref or "").strip().lower()
        if not src or not ref:
            return None
        cur = self.conn.execute(
            """
            SELECT *
            FROM tickets
            WHERE lower(source) = ? AND lower(external_ref) = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (src, ref),
        )
        return cur.fetchone()

    def upsert_ticket_with_external_ref(
        self,
        record: Dict[str, Any],
        note: str,
        actor: str = "import",
    ) -> Dict[str, Any]:
        source = str(record.get("source") or "").strip()
        external_ref = str(record.get("external_ref") or "").strip()
        existing = self.find_ticket_by_external_ref(source, external_ref)
        if existing is not None:
            ticket_id = int(existing["id"])
            self.update_ticket(ticket_id, record, note or "Ticket updated from import.", actor=actor)
            return {"ticket_id": ticket_id, "created": False}
        ticket_id = self.create_ticket(record, note or "Ticket created from import.", actor=actor)
        return {"ticket_id": ticket_id, "created": True}

    def list_events(self, ticket_id: int) -> List[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM ticket_events WHERE ticket_id = ? ORDER BY datetime(created_at) DESC, id DESC",
            (ticket_id,),
        )
        return list(cur.fetchall())

    def summary(self) -> Dict[str, Any]:
        status_counts = dict(
            self.conn.execute(
                "SELECT status, COUNT(*) AS c FROM tickets GROUP BY status"
            ).fetchall()
        )
        priority_counts = dict(
            self.conn.execute(
                "SELECT priority, COUNT(*) AS c FROM tickets GROUP BY priority"
            ).fetchall()
        )
        open_count = self.conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE status != 'closed'"
        ).fetchone()[0]
        total = self.conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        return {
            "total": total,
            "open": open_count,
            "status_counts": status_counts,
            "priority_counts": priority_counts,
        }

    def get_operation(self, connector: str, operation_id: str) -> Optional[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT * FROM operation_catalog
            WHERE lower(connector) = lower(?) AND lower(operation_id) = lower(?)
            """,
            (connector, operation_id),
        )
        return cur.fetchone()

    def list_catalog_connectors(self) -> List[str]:
        cur = self.conn.execute(
            "SELECT DISTINCT connector FROM operation_catalog ORDER BY connector"
        )
        return [r[0] for r in cur.fetchall()]

    def list_operations_by_connector(self, connector: str) -> List[str]:
        cur = self.conn.execute(
            """
            SELECT operation_id
            FROM operation_catalog
            WHERE lower(connector) = lower(?)
            ORDER BY operation_id
            """,
            (connector,),
        )
        return [r[0] for r in cur.fetchall()]

    def list_error_catalog(self) -> List[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT *
            FROM error_catalog
            ORDER BY severity DESC, category, code
            """
        )
        return list(cur.fetchall())

    def add_webhook_event(self, event: Dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO webhook_events (
                created_at, source_label, method, path, remote_addr, headers_json, body_text, status_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get("created_at", now_iso()),
                event.get("source_label", "observer"),
                event.get("method", "GET"),
                event.get("path", "/"),
                event.get("remote_addr", ""),
                json.dumps(event.get("headers", {})),
                event.get("body_text", ""),
                int(event.get("status_code", 200)),
            ),
        )
        self.conn.commit()

    def list_webhook_events(self, limit: int = 200) -> List[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT *
            FROM webhook_events
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return list(cur.fetchall())

    def add_flow_run_import(self, source_label: str, payload: str, analysis: Dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO flow_run_imports (
                created_at, source_label, summary, payload_json, analysis_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                source_label,
                str(analysis.get("summary", "")),
                payload,
                json.dumps(analysis),
            ),
        )
        self.conn.commit()

    def list_flow_run_imports(self, limit: int = 40) -> List[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT *
            FROM flow_run_imports
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return list(cur.fetchall())

    def add_connection_preflight_run(
        self,
        config: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO connection_preflight_runs (
                created_at, summary, status, config_json, result_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                str(result.get("summary", "")),
                str(result.get("overall_status", "unknown")),
                json.dumps(config),
                json.dumps(result),
            ),
        )
        self.conn.commit()

    def list_connection_preflight_runs(self, limit: int = 40) -> List[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT *
            FROM connection_preflight_runs
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return list(cur.fetchall())

    def list_ticket_books(self) -> List[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT
                b.*,
                COUNT(i.id) AS item_count
            FROM ticket_books b
            LEFT JOIN ticket_book_items i
                ON i.book_id = b.id
            GROUP BY b.id
            ORDER BY lower(b.name), b.id
            """
        )
        return list(cur.fetchall())

    def create_ticket_book(self, name: str, description: str = "") -> int:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Book name is required.")
        ts = now_iso()
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO ticket_books (created_at, updated_at, name, description)
            VALUES (?, ?, ?, ?)
            """,
            (ts, ts, clean_name, (description or "").strip()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_ticket_to_book(self, book_id: int, ticket_id: int, note: str = "") -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO ticket_book_items (
                id, book_id, ticket_id, created_at, note
            )
            VALUES (
                (SELECT id FROM ticket_book_items WHERE book_id = ? AND ticket_id = ?),
                ?, ?, ?, ?
            )
            """,
            (
                int(book_id),
                int(ticket_id),
                int(book_id),
                int(ticket_id),
                now_iso(),
                (note or "").strip(),
            ),
        )
        self.conn.commit()

    def remove_ticket_from_book(self, book_id: int, ticket_id: int) -> None:
        self.conn.execute(
            "DELETE FROM ticket_book_items WHERE book_id = ? AND ticket_id = ?",
            (int(book_id), int(ticket_id)),
        )
        self.conn.commit()

    def list_book_items(self, book_id: int, limit: int = 300) -> List[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT
                i.book_id,
                i.ticket_id,
                i.created_at AS linked_at,
                i.note AS link_note,
                t.status,
                t.priority,
                t.subject,
                t.requester_email,
                t.updated_at
            FROM ticket_book_items i
            JOIN tickets t
                ON t.id = i.ticket_id
            WHERE i.book_id = ?
            ORDER BY datetime(t.updated_at) DESC, t.id DESC
            LIMIT ?
            """,
            (int(book_id), int(limit)),
        )
        return list(cur.fetchall())

    def list_table_counts(self) -> Dict[str, int]:
        table_names = [
            "tickets",
            "ticket_events",
            "operation_catalog",
            "error_catalog",
            "webhook_events",
            "flow_run_imports",
            "connection_preflight_runs",
            "ticket_books",
            "ticket_book_items",
            "db_sync_runs",
        ]
        out: Dict[str, int] = {}
        for name in table_names:
            try:
                cur = self.conn.execute(f"SELECT COUNT(*) FROM {name}")
                out[name] = int(cur.fetchone()[0])
            except Exception:
                out[name] = -1
        return out

    def add_db_sync_run(self, mode: str, summary: str, status: str, details: Dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO db_sync_runs (created_at, mode, summary, status, details_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                (mode or "harmonize").strip() or "harmonize",
                (summary or "").strip(),
                (status or "unknown").strip() or "unknown",
                json.dumps(details),
            ),
        )
        self.conn.commit()

    def list_db_sync_runs(self, limit: int = 40) -> List[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT *
            FROM db_sync_runs
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        return list(cur.fetchall())

    def run_db_harmonize(self) -> Dict[str, Any]:
        allowed_status = {"new", "in_progress", "pending", "resolved", "closed"}
        allowed_priority = {"critical", "high", "medium", "low"}
        rows = self.conn.execute("SELECT * FROM tickets ORDER BY id").fetchall()

        changed = 0
        normalized_email = 0
        normalized_status = 0
        normalized_priority = 0
        normalized_subject = 0
        touched_ids: List[int] = []

        for row in rows:
            updates: Dict[str, Any] = {}
            raw_email = str(row["requester_email"] or "")
            clean_email = raw_email.strip().lower()
            if clean_email != raw_email:
                updates["requester_email"] = clean_email
                normalized_email += 1

            raw_status = str(row["status"] or "").strip().lower()
            if raw_status not in allowed_status:
                updates["status"] = "pending"
                normalized_status += 1

            raw_priority = str(row["priority"] or "").strip().lower()
            if raw_priority not in allowed_priority:
                updates["priority"] = "medium"
                normalized_priority += 1

            raw_subject = str(row["subject"] or "")
            clean_subject = raw_subject.strip() or "Untitled Ticket"
            if clean_subject != raw_subject:
                updates["subject"] = clean_subject
                normalized_subject += 1

            raw_assigned = str(row["assigned_to"] or "")
            clean_assigned = raw_assigned.strip()
            if clean_assigned != raw_assigned:
                updates["assigned_to"] = clean_assigned

            if not updates:
                continue
            updates["updated_at"] = now_iso()
            set_cols = ", ".join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values()) + [int(row["id"])]
            self.conn.execute(f"UPDATE tickets SET {set_cols} WHERE id = ?", values)
            changed += 1
            touched_ids.append(int(row["id"]))

        dup_rows = self.conn.execute(
            """
            SELECT
                lower(trim(subject)) AS subject_key,
                lower(trim(requester_email)) AS email_key,
                COUNT(*) AS c
            FROM tickets
            WHERE trim(coalesce(subject, '')) != ''
              AND trim(coalesce(requester_email, '')) != ''
            GROUP BY lower(trim(subject)), lower(trim(requester_email))
            HAVING COUNT(*) > 1
            ORDER BY c DESC
            """
        ).fetchall()
        duplicate_groups = len(dup_rows)
        duplicate_overage = sum(max(0, int(r["c"]) - 1) for r in dup_rows)

        self.conn.commit()
        return {
            "ok": True,
            "total_rows": len(rows),
            "rows_changed": changed,
            "normalized_email": normalized_email,
            "normalized_status": normalized_status,
            "normalized_priority": normalized_priority,
            "normalized_subject": normalized_subject,
            "duplicate_groups": duplicate_groups,
            "duplicate_overage": duplicate_overage,
            "touched_ticket_ids": touched_ids[:100],
        }

    def export_csv(self, out_path: Path) -> None:
        rows = self.list_tickets("all")
        columns = [
            "id",
            "created_at",
            "updated_at",
            "status",
            "priority",
            "subject",
            "requester_name",
            "requester_email",
            "institution_unit",
            "assigned_to",
            "source",
            "channel",
            "external_ref",
            "intake_confidence",
            "description",
        ]
        with out_path.open("w", encoding="utf-8", newline="") as f:
            f.write(",".join(columns) + "\n")
            for row in rows:
                values: List[str] = []
                for col in columns:
                    value = row[col]
                    raw = str(value if value is not None else "")
                    safe = '"' + raw.replace('"', '""') + '"'
                    values.append(safe)
                f.write(",".join(values) + "\n")

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()


def assess_email_intake(payload: Dict[str, Any], allowed_domains: List[str]) -> Dict[str, Any]:
    subject = deep_get(payload, "subject", "body.subject", "Subject") or ""
    sender_raw = (
        deep_get(payload, "from", "body.from", "From")
        or deep_get(payload, "body.from.emailAddress.address")
        or ""
    )
    body_preview = deep_get(payload, "bodyPreview", "body.bodyPreview", "description") or ""
    message_id = deep_get(payload, "id", "body.id", "MessageId") or ""
    requester = extract_email(str(sender_raw))
    flags: List[str] = []
    confidence = 1.0

    if not str(subject).strip():
        flags.append("Missing subject.")
        confidence -= 0.35
    if not requester:
        flags.append("Missing sender email.")
        confidence -= 0.35

    lower_blob = f"{subject} {body_preview}".lower()
    auto_keywords = [
        "automatic reply",
        "auto-reply",
        "out of office",
        "delivery has failed",
        "undeliverable",
        "mailbox full",
    ]
    if any(k in lower_blob for k in auto_keywords):
        flags.append("Likely automated/non-ticket email.")
        confidence -= 0.4

    if requester and allowed_domains:
        domain = requester.split("@")[-1].lower()
        if domain not in allowed_domains:
            flags.append(f"Sender domain not in allowlist: {domain}")
            confidence -= 0.25

    confidence = max(0.0, min(1.0, confidence))
    status = "accept" if confidence >= 0.7 else ("review" if confidence >= 0.4 else "reject")

    parsed = {
        "source": "office365_email",
        "requester_name": requester.split("@")[0] if requester else "",
        "requester_email": requester,
        "institution_unit": "",
        "subject": str(subject).strip() or "[No Subject]",
        "description": str(body_preview).strip(),
        "status": "new",
        "priority": "medium",
        "assigned_to": "",
        "channel": "email",
        "external_ref": str(message_id).strip(),
        "intake_confidence": confidence,
    }

    return {
        "status": status,
        "confidence": confidence,
        "flags": flags,
        "parsed_ticket": parsed,
    }


def _flatten_texts(value: Any, bag: List[str]) -> None:
    if isinstance(value, dict):
        for v in value.values():
            _flatten_texts(v, bag)
        return
    if isinstance(value, list):
        for v in value:
            _flatten_texts(v, bag)
        return
    if isinstance(value, str):
        bag.append(value)


def _extract_codes_and_status(parsed_packet: Dict[str, Any]) -> Tuple[List[str], List[int]]:
    codes: List[str] = []
    statuses: List[int] = []

    def walk(value: Any, key_name: str = "") -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                lk = k.lower()
                if lk == "code" and isinstance(v, str):
                    codes.append(v.strip())
                if lk.endswith("statuscode") or lk == "status":
                    if isinstance(v, int):
                        statuses.append(v)
                    elif isinstance(v, str) and v.strip().isdigit():
                        statuses.append(int(v.strip()))
                walk(v, k)
            return
        if isinstance(value, list):
            for item in value:
                walk(item, key_name)

    walk(parsed_packet)
    uniq_codes = sorted({c for c in codes if c})
    uniq_status = sorted({s for s in statuses})
    return uniq_codes, uniq_status


def _catalog_rows_from_seed() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, row in enumerate(ERROR_CATALOG_SEED, start=1):
        rows.append(
            {
                "id": idx,
                "product": row["product"],
                "code": row["code"],
                "aliases_json": json.dumps(row["aliases"]),
                "pattern": row["pattern"],
                "category": row["category"],
                "severity": row["severity"],
                "summary": row["summary"],
                "recommendations_json": json.dumps(row["recommendations"]),
                "source_url": row["source_url"],
                "last_verified": row["last_verified"],
            }
        )
    return rows


def diagnose_error_packet(raw_text: str, catalog_rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    parsed_packet: Dict[str, Any] = {}
    messages: List[str] = []
    parse_error = ""
    try:
        parsed_packet = json.loads(raw_text)
        _flatten_texts(parsed_packet, messages)
    except Exception as exc:
        parse_error = str(exc)
        messages.append(raw_text)

    blob = "\n".join(messages)
    lower_blob = blob.lower()
    codes, statuses = _extract_codes_and_status(parsed_packet) if parsed_packet else ([], [])
    if not statuses:
        status_hits = re.findall(r"\b([1-5][0-9]{2})\b", blob)
        statuses = sorted({int(s) for s in status_hits})
    if not codes:
        code_hits = re.findall(r"(?:error\s*code|code)\s*[:=]\s*[\"']?([A-Za-z0-9_.() -]{3,80})", blob, flags=re.IGNORECASE)
        aad_hits = re.findall(r"\bAADSTS[0-9]{5}\b", blob, flags=re.IGNORECASE)
        codes = sorted({c.strip() for c in code_hits + aad_hits if c.strip()})
    catalog = catalog_rows if catalog_rows is not None else _catalog_rows_from_seed()

    matches: List[Dict[str, Any]] = []
    for row in catalog:
        code = str(row["code"])
        aliases = json.loads(row["aliases_json"]) if isinstance(row["aliases_json"], str) else row["aliases_json"]
        pattern = str(row["pattern"] or "")
        score = 0
        evidence: List[str] = []

        if any(code.lower() == c.lower() for c in codes):
            score += 100
            evidence.append(f"Exact code match: {code}")
        for alias in aliases:
            if any(alias.lower() == c.lower() for c in codes):
                score = max(score, 95)
                evidence.append(f"Alias code match: {alias}")
        if pattern:
            try:
                if re.search(pattern, lower_blob, flags=re.IGNORECASE):
                    score += 60
                    evidence.append(f"Pattern match: {pattern}")
            except re.error:
                if pattern.lower() in lower_blob:
                    score += 50
                    evidence.append(f"Literal pattern match: {pattern}")
        if "401" in aliases and 401 in statuses:
            score = max(score, 90)
            evidence.append("HTTP statusCode 401 detected.")
        if "403" in aliases and 403 in statuses:
            score = max(score, 90)
            evidence.append("HTTP statusCode 403 detected.")
        if "400" in aliases and 400 in statuses:
            score = max(score, 88)
            evidence.append("HTTP statusCode 400 detected.")
        if "404" in aliases and 404 in statuses:
            score = max(score, 88)
            evidence.append("HTTP statusCode 404 detected.")
        if "429" in aliases and 429 in statuses:
            score = max(score, 88)
            evidence.append("HTTP statusCode 429 detected.")
        if "503" in aliases and 503 in statuses:
            score = max(score, 88)
            evidence.append("HTTP statusCode 503 detected.")

        if score > 0:
            recommendations = (
                json.loads(row["recommendations_json"])
                if isinstance(row["recommendations_json"], str)
                else row["recommendations_json"]
            )
            matches.append(
                {
                    "score": score,
                    "product": row["product"],
                    "code": code,
                    "category": row["category"],
                    "severity": row["severity"],
                    "summary": row["summary"],
                    "evidence": evidence,
                    "recommended_actions": recommendations,
                    "source_url": row["source_url"],
                    "last_verified": row["last_verified"],
                }
            )

    matches.sort(
        key=lambda m: (m["score"], SEVERITY_RANK.get(str(m["severity"]).lower(), 0)),
        reverse=True,
    )
    top = matches[:6]
    exact = [m for m in matches if m["score"] >= 95]
    ambiguity = len(exact) > 1 or (not exact and len(top) > 1 and top[0]["score"] == top[1]["score"])
    if len(exact) == 1:
        determinism = "deterministic"
    elif ambiguity:
        determinism = "ambiguous"
    elif top and top[0]["score"] >= 60:
        determinism = "probable"
    else:
        determinism = "low_confidence"

    if not top:
        top = [
            {
                "score": 10,
                "product": "Unclassified",
                "code": "Unknown",
                "category": "unclassified",
                "severity": "medium",
                "summary": "No known signature matched this packet.",
                "evidence": ["No catalog hit."],
                "recommended_actions": [
                    "Capture full run history including connector action outputs and headers.",
                    "Include error.code, statusCode, and operation name, then rerun diagnostics.",
                ],
                "source_url": "https://learn.microsoft.com/en-us/power-automate/error-reference",
                "last_verified": "2026-04-29",
            }
        ]

    summary_line = (
        f"Top diagnosis: {top[0]['code']} [{top[0]['category']}] "
        f"(score={top[0]['score']}, severity={top[0]['severity']})."
    )
    if ambiguity:
        summary_line += " Multiple plausible root causes detected; check additional evidence fields."

    return {
        "packet_detected_as_json": bool(parsed_packet),
        "json_parse_error": parse_error,
        "detected_error_codes": codes,
        "detected_status_codes": statuses,
        "determinism": determinism,
        "ambiguity_detected": ambiguity,
        "operator_summary": summary_line,
        "matched_definitions": top,
    }


def build_permissions_checklist(connector: str) -> Dict[str, Any]:
    c = connector.strip().lower()
    base = {
        "tenant_checks": [
            "Connection owner account is enabled and not blocked by Conditional Access.",
            "Connector is allowed by DLP policy in this environment.",
            "Flow owner/caller licensing supports all used connectors.",
        ],
        "connector_checks": [],
    }
    if "sharepoint" in c:
        base["connector_checks"] = [
            "Connection identity has at least read/write rights for target site/list/library.",
            "List/library exists in same environment and has expected schema/column names.",
            "Large list queries are indexed and filtered to avoid threshold failures.",
        ]
    elif "office" in c or "outlook" in c or "mail" in c:
        base["connector_checks"] = [
            "Mailbox exists and trigger folder is exactly the mailbox folder receiving mail.",
            "For shared mailbox triggers, identity has required mailbox access level.",
            "Include Attachments trigger setting is minimized to reduce timeout risk.",
        ]
    elif "teams" in c:
        base["connector_checks"] = [
            "Identity has rights to post in target team/channel.",
            "Team and channel IDs are current (not deleted/renamed).",
        ]
    elif "planner" in c:
        base["connector_checks"] = [
            "Identity has access to group/plan and task creation rights.",
            "Plan and bucket IDs are valid in target environment.",
        ]
    else:
        base["connector_checks"] = [
            "Validate operation-specific permissions for this connector.",
            "Confirm connection reference points to valid active connection.",
        ]
    return base


def build_observer_handler(app: "TicketingApp"):
    class ObserverHandler(BaseHTTPRequestHandler):
        def _handle(self, body_required: bool) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            body_bytes = self.rfile.read(length) if length > 0 else b""
            body_text = body_bytes.decode("utf-8", errors="replace")
            shared_token = app.webhook_token_var.get().strip()
            got_token = self.headers.get("X-CITL-Token", "")
            expected = app.webhook_path_var.get().strip() or "/"
            if not expected.startswith("/"):
                expected = "/" + expected
            req_path = self.path.split("?", 1)[0]
            status_code = 200
            reason = "ok"
            if req_path != expected:
                status_code = 404
                reason = "path_mismatch"
            if shared_token and got_token != shared_token:
                status_code = 403
                reason = "token_mismatch"

            event = {
                "created_at": now_iso(),
                "source_label": "local_observer",
                "method": self.command,
                "path": self.path,
                "remote_addr": str(self.client_address[0] if self.client_address else ""),
                "headers": {k: v for k, v in self.headers.items()},
                "body_text": body_text,
                "status_code": status_code,
                "observer_reason": reason,
            }
            app.webhook_queue.put(event)
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "observer": "CITL Ticketing GUI",
                "status": "ok" if status_code == 200 else "rejected",
                "reason": reason,
                "expected_path": expected,
                "timestamp": now_iso(),
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802
            self._handle(body_required=False)

        def do_POST(self) -> None:  # noqa: N802
            self._handle(body_required=True)

        def do_PUT(self) -> None:  # noqa: N802
            self._handle(body_required=True)

        def do_PATCH(self) -> None:  # noqa: N802
            self._handle(body_required=True)

        def do_DELETE(self) -> None:  # noqa: N802
            self._handle(body_required=False)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return ObserverHandler


def build_ticket_flowfx_template(values: Dict[str, str]) -> str:
    return f"""FLOW "{values.get('flow_name', 'CITL Ticket Intake Flow')}"
TRIGGER SHAREPOINT_NEW_ITEM site="{values.get('sharepoint_site', RTC_ORG['sharepoint_site_url'])}" list="{values.get('sharepoint_list', RTC_ORG['default_list'])}"
SET TEAM_ID="{values.get('team_id', 'TEAM_ID_HERE')}"
SET CHANNEL_ID="{values.get('channel_id', 'CHANNEL_ID_HERE')}"
SET DISPATCH_EMAIL="{values.get('dispatch_email', RTC_ORG['dispatch_email'])}"
SET GROUP_ID="{values.get('planner_group_id', 'PLANNER_GROUP_ID')}"
SET PLAN_ID="{values.get('planner_plan_id', 'PLANNER_PLAN_ID')}"

COMPOSE TicketSummary text="fx:concat('Ticket #', string(triggerBody()?['ID']), ' | ', coalesce(triggerBody()?['Title'],'No title'))"
TEAMS_POST NotifyITTeam team_id="${{TEAM_ID}}" channel_id="${{CHANNEL_ID}}" message="fx:outputs('TicketSummary')"
EMAIL NotifyDispatcher to="${{DISPATCH_EMAIL}}" subject="fx:concat('New Service Ticket #', string(triggerBody()?['ID']))" body="fx:concat('A new ticket was captured from Microsoft Lists. Title: ', coalesce(triggerBody()?['Title'],'No title'))"
PLANNER_CREATE_TASK CreatePlannerTask group_id="${{GROUP_ID}}" plan_id="${{PLAN_ID}}" title="fx:concat('Ticket #', string(triggerBody()?['ID']), ' - ', coalesce(triggerBody()?['Title'],'No title'))"
"""


class TicketingApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1260x860")
        self.minsize(1120, 780)
        self.configure(bg=C["bg"])
        self.store = TicketStore(DB_PATH)
        self.current_ticket_id: Optional[int] = None
        self.latest_intake: Optional[Dict[str, Any]] = None
        self.latest_run_import: Optional[Dict[str, Any]] = None
        self.device_code_session: Optional[Dict[str, Any]] = None
        self.webhook_server: Optional[ThreadingHTTPServer] = None
        self.webhook_thread: Optional[threading.Thread] = None
        self.webhook_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._closing = False
        self.protocol("WM_DELETE_WINDOW", self.on_app_close)
        self._build_ui()
        self.refresh_ticket_table()
        self.refresh_report_summary()
        self.after(800, self._poll_webhook_queue)

    def _build_ui(self) -> None:
        self._build_header()
        self.status_var = tk.StringVar(value="Ready.")
        self._build_notebook()
        tk.Label(
            self,
            textvariable=self.status_var,
            bg=C["panel"],
            fg=C["muted"],
            font=(FONT, 9),
            anchor="w",
            padx=12,
        ).pack(fill="x", side="bottom")

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=C["panel"], pady=8)
        header.pack(fill="x")
        tk.Label(
            header,
            text=APP_NAME,
            font=(FONT, 16, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=16)
        tk.Label(
            header,
            text=APP_VERSION,
            font=(FONT, 10),
            bg=C["panel"],
            fg=C["muted"],
        ).pack(side="left")
        tk.Label(
            header,
            text="Service Desk Tracking + Flow Automation Builder",
            font=(FONT, 10),
            bg=C["panel"],
            fg=C["muted"],
        ).pack(side="right", padx=16)

    def _build_notebook(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background=C["bg"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=C["btn"],
            foreground=C["text"],
            padding=[12, 6],
            font=(FONT, 10, "bold"),
        )
        style.map("TNotebook.Tab", background=[("selected", C["accent"])])
        style.configure(
            "Treeview",
            background=C["notebk"],
            fieldbackground=C["notebk"],
            foreground=C["text"],
            rowheight=22,
            font=(FONT, 9),
        )
        style.configure(
            "Treeview.Heading",
            background=C["panel_alt"],
            foreground=C["text"],
            font=(FONT, 9, "bold"),
        )
        style.map("Treeview", background=[("selected", C["card_sel"])])

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.notebook = notebook

        self._tab_tickets(notebook)
        self._tab_ticket_books(notebook)
        self._tab_table_launcher(notebook)
        self._tab_db_sync_harmonize(notebook)
        self._tab_intake_qa(notebook)
        self._tab_environments(notebook)
        self._tab_flow_builder(notebook)
        self._tab_flow_run_import(notebook)
        self._tab_packet_diagnostics(notebook)
        self._tab_connection_preflight(notebook)
        self._tab_sharepoint_crud(notebook)
        self._tab_webhook_monitor(notebook)
        self._tab_reports(notebook)

    def _tab_tickets(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Ticket Desk  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="Professional Ticketing Workspace",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)

        body = tk.Frame(frame, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=10, pady=8)

        left = tk.Frame(body, bg=C["panel"], width=820)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        toolbar = tk.Frame(left, bg=C["panel_alt"], pady=6)
        toolbar.pack(fill="x", padx=8, pady=8)
        self.ticket_filter_var = tk.StringVar(value="all")
        ttk.Combobox(
            toolbar,
            textvariable=self.ticket_filter_var,
            values=["all", "new", "in_progress", "pending", "resolved", "closed"],
            width=14,
            state="readonly",
        ).pack(side="left", padx=6)
        tk.Button(
            toolbar,
            text="Refresh",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.refresh_ticket_table,
        ).pack(side="left", padx=4)
        tk.Button(
            toolbar,
            text="Search",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.search_tickets,
        ).pack(side="left", padx=4)
        self.search_var = tk.StringVar()
        tk.Entry(
            toolbar,
            textvariable=self.search_var,
            width=30,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=6)

        cols = ("id", "status", "priority", "subject", "requester_email", "assigned_to", "updated_at")
        self.ticket_tree = ttk.Treeview(left, columns=cols, show="headings")
        labels = {
            "id": "ID",
            "status": "Status",
            "priority": "Priority",
            "subject": "Subject",
            "requester_email": "Requester",
            "assigned_to": "Assigned",
            "updated_at": "Updated",
        }
        widths = {"id": 52, "status": 90, "priority": 80, "subject": 260, "requester_email": 190, "assigned_to": 140, "updated_at": 150}
        for col in cols:
            self.ticket_tree.heading(col, text=labels[col])
            self.ticket_tree.column(col, width=widths[col], anchor="w")
        self.ticket_tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.ticket_tree.bind("<<TreeviewSelect>>", self.on_ticket_select)

        right = tk.Frame(body, bg=C["panel"], width=400)
        right.pack(side="left", fill="both")
        right.pack_propagate(False)

        form = tk.Frame(right, bg=C["panel"], padx=10, pady=8)
        form.pack(fill="both", expand=True)
        self.form_vars: Dict[str, tk.StringVar] = {
            "subject": tk.StringVar(),
            "requester_name": tk.StringVar(),
            "requester_email": tk.StringVar(),
            "institution_unit": tk.StringVar(),
            "assigned_to": tk.StringVar(),
            "status": tk.StringVar(value="new"),
            "priority": tk.StringVar(value="medium"),
            "source": tk.StringVar(value="manual"),
            "channel": tk.StringVar(value="manual"),
            "external_ref": tk.StringVar(),
        }

        self._add_form_row(form, "Subject", "subject")
        self._add_form_row(form, "Requester Name", "requester_name")
        self._add_form_row(form, "Requester Email", "requester_email")
        self._add_form_row(form, "Unit/Department", "institution_unit")
        self._add_form_row(form, "Assigned To", "assigned_to")
        self._add_form_combo(
            form, "Status", "status", ["new", "in_progress", "pending", "resolved", "closed"]
        )
        self._add_form_combo(form, "Priority", "priority", ["low", "medium", "high", "critical"])
        self._add_form_row(form, "Source", "source")
        self._add_form_row(form, "Channel", "channel")
        self._add_form_row(form, "External Ref", "external_ref")

        tk.Label(
            form, text="Description", bg=C["panel"], fg=C["text"], font=(FONT, 9, "bold")
        ).pack(anchor="w", pady=(8, 2))
        self.desc_text = scrolledtext.ScrolledText(
            form,
            height=8,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=(FONT, 9),
            relief="flat",
        )
        self.desc_text.pack(fill="x")

        tk.Label(
            form, text="Update Note", bg=C["panel"], fg=C["text"], font=(FONT, 9, "bold")
        ).pack(anchor="w", pady=(8, 2))
        self.note_text = scrolledtext.ScrolledText(
            form,
            height=4,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=(FONT, 9),
            relief="flat",
        )
        self.note_text.pack(fill="x")

        btn_row = tk.Frame(form, bg=C["panel"], pady=8)
        btn_row.pack(fill="x")
        tk.Button(
            btn_row,
            text="New Ticket",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.clear_form,
        ).pack(side="left", padx=4)
        tk.Button(
            btn_row,
            text="Create",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.create_ticket,
        ).pack(side="left", padx=4)
        tk.Button(
            btn_row,
            text="Update",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.update_ticket,
        ).pack(side="left", padx=4)
        tk.Button(
            btn_row,
            text="Close Ticket",
            bg=C["btn_gold"],
            fg=C["gold"],
            relief="flat",
            command=self.close_ticket,
        ).pack(side="left", padx=4)

        tk.Label(
            form, text="Ticket History", bg=C["panel"], fg=C["text"], font=(FONT, 9, "bold")
        ).pack(anchor="w", pady=(6, 2))
        self.history_text = scrolledtext.ScrolledText(
            form,
            height=9,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 8),
            relief="flat",
        )
        self.history_text.pack(fill="both", expand=True)

    def _tab_ticket_books(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Ticket Books  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="Ticket Books",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)
        tk.Label(
            top,
            text="Curated ticket groupings for dispatch handoff and recurring workflows.",
            font=(FONT, 9),
            bg=C["panel"],
            fg=C["muted"],
        ).pack(side="right", padx=12)

        controls = tk.Frame(frame, bg=C["bg"], pady=6)
        controls.pack(fill="x", padx=10)

        tk.Label(controls, text="Book", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        self.ticket_book_choice_var = tk.StringVar()
        self.ticket_book_combo = ttk.Combobox(
            controls,
            textvariable=self.ticket_book_choice_var,
            values=[],
            width=42,
            state="readonly",
        )
        self.ticket_book_combo.pack(side="left", padx=6)
        self.ticket_book_combo.bind("<<ComboboxSelected>>", self.on_ticket_book_change)
        tk.Button(
            controls,
            text="Refresh Books",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.refresh_ticket_books,
        ).pack(side="left", padx=4)

        tk.Label(controls, text="Ticket ID", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(
            side="left", padx=(14, 2)
        )
        self.ticket_book_ticket_id_var = tk.StringVar(value="")
        tk.Entry(
            controls,
            textvariable=self.ticket_book_ticket_id_var,
            width=10,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=2)
        tk.Button(
            controls,
            text="Assign Ticket",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.assign_ticket_to_current_book,
        ).pack(side="left", padx=4)
        tk.Button(
            controls,
            text="Remove Selected",
            bg=C["btn_gold"],
            fg=C["gold"],
            relief="flat",
            command=self.remove_selected_ticket_from_book,
        ).pack(side="left", padx=4)

        create_row = tk.Frame(frame, bg=C["bg"], pady=2)
        create_row.pack(fill="x", padx=10)
        tk.Label(create_row, text="New Book", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        self.ticket_book_new_name_var = tk.StringVar()
        tk.Entry(
            create_row,
            textvariable=self.ticket_book_new_name_var,
            width=28,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=6)
        tk.Label(create_row, text="Description", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        self.ticket_book_new_desc_var = tk.StringVar()
        tk.Entry(
            create_row,
            textvariable=self.ticket_book_new_desc_var,
            width=52,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=6)
        tk.Button(
            create_row,
            text="Create Book",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.create_ticket_book_from_ui,
        ).pack(side="left", padx=4)

        body = tk.Frame(frame, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=10, pady=(2, 8))
        cols = ("ticket_id", "status", "priority", "subject", "requester_email", "updated_at", "linked_at")
        self.ticket_book_tree = ttk.Treeview(body, columns=cols, show="headings")
        labels = {
            "ticket_id": "Ticket",
            "status": "Status",
            "priority": "Priority",
            "subject": "Subject",
            "requester_email": "Requester",
            "updated_at": "Updated",
            "linked_at": "Linked",
        }
        widths = {
            "ticket_id": 70,
            "status": 100,
            "priority": 90,
            "subject": 360,
            "requester_email": 220,
            "updated_at": 150,
            "linked_at": 150,
        }
        for col in cols:
            self.ticket_book_tree.heading(col, text=labels[col])
            self.ticket_book_tree.column(col, width=widths[col], anchor="w")
        self.ticket_book_tree.pack(fill="both", expand=True)
        self.ticket_book_tree.bind("<Double-1>", self.jump_to_ticket_from_book)
        self.ticket_book_id_map: Dict[str, int] = {}
        self.refresh_ticket_books()

    def _tab_table_launcher(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Table Launcher  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="Table Launcher",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)
        tk.Label(
            top,
            text="Fast launch rail for local DB tables, harmonization, and ticket books.",
            font=(FONT, 9),
            bg=C["panel"],
            fg=C["muted"],
        ).pack(side="right", padx=12)

        btns = tk.Frame(frame, bg=C["bg"], pady=8)
        btns.pack(fill="x", padx=10)
        tk.Button(
            btns,
            text="Open Ticket Desk",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=lambda: self.select_notebook_tab("Ticket Desk"),
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Open Ticket Books",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=lambda: self.select_notebook_tab("Ticket Books"),
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Open DB Sync / Harmonize",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=lambda: self.select_notebook_tab("DB Sync"),
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Open SharePoint CRUD",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=lambda: self.select_notebook_tab("SharePoint CRUD"),
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Refresh Table Map",
            bg=C["btn_gold"],
            fg=C["gold"],
            relief="flat",
            command=self.refresh_table_launcher,
        ).pack(side="left", padx=12)

        self.table_launcher_output = scrolledtext.ScrolledText(
            frame,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 10),
            wrap="none",
        )
        self.table_launcher_output.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.refresh_table_launcher()

    def _tab_db_sync_harmonize(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  DB Sync / Harmonize  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="DB Sync / Harmonize",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)
        tk.Label(
            top,
            text="Normalize local records, detect duplicate keys, and keep an auditable sync log.",
            font=(FONT, 9),
            bg=C["panel"],
            fg=C["muted"],
        ).pack(side="right", padx=12)

        btns = tk.Frame(frame, bg=C["bg"], pady=8)
        btns.pack(fill="x", padx=10)
        tk.Button(
            btns,
            text="Run Harmonize",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.run_db_harmonize_now,
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Refresh Sync History",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.refresh_db_sync_history,
        ).pack(side="left", padx=4)

        self.db_sync_output = scrolledtext.ScrolledText(
            frame,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.db_sync_output.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.refresh_db_sync_history()

    def _add_form_row(self, parent: tk.Frame, label: str, key: str) -> None:
        tk.Label(parent, text=label, bg=C["panel"], fg=C["muted"], font=(FONT, 9)).pack(
            anchor="w", pady=(5, 1)
        )
        tk.Entry(
            parent,
            textvariable=self.form_vars[key],
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
            font=(FONT, 9),
        ).pack(fill="x")

    def _add_form_combo(self, parent: tk.Frame, label: str, key: str, options: List[str]) -> None:
        tk.Label(parent, text=label, bg=C["panel"], fg=C["muted"], font=(FONT, 9)).pack(
            anchor="w", pady=(5, 1)
        )
        ttk.Combobox(
            parent,
            textvariable=self.form_vars[key],
            values=options,
            state="readonly",
        ).pack(fill="x")

    def _tab_intake_qa(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Intake QA  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="Email Intake Validator (False Scrape Guardrail)",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)

        controls = tk.Frame(frame, bg=C["bg"], pady=6)
        controls.pack(fill="x", padx=10)
        tk.Label(
            controls,
            text="Allowlist Domains (comma-separated):",
            bg=C["bg"],
            fg=C["muted"],
            font=(FONT, 9),
        ).pack(side="left")
        self.allowlist_var = tk.StringVar(value="rtc.edu,rtcedu.sharepoint.com")
        tk.Entry(
            controls,
            textvariable=self.allowlist_var,
            width=56,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=6)
        tk.Button(
            controls,
            text="Validate Payload",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.validate_intake_payload,
        ).pack(side="left", padx=4)
        tk.Button(
            controls,
            text="Create Ticket From Intake",
            bg=C["btn_gold"],
            fg=C["gold"],
            relief="flat",
            command=self.create_ticket_from_intake,
        ).pack(side="left", padx=4)

        split = tk.PanedWindow(frame, orient=tk.HORIZONTAL, bg=C["bg"], sashwidth=6)
        split.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        left = tk.Frame(split, bg=C["panel"])
        right = tk.Frame(split, bg=C["panel"])
        split.add(left, stretch="always")
        split.add(right, stretch="always")

        tk.Label(
            left, text="Raw Payload JSON", bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold")
        ).pack(anchor="w", padx=8, pady=(8, 2))
        self.intake_input = scrolledtext.ScrolledText(
            left,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.intake_input.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.intake_input.insert(
            "1.0",
            json.dumps(
                {
                    "body": {
                        "id": "AAMkExampleMessageId",
                        "subject": "Projector in Room 204 not powering on",
                        "from": "Instructor Name <instructor@weducation.edu>",
                        "bodyPreview": "Projector will not turn on before class at 9am.",
                    }
                },
                indent=2,
            ),
        )

        tk.Label(
            right, text="Validation Result", bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold")
        ).pack(anchor="w", padx=8, pady=(8, 2))
        self.intake_output = scrolledtext.ScrolledText(
            right,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.intake_output.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _tab_environments(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Environments  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="Prototype / Live Environment Profiles",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)
        tk.Label(
            top,
            text=SAFE_MODE_NOTE,
            font=(FONT, 9),
            bg=C["panel"],
            fg=C["muted"],
        ).pack(side="right", padx=12)

        body = tk.Frame(frame, bg=C["bg"], padx=12, pady=10)
        body.pack(fill="both", expand=True)

        self.env_mode_var = tk.StringVar(value="prototype")
        mode_row = tk.Frame(body, bg=C["bg"])
        mode_row.pack(fill="x")
        tk.Label(mode_row, text="Active Mode:", bg=C["bg"], fg=C["muted"], font=(FONT, 10, "bold")).pack(
            side="left"
        )
        tk.Radiobutton(
            mode_row,
            text="Prototype",
            variable=self.env_mode_var,
            value="prototype",
            bg=C["bg"],
            fg=C["text"],
            selectcolor=C["panel_alt"],
            activebackground=C["bg"],
        ).pack(side="left", padx=8)
        tk.Radiobutton(
            mode_row,
            text="Live",
            variable=self.env_mode_var,
            value="live",
            bg=C["bg"],
            fg=C["text"],
            selectcolor=C["panel_alt"],
            activebackground=C["bg"],
        ).pack(side="left", padx=8)

        self.env_profile_vars = {
            "prototype_site": tk.StringVar(value=RTC_ORG["sharepoint_site_prototype_url"]),
            "prototype_list": tk.StringVar(value=f"{RTC_ORG['default_list']}Prototype"),
            "live_site": tk.StringVar(value=RTC_ORG["sharepoint_site_url"]),
            "live_list": tk.StringVar(value=RTC_ORG["default_list"]),
            "dispatch_email": tk.StringVar(value=RTC_ORG["dispatch_email"]),
            "flow_name_prefix": tk.StringVar(value=RTC_ORG["flow_name_prefix"]),
        }

        for label, key in (
            ("Prototype SharePoint Site", "prototype_site"),
            ("Prototype List", "prototype_list"),
            ("Live SharePoint Site", "live_site"),
            ("Live List", "live_list"),
            ("Dispatch Email", "dispatch_email"),
            ("Flow Name Prefix", "flow_name_prefix"),
        ):
            row = tk.Frame(body, bg=C["bg"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=28, anchor="w", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(
                side="left"
            )
            tk.Entry(
                row,
                textvariable=self.env_profile_vars[key],
                bg=C["notebk"],
                fg=C["text"],
                insertbackground=C["text"],
                relief="flat",
            ).pack(side="left", fill="x", expand=True)

        btns = tk.Frame(body, bg=C["bg"], pady=8)
        btns.pack(fill="x")
        tk.Button(
            btns,
            text="Apply Active Profile To Flow Builder",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.apply_environment_to_flow_builder,
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Show Active Profile JSON",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.show_active_environment_profile,
        ).pack(side="left", padx=4)

        self.env_output = scrolledtext.ScrolledText(
            body,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
            height=14,
        )
        self.env_output.pack(fill="both", expand=True, pady=(6, 0))

    def _tab_webhook_monitor(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Webhook Monitor  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="Webhook Observation & Probe",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)
        tk.Label(
            top,
            text="No credential storage. Use for observation/prototyping before live binding.",
            font=(FONT, 9),
            bg=C["panel"],
            fg=C["muted"],
        ).pack(side="right", padx=12)

        controls = tk.Frame(frame, bg=C["bg"], pady=6)
        controls.pack(fill="x", padx=10)
        self.webhook_port_var = tk.StringVar(value="8787")
        self.webhook_path_var = tk.StringVar(value="/citl-hook")
        self.webhook_token_var = tk.StringVar(value="")
        self.webhook_bind_var = tk.StringVar(value="localhost")
        self.webhook_probe_url_var = tk.StringVar(value="https://example.com/webhook")
        self.webhook_probe_method_var = tk.StringVar(value="GET")

        tk.Label(controls, text="Local Port", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        tk.Entry(
            controls,
            textvariable=self.webhook_port_var,
            width=8,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=4)
        tk.Label(controls, text="Path", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        tk.Entry(
            controls,
            textvariable=self.webhook_path_var,
            width=16,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=4)
        tk.Label(controls, text="Bind", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        ttk.Combobox(
            controls,
            textvariable=self.webhook_bind_var,
            values=["localhost", "all_interfaces"],
            state="readonly",
            width=14,
        ).pack(side="left", padx=4)
        tk.Label(controls, text="X-CITL-Token", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        tk.Entry(
            controls,
            textvariable=self.webhook_token_var,
            width=18,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
            show="*",
        ).pack(side="left", padx=4)
        tk.Button(
            controls,
            text="Start Observer",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.start_webhook_observer,
        ).pack(side="left", padx=4)
        tk.Button(
            controls,
            text="Stop Observer",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.stop_webhook_observer,
        ).pack(side="left", padx=4)

        probe = tk.Frame(frame, bg=C["bg"], pady=6)
        probe.pack(fill="x", padx=10)
        tk.Label(probe, text="Probe URL", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        tk.Entry(
            probe,
            textvariable=self.webhook_probe_url_var,
            width=58,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=4)
        ttk.Combobox(
            probe,
            textvariable=self.webhook_probe_method_var,
            values=["GET", "POST"],
            state="readonly",
            width=7,
        ).pack(side="left", padx=4)
        tk.Button(
            probe,
            text="Run Probe",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.run_webhook_probe,
        ).pack(side="left", padx=4)
        tk.Button(
            probe,
            text="Refresh Event Log",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.refresh_webhook_event_log,
        ).pack(side="left", padx=4)

        split = tk.PanedWindow(frame, orient=tk.HORIZONTAL, bg=C["bg"], sashwidth=6)
        split.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        left = tk.Frame(split, bg=C["panel"])
        right = tk.Frame(split, bg=C["panel"])
        split.add(left, stretch="always")
        split.add(right, stretch="always")

        tk.Label(
            left, text="Observer Runtime Log", bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold")
        ).pack(anchor="w", padx=8, pady=(8, 2))
        self.webhook_runtime_output = scrolledtext.ScrolledText(
            left,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.webhook_runtime_output.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        tk.Label(
            right, text="Persisted Webhook Events", bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold")
        ).pack(anchor="w", padx=8, pady=(8, 2))
        self.webhook_event_output = scrolledtext.ScrolledText(
            right,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.webhook_event_output.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _tab_flow_builder(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Flow Builder  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="Flow-Aware Builder (FlowFX -> Power Automate JSON)",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)

        cfg = tk.Frame(frame, bg=C["bg"], pady=6)
        cfg.pack(fill="x", padx=10)
        self.flow_cfg_vars = {
            "flow_name": tk.StringVar(value="CITL Ticket Intake Flow"),
            "sharepoint_site": tk.StringVar(value=RTC_ORG["sharepoint_site_url"]),
            "sharepoint_list": tk.StringVar(value=RTC_ORG["default_list"]),
            "dispatch_email": tk.StringVar(value=RTC_ORG["dispatch_email"]),
            "team_id": tk.StringVar(value=RTC_ORG["team_id"] or "TEAM_ID_HERE"),
            "channel_id": tk.StringVar(value=RTC_ORG["channel_id"] or "CHANNEL_ID_HERE"),
            "planner_group_id": tk.StringVar(value=RTC_ORG["planner_group_id"] or "PLANNER_GROUP_ID"),
            "planner_plan_id": tk.StringVar(value=RTC_ORG["planner_plan_id"] or "PLANNER_PLAN_ID"),
        }
        self._flow_cfg_row(cfg, "Flow Name", "flow_name")
        self._flow_cfg_row(cfg, "SharePoint Site", "sharepoint_site")
        self._flow_cfg_row(cfg, "SharePoint List", "sharepoint_list")
        self._flow_cfg_row(cfg, "Dispatch Email", "dispatch_email")
        self._flow_cfg_row(cfg, "Teams Team ID", "team_id")
        self._flow_cfg_row(cfg, "Teams Channel ID", "channel_id")
        self._flow_cfg_row(cfg, "Planner Group ID", "planner_group_id")
        self._flow_cfg_row(cfg, "Planner Plan ID", "planner_plan_id")

        btns = tk.Frame(frame, bg=C["bg"], pady=4)
        btns.pack(fill="x", padx=10)
        tk.Button(
            btns,
            text="Generate Ticket Flow Template",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.generate_flow_template,
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Compile FlowFX",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.compile_flowfx_from_editor,
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Validate FlowFX Pack",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.validate_flowfx_from_editor,
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Batch Validate Files",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.batch_validate_flowfx_files,
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Save FlowFX",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.save_flowfx_file,
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Save JSON Output",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.save_json_output_file,
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="FlowFX Help",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.show_flowfx_help,
        ).pack(side="left", padx=4)

        split = tk.PanedWindow(frame, orient=tk.HORIZONTAL, bg=C["bg"], sashwidth=6)
        split.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        left = tk.Frame(split, bg=C["panel"])
        right = tk.Frame(split, bg=C["panel"])
        split.add(left, stretch="always")
        split.add(right, stretch="always")

        tk.Label(left, text="FlowFX Editor", bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold")).pack(
            anchor="w", padx=8, pady=(8, 2)
        )
        self.flowfx_editor = scrolledtext.ScrolledText(
            left,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.flowfx_editor.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        tk.Label(
            right, text="Compiled JSON / Errors", bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold")
        ).pack(anchor="w", padx=8, pady=(8, 2))
        self.flowfx_output = scrolledtext.ScrolledText(
            right,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.flowfx_output.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.generate_flow_template()

    def _tab_flow_run_import(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Flow Run Import  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="Flow Run Import + Root-Cause Extraction",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)

        controls = tk.Frame(frame, bg=C["bg"], pady=6)
        controls.pack(fill="x", padx=10)
        tk.Button(
            controls,
            text="Load Run JSON File",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.load_flow_run_import_file,
        ).pack(side="left", padx=4)
        tk.Button(
            controls,
            text="Analyze Run Payload",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.analyze_flow_run_import,
        ).pack(side="left", padx=4)
        tk.Button(
            controls,
            text="Create Ticket From Root Cause",
            bg=C["btn_gold"],
            fg=C["gold"],
            relief="flat",
            command=self.create_ticket_from_run_import,
        ).pack(side="left", padx=4)

        split = tk.PanedWindow(frame, orient=tk.HORIZONTAL, bg=C["bg"], sashwidth=6)
        split.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        left = tk.Frame(split, bg=C["panel"])
        right = tk.Frame(split, bg=C["panel"])
        split.add(left, stretch="always")
        split.add(right, stretch="always")

        tk.Label(
            left,
            text="Imported Run Payload (JSON)",
            bg=C["panel"],
            fg=C["text"],
            font=(FONT, 10, "bold"),
        ).pack(anchor="w", padx=8, pady=(8, 2))
        self.run_import_input = scrolledtext.ScrolledText(
            left,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.run_import_input.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.run_import_input.insert(
            "1.0",
            json.dumps(
                {
                    "id": "run-sample-001",
                    "name": "Sample Run",
                    "properties": {
                        "status": "Failed",
                        "actions": {
                            "Create_Item": {
                                "status": "Failed",
                                "type": "OpenApiConnection",
                                "inputs": {
                                    "host": {
                                        "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline",
                                        "operationId": "PostItem",
                                    }
                                },
                                "outputs": {
                                    "statusCode": 403,
                                    "body": {"error": {"code": "Forbidden", "message": "Access denied."}},
                                },
                            },
                            "Notify_IT": {
                                "status": "Skipped",
                                "error": {
                                    "code": "ActionBranchingConditionNotSatisfied",
                                    "message": "Skipped due to previous failure.",
                                },
                            },
                        },
                    },
                },
                indent=2,
            ),
        )

        tk.Label(
            right,
            text="Run Import Analysis",
            bg=C["panel"],
            fg=C["text"],
            font=(FONT, 10, "bold"),
        ).pack(anchor="w", padx=8, pady=(8, 2))
        self.run_import_output = scrolledtext.ScrolledText(
            right,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.run_import_output.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _tab_connection_preflight(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Connection Preflight  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="Office 365 + SharePoint Connection Preflight",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)
        tk.Label(
            top,
            text="Token kept in memory only. No credential persistence.",
            font=(FONT, 9),
            bg=C["panel"],
            fg=C["muted"],
        ).pack(side="right", padx=12)

        cfg = tk.Frame(frame, bg=C["bg"], pady=6)
        cfg.pack(fill="x", padx=10)

        self.preflight_tenant_var = tk.StringVar(value=RTC_ORG["tenant"])
        self.preflight_client_id_var = tk.StringVar(value="")
        self.preflight_scope_var = tk.StringVar(
            value="User.Read Mail.Read MailboxSettings.Read Sites.Read.All offline_access openid profile"
        )
        self.preflight_site_host_var = tk.StringVar(value=RTC_ORG["sharepoint_hostname"])
        self.preflight_site_path_var = tk.StringVar(value=RTC_ORG["sharepoint_site_path"])
        self.preflight_list_name_var = tk.StringVar(value=RTC_ORG["default_list"])
        self.preflight_mail_folder_var = tk.StringVar(value="inbox")

        for label, var, width in (
            ("Tenant", self.preflight_tenant_var, 20),
            ("Client ID (public app)", self.preflight_client_id_var, 40),
            ("Scope", self.preflight_scope_var, 70),
            ("SharePoint Host", self.preflight_site_host_var, 30),
            ("Site Relative Path", self.preflight_site_path_var, 30),
            ("Target List", self.preflight_list_name_var, 24),
            ("Mail Folder", self.preflight_mail_folder_var, 14),
        ):
            row = tk.Frame(cfg, bg=C["bg"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, width=22, anchor="w", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(
                side="left"
            )
            tk.Entry(
                row,
                textvariable=var,
                width=width,
                bg=C["notebk"],
                fg=C["text"],
                insertbackground=C["text"],
                relief="flat",
                font=(FONT, 9),
            ).pack(side="left", fill="x", expand=True)

        btns = tk.Frame(frame, bg=C["bg"], pady=4)
        btns.pack(fill="x", padx=10)
        tk.Button(
            btns,
            text="Begin Device Code",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.begin_device_code_login,
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Poll Device Token",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.poll_device_code_login,
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Run Preflight Checks",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.run_connection_preflight_checks,
        ).pack(side="left", padx=4)
        tk.Button(
            btns,
            text="Load Last Preflight",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.load_last_preflight_result,
        ).pack(side="left", padx=4)

        split = tk.PanedWindow(frame, orient=tk.HORIZONTAL, bg=C["bg"], sashwidth=6)
        split.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        left = tk.Frame(split, bg=C["panel"])
        right = tk.Frame(split, bg=C["panel"])
        split.add(left, stretch="always")
        split.add(right, stretch="always")

        tk.Label(
            left,
            text="Access Token (in memory only)",
            bg=C["panel"],
            fg=C["text"],
            font=(FONT, 10, "bold"),
        ).pack(anchor="w", padx=8, pady=(8, 2))
        self.preflight_token_input = scrolledtext.ScrolledText(
            left,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
            height=12,
        )
        self.preflight_token_input.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        tk.Label(
            right,
            text="Preflight Result",
            bg=C["panel"],
            fg=C["text"],
            font=(FONT, 10, "bold"),
        ).pack(anchor="w", padx=8, pady=(8, 2))
        self.preflight_output = scrolledtext.ScrolledText(
            right,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.preflight_output.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _tab_packet_diagnostics(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Packet Diagnostics  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="Microsoft Error Packet Diagnostics",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)

        controls = tk.Frame(frame, bg=C["bg"], pady=6)
        controls.pack(fill="x", padx=10)
        tk.Label(
            controls, text="Connector:", bg=C["bg"], fg=C["muted"], font=(FONT, 9)
        ).pack(side="left")
        self.diag_connector_var = tk.StringVar()
        connectors = self.store.list_catalog_connectors()
        self.diag_connector_combo = ttk.Combobox(
            controls,
            textvariable=self.diag_connector_var,
            values=connectors,
            width=30,
            state="readonly",
        )
        self.diag_connector_combo.pack(side="left", padx=6)
        self.diag_connector_combo.bind("<<ComboboxSelected>>", self.on_diag_connector_change)
        if connectors:
            self.diag_connector_var.set(connectors[0])

        tk.Label(
            controls, text="Operation:", bg=C["bg"], fg=C["muted"], font=(FONT, 9)
        ).pack(side="left")
        self.diag_operation_var = tk.StringVar()
        self.diag_operation_combo = ttk.Combobox(
            controls,
            textvariable=self.diag_operation_var,
            values=[],
            width=30,
            state="readonly",
        )
        self.diag_operation_combo.pack(side="left", padx=6)

        tk.Button(
            controls,
            text="Show Operation Spec",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.show_operation_spec,
        ).pack(side="left", padx=4)
        tk.Button(
            controls,
            text="Diagnose Packet",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.run_packet_diagnosis,
        ).pack(side="left", padx=4)

        split = tk.PanedWindow(frame, orient=tk.HORIZONTAL, bg=C["bg"], sashwidth=6)
        split.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        left = tk.Frame(split, bg=C["panel"])
        right = tk.Frame(split, bg=C["panel"])
        split.add(left, stretch="always")
        split.add(right, stretch="always")

        tk.Label(
            left, text="Raw Error Packet (JSON or text)", bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold")
        ).pack(anchor="w", padx=8, pady=(8, 2))
        self.packet_input = scrolledtext.ScrolledText(
            left,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.packet_input.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.packet_input.insert(
            "1.0",
            json.dumps(
                {
                    "error": {
                        "code": "InvalidConnection",
                        "message": "Connection reference is not configured for shared_office365.",
                    },
                    "statusCode": 401,
                },
                indent=2,
            ),
        )

        tk.Label(
            right, text="Diagnostic Result", bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold")
        ).pack(anchor="w", padx=8, pady=(8, 2))
        self.packet_output = scrolledtext.ScrolledText(
            right,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.packet_output.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.on_diag_connector_change()

    def _flow_cfg_row(self, parent: tk.Frame, label: str, key: str) -> None:
        row = tk.Frame(parent, bg=C["bg"])
        row.pack(fill="x", pady=1)
        tk.Label(row, text=label, bg=C["bg"], fg=C["muted"], font=(FONT, 9), width=18, anchor="w").pack(
            side="left"
        )
        tk.Entry(
            row,
            textvariable=self.flow_cfg_vars[key],
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
            font=(FONT, 9),
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

    def _tab_reports(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Reports  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="Ticket Analytics & Export",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)
        tk.Button(
            top,
            text="Refresh",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.refresh_report_summary,
        ).pack(side="right", padx=10)
        tk.Button(
            top,
            text="Export CSV",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.export_ticket_csv,
        ).pack(side="right", padx=4)
        tk.Button(
            top,
            text="Export Styled HTML",
            bg=C["btn_gold"],
            fg=C["gold"],
            relief="flat",
            command=self.export_ticket_html_spreadsheet,
        ).pack(side="right", padx=4)

        self.report_bridge_var = tk.StringVar(
            value="Collation tools ready: historical files, ServiceDesk API, and mailbox intake."
        )
        bridge = tk.Frame(frame, bg=C["bg"], pady=6)
        bridge.pack(fill="x", padx=10)

        row1 = tk.Frame(bridge, bg=C["bg"])
        row1.pack(fill="x", pady=(0, 4))
        tk.Label(row1, text="Historical Source Label", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(
            side="left"
        )
        self.report_import_source_var = tk.StringVar(value="rtc_historical_service_records")
        tk.Entry(
            row1,
            textvariable=self.report_import_source_var,
            width=36,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=6)
        self.report_import_dry_run_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            row1,
            text="Dry run only",
            variable=self.report_import_dry_run_var,
            bg=C["bg"],
            fg=C["muted"],
            activebackground=C["bg"],
            activeforeground=C["text"],
            selectcolor=C["panel_alt"],
        ).pack(side="left", padx=6)
        tk.Button(
            row1,
            text="Import Historical File...",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.import_historical_file_collation,
        ).pack(side="left", padx=4)

        row2 = tk.Frame(bridge, bg=C["bg"])
        row2.pack(fill="x", pady=(0, 4))
        tk.Label(row2, text="ServiceDesk URL", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        self.report_servicedesk_url_var = tk.StringVar(value="https://servicedesk.rtc.edu/app/itdesk")
        tk.Entry(
            row2,
            textvariable=self.report_servicedesk_url_var,
            width=42,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=6)
        tk.Label(row2, text="Auth Token", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        self.report_servicedesk_token_var = tk.StringVar(value="")
        tk.Entry(
            row2,
            textvariable=self.report_servicedesk_token_var,
            show="*",
            width=28,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=6)
        tk.Label(row2, text="Top N", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        self.report_servicedesk_limit_var = tk.StringVar(value="100")
        tk.Entry(
            row2,
            textvariable=self.report_servicedesk_limit_var,
            width=8,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=6)
        tk.Button(
            row2,
            text="Pull ServiceDesk API",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.import_servicedesk_api_collation,
        ).pack(side="left", padx=4)

        row3 = tk.Frame(bridge, bg=C["bg"])
        row3.pack(fill="x", pady=(0, 2))
        tk.Label(row3, text="Inbox Folder", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        self.report_inbox_folder_var = tk.StringVar(value="inbox")
        tk.Entry(
            row3,
            textvariable=self.report_inbox_folder_var,
            width=16,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=6)
        tk.Label(row3, text="Top N", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="left")
        self.report_inbox_limit_var = tk.StringVar(value="25")
        tk.Entry(
            row3,
            textvariable=self.report_inbox_limit_var,
            width=8,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
        ).pack(side="left", padx=6)
        tk.Button(
            row3,
            text="Pull Inbox (Graph)",
            bg=C["btn_acc"],
            fg=C["text"],
            relief="flat",
            command=self.import_mailbox_inbox_collation,
        ).pack(side="left", padx=4)
        tk.Button(
            row3,
            text="Pull SharePoint List",
            bg=C["btn"],
            fg=C["text"],
            relief="flat",
            command=self.import_sharepoint_list_collation,
        ).pack(side="left", padx=4)

        tk.Label(
            bridge,
            textvariable=self.report_bridge_var,
            bg=C["bg"],
            fg=C["muted"],
            font=(FONT, 9),
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(2, 0))

        self.report_text = scrolledtext.ScrolledText(
            frame,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 10),
            wrap="none",
        )
        self.report_text.pack(fill="both", expand=True, padx=10, pady=8)

    def select_notebook_tab(self, contains_text: str) -> bool:
        if not hasattr(self, "notebook"):
            return False
        needle = (contains_text or "").strip().lower()
        if not needle:
            return False
        for tab_id in self.notebook.tabs():
            label = str(self.notebook.tab(tab_id, "text") or "").lower()
            if needle in label:
                self.notebook.select(tab_id)
                return True
        return False

    def refresh_table_launcher(self) -> None:
        counts = self.store.list_table_counts()
        lines = [
            f"Generated: {now_iso()}",
            "",
            "DB Table Counts:",
        ]
        for table_name in sorted(counts.keys()):
            value = counts[table_name]
            shown = "n/a" if value < 0 else str(value)
            lines.append(f"  - {table_name:<28} {shown}")
        lines.append("")
        lines.append("Quick Paths:")
        lines.append("  - Use this tab to jump to Ticket Books, DB Sync / Harmonize, and SharePoint CRUD.")
        lines.append("  - Ticketing app payload now synced as a first-class CITL app key-file set.")
        if hasattr(self, "table_launcher_output"):
            self.table_launcher_output.delete("1.0", "end")
            self.table_launcher_output.insert("1.0", "\n".join(lines) + "\n")

    def _selected_ticket_book_id(self) -> Optional[int]:
        label = self.ticket_book_choice_var.get().strip() if hasattr(self, "ticket_book_choice_var") else ""
        if not label:
            return None
        return self.ticket_book_id_map.get(label)

    def refresh_ticket_books(self) -> None:
        rows = self.store.list_ticket_books()
        current = self.ticket_book_choice_var.get().strip() if hasattr(self, "ticket_book_choice_var") else ""
        self.ticket_book_id_map = {}
        labels: List[str] = []
        for row in rows:
            label = f"{row['name']} (#{row['id']} | {row['item_count']} tickets)"
            labels.append(label)
            self.ticket_book_id_map[label] = int(row["id"])
        self.ticket_book_combo["values"] = labels
        if current in labels:
            self.ticket_book_choice_var.set(current)
        elif labels:
            self.ticket_book_choice_var.set(labels[0])
        else:
            self.ticket_book_choice_var.set("")
        self.refresh_ticket_book_items()
        self.refresh_table_launcher()

    def on_ticket_book_change(self, _event: Any = None) -> None:
        self.refresh_ticket_book_items()

    def create_ticket_book_from_ui(self) -> None:
        name = self.ticket_book_new_name_var.get().strip()
        desc = self.ticket_book_new_desc_var.get().strip()
        if not name:
            messagebox.showwarning("Ticket Books", "Book name is required.")
            return
        try:
            self.store.create_ticket_book(name=name, description=desc)
        except Exception as exc:
            messagebox.showerror("Ticket Books", f"Could not create book:\n{exc}")
            return
        self.ticket_book_new_name_var.set("")
        self.ticket_book_new_desc_var.set("")
        self.refresh_ticket_books()
        self.status(f"Ticket book created: {name}")

    def assign_ticket_to_current_book(self) -> None:
        book_id = self._selected_ticket_book_id()
        if not book_id:
            messagebox.showwarning("Ticket Books", "Select a book first.")
            return
        raw = self.ticket_book_ticket_id_var.get().strip()
        ticket_id: Optional[int] = None
        if raw:
            try:
                ticket_id = int(raw)
            except ValueError:
                messagebox.showwarning("Ticket Books", "Ticket ID must be an integer.")
                return
        elif self.current_ticket_id:
            ticket_id = int(self.current_ticket_id)
        else:
            messagebox.showwarning("Ticket Books", "Provide a ticket ID or select a ticket in Ticket Desk.")
            return
        if self.store.get_ticket(ticket_id) is None:
            messagebox.showwarning("Ticket Books", f"Ticket #{ticket_id} was not found.")
            return
        self.store.add_ticket_to_book(book_id, ticket_id, note="assigned from GUI")
        self.ticket_book_ticket_id_var.set(str(ticket_id))
        self.refresh_ticket_book_items()
        self.refresh_ticket_books()
        self.status(f"Assigned ticket #{ticket_id} to book #{book_id}.")

    def remove_selected_ticket_from_book(self) -> None:
        book_id = self._selected_ticket_book_id()
        if not book_id:
            messagebox.showwarning("Ticket Books", "Select a book first.")
            return
        sel = self.ticket_book_tree.selection()
        if not sel:
            messagebox.showinfo("Ticket Books", "Select a linked ticket row first.")
            return
        row_id = sel[0]
        vals = self.ticket_book_tree.item(row_id, "values")
        if not vals:
            return
        try:
            ticket_id = int(vals[0])
        except Exception:
            return
        self.store.remove_ticket_from_book(book_id, ticket_id)
        self.refresh_ticket_book_items()
        self.refresh_ticket_books()
        self.status(f"Removed ticket #{ticket_id} from book #{book_id}.")

    def refresh_ticket_book_items(self) -> None:
        if not hasattr(self, "ticket_book_tree"):
            return
        for row_id in self.ticket_book_tree.get_children():
            self.ticket_book_tree.delete(row_id)
        book_id = self._selected_ticket_book_id()
        if not book_id:
            return
        rows = self.store.list_book_items(book_id, limit=500)
        for row in rows:
            self.ticket_book_tree.insert(
                "",
                "end",
                values=(
                    row["ticket_id"],
                    row["status"],
                    row["priority"],
                    row["subject"],
                    row["requester_email"],
                    row["updated_at"],
                    row["linked_at"],
                ),
            )

    def jump_to_ticket_from_book(self, _event: Any = None) -> None:
        sel = self.ticket_book_tree.selection()
        if not sel:
            return
        vals = self.ticket_book_tree.item(sel[0], "values")
        if not vals:
            return
        try:
            ticket_id = int(vals[0])
        except Exception:
            return
        self.select_notebook_tab("Ticket Desk")
        self.select_ticket_in_table(ticket_id)
        self.status(f"Loaded ticket #{ticket_id} from Ticket Books.")

    def run_db_harmonize_now(self) -> None:
        result = self.store.run_db_harmonize()
        summary = (
            f"rows_changed={result.get('rows_changed', 0)} "
            f"dupe_groups={result.get('duplicate_groups', 0)} "
            f"dupe_overage={result.get('duplicate_overage', 0)}"
        )
        status = "ok" if result.get("ok") else "warn"
        self.store.add_db_sync_run(
            mode="harmonize",
            summary=summary,
            status=status,
            details=result,
        )
        self.refresh_db_sync_history()
        self.refresh_ticket_table()
        self.refresh_report_summary()
        self.refresh_table_launcher()
        self.status(f"DB harmonize complete: {summary}")

    def refresh_db_sync_history(self) -> None:
        rows = self.store.list_db_sync_runs(limit=40)
        lines = [f"Generated: {now_iso()}", ""]
        for row in rows:
            lines.append(
                f"[{row['created_at']}] mode={row['mode']} status={row['status']} :: {row['summary']}"
            )
            try:
                detail = json.loads(row["details_json"])
                lines.append(f"  details={json.dumps(detail, ensure_ascii=False)}")
            except Exception:
                lines.append(f"  details_raw={row['details_json']}")
        if not rows:
            lines.append("No DB sync/harmonize runs recorded yet.")
        if hasattr(self, "db_sync_output"):
            self.db_sync_output.delete("1.0", "end")
            self.db_sync_output.insert("1.0", "\n".join(lines) + "\n")

    def _tab_sharepoint_crud(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  SharePoint CRUD  ")

        top = tk.Frame(frame, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(
            top,
            text="SharePoint CRUD Operations (Graph)",
            font=(FONT, 12, "bold"),
            bg=C["panel"],
            fg=C["text"],
        ).pack(side="left", padx=12)
        tk.Label(
            top,
            text="Token is in-memory only. Use preflight token or paste a new access token.",
            font=(FONT, 9),
            bg=C["panel"],
            fg=C["muted"],
        ).pack(side="right", padx=12)

        cfg = tk.Frame(frame, bg=C["bg"], pady=6)
        cfg.pack(fill="x", padx=10)
        self.sp_host_var = tk.StringVar(value=RTC_ORG["sharepoint_hostname"])
        self.sp_site_path_var = tk.StringVar(value=RTC_ORG["sharepoint_site_path"])
        self.sp_list_name_var = tk.StringVar(value=RTC_ORG["default_list"])
        self.sp_site_id_var = tk.StringVar(value="")
        self.sp_list_id_var = tk.StringVar(value="")
        self.sp_item_id_var = tk.StringVar(value="")
        self.sp_key_field_var = tk.StringVar(value="Title")
        self.sp_key_value_var = tk.StringVar(value="")
        self.sp_top_var = tk.StringVar(value="25")

        for label, var, width in (
            ("SharePoint Host", self.sp_host_var, 30),
            ("Site Path", self.sp_site_path_var, 30),
            ("List Name", self.sp_list_name_var, 24),
            ("Resolved Site ID", self.sp_site_id_var, 48),
            ("Resolved List ID", self.sp_list_id_var, 48),
            ("Item ID", self.sp_item_id_var, 14),
            ("Upsert Key Field", self.sp_key_field_var, 20),
            ("Upsert Key Value", self.sp_key_value_var, 24),
            ("List Top", self.sp_top_var, 10),
        ):
            row = tk.Frame(cfg, bg=C["bg"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, width=20, anchor="w", bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(
                side="left"
            )
            tk.Entry(
                row,
                textvariable=var,
                width=width,
                bg=C["notebk"],
                fg=C["text"],
                insertbackground=C["text"],
                relief="flat",
                font=(FONT, 9),
            ).pack(side="left", fill="x", expand=True)

        btns = tk.Frame(frame, bg=C["bg"], pady=4)
        btns.pack(fill="x", padx=10)
        tk.Button(btns, text="Use Preflight Token", bg=C["btn"], fg=C["text"], relief="flat", command=self.sp_copy_preflight_token).pack(side="left", padx=4)
        tk.Button(btns, text="Resolve Site + List", bg=C["btn_acc"], fg=C["text"], relief="flat", command=self.sp_resolve_site_list).pack(side="left", padx=4)
        tk.Button(btns, text="List Items", bg=C["btn"], fg=C["text"], relief="flat", command=self.sp_list_items).pack(side="left", padx=4)
        tk.Button(btns, text="Get Item", bg=C["btn"], fg=C["text"], relief="flat", command=self.sp_get_item).pack(side="left", padx=4)
        tk.Button(btns, text="Create Item", bg=C["btn_acc"], fg=C["text"], relief="flat", command=self.sp_create_item).pack(side="left", padx=4)
        tk.Button(btns, text="Update Item", bg=C["btn_acc"], fg=C["text"], relief="flat", command=self.sp_update_item).pack(side="left", padx=4)
        tk.Button(btns, text="Delete Item", bg=C["btn_gold"], fg=C["gold"], relief="flat", command=self.sp_delete_item).pack(side="left", padx=4)
        tk.Button(btns, text="Upsert By Field", bg=C["btn"], fg=C["text"], relief="flat", command=self.sp_upsert_item).pack(side="left", padx=4)

        split = tk.PanedWindow(frame, orient=tk.HORIZONTAL, bg=C["bg"], sashwidth=6)
        split.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        left = tk.Frame(split, bg=C["panel"])
        right = tk.Frame(split, bg=C["panel"])
        split.add(left, stretch="always")
        split.add(right, stretch="always")

        tk.Label(left, text="Access Token (optional, fallback to preflight)", bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self.sp_token_input = scrolledtext.ScrolledText(
            left,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
            height=6,
        )
        self.sp_token_input.pack(fill="x", padx=8, pady=(0, 8))

        tk.Label(left, text="Fields JSON (for create/update/upsert)", bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold")).pack(anchor="w", padx=8, pady=(0, 2))
        self.sp_fields_input = scrolledtext.ScrolledText(
            left,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
            height=12,
        )
        self.sp_fields_input.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.sp_fields_input.insert("1.0", json.dumps({"Title": "CITL Ticket Test"}, indent=2))

        tk.Label(right, text="SharePoint Result", bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self.sp_output = scrolledtext.ScrolledText(
            right,
            bg=C["notebk"],
            fg=C["text"],
            insertbackground=C["text"],
            font=("Consolas", 9),
            wrap="none",
        )
        self.sp_output.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _sp_get_token(self) -> str:
        token = self.sp_token_input.get("1.0", "end").strip() if hasattr(self, "sp_token_input") else ""
        if token:
            return token
        if hasattr(self, "preflight_token_input"):
            return self.preflight_token_input.get("1.0", "end").strip()
        return ""

    def _sp_parse_fields(self) -> Optional[Dict[str, Any]]:
        raw = self.sp_fields_input.get("1.0", "end").strip() if hasattr(self, "sp_fields_input") else ""
        if not raw:
            return {}
        try:
            obj = json.loads(raw)
        except Exception as exc:
            messagebox.showwarning("SharePoint CRUD", f"Fields JSON is invalid:\n{exc}")
            return None
        if not isinstance(obj, dict):
            messagebox.showwarning("SharePoint CRUD", "Fields JSON must be an object/dictionary.")
            return None
        return obj

    def _sp_render(self, title: str, payload: Dict[str, Any]) -> None:
        view = {"operation": title, "timestamp": now_iso(), "result": payload}
        self.sp_output.delete("1.0", "end")
        self.sp_output.insert("1.0", json.dumps(view, indent=2))

    def sp_copy_preflight_token(self) -> None:
        if not hasattr(self, "preflight_token_input"):
            messagebox.showinfo("SharePoint CRUD", "Open Connection Preflight first.")
            return
        token = self.preflight_token_input.get("1.0", "end").strip()
        if not token:
            messagebox.showwarning("SharePoint CRUD", "No token in Connection Preflight box.")
            return
        self.sp_token_input.delete("1.0", "end")
        self.sp_token_input.insert("1.0", token)
        self.status("Copied token from Connection Preflight.")

    def sp_resolve_site_list(self) -> None:
        token = self._sp_get_token()
        if not token:
            messagebox.showwarning("SharePoint CRUD", "Provide an access token first.")
            return
        site_resp = sharepoint_resolve_site(
            access_token=token,
            site_hostname=self.sp_host_var.get().strip(),
            site_relative_path=self.sp_site_path_var.get().strip(),
        )
        if site_resp.get("ok"):
            self.sp_site_id_var.set(str(site_resp.get("site_id") or ""))
        list_resp: Dict[str, Any] = {}
        if self.sp_site_id_var.get().strip():
            list_resp = sharepoint_resolve_list(
                access_token=token,
                site_id=self.sp_site_id_var.get().strip(),
                list_name=self.sp_list_name_var.get().strip(),
                list_id=self.sp_list_id_var.get().strip(),
            )
            if list_resp.get("ok"):
                self.sp_list_id_var.set(str(list_resp.get("list_id") or ""))
        result = {"site": site_resp, "list": list_resp}
        self._sp_render("resolve_site_list", result)
        self.status("SharePoint resolve completed.")

    def sp_list_items(self) -> None:
        token = self._sp_get_token()
        if not token:
            messagebox.showwarning("SharePoint CRUD", "Provide an access token first.")
            return
        if not self.sp_site_id_var.get().strip() or not self.sp_list_id_var.get().strip():
            self.sp_resolve_site_list()
        try:
            top = max(1, int(self.sp_top_var.get().strip() or "25"))
        except ValueError:
            top = 25
        result = sharepoint_list_items_list(
            access_token=token,
            site_id=self.sp_site_id_var.get().strip(),
            list_id=self.sp_list_id_var.get().strip(),
            top=top,
        )
        self._sp_render("list_items", result)
        self.status("SharePoint list-items completed.")

    def sp_get_item(self) -> None:
        token = self._sp_get_token()
        item_id = self.sp_item_id_var.get().strip()
        if not token or not item_id:
            messagebox.showwarning("SharePoint CRUD", "Token and Item ID are required for Get Item.")
            return
        result = sharepoint_list_item_get(
            access_token=token,
            site_id=self.sp_site_id_var.get().strip(),
            list_id=self.sp_list_id_var.get().strip(),
            item_id=item_id,
        )
        self._sp_render("get_item", result)
        self.status("SharePoint get-item completed.")

    def sp_create_item(self) -> None:
        token = self._sp_get_token()
        fields = self._sp_parse_fields()
        if not token or fields is None:
            if not token:
                messagebox.showwarning("SharePoint CRUD", "Token is required for Create Item.")
            return
        result = sharepoint_list_item_create(
            access_token=token,
            site_id=self.sp_site_id_var.get().strip(),
            list_id=self.sp_list_id_var.get().strip(),
            fields=fields,
        )
        item = result.get("item") if isinstance(result.get("item"), dict) else {}
        if item and item.get("id"):
            self.sp_item_id_var.set(str(item.get("id")))
        self._sp_render("create_item", result)
        self.status("SharePoint create-item completed.")

    def sp_update_item(self) -> None:
        token = self._sp_get_token()
        item_id = self.sp_item_id_var.get().strip()
        fields = self._sp_parse_fields()
        if not token or not item_id or fields is None:
            messagebox.showwarning("SharePoint CRUD", "Token, Item ID, and fields JSON are required for Update Item.")
            return
        result = sharepoint_list_item_update(
            access_token=token,
            site_id=self.sp_site_id_var.get().strip(),
            list_id=self.sp_list_id_var.get().strip(),
            item_id=item_id,
            fields=fields,
        )
        self._sp_render("update_item", result)
        self.status("SharePoint update-item completed.")

    def sp_delete_item(self) -> None:
        token = self._sp_get_token()
        item_id = self.sp_item_id_var.get().strip()
        if not token or not item_id:
            messagebox.showwarning("SharePoint CRUD", "Token and Item ID are required for Delete Item.")
            return
        result = sharepoint_list_item_delete(
            access_token=token,
            site_id=self.sp_site_id_var.get().strip(),
            list_id=self.sp_list_id_var.get().strip(),
            item_id=item_id,
        )
        self._sp_render("delete_item", result)
        self.status("SharePoint delete-item completed.")

    def sp_upsert_item(self) -> None:
        token = self._sp_get_token()
        fields = self._sp_parse_fields()
        key_field = self.sp_key_field_var.get().strip()
        key_value = self.sp_key_value_var.get().strip()
        if not token or not key_field or fields is None:
            messagebox.showwarning("SharePoint CRUD", "Token, key field, and fields JSON are required for Upsert.")
            return
        result = sharepoint_list_item_upsert_by_field(
            access_token=token,
            site_id=self.sp_site_id_var.get().strip(),
            list_id=self.sp_list_id_var.get().strip(),
            key_field=key_field,
            key_value=key_value,
            fields=fields,
        )
        item = result.get("item") if isinstance(result.get("item"), dict) else {}
        if item and item.get("id"):
            self.sp_item_id_var.set(str(item.get("id")))
        self._sp_render("upsert_item", result)
        self.status("SharePoint upsert completed.")

    def status(self, message: str) -> None:
        if hasattr(self, "status_var"):
            self.status_var.set(message)

    def _collect_form_record(self) -> Dict[str, Any]:
        return {
            "subject": self.form_vars["subject"].get().strip(),
            "requester_name": self.form_vars["requester_name"].get().strip(),
            "requester_email": self.form_vars["requester_email"].get().strip(),
            "institution_unit": self.form_vars["institution_unit"].get().strip(),
            "assigned_to": self.form_vars["assigned_to"].get().strip(),
            "status": self.form_vars["status"].get().strip() or "new",
            "priority": self.form_vars["priority"].get().strip() or "medium",
            "source": self.form_vars["source"].get().strip() or "manual",
            "channel": self.form_vars["channel"].get().strip() or "manual",
            "external_ref": self.form_vars["external_ref"].get().strip(),
            "description": self.desc_text.get("1.0", "end").strip(),
            "intake_confidence": 1.0,
        }

    def clear_form(self) -> None:
        self.current_ticket_id = None
        for key, var in self.form_vars.items():
            if key == "status":
                var.set("new")
            elif key == "priority":
                var.set("medium")
            elif key == "source":
                var.set("manual")
            elif key == "channel":
                var.set("manual")
            else:
                var.set("")
        self.desc_text.delete("1.0", "end")
        self.note_text.delete("1.0", "end")
        self.history_text.delete("1.0", "end")
        self.status("Ready for new ticket.")

    def create_ticket(self) -> None:
        record = self._collect_form_record()
        if not record["subject"]:
            messagebox.showwarning("Create Ticket", "Subject is required.")
            return
        note = self.note_text.get("1.0", "end").strip()
        ticket_id = self.store.create_ticket(record, note or "Manual ticket created.", actor="gui")
        self.status(f"Ticket #{ticket_id} created.")
        self.refresh_ticket_table()
        self.refresh_report_summary()
        self.select_ticket_in_table(ticket_id)

    def update_ticket(self) -> None:
        if self.current_ticket_id is None:
            messagebox.showinfo("Update Ticket", "Select a ticket first.")
            return
        record = self._collect_form_record()
        note = self.note_text.get("1.0", "end").strip()
        self.store.update_ticket(self.current_ticket_id, record, note, actor="gui")
        self.status(f"Ticket #{self.current_ticket_id} updated.")
        self.refresh_ticket_table()
        self.refresh_report_summary()
        self.select_ticket_in_table(self.current_ticket_id)

    def close_ticket(self) -> None:
        if self.current_ticket_id is None:
            messagebox.showinfo("Close Ticket", "Select a ticket first.")
            return
        note = self.note_text.get("1.0", "end").strip()
        self.store.close_ticket(self.current_ticket_id, note or "Closed from GUI.", actor="gui")
        self.status(f"Ticket #{self.current_ticket_id} closed.")
        self.refresh_ticket_table()
        self.refresh_report_summary()
        self.select_ticket_in_table(self.current_ticket_id)

    def refresh_ticket_table(self) -> None:
        rows = self.store.list_tickets(self.ticket_filter_var.get())
        self.ticket_tree.delete(*self.ticket_tree.get_children())
        for row in rows:
            self.ticket_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["id"],
                    row["status"],
                    row["priority"],
                    row["subject"],
                    row["requester_email"],
                    row["assigned_to"],
                    row["updated_at"],
                ),
            )
        self.status(f"Loaded {len(rows)} tickets.")

    def search_tickets(self) -> None:
        query = self.search_var.get().strip()
        if not query:
            self.refresh_ticket_table()
            return
        rows = self.store.search_tickets(query)
        self.ticket_tree.delete(*self.ticket_tree.get_children())
        for row in rows:
            self.ticket_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["id"],
                    row["status"],
                    row["priority"],
                    row["subject"],
                    row["requester_email"],
                    row["assigned_to"],
                    row["updated_at"],
                ),
            )
        self.status(f"Search returned {len(rows)} tickets.")

    def on_ticket_select(self, _event: Any = None) -> None:
        selected = self.ticket_tree.selection()
        if not selected:
            return
        ticket_id = int(selected[0])
        row = self.store.get_ticket(ticket_id)
        if row is None:
            return
        self.current_ticket_id = ticket_id
        for key in (
            "subject",
            "requester_name",
            "requester_email",
            "institution_unit",
            "assigned_to",
            "status",
            "priority",
            "source",
            "channel",
            "external_ref",
        ):
            self.form_vars[key].set(str(row[key] or ""))
        self.desc_text.delete("1.0", "end")
        self.desc_text.insert("1.0", row["description"] or "")
        self.note_text.delete("1.0", "end")
        if hasattr(self, "ticket_book_ticket_id_var"):
            self.ticket_book_ticket_id_var.set(str(ticket_id))
        self.load_history(ticket_id)
        self.status(f"Selected ticket #{ticket_id}.")

    def load_history(self, ticket_id: int) -> None:
        events = self.store.list_events(ticket_id)
        self.history_text.delete("1.0", "end")
        for e in events:
            line = f"[{e['created_at']}] {e['event_type'].upper()} ({e['actor']}): {e['note']}\n"
            self.history_text.insert("end", line)

    def select_ticket_in_table(self, ticket_id: int) -> None:
        iid = str(ticket_id)
        if iid in self.ticket_tree.get_children():
            self.ticket_tree.selection_set(iid)
            self.ticket_tree.focus(iid)
            self.ticket_tree.see(iid)
            self.on_ticket_select()

    def validate_intake_payload(self) -> None:
        raw = self.intake_input.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("Intake QA", "Payload is empty.")
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.intake_output.delete("1.0", "end")
            self.intake_output.insert("1.0", f"Invalid JSON payload:\n{exc}")
            self.latest_intake = None
            self.status("Payload JSON parse failed.")
            return

        domains = [
            d.strip().lower()
            for d in self.allowlist_var.get().split(",")
            if d.strip()
        ]
        result = assess_email_intake(payload, domains)
        self.latest_intake = result
        self.intake_output.delete("1.0", "end")
        self.intake_output.insert("1.0", json.dumps(result, indent=2))
        self.status(
            f"Intake status: {result['status']} (confidence={result['confidence']:.2f})."
        )

    def create_ticket_from_intake(self) -> None:
        if not self.latest_intake:
            messagebox.showinfo("Create From Intake", "Validate payload first.")
            return
        if self.latest_intake["status"] == "reject":
            if not messagebox.askyesno(
                "High-Risk Intake",
                "This payload was marked REJECT with low confidence. Create ticket anyway?",
            ):
                return
        parsed = dict(self.latest_intake["parsed_ticket"])
        flags = self.latest_intake.get("flags", [])
        note = (
            f"Created from intake QA. status={self.latest_intake['status']} "
            f"confidence={self.latest_intake['confidence']:.2f}. "
            f"flags={'; '.join(flags) if flags else 'none'}"
        )
        ticket_id = self.store.create_ticket(parsed, note, actor="intake_qa")
        self.status(f"Created ticket #{ticket_id} from intake payload.")
        self.refresh_ticket_table()
        self.refresh_report_summary()
        self.select_ticket_in_table(ticket_id)

    def load_flow_run_import_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Load Flow Run JSON",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Flow Run Import", f"Could not read file:\n{exc}")
            return
        self.run_import_input.delete("1.0", "end")
        self.run_import_input.insert("1.0", text)
        self.status(f"Loaded flow run payload: {path}")

    def analyze_flow_run_import(self) -> None:
        raw = self.run_import_input.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("Flow Run Import", "Run payload is empty.")
            return

        catalog_rows = [dict(r) for r in self.store.list_error_catalog()]

        def diag_fn(packet_text: str) -> Dict[str, Any]:
            return diagnose_error_packet(packet_text, catalog_rows=catalog_rows)

        analysis = analyze_flow_run_payload(raw, diag_fn)
        if analysis.get("ok"):
            for entry in analysis.get("failing_actions", []):
                connector_hint = str(entry.get("connector_api", "")).lower()
                if "sharepoint" in connector_hint:
                    entry["permissions_checklist"] = build_permissions_checklist("sharepoint")
                elif "office365" in connector_hint or "outlook" in connector_hint:
                    entry["permissions_checklist"] = build_permissions_checklist("office365 outlook")
                elif "teams" in connector_hint:
                    entry["permissions_checklist"] = build_permissions_checklist("teams")
                else:
                    entry["permissions_checklist"] = build_permissions_checklist("generic")
            self.store.add_flow_run_import("manual_import", raw, analysis)
            self.latest_run_import = analysis
            self.status("Flow run import analysis completed.")
        else:
            self.latest_run_import = None
            self.status("Flow run import analysis failed.")

        self.run_import_output.delete("1.0", "end")
        self.run_import_output.insert("1.0", json.dumps(analysis, indent=2))

    def create_ticket_from_run_import(self) -> None:
        if not self.latest_run_import or not self.latest_run_import.get("ok"):
            messagebox.showinfo("Flow Run Import", "Analyze a run payload first.")
            return
        failures = self.latest_run_import.get("failing_actions", [])
        if not failures:
            messagebox.showinfo("Flow Run Import", "No failed action found in latest analysis.")
            return

        root = failures[0]
        diag = root.get("diagnosis", {})
        top = {}
        if isinstance(diag.get("matched_definitions"), list) and diag["matched_definitions"]:
            top = diag["matched_definitions"][0]
        code = str(top.get("code") or "UnknownError")
        summary = str(diag.get("operator_summary") or self.latest_run_import.get("summary") or "Run failure detected.")
        run_id = str(self.latest_run_import.get("run_info", {}).get("id") or "")
        ticket_payload = {
            "source": "flow_run_import",
            "requester_name": "Automation Monitor",
            "requester_email": "citl-flow-monitor@local",
            "institution_unit": "CITL IT",
            "subject": f"Flow Failure: {root.get('action_name', 'UnknownAction')} ({code})",
            "description": (
                f"{summary}\n\n"
                f"Run ID: {run_id}\n"
                f"Action: {root.get('action_name')}\n"
                f"Status: {root.get('status')}\n"
                f"Connector: {root.get('connector_api')}\n"
                f"Operation: {root.get('operation_id')}\n"
                f"Error Excerpt:\n{root.get('error_excerpt', '')[:1200]}"
            ),
            "status": "new",
            "priority": "high",
            "assigned_to": "",
            "channel": "automation",
            "external_ref": run_id,
            "intake_confidence": 0.95,
        }
        note = "Created from Flow Run Import root-cause analysis."
        ticket_id = self.store.create_ticket(ticket_payload, note, actor="flow_run_import")
        self.refresh_ticket_table()
        self.refresh_report_summary()
        self.select_ticket_in_table(ticket_id)
        self.status(f"Created ticket #{ticket_id} from flow run analysis.")

    def begin_device_code_login(self) -> None:
        tenant = self.preflight_tenant_var.get().strip() or "organizations"
        client_id = self.preflight_client_id_var.get().strip()
        scope = self.preflight_scope_var.get().strip()
        if not client_id:
            messagebox.showwarning("Connection Preflight", "Client ID is required for device-code login.")
            return
        if not scope:
            messagebox.showwarning("Connection Preflight", "Scope is required for device-code login.")
            return

        resp = begin_device_code(tenant=tenant, client_id=client_id, scope=scope)
        payload = resp.get("json") if isinstance(resp.get("json"), dict) else {}
        view = {"http_status": resp.get("status"), "response": payload or resp.get("text", "")}
        self.preflight_output.delete("1.0", "end")
        self.preflight_output.insert("1.0", json.dumps(view, indent=2))
        if not resp.get("ok"):
            self.status("Device-code initialization failed.")
            return

        self.device_code_session = {
            "tenant": tenant,
            "client_id": client_id,
            "device_code": str(payload.get("device_code") or ""),
            "interval": int(payload.get("interval") or 5),
        }
        message = str(payload.get("message") or "")
        if message:
            messagebox.showinfo("Device Code Login", message)
        self.status("Device-code login initialized. Complete user authentication in browser.")

    def poll_device_code_login(self) -> None:
        if not self.device_code_session:
            messagebox.showinfo("Connection Preflight", "Start device-code login first.")
            return
        resp = poll_device_token(
            tenant=self.device_code_session.get("tenant", "organizations"),
            client_id=self.device_code_session.get("client_id", ""),
            device_code=self.device_code_session.get("device_code", ""),
        )
        payload = resp.get("json") if isinstance(resp.get("json"), dict) else {}
        self.preflight_output.delete("1.0", "end")
        self.preflight_output.insert(
            "1.0",
            json.dumps({"http_status": resp.get("status"), "response": payload or resp.get("text", "")}, indent=2),
        )
        if resp.get("ok") and isinstance(payload, dict) and payload.get("access_token"):
            token = str(payload.get("access_token"))
            self.preflight_token_input.delete("1.0", "end")
            self.preflight_token_input.insert("1.0", token)
            self.status("Device-code token acquired and loaded to preflight token box.")
            return

        err = str(payload.get("error") or "")
        if err == "authorization_pending":
            self.status("Authorization pending: finish browser sign-in, then poll again.")
        elif err:
            self.status(f"Device-code token poll failed: {err}")
        else:
            self.status("Device-code token poll failed.")

    def run_connection_preflight_checks(self) -> None:
        token = self.preflight_token_input.get("1.0", "end").strip()
        if not token:
            messagebox.showwarning("Connection Preflight", "Provide an access token first.")
            return
        cfg = {
            "tenant": self.preflight_tenant_var.get().strip() or "organizations",
            "site_hostname": self.preflight_site_host_var.get().strip(),
            "site_relative_path": self.preflight_site_path_var.get().strip(),
            "list_name": self.preflight_list_name_var.get().strip(),
            "mail_folder": self.preflight_mail_folder_var.get().strip() or "inbox",
        }
        result = run_graph_preflight(
            access_token=token,
            site_hostname=cfg["site_hostname"],
            site_relative_path=cfg["site_relative_path"],
            list_name=cfg["list_name"],
            mail_folder=cfg["mail_folder"],
        )
        catalog_rows = [dict(r) for r in self.store.list_error_catalog()]
        for check in result.get("checks", []):
            if check.get("status") == "pass":
                continue
            packet = check.get("error_text") or json.dumps({"statusCode": check.get("http_status", 0)})
            check["diagnosis"] = diagnose_error_packet(packet, catalog_rows=catalog_rows)
        self.store.add_connection_preflight_run(cfg, result)
        self.preflight_output.delete("1.0", "end")
        self.preflight_output.insert("1.0", json.dumps(result, indent=2))
        self.status(f"Connection preflight complete: {result.get('overall_status')}.")

    def load_last_preflight_result(self) -> None:
        rows = self.store.list_connection_preflight_runs(limit=1)
        if not rows:
            messagebox.showinfo("Connection Preflight", "No saved preflight result found.")
            return
        row = rows[0]
        try:
            result = json.loads(row["result_json"])
        except Exception:
            result = {"raw": row["result_json"]}
        self.preflight_output.delete("1.0", "end")
        self.preflight_output.insert("1.0", json.dumps(result, indent=2))
        self.status("Loaded latest saved preflight result.")

    def generate_flow_template(self) -> None:
        values = {k: v.get().strip() for k, v in self.flow_cfg_vars.items()}
        template = build_ticket_flowfx_template(values)
        self.flowfx_editor.delete("1.0", "end")
        self.flowfx_editor.insert("1.0", template)
        self.status("Generated ticket flow template.")

    def compile_flowfx_from_editor(self) -> None:
        text = self.flowfx_editor.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Flow Builder", "FlowFX editor is empty.")
            return
        try:
            compiled = compile_flowfx_text(text)
        except FlowFxError as exc:
            self.flowfx_output.delete("1.0", "end")
            self.flowfx_output.insert("1.0", f"Compile Error:\n{exc}\n")
            self.status("FlowFX compile failed.")
            return
        except Exception as exc:
            self.flowfx_output.delete("1.0", "end")
            self.flowfx_output.insert("1.0", f"Unexpected compile failure:\n{exc}\n")
            self.status("FlowFX compile failed.")
            return
        self.flowfx_output.delete("1.0", "end")
        self.flowfx_output.insert("1.0", json.dumps(compiled, indent=2))
        self.status("FlowFX compiled successfully.")

    def validate_flowfx_from_editor(self) -> None:
        text = self.flowfx_editor.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Flow Builder", "FlowFX editor is empty.")
            return
        report = validate_flowfx_text(text, source="Flow Builder Editor")
        self.flowfx_output.delete("1.0", "end")
        self.flowfx_output.insert("1.0", json.dumps(report, indent=2))
        if report.get("ok"):
            self.status("FlowFX validator pack: PASS.")
        else:
            self.status("FlowFX validator pack: FAIL.")

    def batch_validate_flowfx_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select FlowFX files for validator pack",
            filetypes=[("FlowFX", "*.flowfx"), ("All files", "*.*")],
        )
        if not paths:
            return
        report_dir = EXPORT_DIR / "validator_reports"
        result = run_validator_pack([str(p) for p in paths], report_dir=report_dir)
        self.flowfx_output.delete("1.0", "end")
        self.flowfx_output.insert("1.0", json.dumps(result, indent=2))
        if result.get("ok"):
            self.status(f"Batch validator: PASS ({result.get('passed')}/{result.get('total')}).")
        else:
            self.status(f"Batch validator: FAIL ({result.get('failed')} failed).")

    def save_flowfx_file(self) -> None:
        content = self.flowfx_editor.get("1.0", "end").strip()
        if not content:
            return
        default_name = f"ticket_flow_{datetime.now().strftime('%Y%m%d_%H%M%S')}.flowfx"
        path = filedialog.asksaveasfilename(
            title="Save FlowFX",
            defaultextension=".flowfx",
            initialdir=str(EXPORT_DIR),
            initialfile=default_name,
            filetypes=[("FlowFX", "*.flowfx"), ("All files", "*.*")],
        )
        if not path:
            return
        Path(path).write_text(content + "\n", encoding="utf-8")
        self.status(f"Saved FlowFX: {path}")

    def save_json_output_file(self) -> None:
        content = self.flowfx_output.get("1.0", "end").strip()
        if not content:
            return
        default_name = f"ticket_flow_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path = filedialog.asksaveasfilename(
            title="Save Compiled JSON",
            defaultextension=".json",
            initialdir=str(EXPORT_DIR),
            initialfile=default_name,
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        Path(path).write_text(content + "\n", encoding="utf-8")
        self.status(f"Saved compiled JSON: {path}")

    def show_flowfx_help(self) -> None:
        messagebox.showinfo("FlowFX Help", pretty_print_help())

    def _get_active_environment_profile(self) -> Dict[str, Any]:
        mode = self.env_mode_var.get().strip().lower() if hasattr(self, "env_mode_var") else "prototype"
        if mode == "live":
            site = self.env_profile_vars["live_site"].get().strip()
            list_name = self.env_profile_vars["live_list"].get().strip()
        else:
            site = self.env_profile_vars["prototype_site"].get().strip()
            list_name = self.env_profile_vars["prototype_list"].get().strip()
            mode = "prototype"
        return {
            "mode": mode,
            "sharepoint_site": site,
            "sharepoint_list": list_name,
            "dispatch_email": self.env_profile_vars["dispatch_email"].get().strip(),
            "flow_name_prefix": self.env_profile_vars["flow_name_prefix"].get().strip()
            or RTC_ORG["flow_name_prefix"],
        }

    def apply_environment_to_flow_builder(self) -> None:
        if not hasattr(self, "flow_cfg_vars"):
            messagebox.showinfo("Environments", "Open the Flow Builder tab first.")
            return
        profile = self._get_active_environment_profile()
        if profile["mode"] == "live":
            if not messagebox.askyesno(
                "Live Mode Confirmation",
                "You selected LIVE mode. Apply live SharePoint settings to flow template?",
            ):
                return
        self.flow_cfg_vars["sharepoint_site"].set(profile["sharepoint_site"])
        self.flow_cfg_vars["sharepoint_list"].set(profile["sharepoint_list"])
        self.flow_cfg_vars["dispatch_email"].set(profile["dispatch_email"])
        suffix = "Live" if profile["mode"] == "live" else "Prototype"
        self.flow_cfg_vars["flow_name"].set(f"{profile['flow_name_prefix']} {suffix}")
        self.generate_flow_template()
        self.status(f"Applied {profile['mode']} profile to Flow Builder.")

    def show_active_environment_profile(self) -> None:
        profile = self._get_active_environment_profile()
        profile["safety_note"] = SAFE_MODE_NOTE
        self.env_output.delete("1.0", "end")
        self.env_output.insert("1.0", json.dumps(profile, indent=2))
        self.status(f"Showing active environment profile ({profile['mode']}).")

    def _append_webhook_runtime(self, text: str) -> None:
        if not hasattr(self, "webhook_runtime_output"):
            return
        self.webhook_runtime_output.insert("end", text + "\n")
        self.webhook_runtime_output.see("end")

    def start_webhook_observer(self) -> None:
        if self.webhook_server is not None:
            self.status("Webhook observer is already running.")
            return
        try:
            port = int(self.webhook_port_var.get().strip())
        except ValueError:
            messagebox.showwarning("Webhook Observer", "Port must be an integer.")
            return
        if port < 1 or port > 65535:
            messagebox.showwarning("Webhook Observer", "Port must be 1..65535.")
            return
        bind_mode = self.webhook_bind_var.get().strip()
        bind_host = "127.0.0.1" if bind_mode == "localhost" else "0.0.0.0"
        if bind_mode != "localhost" and not self.webhook_token_var.get().strip():
            if not messagebox.askyesno(
                "Webhook Observer",
                "Observer will bind to all interfaces without a token. Continue?",
            ):
                return
        path = self.webhook_path_var.get().strip() or "/"
        if not path.startswith("/"):
            path = "/" + path
            self.webhook_path_var.set(path)

        handler = build_observer_handler(self)
        try:
            server = ThreadingHTTPServer((bind_host, port), handler)
        except OSError as exc:
            messagebox.showerror("Webhook Observer", f"Could not bind {bind_host}:{port}: {exc}")
            return

        self.webhook_server = server
        self.webhook_thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.webhook_thread.start()
        local_url = f"http://{bind_host}:{port}{path}"
        self._append_webhook_runtime(f"[{now_iso()}] Observer started on {local_url} (bind={bind_mode})")
        self._append_webhook_runtime(
            f"[{now_iso()}] Token check: {'enabled' if self.webhook_token_var.get().strip() else 'disabled'}"
        )
        self.status("Webhook observer started.")

    def stop_webhook_observer(self) -> None:
        if self.webhook_server is None:
            self.status("Webhook observer is not running.")
            return
        self.webhook_server.shutdown()
        self.webhook_server.server_close()
        if self.webhook_thread is not None and self.webhook_thread.is_alive():
            self.webhook_thread.join(timeout=1.5)
        self.webhook_server = None
        self.webhook_thread = None
        self._append_webhook_runtime(f"[{now_iso()}] Observer stopped.")
        self.status("Webhook observer stopped.")

    def _poll_webhook_queue(self) -> None:
        if self._closing:
            return
        try:
            while True:
                event = self.webhook_queue.get_nowait()
                self.store.add_webhook_event(event)
                excerpt = event.get("body_text", "").replace("\n", " ")[:220]
                line = (
                    f"[{event['created_at']}] {event['method']} {event['path']} "
                    f"from {event.get('remote_addr','?')} -> {event['status_code']} "
                    f"({event.get('observer_reason', 'n/a')}) | {excerpt}"
                )
                self._append_webhook_runtime(line)
        except queue.Empty:
            pass
        if not self._closing:
            self.after(800, self._poll_webhook_queue)

    def run_webhook_probe(self) -> None:
        url = self.webhook_probe_url_var.get().strip()
        if not url:
            return
        method = self.webhook_probe_method_var.get().strip().upper() or "GET"
        req_data = None
        if method == "POST":
            payload = {
                "probe": "citl-ticketing-gui",
                "timestamp": now_iso(),
                "note": "prototype webhook probe",
            }
            req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url=url, method=method, data=req_data)
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "CITL-Ticketing-GUI/0.1")
        token = self.webhook_token_var.get().strip()
        if token:
            req.add_header("X-CITL-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                status = int(resp.status)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            status = int(exc.code)
        except Exception as exc:
            body = str(exc)
            status = 0

        packet_diag = diagnose_error_packet(
            body if body else json.dumps({"statusCode": status}),
            catalog_rows=[dict(r) for r in self.store.list_error_catalog()],
        )
        event = {
            "created_at": now_iso(),
            "source_label": "remote_probe",
            "method": method,
            "path": url,
            "remote_addr": "client",
            "headers": {"user-agent": "CITL-Ticketing-GUI/0.1"},
            "body_text": body,
            "status_code": status if status else 520,
        }
        self.store.add_webhook_event(event)
        self._append_webhook_runtime(
            f"[{event['created_at']}] Probe {method} {url} -> {status} | {packet_diag['operator_summary']}"
        )
        self.refresh_webhook_event_log()
        self.status("Webhook probe completed.")

    def refresh_webhook_event_log(self) -> None:
        rows = self.store.list_webhook_events(limit=120)
        lines: List[str] = []
        for r in rows:
            body = str(r["body_text"] or "").replace("\n", " ")
            lines.append(
                f"[{r['created_at']}] {r['source_label']} {r['method']} {r['path']} "
                f"status={r['status_code']} remote={r['remote_addr']} body={body[:180]}"
            )
        self.webhook_event_output.delete("1.0", "end")
        self.webhook_event_output.insert("1.0", "\n".join(lines) + ("\n" if lines else ""))

    def on_diag_connector_change(self, _event: Any = None) -> None:
        connector = self.diag_connector_var.get().strip()
        if not connector:
            return
        ops = self.store.list_operations_by_connector(connector)
        self.diag_operation_combo["values"] = ops
        if ops:
            self.diag_operation_var.set(ops[0])

    def show_operation_spec(self) -> None:
        connector = self.diag_connector_var.get().strip()
        operation = self.diag_operation_var.get().strip()
        if not connector or not operation:
            return
        row = self.store.get_operation(connector, operation)
        if row is None:
            self.packet_output.delete("1.0", "end")
            self.packet_output.insert(
                "1.0",
                f"No operation spec found for connector='{connector}', operation='{operation}'.\n",
            )
            self.status("No operation spec found.")
            return
        spec = {
            "connector": row["connector"],
            "api_name": row["api_name"],
            "operation_id": row["operation_id"],
            "command_alias": row["command_alias"],
            "required_params": json.loads(row["required_params_json"]),
            "sample_flowfx": row["sample_flowfx"],
            "source_url": row["source_url"],
            "last_verified": row["last_verified"],
        }
        self.packet_output.delete("1.0", "end")
        self.packet_output.insert("1.0", json.dumps(spec, indent=2))
        self.status("Operation spec loaded from local catalog DB.")

    def run_packet_diagnosis(self) -> None:
        raw = self.packet_input.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("Packet Diagnostics", "Paste an error packet first.")
            return
        connector = self.diag_connector_var.get().strip()
        catalog_rows = [dict(r) for r in self.store.list_error_catalog()]
        diag = diagnose_error_packet(raw, catalog_rows=catalog_rows)
        operation = self.diag_operation_var.get().strip()
        row = self.store.get_operation(connector, operation) if connector and operation else None
        if row:
            diag["operation_context"] = {
                "connector": row["connector"],
                "operation_id": row["operation_id"],
                "command_alias": row["command_alias"],
                "required_params": json.loads(row["required_params_json"]),
                "source_url": row["source_url"],
            }
        diag["permissions_checklist"] = build_permissions_checklist(connector or "generic")
        if diag.get("ambiguity_detected"):
            diag["next_evidence_to_collect"] = [
                "Capture full action Outputs JSON from flow run history.",
                "Capture HTTP status code + connector operation name.",
                "Capture connection reference and environment name.",
            ]
        self.packet_output.delete("1.0", "end")
        self.packet_output.insert("1.0", json.dumps(diag, indent=2))
        self.status("Packet diagnostics complete.")

    def on_app_close(self) -> None:
        self._closing = True
        try:
            if self.webhook_server is not None:
                self.stop_webhook_observer()
        finally:
            self.store.close()
            self.destroy()

    def refresh_report_summary(self) -> None:
        summary = self.store.summary()
        lines = [
            f"Generated: {now_iso()}",
            "",
            f"Total Tickets : {summary['total']}",
            f"Open Tickets  : {summary['open']}",
            "",
            "Status Counts:",
        ]
        for key, value in sorted(summary["status_counts"].items()):
            lines.append(f"  - {key:<12} {value}")
        lines.append("")
        lines.append("Priority Counts:")
        for key, value in sorted(summary["priority_counts"].items()):
            lines.append(f"  - {key:<12} {value}")
        lines.append("")
        lines.append("Open Ticket Backlog:")
        for row in self.store.list_tickets("all"):
            if row["status"] == "closed":
                continue
            lines.append(
                f"  #{row['id']:>4} [{row['status']}/{row['priority']}] "
                f"{row['subject']} -> {row['assigned_to'] or 'unassigned'}"
            )

        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", "\n".join(lines) + "\n")

    def export_ticket_csv(self) -> None:
        out = EXPORT_DIR / f"tickets_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.store.export_csv(out)
        self.status(f"Exported CSV: {out}")
        messagebox.showinfo("Export Complete", f"Ticket export saved:\n{out}")

    def _read_records_from_import_file(self, path: Path) -> List[Dict[str, Any]]:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                return [dict(r) for r in reader if isinstance(r, dict)]
        if suffix in {".json", ".jsonl"}:
            text = path.read_text(encoding="utf-8")
            if suffix == ".jsonl":
                rows: List[Dict[str, Any]] = []
                for line in text.splitlines():
                    clean = line.strip()
                    if not clean:
                        continue
                    parsed = json.loads(clean)
                    if isinstance(parsed, dict):
                        rows.append(parsed)
                return rows
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [dict(x) for x in parsed if isinstance(x, dict)]
            if isinstance(parsed, dict):
                for key in ("value", "items", "records", "requests", "tickets"):
                    val = parsed.get(key)
                    if isinstance(val, list):
                        return [dict(x) for x in val if isinstance(x, dict)]
                return [parsed]
        raise ValueError(f"Unsupported file type: {path.suffix}")

    def _normalize_row_to_ticket(
        self,
        row: Dict[str, Any],
        *,
        source_label: str,
        channel_hint: str,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(row, dict):
            return None

        subject = first_non_empty(
            row,
            [
                "subject",
                "title",
                "summary",
                "short_description",
                "inquiry - issue - request",
                "inquiry issue request",
                "issue",
            ],
        )
        description = first_non_empty(
            row,
            [
                "description",
                "details",
                "body_preview",
                "short_description",
                "inquiry - issue - request",
                "inquiry issue request",
                "affected hardware",
                "afflicted hardware",
            ],
        )
        requester_name = first_non_empty(
            row,
            [
                "requester_name",
                "requester",
                "reported by",
                "from_name",
                "created_by",
                "reporter",
                "reportedby",
            ],
        )
        requester_email = extract_email(
            first_non_empty(
                row,
                [
                    "requester_email",
                    "email",
                    "reporter_email",
                    "from_email",
                    "reported by email",
                    "reportedbyemail",
                ],
            )
        )
        assigned_to = first_non_empty(
            row,
            ["assigned_to", "technician", "resolved by", "owner", "assignee", "resolvedby"],
        )
        institution_unit = first_non_empty(
            row,
            ["institution_unit", "department", "location", "site", "room", "building"],
        )
        status = normalize_status(
            first_non_empty(row, ["status", "state", "request_status", "request status"])
        )
        priority = normalize_priority(
            first_non_empty(row, ["priority", "severity", "urgency", "impact"])
        )
        external_ref = first_non_empty(
            row,
            [
                "external_ref",
                "ticketid",
                "ticket id",
                "ticket_id",
                "request_id",
                "display_id",
                "id",
                "message_id",
            ],
        )

        if not subject and not description:
            return None

        if not subject:
            subject = "Imported Service Record"
        if not description:
            description = subject

        return {
            "source": (source_label or "historical_import").strip() or "historical_import",
            "requester_name": requester_name,
            "requester_email": requester_email,
            "institution_unit": institution_unit,
            "subject": subject,
            "description": description,
            "status": status,
            "priority": priority,
            "assigned_to": assigned_to,
            "channel": (channel_hint or "import").strip() or "import",
            "external_ref": external_ref,
            "intake_confidence": 0.95,
        }

    def _collate_records_into_tickets(
        self,
        rows: List[Dict[str, Any]],
        *,
        source_label: str,
        channel_hint: str,
        dry_run: bool,
    ) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "source_label": source_label,
            "channel_hint": channel_hint,
            "dry_run": bool(dry_run),
            "input_rows": len(rows),
            "normalized_rows": 0,
            "created": 0,
            "updated": 0,
            "skipped_empty": 0,
            "existing_by_external_ref": 0,
            "sample": [],
        }

        for row in rows:
            record = self._normalize_row_to_ticket(
                row,
                source_label=source_label,
                channel_hint=channel_hint,
            )
            if record is None:
                summary["skipped_empty"] += 1
                continue
            summary["normalized_rows"] += 1

            source = str(record.get("source") or "").strip()
            external_ref = str(record.get("external_ref") or "").strip()
            existing = None
            if source and external_ref:
                existing = self.store.find_ticket_by_external_ref(source, external_ref)
                if existing is not None:
                    summary["existing_by_external_ref"] += 1

            if dry_run:
                if existing is not None:
                    summary["updated"] += 1
                else:
                    summary["created"] += 1
            else:
                if source and external_ref:
                    result = self.store.upsert_ticket_with_external_ref(
                        record,
                        note=f"Collated from {source_label}",
                        actor="collation",
                    )
                    if bool(result.get("created")):
                        summary["created"] += 1
                    else:
                        summary["updated"] += 1
                else:
                    self.store.create_ticket(
                        record,
                        note=f"Collated from {source_label}",
                        actor="collation",
                    )
                    summary["created"] += 1

            if len(summary["sample"]) < 12:
                summary["sample"].append(
                    {
                        "subject": record.get("subject", ""),
                        "requester_email": record.get("requester_email", ""),
                        "status": record.get("status", ""),
                        "priority": record.get("priority", ""),
                        "external_ref": record.get("external_ref", ""),
                    }
                )

        return summary

    def import_historical_file_collation(self) -> None:
        path = filedialog.askopenfilename(
            title="Import historical service records",
            initialdir=str(EXPORT_DIR),
            filetypes=[
                ("Tabular/JSON", "*.csv *.json *.jsonl"),
                ("CSV", "*.csv"),
                ("JSON", "*.json *.jsonl"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        src = self.report_import_source_var.get().strip() or "historical_import"
        dry_run = bool(self.report_import_dry_run_var.get())
        try:
            rows = self._read_records_from_import_file(Path(path))
            summary = self._collate_records_into_tickets(
                rows,
                source_label=src,
                channel_hint="historical_file",
                dry_run=dry_run,
            )
        except Exception as exc:
            messagebox.showerror("Historical Import", f"Import failed:\n{exc}")
            self.report_bridge_var.set(f"Historical import failed: {exc}")
            return
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", json.dumps(summary, indent=2))
        if not dry_run:
            self.refresh_ticket_table()
        self.report_bridge_var.set(
            f"Historical import {'dry run' if dry_run else 'applied'}: "
            f"created={summary['created']} updated={summary['updated']} from {Path(path).name}"
        )
        self.status(self.report_bridge_var.get())

    def import_sharepoint_list_collation(self) -> None:
        token = self.preflight_token_input.get("1.0", "end").strip()
        if not token:
            messagebox.showwarning("SharePoint Import", "Provide Graph access token in Connection Preflight first.")
            return
        host = self.preflight_site_host_var.get().strip() or RTC_ORG["sharepoint_hostname"]
        rel_path = self.preflight_site_path_var.get().strip() or RTC_ORG["sharepoint_site_path"]
        list_name = self.preflight_list_name_var.get().strip() or RTC_ORG["default_list"]
        src = self.report_import_source_var.get().strip() or "sharepoint_list"
        dry_run = bool(self.report_import_dry_run_var.get())

        site_resp = sharepoint_resolve_site(token, host, rel_path)
        if not site_resp.get("ok"):
            messagebox.showerror(
                "SharePoint Import",
                f"Could not resolve site.\nHTTP {site_resp.get('status')}\n{site_resp.get('text','')[:300]}",
            )
            return
        site_id = str((site_resp.get("site") or {}).get("id") or "")
        list_resp = sharepoint_resolve_list(token, site_id, list_name=list_name)
        if not list_resp.get("ok"):
            messagebox.showerror(
                "SharePoint Import",
                f"Could not resolve list '{list_name}'.\nHTTP {list_resp.get('status')}\n{list_resp.get('text','')[:300]}",
            )
            return
        list_id = str((list_resp.get("list") or {}).get("id") or "")
        items_resp = sharepoint_list_items_list(
            access_token=token,
            site_id=site_id,
            list_id=list_id,
            top=500,
        )
        if not items_resp.get("ok"):
            messagebox.showerror(
                "SharePoint Import",
                f"Could not read list items.\nHTTP {items_resp.get('status')}\n{items_resp.get('text','')[:300]}",
            )
            return

        rows: List[Dict[str, Any]] = []
        for item in items_resp.get("items", []):
            if not isinstance(item, dict):
                continue
            row: Dict[str, Any] = {}
            fields = item.get("fields")
            if isinstance(fields, dict):
                row.update(fields)
            row["id"] = str(item.get("id") or "")
            row["webUrl"] = str(item.get("webUrl") or "")
            rows.append(row)

        summary = self._collate_records_into_tickets(
            rows,
            source_label=f"{src}__sharepoint",
            channel_hint="sharepoint",
            dry_run=dry_run,
        )
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", json.dumps(summary, indent=2))
        if not dry_run:
            self.refresh_ticket_table()
        self.report_bridge_var.set(
            f"SharePoint list import {'dry run' if dry_run else 'applied'}: "
            f"rows={summary['normalized_rows']} created={summary['created']} updated={summary['updated']}"
        )
        self.status(self.report_bridge_var.get())

    def import_mailbox_inbox_collation(self) -> None:
        token = self.preflight_token_input.get("1.0", "end").strip()
        if not token:
            messagebox.showwarning("Inbox Import", "Provide Graph access token in Connection Preflight first.")
            return
        folder = self.report_inbox_folder_var.get().strip() or "inbox"
        src = self.report_import_source_var.get().strip() or "mailbox_inbox"
        dry_run = bool(self.report_import_dry_run_var.get())
        try:
            top_n = int(self.report_inbox_limit_var.get().strip() or "25")
        except Exception:
            top_n = 25

        resp = graph_list_mail_messages(
            access_token=token,
            folder=folder,
            top=top_n,
        )
        if not resp.get("ok"):
            messagebox.showerror(
                "Inbox Import",
                f"Could not read folder '{folder}'.\nHTTP {resp.get('status')}\n{str(resp.get('text') or '')[:300]}",
            )
            return

        rows = list(resp.get("messages") or [])
        summary = self._collate_records_into_tickets(
            rows,
            source_label=f"{src}__mailbox",
            channel_hint="email",
            dry_run=dry_run,
        )
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", json.dumps(summary, indent=2))
        if not dry_run:
            self.refresh_ticket_table()
        self.report_bridge_var.set(
            f"Inbox import {'dry run' if dry_run else 'applied'}: "
            f"messages={summary['normalized_rows']} created={summary['created']} updated={summary['updated']}"
        )
        self.status(self.report_bridge_var.get())

    def import_servicedesk_api_collation(self) -> None:
        url = self.report_servicedesk_url_var.get().strip()
        token = self.report_servicedesk_token_var.get().strip()
        if not url or not token:
            messagebox.showwarning("ServiceDesk Import", "ServiceDesk URL and Auth Token are required.")
            return
        try:
            top_n = int(self.report_servicedesk_limit_var.get().strip() or "100")
        except Exception:
            top_n = 100
        src = self.report_import_source_var.get().strip() or "servicedesk_api"
        dry_run = bool(self.report_import_dry_run_var.get())

        resp = servicedesk_list_requests(
            service_desk_url=url,
            authtoken=token,
            row_count=top_n,
        )
        if not resp.get("ok"):
            messagebox.showerror(
                "ServiceDesk Import",
                f"ServiceDesk API pull failed.\nHTTP {resp.get('status')}\nEndpoint: {resp.get('endpoint')}\n"
                f"{str(resp.get('text') or '')[:320]}",
            )
            return

        rows = list(resp.get("requests") or [])
        summary = self._collate_records_into_tickets(
            rows,
            source_label=f"{src}__servicedesk",
            channel_hint="service_desk",
            dry_run=dry_run,
        )
        summary["api_endpoint"] = resp.get("endpoint")
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", json.dumps(summary, indent=2))
        if not dry_run:
            self.refresh_ticket_table()
        self.report_bridge_var.set(
            f"ServiceDesk import {'dry run' if dry_run else 'applied'}: "
            f"records={summary['normalized_rows']} created={summary['created']} updated={summary['updated']}"
        )
        self.status(self.report_bridge_var.get())

    def export_ticket_html_spreadsheet(self) -> None:
        rows = self.store.list_tickets("all")
        summary = self.store.summary()
        out = EXPORT_DIR / f"tickets_spreadsheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"

        badge = {
            "new": "new",
            "in_progress": "progress",
            "pending": "pending",
            "resolved": "resolved",
            "closed": "closed",
            "critical": "critical",
            "high": "high",
            "medium": "medium",
            "low": "low",
        }

        body_rows: List[str] = []
        for row in rows:
            status_key = badge.get(str(row["status"] or "").strip().lower(), "pending")
            priority_key = badge.get(str(row["priority"] or "").strip().lower(), "medium")
            body_rows.append(
                "<tr>"
                f"<td class='id'>#{row['id']}</td>"
                f"<td><span class='pill status {status_key}'>{html.escape(str(row['status'] or ''))}</span></td>"
                f"<td><span class='pill priority {priority_key}'>{html.escape(str(row['priority'] or ''))}</span></td>"
                f"<td class='subject'>{html.escape(str(row['subject'] or ''))}</td>"
                f"<td>{html.escape(str(row['requester_name'] or ''))}</td>"
                f"<td>{html.escape(str(row['requester_email'] or ''))}</td>"
                f"<td>{html.escape(str(row['assigned_to'] or ''))}</td>"
                f"<td>{html.escape(str(row['institution_unit'] or ''))}</td>"
                f"<td>{html.escape(str(row['source'] or ''))}</td>"
                f"<td>{html.escape(str(row['channel'] or ''))}</td>"
                f"<td>{html.escape(str(row['external_ref'] or ''))}</td>"
                f"<td>{html.escape(str(row['updated_at'] or ''))}</td>"
                "</tr>"
            )

        html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CITL Service Records Spreadsheet</title>
  <style>
    :root {{
      --ink: #0f172a;
      --paper: #f8fafc;
      --panel: #ffffff;
      --line: #d9e2ec;
      --teal: #0f766e;
      --teal-soft: #dff7f4;
      --amber: #c2410c;
      --amber-soft: #fff1e8;
      --blue: #1d4ed8;
      --violet: #4f46e5;
      --slate: #334155;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Inter", "Avenir Next", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 8% -10%, #bde7ff 0%, transparent 35%),
        radial-gradient(circle at 90% -20%, #ffe1c4 0%, transparent 38%),
        linear-gradient(180deg, #f8fbff 0%, #f4f7fb 100%);
    }}
    .wrap {{
      max-width: 1600px;
      margin: 24px auto;
      padding: 0 16px;
    }}
    .hero {{
      background: linear-gradient(125deg, #0b2848, #113761 42%, #0f766e);
      color: #ecfeff;
      border-radius: 18px;
      padding: 22px 24px;
      box-shadow: 0 16px 36px rgba(16, 41, 75, 0.25);
    }}
    .hero h1 {{
      margin: 0;
      font-size: 1.45rem;
      letter-spacing: 0.2px;
    }}
    .hero p {{
      margin: 6px 0 0;
      color: #d7f6ff;
      font-size: 0.95rem;
    }}
    .stats {{
      margin-top: 14px;
      display: grid;
      grid-template-columns: repeat(4, minmax(130px, 1fr));
      gap: 10px;
    }}
    .stat {{
      background: rgba(255, 255, 255, 0.16);
      border: 1px solid rgba(255, 255, 255, 0.24);
      border-radius: 12px;
      padding: 10px 12px;
      backdrop-filter: blur(2px);
    }}
    .stat .k {{
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: #e2f7ff;
    }}
    .stat .v {{
      margin-top: 2px;
      font-weight: 700;
      font-size: 1.15rem;
      color: #ffffff;
    }}
    .sheet {{
      margin-top: 16px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 12px 26px rgba(28, 45, 74, 0.12);
    }}
    .table-wrap {{
      overflow: auto;
      max-height: 74vh;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      min-width: 1300px;
      font-size: 0.9rem;
    }}
    thead th {{
      position: sticky;
      top: 0;
      z-index: 2;
      text-align: left;
      padding: 11px 12px;
      color: #e8f4ff;
      background: linear-gradient(180deg, #203a5f, #172f4f);
      border-bottom: 1px solid #0f223b;
      white-space: nowrap;
    }}
    tbody td {{
      padding: 10px 12px;
      border-bottom: 1px solid #ebf0f6;
      vertical-align: top;
      color: var(--slate);
    }}
    tbody tr:nth-child(even) {{ background: #fbfdff; }}
    tbody tr:hover {{ background: #f0f8ff; }}
    td.id {{
      font-weight: 700;
      color: #1f4b7a;
      white-space: nowrap;
    }}
    td.subject {{
      min-width: 280px;
      max-width: 460px;
      font-weight: 600;
      color: #0f2945;
    }}
    .pill {{
      display: inline-block;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 0.75rem;
      font-weight: 700;
      letter-spacing: 0.2px;
      border: 1px solid transparent;
      text-transform: uppercase;
    }}
    .status.new {{ background: #e6f6ff; color: #0a4e78; border-color: #b8e7ff; }}
    .status.progress {{ background: #e8f5ff; color: #1d4ed8; border-color: #c8dcff; }}
    .status.pending {{ background: #fff4df; color: #a14a00; border-color: #ffddb4; }}
    .status.resolved {{ background: #e6f9f1; color: #0f766e; border-color: #beeedd; }}
    .status.closed {{ background: #edf2f7; color: #475569; border-color: #d8e0ea; }}
    .priority.critical {{ background: #ffe5e5; color: #a5122f; border-color: #ffc3cb; }}
    .priority.high {{ background: #fff0e5; color: #b45309; border-color: #ffd7bf; }}
    .priority.medium {{ background: #ebf4ff; color: #1e40af; border-color: #d3e3ff; }}
    .priority.low {{ background: #e9faf0; color: #166534; border-color: #c7f0d8; }}
    .footer {{
      padding: 10px 14px;
      font-size: 0.78rem;
      color: #4b5f79;
      background: #f6f9fc;
      border-top: 1px solid #e6edf4;
    }}
    @media print {{
      body {{ background: #fff; }}
      .wrap {{ margin: 0; max-width: none; }}
      .hero {{ box-shadow: none; }}
      .sheet {{ box-shadow: none; border-radius: 0; }}
      .table-wrap {{ max-height: none; overflow: visible; }}
      thead th {{ position: static; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>CITL Service Records Spreadsheet</h1>
      <p>Generated {html.escape(now_iso())} from CITL Work Ticketing System</p>
      <div class="stats">
        <div class="stat"><div class="k">Total Tickets</div><div class="v">{summary.get("total", 0)}</div></div>
        <div class="stat"><div class="k">Open Tickets</div><div class="v">{summary.get("open", 0)}</div></div>
        <div class="stat"><div class="k">Status Types</div><div class="v">{len(summary.get("status_counts", {}))}</div></div>
        <div class="stat"><div class="k">Priority Types</div><div class="v">{len(summary.get("priority_counts", {}))}</div></div>
      </div>
    </section>
    <section class="sheet">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Ticket</th>
              <th>Status</th>
              <th>Priority</th>
              <th>Subject</th>
              <th>Requester</th>
              <th>Requester Email</th>
              <th>Assigned To</th>
              <th>Location / Unit</th>
              <th>Source</th>
              <th>Channel</th>
              <th>External Ref</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {"".join(body_rows)}
          </tbody>
        </table>
      </div>
      <div class="footer">
        Professional export view for service-history review, supervisor reporting, and spreadsheet-style printing.
      </div>
    </section>
  </div>
</body>
</html>
"""
        out.write_text(html_doc, encoding="utf-8")
        self.status(f"Exported styled HTML spreadsheet: {out}")
        messagebox.showinfo("Export Complete", f"Styled HTML spreadsheet saved:\n{out}")


def main() -> None:
    app = TicketingApp()
    app.mainloop()


if __name__ == "__main__":
    main()
