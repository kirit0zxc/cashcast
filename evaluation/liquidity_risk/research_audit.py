"""Диагностика замороженных прогнозов без выбора моделей и изменения выборки."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from evaluation.fallback_model.metrics import Score
from .cumulative_flows import CumulativeEvaluation, CumulativePolicy
from .horizon_ensemble import HorizonWeights


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def cash_metrics(rows, model, horizon):
    """Каждое окно имеет одинаковую длину; деньги переводятся из копеек в рубли."""
    if not rows:
        raise ValueError('Пустая выборка')
    errors = np.stack([(np.asarray(r['models'][model][:horizon], dtype=np.float64)
                       - r['truth'][:horizon]) / 100 for r in rows])
    if errors.shape != (len(rows), horizon, 3) or not np.isfinite(errors).all():
        raise ValueError('Некорректные прогнозы/цели')
    result = {'windows': len(rows), 'companies': len({r['company'] for r in rows})}
    for channel, name in enumerate(('inflow', 'outflow', 'balance')):
        # В75/25 Chronos прогнозировал остаток; его нативных потоков в benchmark нет.
        if model == 'benchmark75_25' and channel < 2:
            continue
        e = errors[:, :, channel]
        result[name + '_mae_rub'] = float(np.abs(e).mean())
        result[name + '_rmse_rub'] = float(np.sqrt(np.square(e).mean()))
        aggregate = e.sum(axis=1) if channel < 2 else e[:, -1]
        label = name + ('_total' if channel < 2 else '_final')
        result[label + '_mae_rub'] = float(np.abs(aggregate).mean())
        result[label + '_rmse_rub'] = float(np.sqrt(np.square(aggregate).mean()))
    return result


def deltas(candidate, baseline):
    return {key: {'difference_rub': candidate[key] - value,
                  'change_pct': (candidate[key] / value - 1) * 100 if value else None}
            for key, value in baseline.items() if key.endswith('_rub')}


def cluster_intervals(rows, candidate, baseline, horizon, resamples=500):
    """Перевыборка целых компаний со всеми их окнами, не отдельных дней."""
    grouped = defaultdict(list)
    for row in rows:
        truth = row['truth'][:horizon]
        first = np.abs((row['models'][candidate][:horizon] - truth) / 100).mean(axis=0)
        second = np.abs((row['models'][baseline][:horizon] - truth) / 100).mean(axis=0)
        grouped[row['company']].append(first - second)
    companies = sorted(grouped)
    sums = np.stack([np.sum(grouped[c], axis=0) for c in companies])
    counts = np.array([len(grouped[c]) for c in companies])
    rng = np.random.default_rng(20261025)
    samples = rng.integers(0, len(companies), (resamples, len(companies)))
    values = sums[samples].sum(axis=1) / counts[samples].sum(axis=1)[:, None]
    point = sums.sum(axis=0) / counts.sum()
    return {'unit': 'company_all_windows', 'resamples': resamples,
            'independent_control': False,
            'mae_difference_rub': {name: {'point': float(point[i]),
                'ci95': np.quantile(values[:, i], [.025, .975]).tolist()}
                for i, name in enumerate(('inflow', 'outflow', 'balance'))
                if baseline != 'benchmark75_25' or name == 'balance'}}


def reliability(labels, scores):
    y, p = np.asarray(labels, dtype=float), np.asarray(scores, dtype=float)
    if y.shape != p.shape or not len(y) or not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError('Некорректные значения риска')
    edges = np.array([0, .01, .025, .05, .1, .25, .5, 1.])
    bins = np.minimum(np.searchsorted(edges, p, side='right') - 1, len(edges) - 2)
    return {'n': len(y), 'brier': float(np.square(p - y).mean()),
            'calibrated': False, 'interpretation': 'raw_score_diagnostic_only',
            'bins': [{'lower': float(edges[i]), 'upper': float(edges[i+1]),
                      'n': int((bins == i).sum()),
                      'mean_score': float(p[bins == i].mean()) if np.any(bins == i) else None,
                      'observed_rate': float(y[bins == i].mean()) if np.any(bins == i) else None}
                     for i in range(len(edges) - 1)]}


def risk_summary(rows, selection):
    labels = [r['label'] for r in rows]
    mode, threshold = selection['model'], selection['threshold']
    flags = {'current': [r['current'] >= .5 for r in rows],
             'candidate18': [r['risk18'] for r in rows],
             'candidate21': [r['risk18'] or (mode != 'keep' and r['scores'][mode] >= threshold) for r in rows]}
    result = {'n': len(rows), 'companies': len({r['company'] for r in rows}),
              'positive_companies': len({r['company'] for r in rows if r['label']}),
              'policies': {name: Score.classification(labels, value) for name, value in flags.items()},
              'probability_candidate18': None, 'probability_candidate21': None,
              'score_diagnostics': {'current': reliability(labels, [r['current'] for r in rows])}}
    if mode != 'keep':
        result['score_diagnostics'][mode] = reliability(labels, [r['scores'][mode] for r in rows])
    return result


def run(root, output):
    experiment = root / 'data/raw/cumulative-flows-v24/evaluation'
    cache = root / 'data/raw/chronos-specialists-v8'
    risk_root = root / 'data/raw/rolling-peer-risk-v21'
    choice_path = experiment / 'selection-frozen.json'
    choice = json.loads(choice_path.read_text('utf-8'))['selected']
    risk_choice_path = risk_root / 'selection-frozen.json'
    risk_choice = json.loads(risk_choice_path.read_text('utf-8'))['selected']
    sources = {str(p.relative_to(root)): digest(p) for p in (choice_path, risk_choice_path)}
    models = ('current', 'benchmark75_25', 'candidate18_balance', 'selected24')
    summaries, details, audits, all_rows, all_risk = {}, {}, {}, [], []
    for phase in CumulativeEvaluation.PHASES:
        path, baseline_path = experiment / f'inferred-{phase}.pickle', cache / f'inferred-{phase}.pickle'
        rows = CumulativeEvaluation.read_pickle(path)
        original = CumulativeEvaluation.read_pickle(baseline_path)['rows']
        if [(r['company'], r['cutoff']) for r in rows] != [(r['company'], r['cutoff']) for r in original]:
            raise ValueError('Изменился состав выборки')
        for row, old in zip(rows, original, strict=True):
            for key in ('truth', 'opening', 'probability', 'fallback'):
                np.testing.assert_array_equal(row[key], old[key])
            np.testing.assert_array_equal(row['models']['current'], old['models']['current'])
            np.testing.assert_array_equal(row['models']['blend75'], old['models']['blend75'])
            row['models']['benchmark75_25'] = row['models']['blend75'].copy()
            values = np.stack([row['models'][n][:, 2] for n in ('current', 'direct', 'balance365')], axis=1)[None]
            row['models']['candidate18_balance'] = row['models']['current'].copy()
            row['models']['candidate18_balance'][:, 2] = np.rint(HorizonWeights.predict(values, 0., (.5, 1., .75))[0]).astype(np.int64)
            row['models']['selected24'] = CumulativePolicy.assemble(row, choice['incoming'], choice['outgoing'])
            for name in CumulativePolicy.NAMES[1:]:
                predicted = row['models'][name]
                if row['fallback']:
                    np.testing.assert_array_equal(predicted, old['models']['current'])
                else:
                    np.testing.assert_array_equal(predicted[:, 2], row['opening'] + np.cumsum(predicted[:, 0] - predicted[:, 1]))
                    if not np.issubdtype(predicted.dtype, np.integer) or np.any(predicted[:, :2] < 0):
                        raise ValueError('Нарушены денежные инварианты')
        risk_path = risk_root / f'{phase}-rows.json'
        risk_rows = json.loads(risk_path.read_text('utf-8'))
        lookup = {(r['company'], r['cutoff']): r for r in rows if r['opening'] >= 0 and r['probability'] is not None}
        if len(risk_rows) != len(lookup) or set(lookup) != {(r['company'], r['cutoff']) for r in risk_rows}:
            raise ValueError('Разошлась фиксированная выборка риска')
        for risk in risk_rows:
            actual = lookup[(risk['company'], risk['cutoff'])]
            if risk['label'] != bool(np.any(actual['truth'][:, 2] < 0)) or risk['current'] != actual['probability']:
                raise ValueError('Разошлись цели или текущий риск')
        summaries[phase] = {'cash': {model: {str(h): cash_metrics(rows, model, h) for h in (7,14,30)} for model in models},
                            'risk': risk_summary(risk_rows, risk_choice)}
        details[phase] = {}
        for group_key in ('company', 'cutoff'):
            groups = defaultdict(list)
            for row in rows:
                groups[row[group_key]].append(row)
            details[phase][group_key] = {key: {model: {str(h): cash_metrics(group, model, h) for h in (7,14,30)}
                                                    for model in models} for key, group in sorted(groups.items())}
        summaries[phase]['selected_deltas'] = {base: {str(h): deltas(cash_metrics(rows, 'selected24', h), cash_metrics(rows, base, h))
                                                        for h in (7,14,30)} for base in models[:-1]}
        summaries[phase]['cluster_intervals'] = {base: {str(h): cluster_intervals(rows, 'selected24', base, h)
                                                        for h in (7,14,30)} for base in models[:-1]}
        audits[phase] = {'windows': len(rows), 'fallback_windows': sum(r['fallback'] for r in rows),
                         'baseline_and_targets_unchanged': True, 'saved_fallback_matches_evaluated': True,
                         'supported_cumulative_money_identities': True}
        for source in (path, baseline_path, risk_path):
            sources[str(source.relative_to(root))] = digest(source)
        all_rows.extend(rows); all_risk.extend(risk_rows)
    report = {'independent_control': False, 'production_activated': False, 'selection_changed': False,
              'selected24': {k: choice[k] for k in ('incoming', 'outgoing', 'objective', 'eligible')},
              'risk21_selection': risk_choice, 'risk_population': 'opening>=0 and current probability available',
              'benchmark75_25_scope': 'balance_only; no native Chronos flow benchmark',
              'point_negative_is_not_risk_policy': True, 'phases': summaries, 'audit': audits,
              'total_risk': risk_summary(all_risk, risk_choice), 'sources_sha256': sources}
    write_json(output / 'report.json', report)
    write_json(output / 'by-company-and-period.json', details)
    print(json.dumps({'selected24': report['selected24'], 'risk': report['total_risk']['policies'], 'windows': len(all_rows)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, default=Path('data/raw/b-research-audit24'))
    args = parser.parse_args()
    run(args.root.resolve(), args.output.resolve())
