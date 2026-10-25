"""Замороженное объединение трёх разных предупреждений без выдуманной вероятности."""
import argparse
import hashlib
import json
import pickle
from pathlib import Path

import numpy as np

from evaluation.fallback_model.metrics import Score


class ComplementaryRisk:
    RULES = ("current", "veto_union", "majority", "union_intersection", "chronos_union")
    THRESHOLDS = (.01,.02,.05,.1,.15,.2,.3,.4,.5)

    @staticmethod
    def flag(current, chronos, reserve, rule):
        if rule == "current": return current
        if rule == "veto_union": return current and (chronos or reserve)
        if rule == "majority": return int(current)+int(chronos)+int(reserve)>=2
        if rule == "union_intersection": return current or (chronos and reserve)
        if rule == "chronos_union": return chronos or (current and reserve)
        raise ValueError("Неизвестное правило")

    @classmethod
    def statistics(cls,rows,rule,threshold):
        labels=[r["label"] for r in rows]
        flags=[cls.flag(r["current"],r["chronos"],r["reserve"]>=threshold,rule) for r in rows]
        result=Score.classification(labels,flags)
        result["positive_companies"]=len({r["company"] for r in rows if r["label"]})
        result["probability_any_negative"]=None
        return result

    @classmethod
    def choose(cls,rows):
        trials=[{"rule":"current","threshold":.5,"statistics":cls.statistics(rows,"current",.5)}]
        for rule in cls.RULES[1:]:
            for threshold in cls.THRESHOLDS:
                trials.append({"rule":rule,"threshold":threshold,"statistics":cls.statistics(rows,rule,threshold)})
        base=trials[0]["statistics"]
        allowed=[r for r in trials if base["positives"]>=5 and r["statistics"]["tp"]>=base["tp"] and r["statistics"]["fp"]<=base["fp"]]
        choice=min(allowed,key=lambda r:(r["statistics"]["fp"],r["statistics"]["fn"],cls.RULES.index(r["rule"]),r["threshold"])) if allowed else trials[0]
        return {"selected":choice,"trials":trials,"selection":"development January-June only"}

    @staticmethod
    def join(cdf, forecasts):
        valid=[r for r in forecasts if r["opening"]>=0 and r["probability"] is not None]
        lookup={(r["company"],r["cutoff"]):r for r in valid}
        identities=[(r["company"],r["cutoff"]) for r in cdf]
        if len(lookup)!=len(valid) or len(identities)!=len(set(identities)) or set(identities)!=set(lookup):
            raise ValueError("Не совпали окна риска или обнаружены дубли")
        result=[]
        for row in cdf:
            original=lookup[(row["company"],row["cutoff"])]
            label=bool(np.any(original["truth"][:,2]<0))
            if label!=row["labels"]["30"] or row["current"]!=original["probability"]:
                raise ValueError("Источники не совпадают по факту или текущему прогнозу")
            current=original["probability"]>=.5
            chronos=current if original["fallback"] else bool(np.any(original["intervals"]["ft100"][:,0]<0))
            reserve=row["scores"]["cdf6"]["30"]
            if not np.isfinite(reserve) or not 0<=reserve<=1: raise ValueError("Некорректный выход резерва")
            result.append({"company":row["company"],"cutoff":row["cutoff"],"current":current,
                           "chronos":chronos,"reserve":reserve,"label":label})
        return result


class FusionStudy:
    PHASES=("validation","bridge","late_development","other_early","late_other")

    def __init__(self,cdf,chronos,output):
        self.cdf,self.chronos,self.output=cdf,chronos,output
        output.mkdir(parents=True,exist_ok=True)
        self.hashes={}

    def write(self,name,data):
        (self.output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")

    def load(self,phase):
        cdf_path=self.cdf/f"{phase}-rows.json"
        chronos_path=self.chronos/f"inferred-{phase}.pickle"
        for p in (cdf_path,chronos_path): self.hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
        cdf=json.loads(cdf_path.read_text(encoding="utf-8"))
        # Собственные локальные кэши экспериментов09/13, не внешние pickle.
        with chronos_path.open("rb") as stream: forecasts=pickle.load(stream)
        return ComplementaryRisk.join(cdf,forecasts)

    def run(self):
        early={p:self.load(p) for p in self.PHASES[:2]}
        all_early=early["validation"]+early["bridge"]
        policy=ComplementaryRisk.choose(all_early)
        self.write("selection-frozen.json",policy)
        selected=policy["selected"]
        print(f"Frozen fusion: {selected}",flush=True)
        report={"selection":policy,"phases":{},"production_activated":False,"independent_control":False,
                "probability_calibrated":False,"release_allowed":False}
        for phase in self.PHASES:
            rows=early[phase] if phase in early else self.load(phase)
            report["phases"][phase]={"current":ComplementaryRisk.statistics(rows,"current",.5),
                "candidate":ComplementaryRisk.statistics(rows,selected["rule"],selected["threshold"])}
            self.write(f"{phase}-rows.json",rows)
        report["leave_month_out"]={month:ComplementaryRisk.choose([r for r in all_early if r["cutoff"]!=month])["selected"] for month in sorted({r['cutoff'] for r in all_early})}
        report["sources_sha256"]=self.hashes
        self.write("results.json",report)
        print("Fusion evaluation complete",flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--cdf",type=Path,default=Path("data/raw/reserve-distribution-v9"))
    parser.add_argument("--chronos",type=Path,default=Path("data/raw/chronos-finetune-v13/evaluation"))
    parser.add_argument("--output",type=Path,default=Path("data/raw/complementary-risk-v14"))
    args=parser.parse_args()
    FusionStudy(args.cdf,args.chronos,args.output).run()


if __name__=="__main__": main()
