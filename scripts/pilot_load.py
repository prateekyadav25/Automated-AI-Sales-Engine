"""Measure a small, honest pilot load. Prints timings. Invents no capacity claims."""

from __future__ import annotations

import argparse
import time
from uuid import uuid4

import httpx


def timed(name: str, fn) -> None:
    start = time.perf_counter()
    fn()
    elapsed = (time.perf_counter() - start) * 1000
    print(f"{name}\t{elapsed:.1f}ms")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="admin@agrayian.demo")
    parser.add_argument("--password", default="Agrarian!Demo1")
    parser.add_argument("--n", type=int, default=10)
    args = parser.parse_args()
    client = httpx.Client(base_url=args.base, timeout=30.0)
    token = client.post("/api/v1/auth/login", json={"email": args.email, "password": args.password}).json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    def home() -> None:
        client.get("/api/v1/command-center/overview", headers=headers).raise_for_status()

    def approvals() -> None:
        client.get("/api/v1/ai/approvals", headers=headers).raise_for_status()

    def readiness() -> None:
        client.get("/api/v1/pilot/readiness", headers=headers).raise_for_status()

    def cycle() -> None:
        client.post("/api/v1/autonomy/runs", headers=headers, json={}).raise_for_status()

    timed("home_overview", home)
    timed("approvals", approvals)
    timed("pilot_readiness", readiness)
    timed("autopilot_reconcile", cycle)
    for i in range(args.n):
        timed(
            f"lead_create_{i}",
            lambda: client.post(
                " /api/v1/leads".strip(),
                headers=headers,
                json={
                    "first_name": "Load",
                    "last_name": f"{i}",
                    "email": f"load.{i}.{uuid4().hex[:6]}@example.com",
                    "company_name": "Load Co",
                    "consent_email": False,
                },
            ).raise_for_status(),
        )
    print("measured_only=true")


if __name__ == "__main__":
    main()
