"""Restaura, a partir de uma GitHub Release, tudo o que é preciso para reconstruir o site (e, opcionalmente, os parquet por seção),
conferindo SHA-256 pelo manifesto da release. Não precisa de token (release pública).

Uso: python scripts/restore_edicao.py --tag dados-2026-10-24 [--parquet] [--repo Leandro-VPN/observatorio-do-voto]
Depois: python scripts/build_site.py
Nada é extraído antes de o hash conferir; arquivos existentes em relatorios/ são sobrescritos pelos da edição escolhida.
"""
import argparse
import hashlib
import json
import ssl
import sys
import urllib.request
import zipfile
from pathlib import Path

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context()

ROOT = Path('.')


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'votos-restore'})
    with urllib.request.urlopen(req, timeout=900, context=CTX) as r:
        return r.read()


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True)
    ap.add_argument('--repo', default=None)
    ap.add_argument('--parquet', action='store_true', help='também baixa os secoes_indicadores_*.parquet para relatorios/fiscalizacao/')
    a = ap.parse_args()
    repo = a.repo or json.loads((ROOT / 'site/site_config.json').read_text(encoding='utf-8-sig'))['repo_url'].split('github.com/')[1].strip('/')
    base = f'https://github.com/{repo}/releases/download/{a.tag}/'
    man = json.loads(get(base + 'manifesto-release.json'))
    print('edição', man['edicao'].get('edicao'), '| código', man['edicao'].get('codigo_sha'), '| ativos', len(man['ativos']))
    wanted = ['edicao-editorial.zip'] + ([k for k in man['ativos'] if k.endswith('.parquet')] if a.parquet else [])
    for name in wanted:
        info = man['ativos'][name]
        print('baixando', name, f"{info['bytes'] / 1024 ** 2:.1f} MB", flush=True)
        b = get(info['url'])
        if sha256(b) != info['sha256']:
            raise SystemExit(f'SHA-256 divergente em {name}; nada foi extraído deste arquivo')
        if name.endswith('.zip'):
            with zipfile.ZipFile(__import__('io').BytesIO(b)) as z:
                for m in z.namelist():
                    if m.startswith('/') or '..' in m:
                        raise SystemExit(f'caminho inseguro no zip: {m}')
                z.extractall(ROOT)
            print('extraído na raiz:', len(z.namelist()), 'arquivos')
        else:
            dest = ROOT / 'relatorios/fiscalizacao' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b)
            print('gravado', dest)
    print('ok. Agora: python scripts/build_site.py')


if __name__ == '__main__':
    sys.exit(main())
