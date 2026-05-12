"""
FlowFX compiler for Power Automate cloud flow definitions.

FlowFX is a lightweight line-based language that compiles into safe JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import shlex
from typing import Any, Dict, List, Tuple


FLOW_SCHEMA = "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#"
SCHEMA_VERSION = "1.0.0.0"


CONNECTORS: Dict[str, Dict[str, str]] = {
    "office365": {"api": "shared_office365", "connection": "shared_office365"},
    "approvals": {"api": "shared_approvals", "connection": "shared_approvals"},
    "sharepoint": {"api": "shared_sharepointonline", "connection": "shared_sharepointonline"},
    "planner": {"api": "shared_planner", "connection": "shared_planner"},
    "teams": {"api": "shared_teams", "connection": "shared_teams"},
}


ACTION_HELP = {
    "COMPOSE": "COMPOSE ActionName text=\"value\"",
    "EMAIL": "EMAIL ActionName to=\"a@b.com\" subject=\"Subject\" body=\"Body\"",
    "APPROVAL": "APPROVAL ActionName assigned_to=\"a@b.com\" title=\"Title\" details=\"Details\"",
    "SHAREPOINT_CREATE_ITEM": (
        "SHAREPOINT_CREATE_ITEM ActionName site=\"https://...\" list=\"ListName\" "
        "item='{\"Title\":\"Hello\"}'"
    ),
    "PLANNER_CREATE_TASK": (
        "PLANNER_CREATE_TASK ActionName group_id=\"...\" plan_id=\"...\" title=\"Task title\""
    ),
    "TEAMS_POST": (
        "TEAMS_POST ActionName team_id=\"...\" channel_id=\"...\" message=\"Hello team\""
    ),
    "HTTP": "HTTP ActionName method=GET url=\"https://...\"",
    "DELAY": "DELAY ActionName count=5 unit=Minute",
    "TERMINATE": "TERMINATE ActionName status=Succeeded message=\"Done\"",
    "OPENAPI": (
        "OPENAPI ActionName api=shared_x operation=OperationId param.To=\"a@b.com\""
    ),
}

TRIGGER_HELP = {
    "MANUAL": "TRIGGER MANUAL",
    "RECURRENCE": "TRIGGER RECURRENCE frequency=Day interval=1",
    "SHAREPOINT_NEW_ITEM": (
        "TRIGGER SHAREPOINT_NEW_ITEM site=\"https://contoso.sharepoint.com/sites/it\" "
        "list=\"ServiceTickets\""
    ),
}


class FlowFxError(Exception):
    """User-facing parser/compiler error with source line context."""

    def __init__(self, message: str, line_no: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.line_no = line_no

    def __str__(self) -> str:
        if self.line_no is None:
            return self.message
        return f"Line {self.line_no}: {self.message}"


@dataclass
class ActionSpec:
    kind: str
    name: str
    params: Dict[str, Any]
    line_no: int


@dataclass
class FlowSpec:
    name: str = "Untitled FlowFX"
    trigger_type: str = "MANUAL"
    trigger_params: Dict[str, Any] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    actions: List[ActionSpec] = field(default_factory=list)


def strip_inline_comment(raw_line: str) -> str:
    """Remove # comments while respecting simple quoted strings."""
    in_single = False
    in_double = False
    escaped = False
    result: List[str] = []
    for ch in raw_line:
        if escaped:
            result.append(ch)
            escaped = False
            continue
        if ch == "\\":
            result.append(ch)
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            result.append(ch)
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            result.append(ch)
            continue
        if ch == "#" and not in_single and not in_double:
            break
        result.append(ch)
    return "".join(result).strip()


def _sanitize_action_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "Action"
    if cleaned[0].isdigit():
        cleaned = f"A_{cleaned}"
    return cleaned


def _parse_scalar(token: str) -> Any:
    lowered = token.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"-?\d+", token):
        try:
            return int(token)
        except ValueError:
            return token
    if re.fullmatch(r"-?\d+\.\d+", token):
        try:
            return float(token)
        except ValueError:
            return token
    if token and token[0] in "{[" and token[-1] in "}]":
        try:
            return json.loads(token)
        except json.JSONDecodeError:
            return token
    return token


