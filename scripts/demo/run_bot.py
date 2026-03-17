import argparse
import json
from pathlib import Path
import requests
from rich.console import Console
from rich.panel import Panel

console = Console()

def read_text_file(p: str) -> str:
    return Path(p).read_text(encoding="utf-8", errors="ignore")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", required=True)
    ap.add_argument("--api", default="http://127.0.0.1:8787")
    ap.add_argument("--no-server", action="store_true")
    ap.add_argument("--input", default="")
    ap.add_argument("--input-file", default="")
    ap.add_argument("--file", action="append", default=[])
    args = ap.parse_args()

    user_text = args.input
    if args.input_file:
        user_text = read_text_file(args.input_file)

    files_payload = []
    for f in args.file:
        files_payload.append({"name": Path(f).name, "text": read_text_file(f)})

    console.print(Panel(user_text or "(empty input)", title="USER", style="bold cyan"))

    if args.no_server:
        from bots.registry import get_registry
        reg = get_registry(refresh=True)
        if args.bot not in reg:
            console.print(Panel(f"Unknown bot: {args.bot}\\nAvailable: {', '.join(sorted(reg.keys()))}",
                                title="ERROR", style="bold red"))
            raise SystemExit(2)
        impl = reg[args.bot]

        # Invoke like server does
        def _invoke(impl, text, files):
            if callable(impl) and not hasattr(impl, "run") and not hasattr(impl, "invoke"):
                try:
                    return impl(text)
                except TypeError:
                    return impl(text=text, files=files)
            obj = impl() if callable(impl) else impl
            if hasattr(obj, "run"):
                try:
                    return obj.run(text)
                except TypeError:
                    return obj.run(text=text, files=files)
            if hasattr(obj, "invoke"):
                try:
                    return obj.invoke(text)
                except TypeError:
                    return obj.invoke(text=text, files=files)
            return str(obj)

        out = _invoke(impl, user_text, files_payload)
    else:
        # Call API
        try:
            requests.get(args.api + "/health", timeout=2).raise_for_status()
        except Exception:
            console.print(Panel(f"Demo API not reachable at {args.api}\\nStart it first: scripts/windows/demo_server.ps1",
                                title="ERROR", style="bold red"))
            raise SystemExit(3)

        r = requests.post(args.api + "/run", json={"bot": args.bot, "input": user_text, "files": files_payload}, timeout=120)
        r.raise_for_status()
        out = r.json().get("output")

    if isinstance(out, (dict, list)):
        out = json.dumps(out, indent=2)

    console.print(Panel(str(out), title=f"BOT: {args.bot}", style="bold magenta"))

if __name__ == "__main__":
    main()
