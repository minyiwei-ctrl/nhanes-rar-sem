"""Generate the Mplus input files from one template.

    python build_inputs.py            # write files
    python build_inputs.py --check    # verify only, write nothing

Writes m_{outcome}_{cell}_{exposure}[_vol].inp (18 mediation models: 3
exposures x 3 cells x with/without volume adjustment),
m_{outcome}_{cell}_{exposure}_crude.inp (9 unadjusted counterparts of the
primary models: no covariates, fitted to the same participants by adding
COVOK EQ 1 to the SUBPOPULATION statement, on nhanes_sem_covok.dat; STROBE
item 16a) and
x_age_{exposure}[_vol].inp (6 age-interaction models) into this directory.
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
DAT = '../../data/mplus/nhanes_sem.dat'
DAT_COVOK = '../../data/mplus/nhanes_sem_covok.dat'   # DAT plus the COVOK flag

NAMES = """SEQN IV RA IS BA_ADV SII_LOG NLR_LOG OBJ_MVPA PHQ9
        COG_Z MEM_Z FLUEN_Z SPEED_Z
        AGE SEX BMI EDU WEAR_T SLEEP_H VOLUME AGE60
        IV_AGE IS_AGE RA_AGE IV_Q WT4YR STRATUM PSU"""

NAMES_COVOK = NAMES + ' COVOK'

BASE_COVS = 'AGE SEX BMI EDU WEAR_T SLEEP_H'

# outcome blocks: name -> (usevars, measurement model, outcome var in equations)
OUTCOMES = {
    'dep': ('PHQ9', '', 'PHQ9'),
    'cog': ('MEM_Z FLUEN_Z SPEED_Z',
            'COG BY MEM_Z* (l1)\n           FLUEN_Z* (l2)\n           SPEED_Z* (l3);\n    COG@1;',
            'COG'),
}

# age cells: name -> (subpopulation line, label)
CELLS = {
    'young': ('SUBPOPULATION = AGE60 EQ 0;', 'adults 18-59'),
    'old':   ('SUBPOPULATION = AGE60 EQ 1;', 'adults 60+'),
    'all':   ('', 'adults 18+'),
}

TEMPLATE = """TITLE:
    {title}

DATA:
    FILE = {dat};

VARIABLE:
    NAMES =
        {names};

    USEVARIABLES =
        {usevars};

    MISSING = ALL(-9999);
{subpop}
    IDVARIABLE = SEQN;

    STRATIFICATION = STRATUM;
    CLUSTER        = PSU;
    WEIGHT         = WT4YR;

ANALYSIS:
    TYPE        = COMPLEX;
    ESTIMATOR   = MLR;
    INFORMATION = OBSERVED;{starts}

MODEL:
{measurement}
    BA_ADV  ON {exp} (a1){covs_m};

    SII_LOG ON {exp} (a2){covs_m};

    {y} ON {exp} (cp)
           BA_ADV  (b1)
           SII_LOG (b2){covs_y};

    BA_ADV WITH SII_LOG;

MODEL INDIRECT:
    {y} IND {exp};
    {y} IND BA_ADV {exp};
    {y} IND SII_LOG {exp};

MODEL CONSTRAINT:
    NEW(ind_BA ind_SII total_ind prop_BA prop_SII total);
{orient}    ind_BA    = a1 * b1;
    ind_SII   = a2 * b2;
    total_ind = ind_BA + ind_SII;
    total     = cp + total_ind;
    prop_BA   = ind_BA  / total;
    prop_SII  = ind_SII / total;

OUTPUT:
    STDYX CINTERVAL TECH1 TECH3 SVALUES;

SAVEDATA:
    RESULTS = {stem}_results.dat;
    TECH3   = {stem}_tech3.dat;
