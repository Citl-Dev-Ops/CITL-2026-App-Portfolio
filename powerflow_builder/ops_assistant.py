"""
Utilities for Microsoft flow troubleshooting and access preflight checks.

This module intentionally avoids storing credentials. Tokens are supplied by
operators at runtime and kept in memory only.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlencode, urlparse
import urllib.error
import urllib.request

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
LOGIN_BASE = "https://login.microsoftonline.com"
USER_AGENT = "CITL-Ticketing-GUI/0.2"


def now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return None
    return None


def _decode_body(data: bytes) -> str:
    if not data:
        return ""
    return data.decode("utf-8", errors="replace")


def _http_json(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
    timeout: int = 20,
) -> Dict[str, Any]:
    req = urllib.request.Request(url=url, method=method.upper(), data=body)
    req.add_header("User-Agent", USER_AGENT)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            text = _decode_body(raw)
            parsed = _as_json(text)
            return {
                "ok": True,
                "status": int(resp.status),
                "headers": dict(resp.headers.items()),
                "text": text,
                "json": parsed,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        text = _decode_body(raw)
        parsed = _as_json(text)
        return {
            "ok": False,
            "status": int(exc.code),
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "text": text,
            "json": parsed,
            "error": f"HTTPError {exc.code}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": 0,
            "headers": {},
            "text": str(exc),
            "json": None,
            "error": str(exc),
        }


def begin_device_code(
    tenant: str,
    client_id: str,
    scope: str,
    timeout: int = 20,
) -> Dict[str, Any]:
    tenant = (tenant or "organizations").strip()
    payload = urlencode({"client_id": client_id.strip(), "scope": scope.strip()}).encode("utf-8")
    url = f"{LOGIN_BASE}/{tenant}/oauth2/v2.0/devicecode"
    return _http_json(
        "POST",
        url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=payload,
        timeout=timeout,
    )


def poll_device_token(
    tenant: str,
    client_id: str,
    device_code: str,
    timeout: int = 20,
) -> Dict[str, Any]:
    tenant = (tenant or "organizations").strip()
    payload = urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id.strip(),
            "device_code": device_code.strip(),
        }
    ).encode("utf-8")
    url = f"{LOGIN_BASE}/{tenant}/oauth2/v2.0/token"
    return _http_json(
        "POST",
        url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=payload,
        timeout=timeout,
    )


def graph_get(
    path_or_url: str,
    access_token: str,
    *,
    params: Optional[Dict[str, str]] = None,
    timeout: int = 20,
) -> Dict[str, Any]:
    url = path_or_url.strip()
    if not url.lower().startswith("http"):
        if not url.startswith("/"):
            url = "/" + url
        url = GRAPH_BASE + url
    if params:
        qs = urlencode({k: v for k, v in params.items() if v is not None})
        joiner = "&" if "?" in url else "?"
        url = f"{url}{joiner}{qs}"
    return _http_json(
        "GET",
        url,
        headers={"Authorization": f"Bearer {access_token.strip()}"},
        timeout=timeout,
    )


def graph_json_request(
    method: str,
    path_or_url: str,
    access_token: str,
    *,
    params: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    extra_headers: Optional[Dict[str, str]] = None,
    timeout: int = 20,
) -> Dict[str, Any]:
    """Issue a Graph request with optional JSON payload."""
    url = path_or_url.strip()
    if not url.lower().startswith("http"):
        if not url.startswith("/"):
            url = "/" + url
        url = GRAPH_BASE + url
    if params:
        qs = urlencode({k: v for k, v in params.items() if v is not None})
        joiner = "&" if "?" in url else "?"
        url = f"{url}{joiner}{qs}"

    headers: Dict[str, str] = {"Authorization": f"Bearer {access_token.strip()}"}
    body: Optional[bytes] = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if extra_headers:
        headers.update({k: v for k, v in extra_headers.items() if v is not None})

    return _http_json(
        method,
        url,
        headers=headers,
        body=body,
        timeout=timeout,
    )


def graph_post(
    path_or_url: str,
    access_token: str,
    payload: Dict[str, Any],
    *,
    params: Optional[Dict[str, str]] = None,
    timeout: int = 20,
) -> Dict[str, Any]:
    return graph_json_request(
        "POST",
        path_or_url,
        access_token,
        params=params,
        payload=payload,
        timeout=timeout,
    )


def graph_patch(
    path_or_url: str,
    access_token: str,
    payload: Dict[str, Any],
    *,
    params: Optional[Dict[str, str]] = None,
    timeout: int = 20,
    if_match: Optional[str] = None,
) -> Dict[str, Any]:
    headers = {"if-match": if_match} if if_match else None
    return graph_json_request(
        "PATCH",
        path_or_url,
        access_token,
        params=params,
        payload=payload,
        extra_headers=headers,
        timeout=timeout,
    )


def graph_delete(
    path_or_url: str,
    access_token: str,
    *,
    params: Optional[Dict[str, str]] = None,
    timeout: int = 20,
    if_match: Optional[str] = None,
) -> Dict[str, Any]:
    headers = {"if-match": if_match} if if_match else None
    return graph_json_request(
        "DELETE",
        path_or_url,
        access_token,
        params=params,
        payload=None,
        extra_headers=headers,
        timeout=timeout,
    )


def graph_list_mail_messages(
    *,
    access_token: str,
    folder: str = "inbox",
    top: int = 25,
    timeout: int = 20,
) -> Dict[str, Any]:
    """
    List recent messages from a mailbox folder using delegated Graph access.
    Returns normalized message rows suitable for ticket intake collation.
    """
    token = (access_token or "").strip()
    if not token:
        return {
            "ok": False,
            "status": 0,
            "endpoint": "",
            "error": "Missing access token.",
            "messages": [],
            "raw": None,
        }

    folder_name = (folder or "inbox").strip() or "inbox"
    try:
        top_n = int(top)
    except Exception:
        top_n = 25
    top_n = max(1, min(top_n, 100))

    endpoint = f"/me/mailFolders/{folder_name}/messages"
    params = {
        "$top": str(top_n),
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,from,toRecipients,receivedDateTime,bodyPreview,isRead,webLink",
    }
    resp = graph_get(endpoint, token, params=params, timeout=timeout)

    rows: List[Dict[str, Any]] = []
    payload = resp.get("json") if isinstance(resp.get("json"), dict) else {}
    values = payload.get("value") if isinstance(payload, dict) else []
    if isinstance(values, list):
        for item in values:
            if not isinstance(item, dict):
                continue
            sender_obj = item.get("from") if isinstance(item.get("from"), dict) else {}
            sender_addr_obj = (
                sender_obj.get("emailAddress")
                if isinstance(sender_obj, dict) and isinstance(sender_obj.get("emailAddress"), dict)
                else {}
            )
            sender_email = str(sender_addr_obj.get("address") or "").strip().lower()
            sender_name = str(sender_addr_obj.get("name") or "").strip()

            to_list: List[str] = []
            to_raw = item.get("toRecipients")
            if isinstance(to_raw, list):
                for recipient in to_raw:
                    if not isinstance(recipient, dict):
                        continue
                    addr_obj = (
                        recipient.get("emailAddress")
                        if isinstance(recipient.get("emailAddress"), dict)
                        else {}
                    )
                    addr = str(addr_obj.get("address") or "").strip().lower()
                    if addr:
                        to_list.append(addr)

            rows.append(
                {
                    "message_id": str(item.get("id") or "").strip(),
                    "subject": str(item.get("subject") or "").strip(),
                    "from_email": sender_email,
                    "from_name": sender_name,
                    "to_recipients": to_list,
                    "received_at": str(item.get("receivedDateTime") or "").strip(),
                    "is_read": bool(item.get("isRead")),
                    "body_preview": str(item.get("bodyPreview") or "").strip(),
                    "web_link": str(item.get("webLink") or "").strip(),
                }
            )

    return {
        "ok": bool(resp.get("ok")),
        "status": int(resp.get("status") or 0),
        "endpoint": endpoint,
        "error": str(resp.get("error") or ""),
        "messages": rows,
        "raw": resp.get("json"),
        "text": resp.get("text", ""),
    }


def _servicedesk_base_and_portal(service_desk_url: str) -> Dict[str, str]:
    raw = (service_desk_url or "").strip()
    if not raw:
        return {"base_url": "", "portal": ""}
    if not raw.lower().startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return {"base_url": "", "portal": ""}
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    parts = [p for p in parsed.path.split("/") if p]
    portal = ""
    if len(parts) >= 2 and parts[0].lower() == "app":
        portal = parts[1].strip()
    return {"base_url": base_url, "portal": portal}


def _servicedesk_request_urls(service_desk_url: str, portal: str = "") -> List[str]:
    parsed = _servicedesk_base_and_portal(service_desk_url)
    base_url = parsed.get("base_url", "")
    detected_portal = parsed.get("portal", "")
    use_portal = (portal or detected_portal).strip()
    if not base_url:
        return []
    out: List[str] = []
    if use_portal:
        out.append(f"{base_url}/app/{use_portal}/api/v3/requests")
    out.append(f"{base_url}/api/v3/requests")
    deduped: List[str] = []
    seen: set = set()
    for url in out:
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(url)
    return deduped


def servicedesk_list_requests(
    *,
    service_desk_url: str,
    authtoken: str,
    portal: str = "",
    row_count: int = 100,
    start_index: int = 1,
    sort_field: str = "created_time",
    sort_order: str = "desc",
    timeout: int = 25,
) -> Dict[str, Any]:
    """
    Pull request history from ManageEngine ServiceDesk Plus REST API v3.
    Uses GET /api/v3/requests with input_data list_info.
    """
    token = (authtoken or "").strip()
    if not token:
        return {
            "ok": False,
            "status": 0,
            "endpoint": "",
            "error": "Missing ServiceDesk authtoken.",
            "requests": [],
            "raw": None,
        }

    urls = _servicedesk_request_urls(service_desk_url, portal=portal)
    if not urls:
        return {
            "ok": False,
            "status": 0,
            "endpoint": "",
            "error": "Invalid ServiceDesk URL.",
            "requests": [],
            "raw": None,
        }

    try:
        count = int(row_count)
    except Exception:
        count = 100
    count = max(1, min(count, 200))
    try:
        start = int(start_index)
    except Exception:
        start = 1
    start = max(1, start)
    order = (sort_order or "desc").strip().lower()
    if order not in {"asc", "desc"}:
        order = "desc"
    field = (sort_field or "created_time").strip() or "created_time"

    input_data = {
        "list_info": {
            "row_count": count,
            "start_index": start,
            "sort_field": field,
            "sort_order": order,
            "get_total_count": True,
        }
    }

    headers = {
        "Accept": "application/vnd.manageengine.sdp.v3+json",
        "Content-Type": "application/x-www-form-urlencoded",
        "authtoken": token,
    }
    query = urlencode({"input_data": json.dumps(input_data)})

    last_resp: Dict[str, Any] = {
        "ok": False,
        "status": 0,
        "endpoint": "",
        "error": "No endpoint attempted.",
        "requests": [],
        "raw": None,
    }

    for base in urls:
        url = f"{base}?{query}"
        resp = _http_json("GET", url, headers=headers, timeout=timeout)
        payload = resp.get("json") if isinstance(resp.get("json"), dict) else {}
        requests_rows = payload.get("requests") if isinstance(payload, dict) else []
        if not isinstance(requests_rows, list):
            requests_rows = []
        normalized: List[Dict[str, Any]] = []
        for item in requests_rows:
            if not isinstance(item, dict):
                continue
            req_id = str(item.get("id") or item.get("display_id") or "").strip()
            created_obj = item.get("created_time") if isinstance(item.get("created_time"), dict) else {}
            created_display = str(created_obj.get("display_value") or "").strip()
            requester_obj = item.get("requester") if isinstance(item.get("requester"), dict) else {}
            created_by_obj = item.get("created_by") if isinstance(item.get("created_by"), dict) else {}
            status_obj = item.get("status") if isinstance(item.get("status"), dict) else {}
            priority_obj = item.get("priority") if isinstance(item.get("priority"), dict) else {}
            technician_obj = item.get("technician") if isinstance(item.get("technician"), dict) else {}
            normalized.append(
                {
                    "request_id": req_id,
                    "subject": str(item.get("subject") or item.get("short_description") or "").strip(),
                    "description": str(item.get("description") or item.get("short_description") or "").strip(),
                    "status": str(status_obj.get("name") or "").strip(),
                    "priority": str(priority_obj.get("name") or "").strip(),
                    "requester_name": str(
                        requester_obj.get("name") or created_by_obj.get("name") or ""
                    ).strip(),
                    "requester_email": str(
                        requester_obj.get("email_id") or created_by_obj.get("email_id") or ""
                    ).strip().lower(),
                    "assigned_to": str(technician_obj.get("name") or "").strip(),
                    "created_time": created_display,
                    "raw": item,
                }
            )

        last_resp = {
            "ok": bool(resp.get("ok")),
            "status": int(resp.get("status") or 0),
            "endpoint": url,
            "error": str(resp.get("error") or ""),
            "requests": normalized,
            "raw": payload if payload else resp.get("json"),
            "text": resp.get("text", ""),
        }
        if last_resp["ok"]:
            return last_resp

    return last_resp


def _normalize_sharepoint_host_and_path(
    site_hostname: str,
    site_relative_path: str,
) -> Dict[str, str]:
    host = (site_hostname or "").strip()
    rel = (site_relative_path or "").strip()

    if host.lower().startswith("https://"):
        host = host[8:]
    elif host.lower().startswith("http://"):
        host = host[7:]
    host = host.strip().strip("/")

    # Allow passing a full site URL in site_hostname.
    if "/" in host:
        host_only, trailing = host.split("/", 1)
        host = host_only.strip()
        if not rel:
            rel = trailing

    rel = rel.strip().strip("/")
    return {"host": host, "rel": rel}


def sharepoint_resolve_site(
    *,
    access_token: str,
    site_hostname: str,
    site_relative_path: str,
    timeout: int = 20,
) -> Dict[str, Any]:
    norm = _normalize_sharepoint_host_and_path(site_hostname, site_relative_path)
    host = norm["host"]
    rel = norm["rel"]
    if not host:
        return {
            "ok": False,
            "endpoint": "",
            "site_id": "",
            "site": None,
            "response": {"ok": False, "status": 0, "error": "Missing site hostname."},
            "error": "Missing site hostname.",
        }

    endpoint = f"/sites/{host}:/{rel}" if rel else f"/sites/{host}:/"
    resp = graph_get(endpoint, access_token, timeout=timeout)
    site_json = resp.get("json") if resp.get("ok") and isinstance(resp.get("json"), dict) else None
    site_id = str(site_json.get("id") or "") if site_json else ""
    err = "" if resp.get("ok") and site_id else "Unable to resolve SharePoint site."
    return {
        "ok": bool(resp.get("ok") and site_id),
        "endpoint": endpoint,
        "site_id": site_id,
        "site": site_json,
        "response": resp,
        "error": err,
    }


def sharepoint_resolve_list(
    *,
    access_token: str,
    site_id: str,
    list_name: str = "",
    list_id: str = "",
    timeout: int = 20,
) -> Dict[str, Any]:
    sid = (site_id or "").strip()
    if not sid:
        return {
            "ok": False,
            "list_id": "",
            "list": None,
            "response": {"ok": False, "status": 0, "error": "Missing site id."},
            "error": "Missing site id.",
        }

    given_list_id = (list_id or "").strip()
    if given_list_id:
        detail_resp = graph_get(
            f"/sites/{sid}/lists/{given_list_id}",
            access_token,
            params={"$select": "id,name,displayName,webUrl"},
            timeout=timeout,
        )
        detail_json = (
            detail_resp.get("json")
            if detail_resp.get("ok") and isinstance(detail_resp.get("json"), dict)
            else None
        )
        resolved_id = str(detail_json.get("id") or "") if detail_json else ""
        return {
            "ok": bool(detail_resp.get("ok") and resolved_id),
            "list_id": resolved_id,
            "list": detail_json,
            "response": detail_resp,
            "error": "" if detail_resp.get("ok") and resolved_id else "Unable to resolve list by id.",
        }

    wanted = (list_name or "").strip().lower()
    list_resp = graph_get(
        f"/sites/{sid}/lists",
        access_token,
        params={"$select": "id,name,displayName,webUrl"},
        timeout=timeout,
    )
    list_json = list_resp.get("json") if list_resp.get("ok") and isinstance(list_resp.get("json"), dict) else {}
    entries = list_json.get("value") if isinstance(list_json.get("value"), list) else []

    found: Optional[Dict[str, Any]] = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not wanted:
            found = entry
            break
        n1 = str(entry.get("name") or "").strip().lower()
        n2 = str(entry.get("displayName") or "").strip().lower()
        if wanted in {n1, n2}:
            found = entry
            break

    resolved_id = str(found.get("id") or "") if isinstance(found, dict) else ""
    return {
        "ok": bool(list_resp.get("ok") and resolved_id),
        "list_id": resolved_id,
        "list": found,
        "response": list_resp,
        "error": "" if list_resp.get("ok") and resolved_id else f"List '{list_name}' not found.",
    }


def sharepoint_list_items_list(
    *,
    access_token: str,
    site_id: str,
    list_id: str,
    top: int = 100,
    filter_expr: str = "",
    orderby: str = "",
    select_fields: Optional[List[str]] = None,
    timeout: int = 20,
) -> Dict[str, Any]:
    sid = (site_id or "").strip()
    lid = (list_id or "").strip()
    if not sid or not lid:
        return {
            "ok": False,
            "items": [],
            "response": {"ok": False, "status": 0, "error": "Missing site/list id."},
            "error": "Missing site/list id.",
        }

    params: Dict[str, str] = {}
    if top and top > 0:
        params["$top"] = str(int(top))
    if filter_expr.strip():
        params["$filter"] = filter_expr.strip()
    if orderby.strip():
        params["$orderby"] = orderby.strip()

    cleaned = [f.strip() for f in (select_fields or []) if f and f.strip()]
    if cleaned:
        params["$expand"] = f"fields($select={','.join(cleaned)})"
    else:
        params["$expand"] = "fields"

    resp = graph_get(
        f"/sites/{sid}/lists/{lid}/items",
        access_token,
        params=params,
        timeout=timeout,
    )
    payload = resp.get("json") if resp.get("ok") and isinstance(resp.get("json"), dict) else {}
    items = payload.get("value") if isinstance(payload.get("value"), list) else []
    return {
        "ok": bool(resp.get("ok")),
        "items": items,
        "next_link": str(payload.get("@odata.nextLink") or ""),
        "response": resp,
        "error": "" if resp.get("ok") else "Unable to list SharePoint items.",
    }


def sharepoint_list_item_get(
    *,
    access_token: str,
    site_id: str,
    list_id: str,
    item_id: str,
    select_fields: Optional[List[str]] = None,
    timeout: int = 20,
) -> Dict[str, Any]:
    sid = (site_id or "").strip()
    lid = (list_id or "").strip()
    iid = str(item_id or "").strip()
    if not sid or not lid or not iid:
        return {
            "ok": False,
            "item": None,
            "response": {"ok": False, "status": 0, "error": "Missing site/list/item id."},
            "error": "Missing site/list/item id.",
        }

    params: Dict[str, str] = {}
    cleaned = [f.strip() for f in (select_fields or []) if f and f.strip()]
    if cleaned:
        params["$expand"] = f"fields($select={','.join(cleaned)})"
    else:
        params["$expand"] = "fields"

    resp = graph_get(
        f"/sites/{sid}/lists/{lid}/items/{iid}",
        access_token,
        params=params,
        timeout=timeout,
    )
    item_json = resp.get("json") if resp.get("ok") and isinstance(resp.get("json"), dict) else None
    return {
        "ok": bool(resp.get("ok") and item_json is not None),
        "item": item_json,
        "response": resp,
        "error": "" if resp.get("ok") else "Unable to read SharePoint item.",
    }


def sharepoint_list_item_create(
    *,
    access_token: str,
    site_id: str,
    list_id: str,
    fields: Dict[str, Any],
    timeout: int = 20,
) -> Dict[str, Any]:
    sid = (site_id or "").strip()
    lid = (list_id or "").strip()
    if not sid or not lid:
        return {
            "ok": False,
            "item": None,
            "response": {"ok": False, "status": 0, "error": "Missing site/list id."},
            "error": "Missing site/list id.",
        }
    if not isinstance(fields, dict) or not fields:
        return {
            "ok": False,
            "item": None,
            "response": {"ok": False, "status": 0, "error": "Create fields payload is empty."},
            "error": "Create fields payload is empty.",
        }

    resp = graph_post(
        f"/sites/{sid}/lists/{lid}/items",
        access_token,
        {"fields": fields},
        timeout=timeout,
    )
    item_json = resp.get("json") if resp.get("ok") and isinstance(resp.get("json"), dict) else None
    return {
        "ok": bool(resp.get("ok") and item_json is not None),
        "item": item_json,
        "response": resp,
        "error": "" if resp.get("ok") else "Unable to create SharePoint item.",
    }


def sharepoint_list_item_update(
    *,
    access_token: str,
    site_id: str,
    list_id: str,
    item_id: str,
    fields: Dict[str, Any],
    timeout: int = 20,
    if_match: Optional[str] = None,
) -> Dict[str, Any]:
    sid = (site_id or "").strip()
    lid = (list_id or "").strip()
    iid = str(item_id or "").strip()
    if not sid or not lid or not iid:
        return {
            "ok": False,
            "fields": None,
            "response": {"ok": False, "status": 0, "error": "Missing site/list/item id."},
            "error": "Missing site/list/item id.",
        }
    if not isinstance(fields, dict) or not fields:
        return {
            "ok": False,
            "fields": None,
            "response": {"ok": False, "status": 0, "error": "Update fields payload is empty."},
            "error": "Update fields payload is empty.",
        }

    # For SharePoint list items, Graph expects a fieldValueSet payload on /fields.
    resp = graph_patch(
        f"/sites/{sid}/lists/{lid}/items/{iid}/fields",
        access_token,
        fields,
        timeout=timeout,
        if_match=if_match,
    )
    updated_fields = resp.get("json") if resp.get("ok") and isinstance(resp.get("json"), dict) else None
    return {
        "ok": bool(resp.get("ok")),
        "fields": updated_fields,
        "response": resp,
        "error": "" if resp.get("ok") else "Unable to update SharePoint item.",
    }


def sharepoint_list_item_delete(
    *,
    access_token: str,
    site_id: str,
    list_id: str,
    item_id: str,
    timeout: int = 20,
    if_match: Optional[str] = None,
) -> Dict[str, Any]:
    sid = (site_id or "").strip()
    lid = (list_id or "").strip()
    iid = str(item_id or "").strip()
    if not sid or not lid or not iid:
        return {
            "ok": False,
            "response": {"ok": False, "status": 0, "error": "Missing site/list/item id."},
            "error": "Missing site/list/item id.",
        }

    resp = graph_delete(
        f"/sites/{sid}/lists/{lid}/items/{iid}",
        access_token,
        timeout=timeout,
        if_match=if_match,
    )
    return {
        "ok": bool(resp.get("ok")),
        "response": resp,
        "error": "" if resp.get("ok") else "Unable to delete SharePoint item.",
    }


def sharepoint_list_item_upsert_by_field(
    *,
    access_token: str,
    site_id: str,
    list_id: str,
    key_field: str,
    key_value: str,
    fields: Dict[str, Any],
    timeout: int = 20,
) -> Dict[str, Any]:
    """Update existing item by a key field; create if not found."""
    sid = (site_id or "").strip()
    lid = (list_id or "").strip()
    key = (key_field or "").strip()
    val = (key_value or "").strip()
    if not sid or not lid or not key:
        return {
            "ok": False,
            "mode": "none",
            "response": {"ok": False, "status": 0, "error": "Missing site/list/key field."},
            "error": "Missing site/list/key field.",
        }

    safe_val = val.replace("'", "''")
    lookup = sharepoint_list_items_list(
        access_token=access_token,
        site_id=sid,
        list_id=lid,
        top=1,
        filter_expr=f"fields/{key} eq '{safe_val}'",
        select_fields=[key],
        timeout=timeout,
    )
    if not lookup.get("ok"):
        return {
            "ok": False,
            "mode": "none",
            "response": lookup.get("response", {}),
            "error": lookup.get("error", "Lookup failed."),
        }

    items = lookup.get("items") if isinstance(lookup.get("items"), list) else []
    if items:
        item_id = str(items[0].get("id") or "")
        update_resp = sharepoint_list_item_update(
            access_token=access_token,
            site_id=sid,
            list_id=lid,
            item_id=item_id,
            fields=fields,
            timeout=timeout,
        )
        return {"mode": "update", **update_resp}

    create_fields = dict(fields)
    if key and key not in create_fields and val:
        create_fields[key] = val
    create_resp = sharepoint_list_item_create(
        access_token=access_token,
        site_id=sid,
        list_id=lid,
        fields=create_fields,
        timeout=timeout,
    )
    return {"mode": "create", **create_resp}


def _collect_actions_from_map(actions_map: Dict[str, Any], bucket: List[Dict[str, Any]]) -> None:
    for name, node in actions_map.items():
        if isinstance(node, dict):
            bucket.append({"action_name": str(name), "node": node})


def _walk_for_actions(value: Any, bucket: List[Dict[str, Any]]) -> None:
    if isinstance(value, dict):
        actions = value.get("actions")
        if isinstance(actions, dict):
            _collect_actions_from_map(actions, bucket)
        props = value.get("properties")
        if isinstance(props, dict) and isinstance(props.get("actions"), dict):
            _collect_actions_from_map(props["actions"], bucket)
        for v in value.values():
            _walk_for_actions(v, bucket)
        return
    if isinstance(value, list):
        for item in value:
            _walk_for_actions(item, bucket)


def _extract_error_blob(node: Dict[str, Any]) -> str:
    candidates: List[Any] = []
    for path in (
        ("error",),
        ("properties", "error"),
        ("outputs",),
        ("properties", "outputs"),
        ("outputs", "body"),
        ("properties", "outputs", "body"),
        ("message",),
    ):
        cur: Any = node
        ok = True
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            candidates.append(cur)

    if not candidates:
        return json.dumps(node)

    blocks: List[str] = []
    for c in candidates:
        if isinstance(c, str):
            blocks.append(c)
        else:
            try:
                blocks.append(json.dumps(c))
            except Exception:
                blocks.append(str(c))
    return "\n".join(blocks)


def analyze_flow_run_payload(
    raw_text: str,
    diagnose_fn: Callable[[str], Dict[str, Any]],
) -> Dict[str, Any]:
    parsed = _as_json(raw_text)
    if parsed is None:
        return {
            "ok": False,
            "parse_error": "Input is not valid JSON.",
            "summary": "Could not parse flow run payload as JSON.",
            "failing_actions": [],
        }

    run_info = {
        "id": "",
        "name": "",
        "status": "",
        "start_time": "",
        "end_time": "",
        "client_tracking_id": "",
    }

    if isinstance(parsed, dict):
        run_info["id"] = str(parsed.get("id") or "")
        run_info["name"] = str(parsed.get("name") or "")
        run_info["status"] = str(parsed.get("status") or "")
        props = parsed.get("properties") if isinstance(parsed.get("properties"), dict) else {}
        run_info["status"] = run_info["status"] or str(props.get("status") or "")
        run_info["start_time"] = str(props.get("startTime") or props.get("start_time") or "")
        run_info["end_time"] = str(props.get("endTime") or props.get("end_time") or "")
        run_info["client_tracking_id"] = str(
            props.get("clientTrackingId") or props.get("correlation", {}).get("clientTrackingId", "")
        )

    action_nodes: List[Dict[str, Any]] = []
    _walk_for_actions(parsed, action_nodes)

    if isinstance(parsed, dict) and isinstance(parsed.get("value"), list):
        for item in parsed["value"]:
            if not isinstance(item, dict):
                continue
            pname = str(item.get("name") or item.get("id") or "Action")
            pnode = item.get("properties") if isinstance(item.get("properties"), dict) else item
            action_nodes.append({"action_name": pname, "node": pnode})

    failing_actions: List[Dict[str, Any]] = []
    cascade_actions: List[Dict[str, Any]] = []
    seen = set()

    for item in action_nodes:
        action_name = str(item.get("action_name") or "Action")
        node = item.get("node") if isinstance(item.get("node"), dict) else {}
        dedupe_key = (action_name, id(node))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        status = str(node.get("status") or node.get("properties", {}).get("status") or "")
        lower_status = status.lower()

        error_blob = _extract_error_blob(node)
        diagnosis = diagnose_fn(error_blob)

        action_row = {
            "action_name": action_name,
            "status": status or "unknown",
            "type": str(node.get("type") or node.get("properties", {}).get("type") or ""),
            "connector_api": str(
                node.get("inputs", {}).get("host", {}).get("apiId")
                or node.get("properties", {}).get("inputs", {}).get("host", {}).get("apiId")
                or ""
            ),
            "operation_id": str(
                node.get("inputs", {}).get("host", {}).get("operationId")
                or node.get("properties", {}).get("inputs", {}).get("host", {}).get("operationId")
                or ""
            ),
            "error_excerpt": error_blob[:1200],
            "diagnosis": diagnosis,
        }

        if lower_status in {"failed", "timedout", "cancelled", "aborted"}:
            failing_actions.append(action_row)
        elif lower_status == "skipped":
            code_blob = error_blob.lower()
            if "actionbranchingconditionnotsatisfied" in code_blob or "branching condition" in code_blob:
                cascade_actions.append(action_row)

    failing_actions.sort(
        key=lambda a: (
            0 if a.get("status", "").lower() == "failed" else 1,
            0 if a.get("diagnosis", {}).get("determinism") == "deterministic" else 1,
        )
    )

    root_cause = failing_actions[0] if failing_actions else None
    summary = "No failed actions were detected in imported payload."
    if root_cause:
        top_diag = root_cause.get("diagnosis", {}).get("operator_summary", "")
        summary = f"Root candidate: {root_cause['action_name']} ({root_cause['status']}). {top_diag}"

    return {
        "ok": True,
        "run_info": run_info,
        "summary": summary,
        "failing_actions": failing_actions,
        "cascade_actions": cascade_actions,
        "imported_action_count": len(action_nodes),
    }


def run_graph_preflight(
    *,
    access_token: str,
    site_hostname: str,
    site_relative_path: str,
    list_name: str,
    mail_folder: str,
    timeout: int = 20,
) -> Dict[str, Any]:
    token = (access_token or "").strip()
    if not token:
        return {
            "ok": False,
            "overall_status": "fail",
            "summary": "No access token provided.",
            "checks": [],
            "generated_at": now_iso_utc(),
        }

    checks: List[Dict[str, Any]] = []

    def record(
        check_id: str,
        name: str,
        endpoint: str,
        response: Dict[str, Any],
        required_permissions: List[str],
        optional_detail: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        status_code = int(response.get("status") or 0)
        if response.get("ok"):
            status = "pass"
        elif status_code in (401, 403):
            status = "fail"
        elif status_code in (404, 429, 500, 502, 503, 504):
            status = "warning"
        else:
            status = "fail"

        row = {
            "id": check_id,
            "name": name,
            "endpoint": endpoint,
            "http_status": status_code,
            "status": status,
            "required_permissions": required_permissions,
            "error_text": response.get("text", "")[:800],
        }
        if optional_detail is not None:
            row["detail"] = optional_detail
        checks.append(row)
        return row

    me_resp = graph_get(
        "/me",
        token,
        params={"$select": "id,displayName,userPrincipalName"},
        timeout=timeout,
    )
    record(
        "graph_me",
        "Graph delegated identity",
        "/me?$select=id,displayName,userPrincipalName",
        me_resp,
        ["User.Read"],
        me_resp.get("json") if me_resp.get("ok") else None,
    )

    mailbox_resp = graph_get(
        "/me/mailboxSettings",
        token,
        params={"$select": "timeZone,language,userPurpose"},
        timeout=timeout,
    )
    record(
        "mailbox_settings",
        "Mailbox settings read",
        "/me/mailboxSettings",
        mailbox_resp,
        ["MailboxSettings.Read"],
        mailbox_resp.get("json") if mailbox_resp.get("ok") else None,
    )

    folder = (mail_folder or "inbox").strip().lower()
    folder_resp = graph_get(
        f"/me/mailFolders/{folder}",
        token,
        params={"$select": "id,displayName,parentFolderId,totalItemCount"},
        timeout=timeout,
    )
    record(
        "mail_folder",
        "Inbox/shared folder visibility",
        f"/me/mailFolders/{folder}",
        folder_resp,
        ["Mail.ReadBasic or Mail.Read"],
        folder_resp.get("json") if folder_resp.get("ok") else None,
    )

    host = (site_hostname or "").strip()
    rel = (site_relative_path or "").strip().strip("/")
    site_endpoint = f"/sites/{host}:/{rel}" if rel else f"/sites/{host}:/"

    site_resp = graph_get(site_endpoint, token, timeout=timeout)
    record(
        "sharepoint_site",
        "SharePoint site path lookup",
        site_endpoint,
        site_resp,
        ["Sites.Read.All"],
        site_resp.get("json") if site_resp.get("ok") else None,
    )

    matched_list = None
    if site_resp.get("ok") and isinstance(site_resp.get("json"), dict):
        site_id = str(site_resp["json"].get("id") or "")
        if site_id:
            lists_resp = graph_get(
                f"/sites/{site_id}/lists",
                token,
                params={"$select": "id,name,displayName"},
                timeout=timeout,
            )
            detail = lists_resp.get("json") if lists_resp.get("ok") else None
            list_row = record(
                "sharepoint_lists",
                "SharePoint lists enumeration",
                f"/sites/{site_id}/lists",
                lists_resp,
                ["Sites.Read.All"],
                detail,
            )

            wanted = (list_name or "").strip().lower()
            if lists_resp.get("ok") and isinstance(detail, dict) and isinstance(detail.get("value"), list):
                for entry in detail["value"]:
                    if not isinstance(entry, dict):
                        continue
                    for key in ("name", "displayName"):
                        value = str(entry.get(key) or "").strip().lower()
                        if wanted and value == wanted:
                            matched_list = entry
                            break
                    if matched_list:
                        break
                if wanted and not matched_list:
                    list_row["status"] = "warning"
                    list_row["error_text"] = f"Target list '{list_name}' was not found in site enumeration."

            if matched_list and isinstance(matched_list, dict):
                list_id = str(matched_list.get("id") or "")
                list_get_resp = graph_get(
                    f"/sites/{site_id}/lists/{list_id}",
                    token,
                    params={"$select": "id,name,displayName,webUrl"},
                    timeout=timeout,
                )
                record(
                    "sharepoint_list",
                    "Target list detail read",
                    f"/sites/{site_id}/lists/{list_id}",
                    list_get_resp,
                    ["Sites.Read.All"],
                    list_get_resp.get("json") if list_get_resp.get("ok") else None,
                )

    total_fail = sum(1 for c in checks if c["status"] == "fail")
    total_warn = sum(1 for c in checks if c["status"] == "warning")
    if total_fail:
        overall = "fail"
    elif total_warn:
        overall = "warning"
    else:
        overall = "pass"

    return {
        "ok": overall != "fail",
        "overall_status": overall,
        "summary": f"Preflight completed with {total_fail} fail, {total_warn} warning, {len(checks)} checks.",
        "checks": checks,
        "generated_at": now_iso_utc(),
        "observed_target_list": matched_list,
    }
