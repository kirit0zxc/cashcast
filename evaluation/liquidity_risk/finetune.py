"""Дообучение локальной копии Chronos исключительно на сверенной истории 2025."""
import argparse
from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from evaluation.fallback_model.data import Dataset


class TrainingSegments:
    LIMIT = date(2025, 12, 31)

    @staticmethod
    def segments(company, transactions, balances, limit):
        daily = defaultdict(int)
        for txn in transactions:
            if txn.account_id == company and txn.booked_on <= limit:
                daily[txn.booked_on] += txn.amount_minor * (1 if txn.direction == "in" else -1)
        observed = sorted(d for d in balances if d <= limit)
        if not observed:
            return []
        start = previous = observed[0]
        values = [balances[start]]
        result = []
        for day in observed[1:]:
            interval = [previous + timedelta(days=i) for i in range(1, (day-previous).days+1)]
            additions = np.cumsum([daily[d] for d in interval], dtype=np.int64) + values[-1]
            if int(additions[-1]) == balances[day]:
                values.extend(additions.tolist())
            else:
                # Неподтверждённый интервал не превращается в нулевые наблюдения.
                result.append((start, previous, np.asarray(values, dtype=np.int64)))
                start, values = day, [balances[day]]
            previous = day
        result.append((start, previous, np.asarray(values, dtype=np.int64)))
        return result

    @classmethod
    def build(cls, dataset):
        inputs, manifest = [], []
        for company, transactions in sorted(dataset.transactions.items()):
            if Dataset.heldout(company):
                continue
            segments = cls.segments(company, transactions, dataset.balances[company], cls.LIMIT)
            eligible = [segment for segment in segments if len(segment[2]) >= 86]
            if not eligible:
                continue
            start, end, values = min(eligible, key=lambda s: (-len(s[2]), s[0]))
            # Фиксированный масштаб и первый известный уровень, без статистик будущего.
            normalized = ((values.astype(np.float64)-values[0])/1_000_000).astype(np.float32)
            inputs.append(normalized[None, :])
            manifest.append({"company": company, "start": str(start), "end": str(end),
                             "days": len(values), "sha256": hashlib.sha256(normalized.tobytes()).hexdigest()})
        if not inputs:
            raise ValueError("Нет пригодных обучающих рядов")
        return inputs, manifest


class FineTune:
    SEGMENTS = TrainingSegments
    @staticmethod
    def fingerprints(root):
        result = {}
        for path in sorted(root.iterdir()):
            if path.is_file() and path.suffix in (".json", ".safetensors", ".bin"):
                with path.open("rb") as stream:
                    result[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
        return result

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    @classmethod
    def train(cls, source, metadata, output):
        import torch
        from chronos import Chronos2Pipeline
        torch.set_num_threads(4)
        torch.manual_seed(20261025)
        output.mkdir(parents=True, exist_ok=True)
        if (output/"training-started.json").exists():
            raise RuntimeError("Каталог уже использован; проверить живой процесс/состояние, не перезапускать молча")
        info = json.loads(metadata.read_text(encoding="utf-8"))
        original = Path(info["snapshot"])
        before = cls.fingerprints(original)
        inputs, manifest = cls.SEGMENTS.build(Dataset(source))
        cls.write(output/"training-data.json", {"series": manifest, "limit": str(cls.SEGMENTS.LIMIT),
                    "dataset_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
        cls.write(output/"original-hashes.json", before)
        cls.write(output/"training-started.json", {"model": info, "series": len(inputs), "seed": 20261025,
                   "steps": 300, "context": 365, "horizon": 30, "batch_size": 8, "lr": 1e-6})
        pipeline = Chronos2Pipeline.from_pretrained(str(original), device_map="cpu", local_files_only=True)
        started = time.perf_counter()
        print(f"Training Chronos: {len(inputs)} companies, 300 steps, CPU4", flush=True)
        trained = pipeline.fit(inputs, prediction_length=30, context_length=365, min_past=56,
                    learning_rate=1e-6, num_steps=300, batch_size=8, output_dir=output,
                    finetune_mode="full", optim="adamw_torch", save_strategy="steps", save_steps=100,
                    save_total_limit=3, logging_steps=25, disable_tqdm=True, seed=20261025, data_seed=20261025)
        after = cls.fingerprints(original)
        if before != after:
            raise RuntimeError("Исходные веса изменились")
        prediction, _ = trained.predict_quantiles([inputs[0][:, -365:]], prediction_length=30,
                           quantile_levels=[.1,.5,.9], batch_size=1, context_length=365, cross_learning=False)
        finite = bool(np.isfinite(prediction[0].detach().numpy()).all())
        if not finite:
            raise RuntimeError("Неконечный прогноз после обучения")
        cls.write(output/"training-completed.json", {"seconds": time.perf_counter()-started,
                  "original_unchanged": True, "finite_prediction": finite,
                  "checkpoints": [p.name for p in output.glob("checkpoint-*")],
                  "final_weights": cls.fingerprints(output/"finetuned-ckpt")})
        print("Fine-tuning completed; original weights unchanged", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--model-info", type=Path, default=Path("journal/chronos-source.json"))
    parser.add_argument("--output", type=Path, default=Path("data/raw/chronos-finetune-v13"))
    args = parser.parse_args()
    FineTune.train(args.zip, args.model_info, args.output)
