"""Причинная оценка риска с исключением целых групп компаний из обучения."""
import argparse
from collections import Counter
from datetime import date, timedelta
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import pickle
import sys

import numpy as np

from evaluation.fallback_model.data import Dataset
from evaluation.fallback_model.metrics import Score
from .research_audit import digest, reliability, write_json


class CrossfitPolicy:
    THRESHOLDS = (.025, .05, .1, .25, .5)
    EARLY = ('validation', 'bridge')

    @staticmethod
    def group(company):
        return hashlib.sha256(company.encode()).digest()[1] % 5

    @classmethod
    def eligible(cls, row, cutoff, excluded):
        return (not Dataset.heldout(row['company']) and cls.group(row['company']) != excluded
                and row['opening'] >= 0 and date.fromisoformat(row['as_of']) + timedelta(days=37) <= cutoff)

    @staticmethod
    def weights(rows):
        counts = Counter(r['company'] for r in rows)
        values = np.array([1 / counts[r['company']] for r in rows])
        return values / values.mean()

    @staticmethod
    def flags(rows, threshold):
        return [r['risk21'] if threshold is None else r['risk18'] or r['crossfit_score'] >= threshold for r in rows]

    @classmethod
    def choose(cls, rows):
        if not rows or any(r['phase'] not in cls.EARLY or r['cutoff'] > '2026-06-30' or Dataset.heldout(r['company']) for r in rows):
            raise ValueError('Выбор разрешён только на development январь–июнь')
        trials = []
        enough = sum(r['label'] for r in rows) >= 5
        for threshold in (None, *cls.THRESHOLDS):
            metrics = Score.classification([r['label'] for r in rows], cls.flags(rows, threshold))
            eligible = threshold is None or enough
            for cutoff in sorted({r['cutoff'] for r in rows}):
                group = [r for r in rows if r['cutoff'] == cutoff]
                labels = [r['label'] for r in group]
                new = Score.classification(labels, cls.flags(group, threshold))
                base = Score.classification(labels, [r['risk21'] for r in group])
                current = Score.classification(labels, [r['current'] >= .5 for r in group])
                if threshold is not None:
                    eligible &= new['tp'] >= base['tp'] and new['fp'] <= current['fp']
            trials.append({'threshold': threshold, 'policy': 'keep21' if threshold is None else 'risk18_or_crossfit',
                           'eligible': bool(eligible), 'metrics': metrics})
        chosen = min((t for t in trials if t['eligible']), key=lambda t: (-t['metrics']['tp'], t['metrics']['fp'],
                     t['threshold'] is not None, t['threshold'] or 0))
        return {'selected': chosen, 'trials': trials, 'selection': 'development January-June only'}


