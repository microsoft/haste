# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Benchmark GetProjectDetails against a running HASTE API (real latency).

Use this once the full stack is up (Docker Compose or Azure) and a synthetic
project has been seeded into that backend. It captures end-to-end p50/p95 latency
plus the server-side round-trip count and storage time exposed by the Phase 0
headers (requires HASTE_PERF=true on the API).

Run:
    python spec/features/perf-layer-loading/tools/bench_api_http.py \
        --base-url http://localhost:7071/api \
        --project-id <guid> --repeats 30 [--code <function-key>]

Reads only the standard library so it can run anywhere.
"""
import argparse
import json
import statistics
import time
import urllib.request


def _pct(values, p):
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:7071/api")
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--repeats", type=int, default=30)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--code", default=None, help="Azure Functions key, if required")
    args = ap.parse_args()

    qs = f"?projectId={args.project_id}&includeModels=True"
    if args.code:
        qs += f"&code={args.code}"
    url = f"{args.base_url}/GetProjectDetails{qs}"

    latencies, storage_calls, storage_ms, payloads = [], [], [], []
    for i in range(args.warmup + args.repeats):
        t0 = time.perf_counter()
        with urllib.request.urlopen(url) as resp:
            body = resp.read()
            hdrs = resp.headers
        dt = (time.perf_counter() - t0) * 1000.0
        if i < args.warmup:
            continue
        latencies.append(dt)
        payloads.append(len(body))
        if hdrs.get("X-Haste-Storage-Calls"):
            storage_calls.append(int(hdrs["X-Haste-Storage-Calls"]))
        if hdrs.get("X-Haste-Storage-Ms"):
            storage_ms.append(float(hdrs["X-Haste-Storage-Ms"]))

    result = {
        "project_id": args.project_id,
        "repeats": args.repeats,
        "latency_p50_ms": round(statistics.median(latencies), 1),
        "latency_p95_ms": round(_pct(latencies, 95), 1),
        "latency_max_ms": round(max(latencies), 1),
        "payload_kb": round(statistics.median(payloads) / 1024, 1),
        "server_storage_calls": storage_calls[0] if storage_calls else None,
        "server_storage_ms_p50": (
            round(statistics.median(storage_ms), 1) if storage_ms else None
        ),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
