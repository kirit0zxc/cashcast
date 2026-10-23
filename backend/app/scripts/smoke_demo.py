"""Ручная приёмка отдельного локального демо: создаёт данные, не очищает таблицы."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

DATASET_SHA256 = "e753802b7f7a2eecb7b5a558f9923b529e711c40fe431774750904b62ec79987"


class DemoCheck:
    """Проверяет реальную цепочку HTTP → PostgreSQL → worker без доступа к БД."""

    def __init__(self, client: httpx.Client):
        self.client = client

    def request(self, method: str, path: str, **kwargs):
        response = self.client.request(method, "/api/v1" + path, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    def wait(self, accepted: dict) -> dict:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            job = self.request("GET", "/jobs/" + accepted["job_id"])
            if job["status"] == "failed":
                raise RuntimeError("worker failed: " + str(job["error_code"]))
            if job["status"] == "succeeded":
                result = self.request("GET", "/forecasts/" + accepted["forecast_run_id"])
                assert result["status"] == "succeeded" and len(result["points"]) == 30
                return result
            time.sleep(0.5)
        raise TimeoutError("worker did not finish within 90 seconds")

    def transaction_ids(self, company: str, account: str) -> set[str]:
        ids: set[str] = set()
        cursor = None
        while True:
            params = {"account_id": account, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            page = self.request("GET", f"/companies/{company}/transactions", params=params)
            for item in page["items"]:
                assert item["id"] not in ids, "Duplicate cursor item"
                ids.add(item["id"])
            cursor = page["next_cursor"]
            if not cursor:
                return ids

    def run(self, archive: Path) -> None:
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == DATASET_SHA256
        assert self.request("GET", "/health")["status"] == "ok"
        me = self.request("POST", "/auth/login", json={
            "email": os.getenv("CC_DEMO_EMAIL", "demo@example.com"),
            "password": os.getenv("CC_DEMO_PASSWORD", "demo-password"),
        })
        self.client.headers["X-CSRF-Token"] = me["csrf_token"]
        company = me["companies"][0]["id"]
        accounts = self.request("GET", f"/companies/{company}/accounts")["items"]
        assert accounts and accounts[0]["currency"] == "RUB"
        account = accounts[0]["id"]
        mapping = next(p["mapping"] for p in self.request("GET", "/import-presets")["items"]
                       if p["id"] == "participants-v1")
        with zipfile.ZipFile(archive) as source:
            content = source.read("statements/C001.csv")
        upload = {"data": {"account_id": account, "mapping": json.dumps(mapping)},
                  "files": {"file": ("C001.csv", content, "text/csv")}}
        preview = self.request("POST", f"/companies/{company}/imports", **upload)
        assert preview["error_count"] == 0 and preview["total_rows"] > 100
        committed = self.request("POST", "/imports/" + preview["import_id"] + "/commit")
        before = self.transaction_ids(company, account)
        repeated = self.request("POST", f"/companies/{company}/imports", **upload)
        assert repeated["reused"] and repeated["import_id"] == preview["import_id"]
        duplicate = self.request("POST", "/imports/" + preview["import_id"] + "/commit")
        # Повтор возвращает сохранённую статистику первого commit, а не новый счётчик вставки.
        assert duplicate == committed and self.transaction_ids(company, account) == before
        print("Import / repeat without duplicates:", committed["total_rows"], "rows")

        # Исторический расчёт до создания нового плана не знает сегодняшнего обязательства.
        historic = self.wait(self.request("POST", f"/companies/{company}/forecasts", json={
            "account_id": account, "as_of": "2026-09-30", "horizon_days": 30,
        }))
        explanation = self.request("GET", "/forecasts/" + historic["id"] + "/explanations")
        assert explanation["available"] and explanation["items"]
        today = datetime.now(UTC).date()
        due = today + timedelta(days=5)
        event = self.request("POST", f"/companies/{company}/planned-events", json={
            "account_id": account, "direction": "out", "amount_minor": 123456,
            "due_date": due.isoformat(), "kind": "manual",
            "counterparty_name": "Демонстрационная проверка",
        })
        plan_fact = self.request("POST", f"/companies/{company}/plan-fact", params={
            "account_id": account, "as_of": today.isoformat(),
        })
        assert any(item["event"]["id"] == event["id"] for item in plan_fact["items"])
        base = self.wait(self.request("POST", f"/companies/{company}/forecasts", json={
            "account_id": account, "as_of": today.isoformat(), "horizon_days": 30,
        }))
        changes = [
            {"kind": "add_expense", "amount_minor": 100000, "on_date": due.isoformat()},
            {"kind": "delay_event", "target_id": event["id"], "shift_days": 2},
            {"kind": "reduce_irregular_inflow", "factor": 0},
            {"kind": "increase_recurring", "factor": 1.1},
        ]
        for change in changes:
            # На свежей дате регулярности C001 уже не подтверждены. Проверяем их на
            # историческом срезе исходной выписки, где детектор действительно нашёл группы.
            scenario_base = historic if change["kind"] == "increase_recurring" else base
            scenario = self.wait(self.request("POST", "/forecasts/" + scenario_base["id"] + "/scenarios",
                                              json={"changes": [change]}))
            comparison = self.request("GET", "/forecasts/" + scenario["id"] + "/comparison")
            assert comparison["base_forecast_id"] == scenario_base["id"] and len(comparison["points"]) == 30
            deltas = [p["delta_balance_minor"] for p in comparison["points"]]
            if change["kind"] == "add_expense":
                assert deltas[-1] == -100000
            elif change["kind"] == "delay_event":
                assert deltas[4] == 123456 and deltas[6] == 0
            else:
                assert any(deltas), "Scenario did not change this real dataset"
            print("Scenario / comparison:", change["kind"], "OK")
        assert self.request("GET", "/forecasts/" + base["id"])["points"] == base["points"]
        self.request("POST", "/auth/logout")
        assert self.client.get("/api/v1/auth/me").status_code == 401
        print("PASS: real API, worker, explanations, plan-fact, four scenarios, immutable base, logout")
        print("Forecast IDs for persistence check:", historic["id"], base["id"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="URL отдельного локального демо")
    parser.add_argument("--zip", required=True, type=Path, help="ZIP организаторов вне Git")
    parser.add_argument("--write-demo-data", action="store_true",
                        help="Обязательное подтверждение записи импорта и тестового плана")
    args = parser.parse_args()
    if not args.write_demo_data:
        parser.error("Проверка добавляет данные: требуется --write-demo-data")
    # Приёмка не предназначена для production: только отдельный локальный Compose.
    if httpx.URL(args.base_url).host not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Разрешён только локальный демостенд")
    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        DemoCheck(client).run(args.zip)


if __name__ == "__main__":
    main()
