import sys
from pathlib import Path
p=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(p))
from base_install import destination
if (destination()/"ready").is_file():
    import site
    site.addsitedir(str(destination()))
