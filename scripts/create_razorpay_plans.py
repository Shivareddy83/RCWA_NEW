"""Create RCAA recurring plans in Razorpay test/live mode and print env values.

Run with RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET configured.
The script is intentionally explicit: it does not modify the RCAA database.
"""
from __future__ import annotations
import os
import httpx

BASE = "https://api.razorpay.com/v1/plans"
PLANS = {
    "STARTER": (999900, "RCAA Starter", "Up to 100,000 billable transactions/month"),
    "GROWTH": (2499900, "RCAA Growth", "Up to 500,000 billable transactions/month"),
    "BUSINESS": (4999900, "RCAA Business", "Up to 2,000,000 billable transactions/month"),
}

def main() -> None:
    key = os.environ.get("RAZORPAY_KEY_ID", "")
    secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not key or not secret:
        raise SystemExit("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are required")
    for code, (amount, name, description) in PLANS.items():
        response = httpx.post(BASE, auth=(key, secret), json={
            "period": "monthly",
            "interval": 1,
            "item": {"name": name, "amount": amount, "currency": "INR", "description": description},
            "notes": {"rcaa_plan_code": code},
        }, timeout=20.0)
        if response.status_code >= 400:
            raise SystemExit(f"{code}: Razorpay rejected the plan: {response.text}")
        plan_id = response.json().get("id")
        print(f"RAZORPAY_PLAN_{code}={plan_id}")

if __name__ == "__main__":
    main()
