"""Coleta oficial progressiva: presidente e prefeito, exclusivamente."""
import argparse
import json
from pathlib import Path

from auditabr.domain import YEARS
from auditabr.regional import collect_regions
from auditabr.utils import storage_root

parser = argparse.ArgumentParser()
parser.add_argument('--year', type=int, default=2022)
parser.add_argument('--uf', default='MA')
parser.add_argument('--all-samples', action='store_true')
args = parser.parse_args()
scopes = [(args.year,args.uf)] if not args.all_samples else [(2022,'MA')]+[(y,'AC') for y in YEARS]
for year,uf in scopes:
    collect_regions(storage_root(),Path('storage'),(year,),
                    lambda item:print(json.dumps(item,ensure_ascii=True),flush=True),states=(uf,))
