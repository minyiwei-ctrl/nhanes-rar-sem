"""Lower-dimensional cycle contrasts after design-rank warnings in split-cycle SEM.

Imported unchanged from the F1 results freeze (2026-10-19); run from stage
19 after build_cycle_audit.py. Writes 12 pooled single-outcome inputs under
scripts/9_mplus_models/cycle_contrasts/ (two age groups x two biological
outcomes x three rhythm metrics) in which the exposure, every covariate slope
and the intercept differ by survey cycle, with a 1-df MODEL TEST on the
exposure-by-cycle term; the plan and the list of retired split-cycle full
SEMs go to plan.json and result/qc/freeze/cycle_contrast_plan.json.
"""
from pathlib import Path
import json,re,datetime
P=Path(__file__).resolve().parents[1];M=P/'scripts/9_mplus_models';O=M/'cycle_contrasts';O.mkdir(exist_ok=True);Q=P/'result/qc/freeze'
cols=re.findall(r'^#\s+\d+\s+(\w+)\s*$',(P/'data/mplus/nhanes_sem_p1_vars.txt').read_text(),re.M)+['CYCLE2']
names='\n        '.join(' '.join(cols[i:i+7]) for i in range(0,len(cols),7));cov=['AGE','SEX','BMI','EDU','WEAR_T','SLEEP_H'];recs=[]
for age,sub in [('young','ADULT20 EQ 1 AND AGE60 EQ 0'),('old','AGE60 EQ 1')]:
 for y in ['BA_ADV','SII_LOG']:
  for x in ['RA','IS','IV']:
   stem=f'cycle_diff_{age}_{y.lower()}_{x.lower()}';v=[x]+cov;prod=['C'+str(i) for i in range(len(v))]
   defs='\n    '.join(f'{p} = CYCLE2 * {c};' for p,c in zip(prod,v))
   t=f'''TITLE: Cycle difference in {x} to {y}, {age}.
DATA:
    FILE = ../../../data/mplus/nhanes_sem_cycle.dat;
VARIABLE:
    NAMES =
        {names};
    USEVARIABLES = {y} {x} {' '.join(cov)} CYCLE2 {' '.join(prod)};
    MISSING = ALL(-9999);
    SUBPOPULATION = {sub};
    IDVARIABLE = SEQN;
    STRATIFICATION = STRATUM;
    CLUSTER = PSU;
    WEIGHT = WT4YR;
DEFINE:
    {defs}
ANALYSIS:
    TYPE = COMPLEX;
    ESTIMATOR = MLR;
    INFORMATION = OBSERVED;
MODEL:
    {y} ON {x} (bG)
        C0 (delta)
        {' '.join(cov)} CYCLE2 {' '.join(prod[1:])};
MODEL CONSTRAINT:
    NEW(bH);
    bH = bG + delta;
MODEL TEST:
    delta = 0;
OUTPUT:
    STDYX CINTERVAL TECH1 TECH3;
'''
   # Keep all Mplus executable lines below its 90-character limit.
   t=t.replace(f'    USEVARIABLES = {y} {x} {" ".join(cov)} CYCLE2 {" ".join(prod)};',f'    USEVARIABLES = {y} {x} {" ".join(cov)}\n        CYCLE2 {" ".join(prod)};')
   (O/(stem+'.inp')).write_text(t);recs.append({'model':stem,'age':age,'outcome':y,'exposure':x})
plan={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'models':recs,'reason':'Eight cycle-specific full SEM outputs carry non-positive first-order derivative product matrix warnings attributed by Mplus to parameters exceeding design degrees of freedom. All 18 split-cycle primary SEMs are retained as retired audit runs, with no inferential use. Replace those comparisons with 12 single-outcome pooled regressions allowing all exposure and covariate slopes and intercepts to differ by cycle. The pooled design retains 29 strata and 61 PSUs.','scope':['Two age groups x two biological outcomes x three rhythm metrics, fixed before fitting replacement models.','The exposure-by-cycle coefficient is the formal cycle contrast; bG and bH are cycle-specific slopes in the pooled model, common observed-variable scale.','No cognitive/depressive indirect effects inferred from these regressions. They are diagnostic exposure–biological-measure associations, not full SEM a paths.','Outcome-specific observed samples differ from full FIML SEM samples. Models retain original covariates and do not add activity-volume adjustment.','P values are exploratory and unadjusted; the cycle contrast cannot isolate laboratory instrument effects from period differences.'],'retired_models':[r['model'] for r in json.loads((Q/'cycle_analysis_plan.json').read_text())['models'] if r['variant']!='adjusted' and r['base'].startswith('m_')]}
(O/'plan.json').write_text(json.dumps(plan,indent=2));(Q/'cycle_contrast_plan.json').write_text(json.dumps(plan,indent=2));print('Created',len(recs),'pooled cycle contrast inputs; retired',len(plan['retired_models']),'split-cycle SEMs')
