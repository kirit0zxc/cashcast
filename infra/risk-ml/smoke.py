"""Проверка настоящих весов и HTTP на искусственных данных; это не оценка качества."""

import json
from datetime import date, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class ModelSmoke:
    @staticmethod
    def check():
        for income, expense, opening, expected in [(10000, 5000, 1000000, False), (1000, 10000, 1000, True)]:
            start = date(2026, 1, 1)
            history = [{"date": str(start + timedelta(days=i)), "incoming": income, "outgoing": expense,
                        "balance": opening - (83 - i) * (income - expense)} for i in range(84)]
            payload = {"as_of": history[-1]["date"], "horizon_days": 30, "history": history}
            request = Request("http://127.0.0.1:8765/predict", data=json.dumps(payload).encode(),
                              headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=15) as response:
                result = json.load(response)
            assert result["model_version"] == "cashcast-risk-sr04-frozen-20261025"
            assert result["alert"] is expected and result["probability"] is None
        try:
            urlopen(Request("http://127.0.0.1:8765/predict", data=b"{}"), timeout=5)
        except HTTPError as error:
            assert error.code == 422
        else:
            raise AssertionError("Невалидный вход должен отклоняться")
        print("SR04 HTTP: synthetic yes/no and invalid input passed")


if __name__ == "__main__":
    ModelSmoke.check()
