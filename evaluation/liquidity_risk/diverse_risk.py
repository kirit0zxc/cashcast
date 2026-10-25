"""Причинный CatBoost с исключением компаний и фиксированная смесь с25."""
import argparse
from datetime import date, timedelta
import hashlib
from importlib.metadata import version
import json
from pathlib import Path

import numpy as np

from evaluation.fallback_model.data import Dataset
from evaluation.fallback_model.metrics import Score
from .company_crossfit import CrossfitExperiment, CrossfitPolicy
from .research_audit import digest, reliability, write_json


class DiversePolicy:
    MODES = ('cat', 'mean50')

    @staticmethod
    def score(row, mode):
        if mode == 'cat':
            return row['cat_score']
        if mode == 'mean50':
            return .5 * (row['cat_score'] + row['score25'])
        raise ValueError('Неизвестный режим')

    @classmethod
    def flags(cls, rows, choice):
        return [r['risk25'] if choice['mode'] == 'keep25' else
                bool(r['risk18'] or cls.score(r, choice['mode']) >= choice['threshold']) for r in rows]

    @classmethod
    def choose(cls, rows):
        if not rows or any(r['phase'] not in CrossfitPolicy.EARLY or r['cutoff'] > '2026-06-30'
                           or Dataset.heldout(r['company']) for r in rows):
            raise ValueError('Выбор только на ранних development-компаниях')
        choices = [{'mode': 'keep25', 'threshold': None}] + [
            {'mode': mode, 'threshold': t} for mode in cls.MODES for t in CrossfitPolicy.THRESHOLDS]
        enough = sum(r['label'] for r in rows) >= 5
        trials = []
        for choice in choices:
            eligible = choice['mode'] == 'keep25' or enough
            for cutoff in sorted({r['cutoff'] for r in rows}):
                group = [r for r in rows if r['cutoff'] == cutoff]
                labels = [r['label'] for r in group]
                new = Score.classification(labels, cls.flags(group, choice))
                old = Score.classification(labels, [r['risk25'] for r in group])
                current = Score.classification(labels, [r['current'] >= .5 for r in group])
                if choice['mode'] != 'keep25':
                    eligible &= new['tp'] >= old['tp'] and new['fp'] <= current['fp']
            trials.append({**choice, 'eligible': bool(eligible), 'metrics': Score.classification(
                [r['label'] for r in rows], cls.flags(rows, choice))})
        order = {'keep25': 0, 'cat': 1, 'mean50': 2}
        selected = min((t for t in trials if t['eligible']), key=lambda t: (
            -t['metrics']['tp'], t['metrics']['fp'], order[t['mode']], t['threshold'] or 0))
        return {'selected': selected, 'trials': trials, 'selection': 'development January-June only'}


