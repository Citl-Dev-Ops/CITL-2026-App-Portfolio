"""
FlowFX validator pack for CI-style quality gates.

Usage examples:
    python -m powerflow_builder.flowfx_validator_pack --input examples/*.flowfx
    python -m powerflow_builder.flowfx_validator_pack --input my.flowfx --report out

Exit code is non-zero when validation fails.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
import re
from typing import Any, Dict, List

try:
    from .flowfx_compiler import FlowFxError, compile_flowfx_text, parse_flowfx
except ImportError:
    from flowfx_compiler import FlowFxError, compile_flowfx_text, parse_flowfx


SECRET_PATTERNS = [
    re.compile(r"client[_-]?secret\s*=\s*[^\s]+", re.IGNORECASE),
    re.compile(r"password\s*=\s*[^\s]+", re.IGNORECASE),
    re.compile(r"token\s*=\s*[^\s]+", re.IGNORECASE),
]


def _line_warnings(text: str) -> List[str]:
    warnings: List[str] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if len(line) > 280:
            warnings.append(f"Line {idx}: extremely long line (>280 chars), hard to debug in run history.")
        for pat in SECRET_PATTERNS:
            if pat.search(line):
                warnings.append(f"Line {idx}: possible secret literal detected; move to secure parameters.")
                break
    return warnings


def validate_flowfx_text(text: str, source: str = "<memory>") -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    infos: List[str] = []
    compiled: Dict[str, Any] = {}

    warnings.extend(_line_warnings(text))

    try:
        spec = parse_flowfx(text)
    except FlowFxError as exc:
        return {
            "source": source,
            "ok": False,
            "errors": [str(exc)],
            "warnings": warnings,
            "infos": infos,
            "action_count": 0,
            "trigger": "unknown",
        }

    trigger = spec.trigger_type
    if trigger == "MANUAL":
        warnings.append("Trigger is MANUAL; production ticket intake usually needs a data trigger.")
    if not spec.actions:
        errors.append("Flow contains no actions.")

    for a in spec.actions:
        if a.kind == "SHAREPOINT_CREATE_ITEM":
            item = a.params.get("item")
            if isinstance(item, dict) and not any(k.lower() == "title" for k in item.keys()):
                warnings.append(
                    f"Line {a.line_no}: SHAREPOINT_CREATE_ITEM item has no 'Title' field; many lists require it."
                )

    try:
        compiled = compile_flowfx_text(text)
    except FlowFxError as exc:
        errors.append(str(exc))
    except Exception as exc:
        errors.append(f"Unexpected compile error: {exc}")

    if compiled:
        actions = (
            compiled.get("properties", {})
            .get("definition", {})
            .get("actions", {})
        )
        action_names = set(actions.keys())
        blob = json.dumps(compiled)

        for ref in re.findall(r"outputs\('([^']+)'\)", blob):
            if ref not in action_names:
                errors.append(f"Expression references unknown action output: {ref}")

        conn_refs = compiled.get("properties", {}).get("connectionReferences", {})
        for name, action in actions.items():
            inputs = action.get("inputs", {}) if isinstance(action, dict) else {}
            host = inputs.get("host", {}) if isinstance(inputs, dict) else {}
            conn_name = host.get("connectionName")
            if conn_name and conn_name not in conn_refs:
                errors.append(
                    f"Action '{name}' uses connection '{conn_name}' not present in connectionReferences."
                )

        infos.append(f"Compiled actions: {len(action_names)}")
        infos.append(f"Connection references: {len(conn_refs)}")

    return {
        "source": source,
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "action_count": len(spec.actions),
        "trigger": trigger,
    }


def validate_flowfx_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return validate_flowfx_text(text, source=str(path))


def run_validator_pack(inputs: List[str], report_dir: Path | None = None) -> Dict[str, Any]:
    expanded: List[Path] = []
    for raw in inputs:
        matches = [Path(p) for p in glob.glob(raw)]
        if matches:
            expanded.extend(matches)
        else:
            expanded.append(Path(raw))

    reports: List[Dict[str, Any]] = []
    for path in expanded:
        if not path.exists():
            reports.append(
                {
                    "source": str(path),
                    "ok": False,
                    "errors": ["File not found."],
                    "warnings": [],
                    "infos": [],
                    "action_count": 0,
                    "trigger": "unknown",
                }
            )
            continue
        reports.append(validate_flowfx_file(path))

    failed = [r for r in reports if not r.get("ok")]
    summary = {
        "ok": not failed,
        "total": len(reports),
        "failed": len(failed),
        "passed": len(reports) - len(failed),
        "reports": reports,
    }

    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
        out = report_dir / "flowfx_validator_report.json"
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return summary


def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate FlowFX files with CI-style checks.")
    parser.add_argument("--input", action="append", required=True, help="Input file or glob pattern.")
    parser.add_argument("--report", default="", help="Optional report directory.")
    args = parser.parse_args()

    report_dir = Path(args.report).resolve() if args.report else None
    result = run_validator_pack(args.input, report_dir=report_dir)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(_main())