class CrossfitExperiment:
    PARAMS = dict(n_estimators=300, learning_rate=.03, num_leaves=15, min_child_samples=50,
                  reg_lambda=5., random_state=42, deterministic=True, force_row_wise=True,
                  verbose=-1, subsample=.8, subsample_freq=1, colsample_bytree=.8, n_jobs=4)

    def __init__(self, source, output):
        self.source, self.output = source, output
        if output.exists():
            raise FileExistsError('Каталог опыта уже существует: сначала проверить живой процесс и артефакты')
        output.mkdir(parents=True)
        with (source / 'prepared.pickle').open('rb') as stream:
            prepared = pickle.load(stream)
        self.train, self.control = prepared['train'], prepared['control']
        choice = json.loads((source / 'selection-frozen.json').read_text('utf-8'))['selected']
        previous = {}
        for phase in ('validation','bridge','late_development','other_early','late_other'):
            for row in json.loads((source / f'{phase}-rows.json').read_text('utf-8')):
                previous[(row['company'],row['cutoff'])] = row
        if len(previous) != len(self.control):
            raise ValueError('Разошлись ключи исходного опыта21')
        for row in self.control:
            old = previous[(row['company'],row['cutoff'])]
            if any(row[k] != old[k] for k in ('label','current','risk18','phase')):
                raise ValueError('Разошлись исходные цели или baseline')
            row['risk21'] = old['risk18'] or (choice['model'] != 'keep' and old['scores'][choice['model']] >= choice['threshold'])
        self.models, self.audits = {}, {}
        write_json(output / 'started.json', {'params': self.PARAMS, 'python': sys.version,
            'packages': {name: version(name) for name in ('numpy','lightgbm','scikit-learn')},
            'prepared_sha256': digest(source/'prepared.pickle'), 'policy21_sha256': digest(source/'selection-frozen.json'),
            'code_sha256': digest(Path(__file__)), 'independent_control': False,
            'protocol_sha256': digest(Path('journal/25_company_crossfit.md'))})

    def train_cutoff(self, cutoff):
        import lightgbm as lgb
        if cutoff in self.models:
            return
        self.models[cutoff] = {}
        for excluded in range(5):
            rows = [r for r in self.train if CrossfitPolicy.eligible(r, date.fromisoformat(cutoff), excluded)]
            x, y = np.array([r['features'] for r in rows]), np.array([r['label'] for r in rows])
            if len(set(y)) != 2:
                raise ValueError('После исключения группы недостаточно классов')
            weights = CrossfitPolicy.weights(rows)
            model = lgb.LGBMClassifier(**self.PARAMS)
            model.fit(x, y, sample_weight=weights)
            path = self.output / f'{cutoff}-exclude{excluded}.txt'
            model.booster_.save_model(str(path))
            loaded = lgb.Booster(model_file=str(path))
            expected = model.predict_proba(x[:20])[:,1]
            np.testing.assert_allclose(expected, loaded.predict(x[:20], num_threads=4), rtol=0, atol=1e-12)
            self.models[cutoff][excluded] = loaded
            self.audits[f'{cutoff}/{excluded}'] = {'windows':len(rows),'companies':len({r['company'] for r in rows}),
                'positives':int(y.sum()),'positive_companies':len({r['company'] for r in rows if r['label']}),
                'excluded_group':excluded,'heldout_excluded':True,
                'max_confirmation':str(max(date.fromisoformat(r['as_of'])+timedelta(days=37) for r in rows)),
                'identities_sha256':hashlib.sha256(repr([(r['company'],r['as_of']) for r in rows]).encode()).hexdigest(),
                'weights_sha256':digest(path),'sample_weights_sha256':hashlib.sha256(weights.tobytes()).hexdigest()}
            write_json(self.output/'training-audit.json',self.audits)
        print('Crossfit trained ' + cutoff, flush=True)

    def predict(self, rows):
        for cutoff in sorted({r['cutoff'] for r in rows}):
            self.train_cutoff(cutoff)
            group = [r for r in rows if r['cutoff'] == cutoff]
            x = np.array([r['features'] for r in group])
            scores = np.stack([self.models[cutoff][i].predict(x, num_threads=4) for i in range(5)], axis=1)
            for row, values in zip(group,scores,strict=True):
                heldout = Dataset.heldout(row['company'])
                row['crossfit_score'] = float(values.mean() if heldout else values[CrossfitPolicy.group(row['company'])])
                row['prediction_mode'] = 'heldout_mean5' if heldout else 'excluded_company_group'

    @staticmethod
    def metrics(rows, threshold):
        labels = [r['label'] for r in rows]
        return {name: Score.classification(labels, flags) for name,flags in {
            'current':[r['current']>=.5 for r in rows], 'candidate18':[r['risk18'] for r in rows],
            'candidate21':[r['risk21'] for r in rows], 'selected25':CrossfitPolicy.flags(rows,threshold)}.items()}

    @staticmethod
    def cluster_bootstrap(rows, threshold, resamples=1000):
        # Один индекс выбирает компанию целиком с её зависимыми окнами обеих политик.
        companies=sorted({r['company'] for r in rows})
        counts=[]
        for company in companies:
            scores=CrossfitExperiment.metrics([r for r in rows if r['company']==company],threshold)
            counts.append([[scores[model][key] for key in ('tp','fp','fn','tn')]
                           for model in ('candidate21','selected25')])
        counts=np.asarray(counts,dtype=float)
        rng=np.random.default_rng(20261025)
        indexes=rng.integers(0,len(companies),(resamples,len(companies)))
        draws=counts[indexes].sum(axis=1)
        total=counts.sum(axis=0)
        def metrics(values):
            tp,fp,fn,tn=np.moveaxis(values,-1,0)
            def ratio(top,bottom):
                return np.divide(top,bottom,out=np.full_like(top,np.nan),where=bottom!=0)
            return {'tp':tp,'fp':fp,'fn':fn,'tn':tn,
                    'precision':ratio(tp,tp+fp),'recall':ratio(tp,tp+fn),
                    'f1':ratio(2*tp,2*tp+fp+fn)}
        sampled,point=metrics(draws),metrics(total)
        result={}
        for key,values in sampled.items():
            difference=values[:,1]-values[:,0]
            finite=difference[np.isfinite(difference)]
            actual=point[key][1]-point[key][0]
            result[key]={'point':float(actual) if np.isfinite(actual) else None,
                         'ci95':np.quantile(finite,[.025,.975]).tolist() if len(finite) else None,
                         'defined_resamples':len(finite)}
        return {'unit':'company_all_windows','companies':len(companies),'resamples':resamples,
                'comparison':'selected25_minus_candidate21','independent_control':False,'differences':result}

    def run(self):
        early = [r for r in self.control if r['phase'] in CrossfitPolicy.EARLY]
        self.predict(early)
        selection = CrossfitPolicy.choose(early)
        write_json(self.output/'selection-frozen.json',selection)
        print('Frozen crossfit policy: '+str(selection['selected']),flush=True)
        later = [r for r in self.control if r['phase'] not in CrossfitPolicy.EARLY]
        self.predict(later)
        threshold = selection['selected']['threshold']
        report = {'selection':selection,'independent_control':False,'production_activated':False,
                  'probability_calibrated':False,'probability_any_negative':None,'phases':{}}
        for phase in sorted({r['phase'] for r in self.control}):
            rows = [r for r in self.control if r['phase']==phase]
            report['phases'][phase] = {'metrics':self.metrics(rows,threshold),
                'companies':len({r['company'] for r in rows}), 'positive_companies':len({r['company'] for r in rows if r['label']}),
                'score_diagnostics':reliability([r['label'] for r in rows],[r['crossfit_score'] for r in rows]),
                'fixed_threshold_sensitivity':{str(t):self.metrics(rows,t)['selected25'] for t in CrossfitPolicy.THRESHOLDS}}
        report['total'] = self.metrics(self.control,threshold)
        report['paired_company_bootstrap'] = self.cluster_bootstrap(self.control,threshold)
        report['preliminary_improvement'] = bool(threshold is not None
            and report['total']['selected25']['tp']>=report['total']['candidate21']['tp']
            and report['total']['selected25']['fp']<report['total']['candidate21']['fp']
            and all(p['metrics']['selected25']['tp']>=p['metrics']['candidate21']['tp'] for p in report['phases'].values()))
        report['early_leave_one_out'] = {}
        for mode in ('cutoff','company_group'):
            value = (lambda r:r['cutoff']) if mode=='cutoff' else (lambda r:CrossfitPolicy.group(r['company']))
            report['early_leave_one_out'][mode] = {str(key):CrossfitPolicy.choose([r for r in early if value(r)!=key])['selected']
                                                  for key in sorted({value(r) for r in early})}
        for mode in ('cutoff','company'):
            report['by_'+mode] = {str(key):self.metrics([r for r in self.control if r[mode]==key],threshold)
                                 for key in sorted({r[mode] for r in self.control})}
        write_json(self.output/'predictions.json',[{k:v for k,v in r.items() if k!='features'} for r in self.control])
        write_json(self.output/'results.json',report)
        write_json(self.output/'completed.json',{'models':sum(len(m) for m in self.models.values()),
            'selection_sha256':digest(self.output/'selection-frozen.json'),'results_sha256':digest(self.output/'results.json')})
        print(json.dumps({'total':report['total'],'preliminary_improvement':report['preliminary_improvement']},indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=Path('data/raw/rolling-peer-risk-v21'))
    parser.add_argument('--output',type=Path,default=Path('data/raw/company-crossfit-v25'))
    args=parser.parse_args()
    CrossfitExperiment(args.source,args.output).run()
