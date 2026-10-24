"""Метрики, воспроизводимость снимка и реальная сессионная защита отчёта."""

import importlib.util
import json
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.modules.model_quality import service
from tests.test_accounts import account_context  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("export_quality", ROOT / "evaluation/export_quality.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
Builder = exporter.QualityReportBuilder


def test_packaged_report_matches_measured_sources_and_schema():
    report = service.ModelQualityService.read()
    assert report.model_dump(mode="json") == Builder.build()
    assert not report.production_activated
    assert not report.applies_to_current_forecast
    assert not report.probability_calibrated
    assert report.release["allowed"] is False
    assert report.selection_policy["selected"] is None
    assert report.calibration["positives"] == 8


def test_report_identical_across_windows_and_linux_line_endings(tmp_path):
    directory = tmp_path / "evaluation"
    directory.mkdir()
    for name in exporter.SOURCES:
        text = (ROOT / "evaluation" / name).read_text(encoding="utf-8")
        (directory / name).write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert Builder.build(tmp_path) == Builder.build(ROOT)


def test_hand_calculated_confusion_metrics_and_real_cohort():
    # Матрица с разными частотами проверяет формулы независимо от исходного отчёта.
    values = Builder.metrics({"tp": 2, "fp": 1, "fn": 3, "tn": 2})
    assert values["precision"]["value"] == pytest.approx(2 / 3)
    assert values["recall"]["value"] == pytest.approx(2 / 5)
    assert values["f1"]["value"] == 0.5
    assert values["f2"]["value"] == pytest.approx(10 / 23)
    assert values["mcc"]["value"] == pytest.approx(1 / 15)
    real = service.ModelQualityService.read().cohorts[-1]
    assert real.confusion_matrix == {"tp": 6, "fp": 14, "fn": 5, "tn": 3148}
    assert real.metrics["f1"].value == pytest.approx(12 / 31)
    assert real.uncertainty is not None


@pytest.mark.parametrize("row", [
    {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
    {"tp": 0, "fp": 0, "fn": 0, "tn": 10},
])
def test_undefined_metrics_remain_null(row):
    values = Builder.metrics(row)
    for key in ("precision", "recall", "f1", "mcc", "roc_auc", "average_precision"):
        assert values[key]["value"] is None
        assert values[key]["unavailable_reason"]
    json.dumps(values, allow_nan=False)


@pytest.mark.parametrize("content", [None, "{broken", "{}"])
def test_missing_or_corrupt_snapshot_fails_closed(tmp_path, monkeypatch, content):
    path = tmp_path / "report.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(service, "REPORT_PATH", path)
    with pytest.raises(AppError) as error:
        service.ModelQualityService.read()
    assert error.value.code == "quality_report_unavailable"
    assert error.value.status_code == 503


def test_report_requires_real_session(client):
    assert client.get("/api/v1/models/quality").status_code == 401


def test_report_after_login_without_company_data(client, account_context):  # noqa: F811
    response = client.get("/api/v1/models/quality")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.json() == service.ModelQualityService.read().model_dump(mode="json")
    assert all(identifier not in response.text for identifier in account_context)
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/models/quality").status_code == 401


@pytest.mark.usefixtures("account_context")
def test_missing_snapshot_api_has_documented_error(client, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "REPORT_PATH", tmp_path / "missing.json")
    response = client.get("/api/v1/models/quality")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "quality_report_unavailable"
    assert "503" in client.get("/openapi.json").json()["paths"]["/api/v1/models/quality"]["get"]["responses"]