def _parse_keyvals(tokens: List[str], line_no: int) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for token in tokens:
        if "=" not in token:
            raise FlowFxError(
                f"Expected key=value token but got '{token}'", line_no=line_no
            )
        key, value = token.split("=", 1)
        key = key.strip()
        if not key:
            raise FlowFxError("Found empty key in key=value token.", line_no=line_no)
        params[key] = _parse_scalar(value.strip())
    return params


def parse_flowfx(text: str) -> FlowSpec:
    spec = FlowSpec()
    seen_flow_name = False
    seen_trigger = False

    for idx, raw in enumerate(text.splitlines(), start=1):
        line = strip_inline_comment(raw)
        if not line:
            continue
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError as exc:
            raise FlowFxError(f"Invalid quoting: {exc}", line_no=idx) from exc
        if not tokens:
            continue

        command = tokens[0].upper()

        if command == "FLOW":
            if len(tokens) < 2:
                raise FlowFxError("FLOW requires a display name.", line_no=idx)
            spec.name = " ".join(tokens[1:]).strip()
            seen_flow_name = True
            continue

        if command == "TRIGGER":
            if len(tokens) < 2:
                raise FlowFxError(
                    "TRIGGER requires a type: MANUAL or RECURRENCE.", line_no=idx
                )
            trigger = tokens[1].upper()
            if trigger not in {"MANUAL", "RECURRENCE", "SHAREPOINT_NEW_ITEM"}:
                raise FlowFxError(
                    "Unsupported trigger. Use MANUAL, RECURRENCE, or SHAREPOINT_NEW_ITEM.",
                    line_no=idx,
                )
            spec.trigger_type = trigger
            if trigger == "RECURRENCE":
                trigger_params = _parse_keyvals(tokens[2:], idx)
                if "frequency" not in trigger_params:
                    trigger_params["frequency"] = "Day"
                if "interval" not in trigger_params:
                    trigger_params["interval"] = 1
                spec.trigger_params = trigger_params
            elif trigger == "SHAREPOINT_NEW_ITEM":
                trigger_params = _parse_keyvals(tokens[2:], idx)
                if "site" not in trigger_params or "list" not in trigger_params:
                    raise FlowFxError(
                        "SHAREPOINT_NEW_ITEM requires site= and list=.",
                        line_no=idx,
                    )
                spec.trigger_params = trigger_params
            else:
                spec.trigger_params = {}
            seen_trigger = True
            continue

        if command == "SET":
            if len(tokens) < 2:
                raise FlowFxError(
                    "SET requires either key=value or key value.", line_no=idx
                )
            if "=" in tokens[1]:
                key, value = tokens[1].split("=", 1)
                if not key.strip():
                    raise FlowFxError("SET variable name is empty.", line_no=idx)
                spec.variables[key.strip()] = _parse_scalar(value.strip())
            else:
                if len(tokens) < 3:
                    raise FlowFxError(
                        "SET key value is missing value token.", line_no=idx
                    )
                key = tokens[1].strip()
                spec.variables[key] = _parse_scalar(tokens[2].strip())
            continue

        if command in ACTION_HELP:
            if len(tokens) < 2:
                raise FlowFxError(
                    f"{command} requires an action name. Example: {ACTION_HELP[command]}",
                    line_no=idx,
                )
            raw_name = tokens[1]
            action_name = _sanitize_action_name(raw_name)
            params = _parse_keyvals(tokens[2:], idx)
            spec.actions.append(
                ActionSpec(kind=command, name=action_name, params=params, line_no=idx)
            )
            continue

        raise FlowFxError(
            (
                f"Unknown command '{command}'. "
                "Supported commands: FLOW, TRIGGER, SET, "
                + ", ".join(sorted(ACTION_HELP.keys()))
            ),
            line_no=idx,
        )

    if not seen_flow_name:
        spec.name = "Untitled FlowFX"
    if not seen_trigger:
        spec.trigger_type = "MANUAL"
        spec.trigger_params = {}
    return spec


def _expand_vars(value: Any, variables: Dict[str, Any], line_no: int | None = None) -> Any:
    if isinstance(value, dict):
        return {k: _expand_vars(v, variables, line_no) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_vars(v, variables, line_no) for v in value]
    if isinstance(value, str):
        pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in variables:
                raise FlowFxError(f"Variable '{name}' is not defined.", line_no=line_no)
            return str(variables[name])

        replaced = pattern.sub(replace, value)
        if replaced.startswith("fx:"):
            return f"@{{{replaced[3:]}}}"
        return replaced
    return value