"""

# COG@1 identifies the factor only up to sign; l1 > 0 fixes the orientation
# so the optimiser cannot return the mirror solution.
ORIENT = '    l1 > 0;\n\n'


def build(exp, outcome, cell, volume, crude=False):
    """One mediation input. crude=True writes the unadjusted counterpart:
    no covariates in any equation, fitted to the same participants as the
    adjusted model by adding COVOK EQ 1 to the SUBPOPULATION statement
    (Mplus does not allow USEOBSERVATIONS together with SUBPOPULATION, and
    domain analysis is the correct subsetting under TYPE = COMPLEX)."""
    y_use, meas, y = OUTCOMES[outcome]
    subpop, cell_lab = CELLS[cell]
    covs = '' if crude else BASE_COVS + (' VOLUME' if volume else '')

    stem = (f"m_{outcome}_{cell}_{exp.lower()}"
            + ('_vol' if volume else '') + ('_crude' if crude else ''))
    usevars = f'{exp} BA_ADV SII_LOG\n        {y_use}' + (f'\n        {covs}' if covs else '')

    title = (f'{exp} -> (KDM-BA, log SII) -> {y}, {cell_lab}'
             + (', adjusted for activity volume' if volume else '')
             + (', unadjusted (same participants)\n    no covariates - '
                'COVOK EQ 1 in SUBPOPULATION gives the same participants'
                if crude else ''))
    if crude:
        # the age cell and the covariate-complete flag in one statement
        subpop = subpop.replace(';', ' AND COVOK EQ 1;')

    return stem, TEMPLATE.format(
        title=title,
        dat=DAT_COVOK if crude else DAT,
        names=NAMES_COVOK if crude else NAMES,
        usevars=usevars,
        subpop=f'\n    {subpop}\n' if subpop else '',
        starts='\n    STARTS      = 20;' if outcome == 'cog' else '',
        measurement=f'    {meas}\n\n' if meas else '',
        exp=exp, y=y,
        covs_m=f'\n               {covs}' if covs else '',
        covs_y=f'\n           {covs}' if covs else '',
        orient=ORIENT if outcome == 'cog' else '',
        stem=stem)


def spec():
    """The models to write. Cognition only exists at 60+. The unadjusted
    counterpart exists for the primary (not volume-adjusted) models only."""
    for exp in ('IV', 'IS', 'RA'):
        for outcome, cell in (('dep', 'young'), ('dep', 'old'), ('cog', 'old')):
            for volume in (False, True):
                yield exp, outcome, cell, volume, False
            yield exp, outcome, cell, False, True


# Age-interaction models: the a1 equation alone with an exposure x age
# product, plus simple slopes at -1 s.d., mean and +1 s.d. of age.
INTERACTION = """TITLE:
    {exp} x age on the a1 path (KDM-BA advancement), adults 18+{voltxt}

DATA:
    FILE = {dat};

VARIABLE:
    NAMES =
        {names};

    USEVARIABLES =
        {exp} {exp}_AGE BA_ADV
        {covs};

    MISSING = ALL(-9999);

    IDVARIABLE = SEQN;

    STRATIFICATION = STRATUM;
    CLUSTER        = PSU;
    WEIGHT         = WT4YR;

ANALYSIS:
    TYPE        = COMPLEX;
    ESTIMATOR   = MLR;
    INFORMATION = OBSERVED;

MODEL:
    BA_ADV ON {exp}      (a_main)
              {exp}_AGE  (a_int)
              {covs};

MODEL CONSTRAINT:
    ! simple slopes at +/- 1 SD of age, and at the mean
    NEW(slope_lo slope_mid slope_hi);
    slope_lo  = a_main - a_int;
    slope_mid = a_main;
    slope_hi  = a_main + a_int;

OUTPUT:
    STDYX CINTERVAL TECH1 TECH3;

SAVEDATA:
    RESULTS = {stem}_results.dat;
"""


def build_interaction(exp, volume):
    covs = BASE_COVS + (' VOLUME' if volume else '')
    stem = f'x_age_{exp.lower()}' + ('_vol' if volume else '')
    return stem, INTERACTION.format(
        exp=exp, dat=DAT, names=NAMES, covs=covs, stem=stem,
        voltxt=', adjusted for activity volume' if volume else '')


def main():
    check = '--check' in sys.argv
    for dat, names in ((DAT, NAMES), (DAT_COVOK, NAMES_COVOK)):
        ncol = len(open(HERE / dat).readline().split()) if (HERE / dat).exists() else None
        nnames = len(names.split())
        if ncol and ncol != nnames:
            print(f'WARNING: {Path(dat).name} has {ncol} columns, NAMES expects '
                  f'{nnames}. Re-run 9_mplus_prep before running any of these.')

    jobs = [build(*a) for a in spec()]
    jobs += [build_interaction(e, v) for e in ('IV', 'IS', 'RA') for v in (False, True)]

    written = []
    for stem, text in jobs:
        path = HERE / f'{stem}.inp'
        if not check:
            path.write_text(text)
        written.append(stem)

        # every variable used in the model must be declared in USEVARIABLES
        use = set(text.split('USEVARIABLES =')[1].split(';')[0].split())
        block = text.split('\nMODEL:')[1].split('\nMODEL CONSTRAINT:')[0]
        block = block.replace('MODEL INDIRECT:', ' ')
        for ch in ';(*@':
            block = block.replace(ch, ' ')
        used = {w for w in block.split()
                if w.isupper() and w not in {'ON', 'BY', 'WITH', 'IND', 'COG'}}
        missing = used - use
        if missing:
            sys.exit(f'{stem}: {sorted(missing)} used but not in USEVARIABLES')

    print(f'{"checked" if check else "wrote"} {len(written)} inputs')
    for s in written:
        print(' ', s)


if __name__ == '__main__':
    main()
