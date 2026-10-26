"""Create a bounded cycle sensitivity set without changing the baseline models.

All variants and comparisons are fixed before reading their results. A cycle
indicator cannot correct the documented within-cycle instrument transition.

Imported unchanged from the F1 results freeze (2026-10-19); run from stage
19 (19_sensitivity_mplus.ipynb) after 9_mplus_models/build_p1.py. Writes
data/mplus/nhanes_sem_cycle.dat and the inputs under
scripts/9_mplus_models/cycle_audit/ (42 cycle-adjusted full and P1 models,
30 cycle-specific variants), with the audit plan in plan.json and
result/qc/freeze/cycle_analysis_plan.json.
"""
from pathlib import Path
import re,json,hashlib,datetime
import pandas as pd

P=Path(__file__).resolve().parents[1];M=P/'scripts/9_mplus_models';O=M/'cycle_audit';O.mkdir(exist_ok=True)
Q=P/'result/qc/freeze';Q.mkdir(parents=True,exist_ok=True)
cols=re.findall(r'^#\s+\d+\s+(\w+)\s*$',(P/'data/mplus/nhanes_sem_p1_vars.txt').read_text(),re.M)
dat=pd.read_csv(P/'data/mplus/nhanes_sem_p1.dat',sep=r'\s+',header=None,names=cols)
raw=pd.read_csv(P/'data/processed/8_nhanes_analytic.csv',usecols=['SEQN','CYCLE'])
dat=dat.merge(raw,on='SEQN',how='left',validate='one_to_one');assert dat.CYCLE.notna().all()
dat['CYCLE2']=dat.CYCLE.map({'2011-2012':0,'2013-2014':1});dat=dat.drop(columns='CYCLE')
target=P/'data/mplus/nhanes_sem_cycle.dat';dat.to_csv(target,sep=' ',header=False,index=False,float_format='%.6f')
assert len(dat)==11977 and len(dat.columns)==48
names='\n        '.join(' '.join(list(dat.columns)[i:i+7]) for i in range(0,len(dat.columns),7))
primary=[f'm_{y}_{a}_{x}' for y,a in [('dep','young'),('dep','old'),('cog','old')] for x in ['ra','is','iv']]
age=[f'x_age_{s}{x}' for s in ['', 'sii_'] for x in ['ra','is','iv']]
adjusted=primary+[s+'_vol' for s in primary]+age+[s+'_vol' for s in age]+[f'p1_{x}_{v}' for x in ['ra','iv'] for v in ['linear','spline','spline_age','spline_age_nl','quint','quint_age']]
variants=[(s,'adjusted') for s in adjusted]+[(s,v) for s in primary+age for v in ['cycleG','cycleH']]
records=[]
for stem,variant in variants:
    base=M/(stem+'.inp');assert base.exists(),base
    t=base.read_text();new=f'{variant}_{stem}'
    t=re.sub(r'(?im)^\s*FILE\s*=\s*[^;]+;', '\n    FILE = ../../../data/mplus/nhanes_sem_cycle.dat;',t,count=1)
    t=re.sub(r'(?is)(\bNAMES\s*=).*?;',lambda m:m[1]+'\n        '+names+';',t,count=1)
    if variant=='adjusted':
        def add_cycle_use(m):
            v=m[2].split(); ordered=[x for x in v if x in dat.columns]+['CYCLE2']+[x for x in v if x not in dat.columns]
            return m[1]+'\n        '+'\n        '.join(' '.join(ordered[i:i+7]) for i in range(0,len(ordered),7))+';'
        t=re.sub(r'(?is)(\bUSEVARIABLES\s*=)(.*?);',add_cycle_use,t,count=1)
        # Add the cycle main effect to each structural regression, not the factor measurement equation.
        t,n=re.subn(r'(?ims)(^\s*\w+\s+ON\b[^;]*);',r'\1 CYCLE2;',t)
        assert n==(3 if stem.startswith('m_') else 1),(stem,n)
    else:
        value=0 if variant=='cycleG' else 1
        t,n=re.subn(r'(?im)(^\s*SUBPOPULATION\s*=\s*)([^;]+);',lambda m:m[1]+'('+m[2].strip()+f') AND CYCLE2 EQ {value};',t,count=1)
        assert n==1
    # Saved diagnostics must be unique to the variant.
    t=t.replace(stem+'_results.dat',new+'_results.dat').replace(stem+'_tech3.dat',new+'_tech3.dat')
    t=t.replace('TITLE:',f'TITLE:\n    Cycle audit: {variant}; baseline {stem}.',1)
    (O/(new+'.inp')).write_text(t)
    records.append({'model':new,'base':stem,'variant':variant,'input_sha256':hashlib.sha256(t.encode()).hexdigest()})
plan={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'baseline_preserved':True,'models':records,'n_adjusted':len(adjusted),'n_by_cycle':2*len(primary+age),'data_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'reason':'CDC CBC_H flags RDW/WBC instrument effects; both are used in internally calibrated KDM. Cycle is added to every structural regression while exposures, outcomes, scales, survey design, missingness and spline knots stay fixed. Cycle-specific variants retain the common data scales and use design subpopulations.','interpretation_rules':['Do not replace primary estimates or select variants by P value.','Compare estimates and uncertainty, not only significance categories.','Cycle-specific cognition effects are descriptive because factor measurement invariance is not established.','Between-cycle contrasts are restricted to biological-measure paths and age interactions on a common scale.','Use reported standard errors for independent-cycle contrasts; the cycles use distinct strata/PSUs.','Period adjustment does not identify or correct the actual within-2012 instrument transition; retain this limitation.','No activity-volume-adjusted flexible interactions or nonlinear full-path indirect effects are introduced by this audit.']}
if (O/'plan.json').exists():
    previous=json.loads((O/'plan.json').read_text())
    assert [(x['model'],x['base'],x['variant']) for x in previous['models']]==[(x['model'],x['base'],x['variant']) for x in records]
    plan['created_utc']=previous['created_utc']
    plan['input_format_fix']='NAMES variables, including CYCLE2, precede DEFINE-created products in USEVARIABLES; model set and hypotheses unchanged.'
(O/'plan.json').write_text(json.dumps(plan,indent=2));(Q/'cycle_analysis_plan.json').write_text(json.dumps(plan,indent=2))
print('Created',len(records),'inputs;',len(adjusted),'cycle-adjusted and',2*len(primary+age),'cycle-specific')