class DiverseExperiment(CrossfitExperiment):
    PARAMS = dict(iterations=600, depth=4, learning_rate=.03, l2_leaf_reg=8,
                  loss_function='Logloss', boosting_type='Ordered', random_seed=20261025,
                  thread_count=4, allow_writing_files=False, verbose=False)

    def __init__(self, source, reference, output):
        expected = json.loads(Path('research_handoff/results/local-artifact-index.json').read_text('utf-8'))
        prediction_path = reference/'predictions.json'
        if digest(prediction_path) != expected['data/raw/company-crossfit-v25/predictions.json']['sha256']:
            raise ValueError('Изменились исходные прогнозы25')
        started25 = json.loads((reference/'started.json').read_text('utf-8'))
        if digest(source/'prepared.pickle') != started25['prepared_sha256']:
            raise ValueError('Изменились исходные признаки/цели21')
        super().__init__(source, output)
        previous = {(r['company'], r['cutoff']): r for r in json.loads(prediction_path.read_text('utf-8'))}
        if len(previous) != len(self.control):
            raise ValueError('Разошлись окна25')
        for row in self.control:
            old = previous[(row['company'], row['cutoff'])]
            if any(row[k] != old[k] for k in ('label', 'current', 'risk18', 'risk21', 'phase')):
                raise ValueError('Изменился baseline25')
            row['score25'] = old['crossfit_score']
            row['risk25'] = bool(row['risk18'] or row['score25'] >= .025)
        started = json.loads((output/'started.json').read_text('utf-8'))
        started.update(code_sha256=digest(Path(__file__)),
                       protocol_sha256=digest(Path('journal/29_diverse_risk.md')),
                       reference25_predictions_sha256=digest(prediction_path),
                       base_crossfit_code_sha256=digest(Path('evaluation/liquidity_risk/company_crossfit.py')))
        started['packages']['catboost'] = version('catboost')
        write_json(output/'started.json', started)

    def train_cutoff(self, cutoff):
        from catboost import CatBoostClassifier
        if cutoff in self.models:
            return
        self.models[cutoff] = {}
        for excluded in range(5):
            rows = [r for r in self.train if CrossfitPolicy.eligible(r, date.fromisoformat(cutoff), excluded)]
            x = np.asarray([r['features'] for r in rows])
            y = np.asarray([r['label'] for r in rows], dtype=int)
            if len(set(y)) != 2:
                raise ValueError('Недостаточно классов после исключения группы')
            weights = CrossfitPolicy.weights(rows)
            model = CatBoostClassifier(**self.PARAMS)
            model.fit(x, y, sample_weight=weights)
            path = self.output/f'{cutoff}-exclude{excluded}.cbm'
            model.save_model(str(path))
            loaded = CatBoostClassifier()
            loaded.load_model(str(path))
            np.testing.assert_allclose(model.predict_proba(x[:20]), loaded.predict_proba(x[:20]), atol=1e-12, rtol=0)
            self.models[cutoff][excluded] = loaded
            self.audits[f'{cutoff}/{excluded}'] = {
                'windows': len(rows), 'companies': len({r['company'] for r in rows}),
                'positives': int(y.sum()), 'positive_companies': len({r['company'] for r in rows if r['label']}),
                'heldout_excluded': True, 'excluded_group': excluded,
                'max_confirmation': str(max(date.fromisoformat(r['as_of'])+timedelta(days=37) for r in rows)),
                'identities_sha256': hashlib.sha256(repr([(r['company'], r['as_of']) for r in rows]).encode()).hexdigest(),
                'sample_weights_sha256': hashlib.sha256(weights.tobytes()).hexdigest(), 'weights_sha256': digest(path)}
            write_json(self.output/'training-audit.json', self.audits)
            print(f'CatBoost29 trained {cutoff} excluded={excluded}', flush=True)

    def predict(self, rows):
        for cutoff in sorted({r['cutoff'] for r in rows}):
            self.train_cutoff(cutoff)
            group = [r for r in rows if r['cutoff'] == cutoff]
            x = np.asarray([r['features'] for r in group])
            scores = np.stack([self.models[cutoff][i].predict_proba(x, thread_count=4)[:, 1] for i in range(5)], axis=1)
            if not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 1)):
                raise ValueError('Некорректный score29')
            for row, values in zip(group, scores, strict=True):
                heldout = Dataset.heldout(row['company'])
                row['cat_score'] = float(values.mean() if heldout else values[CrossfitPolicy.group(row['company'])])
                row['prediction_mode'] = 'heldout_mean5' if heldout else 'excluded_company_group'

    @staticmethod
    def metrics29(rows, choice):
        labels = [r['label'] for r in rows]
        flags = {name: [r[key] for r in rows] for name, key in (
            ('candidate18', 'risk18'), ('candidate21', 'risk21'), ('candidate25', 'risk25'))}
        flags['current'] = [r['current'] >= .5 for r in rows]
        flags['selected29'] = DiversePolicy.flags(rows, choice)
        return {name: Score.classification(labels, values) for name, values in flags.items()}

    @staticmethod
    def bootstrap(rows, choice, baseline):
        # Используется прежняя парная перевыборка целых компаний, без мутации baseline.
        flags = DiversePolicy.flags(rows, choice)
        transformed = [{**r, 'risk21': r[baseline], 'risk18': False, 'crossfit_score': float(flag)}
                       for r, flag in zip(rows, flags, strict=True)]
        result = CrossfitExperiment.cluster_bootstrap(transformed, .5)
        result['comparison'] = 'selected29_minus_'+baseline
        return result

    def run(self):
        early = [r for r in self.control if r['phase'] in CrossfitPolicy.EARLY]
        self.predict(early)
        selection = DiversePolicy.choose(early)
        write_json(self.output/'selection-frozen.json', selection)
        print('Frozen29: '+str(selection['selected']), flush=True)
        self.predict([r for r in self.control if r['phase'] not in CrossfitPolicy.EARLY])
        choice = selection['selected']
        report = {'selection': selection, 'independent_control': False, 'production_activated': False,
                  'probability_calibrated': False, 'probability_any_negative': None,
                  'phases': {}, 'total': self.metrics29(self.control, choice)}
        for phase in sorted({r['phase'] for r in self.control}):
            rows = [r for r in self.control if r['phase'] == phase]
            report['phases'][phase] = {'metrics': self.metrics29(rows, choice),
                'companies': len({r['company'] for r in rows}),
                'positive_companies': len({r['company'] for r in rows if r['label']}),
                'score_diagnostics': {mode: reliability([r['label'] for r in rows],
                    [DiversePolicy.score(r, mode) for r in rows]) for mode in DiversePolicy.MODES},
                'diagnostic_fixed_policies': {mode: {str(t): Score.classification([r['label'] for r in rows],
                    DiversePolicy.flags(rows, {'mode': mode, 'threshold': t})) for t in CrossfitPolicy.THRESHOLDS}
                    for mode in DiversePolicy.MODES}}
        old, new = report['total']['candidate25'], report['total']['selected29']
        report['preliminary_improvement'] = bool(choice['mode'] != 'keep25' and
            ((new['tp'] >= old['tp'] and new['fp'] < old['fp']) or (new['tp'] > old['tp'] and new['fp'] <= old['fp']))
            and all(p['metrics']['selected29']['tp'] >= p['metrics']['candidate25']['tp'] for p in report['phases'].values()))
        report['paired_company_bootstrap'] = {base: self.bootstrap(self.control, choice, base) for base in ('risk25', 'risk21')}
        for mode in ('cutoff', 'company'):
            report['by_'+mode] = {key: self.metrics29([r for r in self.control if r[mode] == key], choice)
                                 for key in sorted({r[mode] for r in self.control})}
        write_json(self.output/'predictions.json', [{k: v for k, v in r.items() if k != 'features'} for r in self.control])
        write_json(self.output/'results.json', report)
        write_json(self.output/'completed.json', {'models': sum(len(m) for m in self.models.values()),
            'selection_sha256': digest(self.output/'selection-frozen.json'), 'results_sha256': digest(self.output/'results.json')})
        print('Experiment29 complete: '+str(report['total']['selected29']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path('data/raw/rolling-peer-risk-v21'))
    parser.add_argument('--reference', type=Path, default=Path('data/raw/company-crossfit-v25'))
    parser.add_argument('--output', type=Path, default=Path('data/raw/diverse-risk-v29'))
    args = parser.parse_args()
    DiverseExperiment(args.source, args.reference, args.output).run()
