"""Bounded complete-case cognition sensitivity; fixes the model set before fitting.

Imported unchanged from the F1 results freeze (2026-10-19); run from stage
19 after 9_mplus_models/build_p1.py. Writes data/mplus/nhanes_sem_selection.dat
(the P1 file plus CC_RA / CC_IS / CC_IV, 1 when every modelled variable of
the cognition model is observed) and the three complete-case cognition
inputs under scripts/9_mplus_models/selection_audit/, with the plan in
plan.json and result/qc/freeze/selection_analysis_plan.json.
"""
from pathlib import Path
import json,re,datetime,hashlib
import pandas as pd
P=Path(__file__).resolve().parents[1];M=P/'scripts/9_mplus_models';O=M/'selection_audit';O.mkdir(exist_ok=True)
Q=P/'result/qc/freeze'
cols=re.findall(r'^#\s+\d+\s+(\w+)\s*$',(P/'data/mplus/nhanes_sem_p1_vars.txt').read_text(),re.M)
d=pd.read_csv(P/'data/mplus/nhanes_sem_p1.dat',sep=r'\s+',names=cols)
common=['BA_ADV','SII_LOG','MEM_Z','FLUEN_Z','SPEED_Z','AGE','SEX','BMI','EDU','WEAR_T','SLEEP_H']
for x in ['RA','IS','IV']:d['CC_'+x]=(d[common+[x]].ne(-9999).all(axis=1)).astype(int)
f=P/'data/mplus/nhanes_sem_selection.dat';d.to_csv(f,sep=' ',header=False,index=False,float_format='%.6f')
names='\n        '.join(' '.join(list(d.columns)[i:i+7]) for i in range(0,len(d.columns),7))
records=[]
for x in ['ra','is','iv']:
    stem='m_cog_old_'+x;new='cc_'+stem;t=(M/(stem+'.inp')).read_text()
    t=re.sub(r'(?im)^\s*FILE\s*=\s*[^;]+;', '\n    FILE = ../../../data/mplus/nhanes_sem_selection.dat;',t,count=1)
    t=re.sub(r'(?is)(\bNAMES\s*=).*?;',lambda m:m[1]+'\n        '+names+';',t,count=1)
    t=t.replace('SUBPOPULATION = AGE60 EQ 1;',f'SUBPOPULATION = AGE60 EQ 1 AND CC_{x.upper()} EQ 1;')
    t=t.replace(stem+'_results',new+'_results').replace(stem+'_tech3',new+'_tech3')
    t=t.replace('TITLE:', 'TITLE:\n    Complete-case sensitivity; all modeled variables observed.',1)
    (O/(new+'.inp')).write_text(t)
    records.append({'model':new,'base':stem,'n_complete':int(((d.AGE60==1)&(d['CC_'+x.upper()]==1)).sum()),'input_sha256':hashlib.sha256(t.encode()).hexdigest()})
plan={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'models':records,'data_sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'reason':'CFQ guidance calls for assessment of selection. Compare baseline FIML with fully observed cases for all three existing cognition models; preserve the exposure/outcome definitions, common scales, survey weights, design, and latent-factor orientation.','interpretation':['Weighted availability profiles describe observed selection; they do not establish MAR.','Complete-case refits are sensitivity analyses, not corrections for selection or substitutes for primary results.','No nonresponse weight is estimated from unobserved outcomes; no new model selected by significance.','Cognitive latent scales can vary by sample; compare both common-file coefficients and STDYX with this qualification.']}
(O/'plan.json').write_text(json.dumps(plan,indent=2));(Q/'selection_analysis_plan.json').write_text(json.dumps(plan,indent=2));print(json.dumps(plan,indent=2))