def _action_ref(action_name: str) -> str:
    return f"@outputs('{action_name}')"


def _build_host(api_name: str, connection_name: str, operation_id: str) -> Dict[str, str]:
    return {
        "apiId": f"/providers/Microsoft.PowerApps/apis/{api_name}",
        "connectionName": connection_name,
        "operationId": operation_id,
    }


def _build_openapi_action(
    *,
    api_name: str,
    connection_name: str,
    operation_id: str,
    parameters: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "type": "OpenApiConnection",
        "inputs": {
            "host": _build_host(api_name, connection_name, operation_id),
            "parameters": parameters,
            "authentication": "@parameters('$authentication')",
        },
    }


def _require(params: Dict[str, Any], required: Tuple[str, ...], line_no: int) -> None:
    missing = [name for name in required if name not in params]
    if missing:
        raise FlowFxError(f"Missing required parameter(s): {', '.join(missing)}", line_no)


def _build_action(
    action: ActionSpec,
    variables: Dict[str, Any],
    used_connectors: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    kind = action.kind
    params = _expand_vars(action.params, variables, line_no=action.line_no)

    if kind == "COMPOSE":
        value = params.get("text", params.get("value"))
        if value is None:
            raise FlowFxError(
                "COMPOSE requires text=... or value=...", line_no=action.line_no
            )
        return {"type": "Compose", "inputs": value}

    if kind == "EMAIL":
        _require(params, ("to", "subject", "body"), action.line_no)
        c = CONNECTORS["office365"]
        used_connectors[c["connection"]] = c
        payload: Dict[str, Any] = {
            "To": params["to"],
            "Subject": params["subject"],
            "Body": params["body"],
        }
        if "cc" in params:
            payload["Cc"] = params["cc"]
        if "bcc" in params:
            payload["Bcc"] = params["bcc"]
        if "importance" in params:
            payload["Importance"] = params["importance"]
        if "reply_to" in params:
            payload["ReplyTo"] = params["reply_to"]
        if "from" in params:
            payload["From"] = params["from"]
        return _build_openapi_action(
            api_name=c["api"],
            connection_name=c["connection"],
            operation_id="SendEmailV2",
            parameters=payload,
        )

    if kind == "APPROVAL":
        _require(params, ("assigned_to", "title"), action.line_no)
        c = CONNECTORS["approvals"]
        used_connectors[c["connection"]] = c
        approval_type = params.get("approval_type", "ApproveReject")
        payload: Dict[str, Any] = {
            "approvalType": approval_type,
            "WebhookApprovalCreationInput/title": params["title"],
            "WebhookApprovalCreationInput/assignedTo": params["assigned_to"],
        }
        if "details" in params:
            payload["WebhookApprovalCreationInput/details"] = params["details"]
        if "item_link" in params:
            payload["WebhookApprovalCreationInput/itemLink"] = params["item_link"]
        if "item_link_description" in params:
            payload["WebhookApprovalCreationInput/itemLinkDescription"] = params[
                "item_link_description"
            ]
        if "enable_notifications" in params:
            payload["WebhookApprovalCreationInput/enableNotifications"] = params[
                "enable_notifications"
            ]
        return _build_openapi_action(
            api_name=c["api"],
            connection_name=c["connection"],
            operation_id="StartAndWaitForAnApproval",
            parameters=payload,
        )

    if kind == "SHAREPOINT_CREATE_ITEM":
        _require(params, ("site", "list", "item"), action.line_no)
        c = CONNECTORS["sharepoint"]
        used_connectors[c["connection"]] = c
        item_payload = params["item"]
        if isinstance(item_payload, str):
            try:
                item_payload = json.loads(item_payload)
            except json.JSONDecodeError as exc:
                raise FlowFxError(
                    "SHAREPOINT_CREATE_ITEM item= must be valid JSON object.",
                    line_no=action.line_no,
                ) from exc
        if not isinstance(item_payload, dict):
            raise FlowFxError(
                "SHAREPOINT_CREATE_ITEM item= must parse to a JSON object.",
                line_no=action.line_no,
            )
        return _build_openapi_action(
            api_name=c["api"],
            connection_name=c["connection"],
            operation_id="PostItem",
            parameters={
                "dataset": params["site"],
                "table": params["list"],
                "item": item_payload,
            },
        )

    if kind == "PLANNER_CREATE_TASK":
        _require(params, ("group_id", "plan_id", "title"), action.line_no)
        c = CONNECTORS["planner"]
        used_connectors[c["connection"]] = c
        payload: Dict[str, Any] = {
            "groupId": params["group_id"],
            "planId": params["plan_id"],
            "title": params["title"],
        }
        optional_keys = {
            "bucket_id": "bucketId",
            "start_date_time": "startDateTime",
            "due_date_time": "dueDateTime",
            "assignments": "assignments",
        }
        for source_key, target_key in optional_keys.items():
            if source_key in params:
                payload[target_key] = params[source_key]
        return _build_openapi_action(
            api_name=c["api"],
            connection_name=c["connection"],
            operation_id="CreateTask_V3",
            parameters=payload,
        )

    if kind == "TEAMS_POST":
        _require(params, ("team_id", "channel_id", "message"), action.line_no)
        c = CONNECTORS["teams"]
        used_connectors[c["connection"]] = c
        payload: Dict[str, Any] = {
            "groupId": params["team_id"],
            "channelId": params["channel_id"],
            "content": params["message"],
        }
        if "subject" in params:
            payload["subject"] = params["subject"]
        return _build_openapi_action(
            api_name=c["api"],
            connection_name=c["connection"],
            operation_id="PostMessageToChannelV3",
            parameters=payload,
        )

    if kind == "HTTP":
        _require(params, ("method", "url"), action.line_no)
        payload: Dict[str, Any] = {
            "method": str(params["method"]).upper(),
            "uri": params["url"],
        }
        if "headers" in params:
            headers = params["headers"]
            if isinstance(headers, str):
                try:
                    headers = json.loads(headers)
                except json.JSONDecodeError as exc:
                    raise FlowFxError(
                        "HTTP headers= must be valid JSON object when provided as string.",
                        line_no=action.line_no,
                    ) from exc
            if not isinstance(headers, dict):
                raise FlowFxError(
                    "HTTP headers= must be a JSON object.",
                    line_no=action.line_no,
                )
            payload["headers"] = headers
        if "body" in params:
            payload["body"] = params["body"]
        return {"type": "Http", "inputs": payload}

    if kind == "DELAY":
        _require(params, ("count", "unit"), action.line_no)
        count = params["count"]
        if not isinstance(count, int) or count <= 0:
            raise FlowFxError("DELAY count must be a positive integer.", action.line_no)
        return {
            "type": "Wait",
            "inputs": {
                "interval": {
                    "count": count,
                    "unit": params["unit"],
                }
            },
        }

    if kind == "TERMINATE":
        status = params.get("status", "Succeeded")
        message = params.get("message", "")
        return {
            "type": "Terminate",
            "inputs": {
                "runStatus": status,
                "runError": {
                    "message": message,
                },
            },
        }

    if kind == "OPENAPI":
        _require(params, ("api", "operation"), action.line_no)
        api_name = str(params["api"])
        connection_name = str(params.get("connection", api_name))
        operation_id = str(params["operation"])
        openapi_params: Dict[str, Any] = {}
        for key, value in params.items():
            if key.startswith("param."):
                target_key = key[6:]
                if not target_key:
                    raise FlowFxError(
                        "OPENAPI param.<name>=value contains empty param name.",
                        line_no=action.line_no,
                    )
                openapi_params[target_key] = value
        if not openapi_params:
            raise FlowFxError(
                "OPENAPI requires at least one param.<name>=value token.",
                line_no=action.line_no,
            )
        used_connectors[connection_name] = {"api": api_name, "connection": connection_name}
        return _build_openapi_action(
            api_name=api_name,
            connection_name=connection_name,
            operation_id=operation_id,
            parameters=openapi_params,
        )

    raise FlowFxError(f"Unsupported action kind: {kind}", line_no=action.line_no)


def _build_trigger(spec: FlowSpec) -> Dict[str, Any]:
    if spec.trigger_type == "MANUAL":
        return {
            "manual": {
                "type": "Request",
                "kind": "Button",
                "inputs": {"schema": {"type": "object", "properties": {}, "required": []}},
            }
        }

    if spec.trigger_type == "SHAREPOINT_NEW_ITEM":
        c = CONNECTORS["sharepoint"]
        site = spec.trigger_params["site"]
        list_name = spec.trigger_params["list"]
        return {
            "When_a_new_item_is_created": {
                "type": "OpenApiConnection",
                "inputs": {
                    "host": _build_host(
                        c["api"],
                        c["connection"],
                        "GetOnNewItems",
                    ),
                    "parameters": {
                        "dataset": site,
                        "table": list_name,
                    },
                    "authentication": "@parameters('$authentication')",
                },
                "splitOn": "@triggerOutputs()?['body/value']",
            }
        }

    recurrence_params = dict(spec.trigger_params)
    frequency = recurrence_params.get("frequency", "Day")
    interval = recurrence_params.get("interval", 1)
    recurrence: Dict[str, Any] = {"frequency": frequency, "interval": interval}
    for passthrough in ("startTime", "timeZone"):
        if passthrough in recurrence_params:
            recurrence[passthrough] = recurrence_params[passthrough]
    schedule: Dict[str, Any] = {}
    for key, schedule_key in (
        ("hours", "hours"),
        ("minutes", "minutes"),
        ("weekDays", "weekDays"),
        ("monthDays", "monthDays"),
    ):
        if key in recurrence_params:
            schedule[schedule_key] = recurrence_params[key]
    if schedule:
        recurrence["schedule"] = schedule
    return {"recurrence": {"type": "Recurrence", "recurrence": recurrence}}


def compile_flow(spec: FlowSpec) -> Dict[str, Any]:
    used_connectors: Dict[str, Dict[str, str]] = {}
    actions: Dict[str, Any] = {}
    previous_action: str | None = None
    seen_names: set[str] = set()

    if spec.trigger_type == "SHAREPOINT_NEW_ITEM":
        c = CONNECTORS["sharepoint"]
        used_connectors[c["connection"]] = c

    for action in spec.actions:
        if action.name in seen_names:
            raise FlowFxError(
                f"Duplicate action name '{action.name}'. Use unique action names.",
                line_no=action.line_no,
            )
        seen_names.add(action.name)
        built = _build_action(action, spec.variables, used_connectors)
        if previous_action is None:
            built["runAfter"] = {}
        else:
            built["runAfter"] = {previous_action: ["Succeeded"]}
        actions[action.name] = built
        previous_action = action.name

    connection_references: Dict[str, Any] = {}
    for connection_name, connector in used_connectors.items():
        connection_references[connection_name] = {
            "runtimeSource": "embedded",
            "connection": {},
            "api": {"name": connector["api"]},
        }

    definition = {
        "$schema": FLOW_SCHEMA,
        "contentVersion": "1.0.0.0",
        "parameters": {
            "$connections": {"defaultValue": {}, "type": "Object"},
            "$authentication": {"defaultValue": {}, "type": "SecureObject"},
        },
        "triggers": _build_trigger(spec),
        "actions": actions,
        "outputs": {},
    }

    compiled = {
        "name": spec.name,
        "properties": {
            "definition": definition,
            "connectionReferences": connection_references,
        },
        "schemaVersion": SCHEMA_VERSION,
    }
    return compiled


def compile_flowfx_text(text: str) -> Dict[str, Any]:
    spec = parse_flowfx(text)
    return compile_flow(spec)


def compile_file(input_path: str | Path, output_path: str | Path | None = None) -> Dict[str, Any]:
    in_path = Path(input_path)
    text = in_path.read_text(encoding="utf-8")
    compiled = compile_flowfx_text(text)
    if output_path is not None:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(compiled, indent=2), encoding="utf-8")
    return compiled


def pretty_print_help() -> str:
    command_lines = "\n".join(f"  - {v}" for v in ACTION_HELP.values())
    return (
        "FlowFX quick help:\n"
        "Core commands:\n"
        "  - FLOW \"Display Name\"\n"
        "  - TRIGGER MANUAL\n"
        "  - TRIGGER RECURRENCE frequency=Day interval=1 timeZone=\"Pacific Standard Time\"\n"
        "  - SET VAR_NAME=\"value\"\n"
        "Action commands:\n"
        f"{command_lines}\n"
        "Notes:\n"
        "  - Variables use ${NAME} syntax inside values.\n"
        "  - Prefix value with fx: to emit a Power Automate expression wrapper, e.g. fx:concat('A','B').\n"
    )
