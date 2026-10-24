"""Publica os pacotes grandes de dados como GitHub Release do repositório do projeto (o site só guarda arquivos pequenos e aponta para cá).

Uso: .\\.venv-report\\Scripts\\python.exe scripts\\publish_release.py [--tag dados-AAAA-MM-DD]
Token: lido de api.env.txt na raiz (nunca impresso). Precisa de permissão Contents: read and write no repositório.
Cria a release (ou reutiliza a de mesma tag), envia/substitui os ativos listados em site/site_config.json ("release_assets") e grava a tag em
"release_tag" para o build_site.py gerar os links.
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import certifi
import pandas as pd

SSL_CTX = ssl.create_default_context(cafile=certifi.where())

ROOT = Path('.')
CFG = ROOT / 'site/site_config.json'
API = 'https://api.github.com'


def token():
    return (ROOT / 'api.env.txt').read_text(encoding='utf-8-sig').strip()


def call(method, url, body=None, ctype='application/json', raw=False):
    data = body if raw else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers={'Authorization': f'Bearer {token()}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'votos-publish', 'Content-Type': ctype})
    try:
        with urllib.request.urlopen(req, timeout=600, context=SSL_CTX) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f'{method} {url.split("?")[0]} -> HTTP {e.code}: {e.read().decode()[:300]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default=None)
    a = ap.parse_args()
    cfg = json.loads(CFG.read_text(encoding='utf-8-sig'))
    repo = cfg['repo_url'].split('github.com/')[1].strip('/')
    edicao = pd.Timestamp((ROOT / 'relatorios/fiscalizacao/varredura/resumo_por_eleicao.csv').stat().st_mtime, unit='s')
    tag = a.tag or f'dados-{edicao:%Y-%m-%d}'
    assets = cfg['release_assets']
    for f in assets:
        if not Path(f).exists():
            raise SystemExit(f'ativo ausente: {f}')
    # release: reutiliza se existir
    try:
        rel = call('GET', f'{API}/repos/{repo}/releases/tags/{tag}')
        print('release existente', tag, rel['id'])
    except SystemExit:
        body = {'tag_name': tag, 'target_commitish': 'main', 'name': f'Dados · edição {edicao:%d/%m/%Y}', 'draft': False, 'prerelease': False,
                'body': (f'Pacotes de dados da varredura de fiscalização, edição de {edicao:%d/%m/%Y} (11 estados). Arquivos CSV com separador ponto e vírgula e decimal com vírgula; '
                         'parquet com uma linha por seção. Dicionário de campos e documentos no site. Derivados de dados públicos do TSE. Sinalização não é acusação.')}
        rel = call('POST', f'{API}/repos/{repo}/releases', body)
        print('release criada', tag, rel['id'])
    existing = {x['name']: x['id'] for x in call('GET', f"{API}/repos/{repo}/releases/{rel['id']}/assets?per_page=100")}
    for f in assets:
        p = Path(f)
        if p.name in existing:
            call('DELETE', f'{API}/repos/{repo}/releases/assets/{existing[p.name]}')
            print('substituindo', p.name)
        url = f"https://uploads.github.com/repos/{repo}/releases/{rel['id']}/assets?name={urllib.parse.quote(p.name)}"
        res = call('POST', url, p.read_bytes(), ctype='application/octet-stream', raw=True)
        print('enviado', p.name, f"{res['size'] / 1024 ** 2:.1f} MB", flush=True)
    cfg['release_tag'] = tag
    cfg['release_url'] = rel['html_url']
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('ok', rel['html_url'])


if __name__ == '__main__':
    sys.exit(main())
