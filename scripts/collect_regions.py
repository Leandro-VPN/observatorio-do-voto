"""Collect only Norte/Nordeste, resume completed captures without downloading again."""
import argparse
import json
from pathlib import Path

from auditabr.domain import YEARS
from auditabr.regional import collect_regions

parser = argparse.ArgumentParser()
parser.add_argument("--years", nargs="+", type=int, default=list(YEARS))
args = parser.parse_args()

def progress(item):
    print(json.dumps(item,ensure_ascii=True),flush=True)

collect_regions(Path("storage-regional"),Path("storage"),args.years,progress)
