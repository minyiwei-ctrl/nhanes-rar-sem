"""
Project paths shared by the data-preparation notebooks (stages 1, 3, 4_5
and 5): project_root (the parent of scripts/), the raw NHANES folders
data/raw/2011-2012 and data/raw/2013-2014, data/raw itself (where the
minute-level PAXMIN files go) and data/processed. Reads and writes nothing.

raw_file(folder, name) returns the path of one raw NHANES file, matched
without regard to the case of the name or the extension: CDC serves
DEMO_G.XPT, some download tools save demo_g.xpt, and a case-sensitive file
system would otherwise not find one of the two.
"""
from pathlib import Path

project_root = Path(__file__).parent.resolve().parent
raw_root = project_root / "data" / "raw"
raw_2011 = raw_root / "2011-2012"
raw_2013 = raw_root / "2013-2014"

processed = project_root / "data" / "processed"


def raw_file(folder, name):
    """Path of raw NHANES file `name` inside `folder`, matched case-insensitively.

    Raises FileNotFoundError naming the folder when no file matches, so a
    missing download is reported at the point of use.
    """
    folder = Path(folder)
    wanted = name.lower()
    if folder.is_dir():
        for p in sorted(folder.iterdir()):
            if p.name.lower() == wanted:
                return p
    raise FileNotFoundError(f"{name} not found in {folder}")
