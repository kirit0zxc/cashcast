"""Приёмка CSV-обязательств на отдельном локальном демо: создаёт один синтетический счёт."""

import argparse
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx

from app.scripts.smoke_demo import DemoCheck


class ObligationDemo(DemoCheck):
    def run_obligation(self) -> None:
        import os

        me = self.request("POST", "/auth/login", json={
            "email": os.getenv("CC_DEMO_EMAIL", "demo@example.com"),
            "password": os.getenv("CC_DEMO_PASSWORD", "demo-password"),
        })
        self.client.headers["X-CSRF-Token"] = me["csrf_token"]
        company = me["companies"][0]["id"]
        account = self.request("GET", f"/companies/{company}/accounts")["items"][0]["id"]
        today = datetime.now(UTC).date()
        payload = {"account_id": account, "as_of": today.isoformat(), "horizon_days": 30, "seed": 42}
        base = self.wait(self.request("POST", f"/companies/{company}/forecasts", json=payload))
        external_id = "demo-" + uuid.uuid4().hex
        due = today + timedelta(days=5)
        content = (
            "id;counterparty_ref;direction;amount;currency;due_date;available_at;kind;provenance\n"
            f"{external_id};demo-{external_id};out;321.00;RUB;{due};{today};invoice;Synthetic demo\n"
        ).encode("utf-8-sig")
        preview = self.request("POST", f"/companies/{company}/obligation-imports", data={
            "account_id": account, "source_name": "synthetic-demo",
        }, files={"file": ("synthetic.csv", content, "text/csv")})
        assert preview["valid_count"] == 1 and preview["error_count"] == 0
        path = "/obligation-imports/" + preview["import_id"] + "/commit"
        committed = self.request("POST", path)
        assert committed["inserted"] == 1 and committed["skipped_existing"] == 0
        assert self.request("POST", path) == committed
        updated = self.wait(self.request("POST", f"/companies/{company}/forecasts", json=payload))
        assert updated["data_version"] != base["data_version"]
        for before, after in zip(base["points"], updated["points"], strict=True):
            assert before["point_date"] == after["point_date"]
            expected = -32100 if after["point_date"] >= due.isoformat() else 0
            assert after["balance_p50_minor"] - before["balance_p50_minor"] == expected
        assert self.request("GET", "/forecasts/" + base["id"])["points"] == base["points"]
        self.request("POST", "/auth/logout")
        print("CSV obligation: preview, atomic commit, repeat, real worker and -32100 minor forecast effect OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--write-demo-data", action="store_true")
    args = parser.parse_args()
    if not args.write_demo_data or urlparse(args.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Нужны --write-demo-data и локальный демонстрационный адрес")
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        ObligationDemo(client).run_obligation()


if __name__ == "__main__":
    main()
