#!/usr/bin/env python3
"""
Run extensive Locust profiles for Module B and export structured artifacts.

Outputs:
- CSV per profile: performance/locust_<profile>_*.csv
- JSON per profile: performance/module_b_locust_report_<profile>.json
- Consolidated JSON: performance/module_b_locust_profiles_report.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_USERNAMES = [
    "rahul.sharma@iitgn.ac.in",
    "priya.patel@iitgn.ac.in",
    "ananya.singh@iitgn.ac.in",
    "neha.desai@iitgn.ac.in",
    "aditya.verma@iitgn.ac.in",
]

PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "smoke": {"users": 30, "spawn_rate": 6, "run_time": "90s"},
    "medium": {"users": 80, "spawn_rate": 12, "run_time": "3m"},
    "high": {"users": 160, "spawn_rate": 20, "run_time": "5m"},
    "extreme": {"users": 240, "spawn_rate": 30, "run_time": "7m"},
}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_usernames(raw: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in raw.split(","):
        email = item.strip()
        if not email or email in seen:
            continue
        seen.add(email)
        out.append(email)
    return out


def _parse_profiles(raw: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in raw.split(","):
        name = item.strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    raw = str(value).strip().replace(",", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _find_aggregated_row(rows: list[dict[str, str]]) -> dict[str, str]:
    for row in rows:
        row_type = (row.get("Type") or "").strip().lower()
        row_name = (row.get("Name") or "").strip().lower()
        if row_type == "aggregated" or row_name == "aggregated":
            return row
    if rows:
        return rows[-1]
    raise RuntimeError("No rows found in Locust stats CSV")


def _read_stats_summary(stats_csv: Path) -> dict[str, float | int]:
    rows = _read_csv_rows(stats_csv)
    agg = _find_aggregated_row(rows)

    request_count = int(_to_float(agg.get("Request Count"), 0.0))
    failure_count = int(_to_float(agg.get("Failure Count"), 0.0))
    error_rate = (failure_count / request_count) if request_count > 0 else 0.0

    p50_value = _to_float(agg.get("50%"), _to_float(agg.get("Median Response Time"), 0.0))

    return {
        "request_count": request_count,
        "failure_count": failure_count,
        "error_rate": round(error_rate, 6),
        "avg_response_ms": round(_to_float(agg.get("Average Response Time"), 0.0), 3),
        "min_response_ms": round(_to_float(agg.get("Min Response Time"), 0.0), 3),
        "max_response_ms": round(_to_float(agg.get("Max Response Time"), 0.0), 3),
        "p50_response_ms": round(p50_value, 3),
        "p95_response_ms": round(_to_float(agg.get("95%"), 0.0), 3),
        "p99_response_ms": round(_to_float(agg.get("99%"), 0.0), 3),
        "requests_per_s": round(_to_float(agg.get("Requests/s"), 0.0), 3),
        "failures_per_s": round(_to_float(agg.get("Failures/s"), 0.0), 3),
    }


def _read_failures_summary(failures_csv: Path, top_n: int = 10) -> list[dict[str, Any]]:
    rows = _read_csv_rows(failures_csv)
    out: list[dict[str, Any]] = []
    for row in rows[:top_n]:
        out.append(
            {
                "method": row.get("Method", ""),
                "name": row.get("Name", ""),
                "error": row.get("Error", ""),
                "occurrences": int(_to_float(row.get("Occurrences"), _to_float(row.get("Count"), 0.0))),
            }
        )
    return out


def _check_locust_available() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "locust", "--version"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Locust is not available. Install dependencies using: "
            "python -m pip install -r Module_B/requirements.txt"
        )
    output = (proc.stdout or proc.stderr).strip()
    return output if output else "locust (version unavailable)"


def _run_profile(
    *,
    profile_name: str,
    profile_cfg: dict[str, Any],
    base_url: str,
    usernames: list[str],
    password: str,
    post_id: int,
    target_member_id: int,
    stop_timeout: int,
    csv_full_history: bool,
    max_error_rate: float,
    max_p95_ms: float,
    output_dir: Path,
    locustfile: Path,
    module_b_root: Path,
) -> dict[str, Any]:
    csv_prefix = output_dir / f"locust_{profile_name}"
    cmd = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(locustfile),
        "--headless",
        "--host",
        base_url,
        "--users",
        str(profile_cfg["users"]),
        "--spawn-rate",
        str(profile_cfg["spawn_rate"]),
        "--run-time",
        str(profile_cfg["run_time"]),
        "--stop-timeout",
        str(stop_timeout),
        "--csv",
        str(csv_prefix),
        "--only-summary",
    ]
    if csv_full_history:
        cmd.append("--csv-full-history")

    env = os.environ.copy()
    env["MODULE_B_USERNAMES"] = ",".join(usernames)
    env["MODULE_B_PASSWORD"] = password
    env["MODULE_B_POST_ID"] = str(post_id)
    env["MODULE_B_TARGET_MEMBER_ID"] = str(target_member_id)

    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(module_b_root),
        capture_output=True,
        text=True,
        env=env,
    )
    elapsed_s = round(time.perf_counter() - started, 3)

    stats_csv = Path(f"{csv_prefix}_stats.csv")
    failures_csv = Path(f"{csv_prefix}_failures.csv")
    exceptions_csv = Path(f"{csv_prefix}_exceptions.csv")

    result: dict[str, Any] = {
        "profile": profile_name,
        "config": profile_cfg,
        "command": cmd,
        "elapsed_s": elapsed_s,
        "return_code": proc.returncode,
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-25:]),
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-25:]),
        "stats_csv": str(stats_csv),
        "failures_csv": str(failures_csv),
        "exceptions_csv": str(exceptions_csv),
    }

    if proc.returncode != 0:
        result["status"] = "runner_error"
        result["profile_pass"] = False
        return result

    if not stats_csv.exists():
        result["status"] = "missing_stats_csv"
        result["profile_pass"] = False
        return result

    summary = _read_stats_summary(stats_csv)
    top_failures = _read_failures_summary(failures_csv)

    profile_pass = summary["error_rate"] <= max_error_rate
    if max_p95_ms > 0:
        profile_pass = profile_pass and summary["p95_response_ms"] <= max_p95_ms

    result["status"] = "completed"
    result["summary"] = summary
    result["top_failures"] = top_failures
    result["pass_thresholds"] = {
        "max_error_rate": max_error_rate,
        "max_p95_ms": max_p95_ms,
    }
    result["profile_pass"] = bool(profile_pass)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run extensive Locust profiles for Module B")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--usernames", default=",".join(DEFAULT_USERNAMES))
    parser.add_argument("--password", default="password123")
    parser.add_argument("--post-id", type=int, default=1)
    parser.add_argument("--target-member-id", type=int, default=19)

    parser.add_argument("--profiles", default="smoke,medium,high")
    parser.add_argument("--include-extreme", action="store_true")

    parser.add_argument("--max-error-rate", type=float, default=0.05)
    parser.add_argument("--max-p95-ms", type=float, default=1500.0)
    parser.add_argument("--stop-timeout", type=int, default=30)

    parser.add_argument("--csv-full-history", action="store_true")
    parser.add_argument("--output-dir", default="performance")
    parser.add_argument("--locustfile", default="performance/locustfile_module_b.py")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    usernames = _parse_usernames(args.usernames)
    if not usernames:
        raise RuntimeError("Provide at least one username via --usernames")

    module_b_root = Path(__file__).resolve().parents[1]
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = module_b_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    locustfile = Path(args.locustfile)
    if not locustfile.is_absolute():
        locustfile = module_b_root / locustfile
    if not locustfile.exists():
        raise FileNotFoundError(f"Locust file not found: {locustfile}")

    locust_version = _check_locust_available()

    selected_profiles = _parse_profiles(args.profiles)
    if args.include_extreme and "extreme" not in selected_profiles:
        selected_profiles.append("extreme")

    unknown = [name for name in selected_profiles if name not in PROFILE_PRESETS]
    if unknown:
        raise RuntimeError(f"Unknown profile(s): {unknown}. Allowed: {list(PROFILE_PRESETS.keys())}")

    results: list[dict[str, Any]] = []
    for profile_name in selected_profiles:
        profile_cfg = PROFILE_PRESETS[profile_name]
        print(
            f"Running Locust profile {profile_name} "
            f"(users={profile_cfg['users']}, spawn_rate={profile_cfg['spawn_rate']}, run_time={profile_cfg['run_time']})"
        )
        result = _run_profile(
            profile_name=profile_name,
            profile_cfg=profile_cfg,
            base_url=args.base_url,
            usernames=usernames,
            password=args.password,
            post_id=args.post_id,
            target_member_id=args.target_member_id,
            stop_timeout=args.stop_timeout,
            csv_full_history=args.csv_full_history,
            max_error_rate=args.max_error_rate,
            max_p95_ms=args.max_p95_ms,
            output_dir=output_dir,
            locustfile=locustfile,
            module_b_root=module_b_root,
        )
        results.append(result)

        per_profile_path = output_dir / f"module_b_locust_report_{profile_name}.json"
        per_profile_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

        status = result.get("status", "unknown")
        profile_pass = result.get("profile_pass", False)
        print(f"  status={status}, pass={profile_pass}, elapsed={result['elapsed_s']}s")

    overall_pass = all(r.get("status") == "completed" and r.get("profile_pass", False) for r in results)

    consolidated = {
        "timestamp_utc": _now_utc_iso(),
        "locust_version": locust_version,
        "base_url": args.base_url,
        "usernames": usernames,
        "profile_count": len(selected_profiles),
        "profiles": selected_profiles,
        "thresholds": {
            "max_error_rate": args.max_error_rate,
            "max_p95_ms": args.max_p95_ms,
        },
        "results": results,
        "overall_pass": overall_pass,
    }

    consolidated_path = output_dir / "module_b_locust_profiles_report.json"
    consolidated_path.write_text(json.dumps(consolidated, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "overall_pass": overall_pass,
                "profiles": selected_profiles,
                "output": str(consolidated_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
