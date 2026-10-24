"""Publica os pacotes de uma edição como GitHub Release imutável do repositório do projeto.

Uso: .\\.venv-report\\Scripts\\python.exe scripts\\publish_release.py [--tag dados-AAAA-MM-DD] [--replace]
Token: lido de api.env.txt na raiz (nunca impresso). Precisa de permissão Contents: read and write no repositório.

Regras (revisão de 24/10/2026):
- A tag vem da edição registrada em relatorios/fiscalizacao/varredura/edicao.json (data da geração), não da data física de arquivos.
- Se a tag já existir, NÃO substitui: cria a próxima revisão (…-r2, …-r3). Só --replace reutiliza a release existente, e isso fica registrado no manifesto.
- A release nasce como rascunho; os ativos são enviados e conferidos (SHA-256 local × digest do GitHub) e só então ela é publicada.
- Além dos pacotes de dados, envia o pacote editorial (tudo o que build_site.py precisa para reconstruir o site) e um manifesto com hashes,
  SHA do código produtor, parâmetros e lista de entradas.
- Erros HTTP diferentes de 404 interrompem com mensagem; não se cria release por engano.
"""
import argparse
import hashlib
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import certifi
import pandas as pd

ROOT = Path('.')
CFG = ROOT / 'site/site_config.json'
API = 'https://api.github.com'
SSL_CTX = ssl.create_default_context(cafile=certifi.where())
FISC = ROOT / 'relatorios/fiscalizacao'
VAR, DOC, MAPA = FISC / 'varredura', FISC / 'documentos', FISC / 'mapa_2026_T2'


class Http(Exception):
    def __init__(self, code, msg):
        super().__init__(f'HTTP {code}: {msg}')
        self.code = code


def token():
    return (ROOT / 'api.env.txt').read_text(encoding='utf-8-sig').strip()


def call(method, url, body=None, ctype='application/json', raw=False):
    data = body if raw else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers={'Authorization': f'Bearer {token()}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'votos-publish', 'Content-Type': ctype})
    try:
        with urllib.request.urlopen(req, timeout=900, context=SSL_CTX) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        raise Http(e.code, e.read().decode()[:300])


def sha256(p, chunk=8 * 1024 ** 2):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def editorial_bundle(dest):
    """Tudo o que build_site.py lê, com caminhos relativos à raiz do repositório (restore_edicao.py extrai na raiz)."""
    files = list(VAR.glob('*.csv')) + [VAR / 'edicao.json', VAR / 'VARREDURA_LOCAIS_RISCO.pdf'] + list(DOC.glob('*.pdf')) + list((DOC / 'figuras').glob('*.png')) + [DOC / 'figuras/legendas.json'] \
        + list(MAPA.glob('*.csv')) + [MAPA / 'MAPA_FISCALIZACAO_2026T2_GERAL.pdf'] + [FISC / 'resumo_indicadores.csv', FISC / 'testes_permutacao.csv', FISC / 'INCONSISTENCIAS_E_FISCALIZACAO.pdf']
    files = [f for f in files if f.exists()]
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in files:
            z.write(f, f.as_posix())
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default=None)
    ap.add_argument('--replace', action='store_true', help='reutiliza a release da tag e substitui ativos (fica registrado no manifesto)')
    a = ap.parse_args()
    cfg = json.loads(CFG.read_text(encoding='utf-8-sig'))
    repo = cfg['repo_url'].split('github.com/')[1].strip('/')
    ed = json.loads((VAR / 'edicao.json').read_text(encoding='utf-8'))
    base = a.tag or f"dados-{pd.Timestamp(ed['edicao']):%Y-%m-%d}"
    assets = [Path(f) for f in cfg['release_assets']]
    pac = ROOT / 'site/pacotes'
    pac.mkdir(exist_ok=True)
    bundle = pac / 'edicao-editorial.zip'
    files = editorial_bundle(bundle)
    assets.append(bundle)
    for f in assets:
        if not f.exists():
            raise SystemExit(f'ativo ausente: {f}')
    # tag imutável: próxima revisão se já existir
    tag, rel, n = base, None, 1
    while True:
        try:
            rel = call('GET', f'{API}/repos/{repo}/releases/tags/{tag}')
        except Http as e:
            if e.code != 404:
                raise SystemExit(f'falha ao consultar a release {tag}: {e}')
            rel = None
        if rel is None or a.replace:
            break
        n += 1
        tag = f'{base}-r{n}'
    if rel is None:
        body = {'tag_name': tag, 'target_commitish': 'main', 'name': f"Dados · edição {pd.Timestamp(ed['edicao']):%d/%m/%Y}" + (f' (revisão {n})' if n > 1 else ''), 'draft': True, 'prerelease': False,
                'body': (f"Pacotes de dados da varredura de fiscalização, edição de {pd.Timestamp(ed['edicao']):%d/%m/%Y} ({len(ed.get('ufs', []))} estados), código {ed.get('codigo_sha', 'n/d')}. "
                         'CSV com separador ponto e vírgula e decimal com vírgula; parquet com uma linha por seção. manifesto-release.json traz SHA-256 de cada ativo, parâmetros e entradas. '
                         'edicao-editorial.zip contém tudo o que scripts/build_site.py precisa para reconstruir o site (scripts/restore_edicao.py). Derivados de dados públicos do TSE. Sinalização não é acusação.')}
        rel = call('POST', f'{API}/repos/{repo}/releases', body)
        print('release criada como rascunho:', tag, flush=True)
    else:
        print('reutilizando release existente (--replace):', tag, flush=True)
    existing = {x['name']: x for x in call('GET', f"{API}/repos/{repo}/releases/{rel['id']}/assets?per_page=100")}
    manifest = {'tag': tag, 'edicao': ed, 'ativos': {}, 'substituiu_ativos': bool(a.replace and existing), 'pacote_editorial': [f.as_posix() for f in files]}
    for p in assets:
        if p.name in existing:
            if not a.replace:
                raise SystemExit(f'ativo {p.name} já existe em {tag}; use --replace para substituir')
            call('DELETE', f"{API}/repos/{repo}/releases/assets/{existing[p.name]['id']}")
        local = sha256(p)
        res = call('POST', f"https://uploads.github.com/repos/{repo}/releases/{rel['id']}/assets?name={urllib.parse.quote(p.name)}", p.read_bytes(), ctype='application/octet-stream', raw=True)
        remote = (res.get('digest') or '').replace('sha256:', '')
        if remote and remote != local:
            raise SystemExit(f'digest divergente em {p.name}: local {local} × GitHub {remote}')
        manifest['ativos'][p.name] = {'bytes': res['size'], 'sha256': local, 'url': res['browser_download_url']}
        print('enviado', p.name, f"{res['size'] / 1024 ** 2:.1f} MB", 'sha256 ok' if remote else 'sha256 local', flush=True)
    mpath = pac / 'manifesto-release.json'
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    if 'manifesto-release.json' in existing:
        call('DELETE', f"{API}/repos/{repo}/releases/assets/{existing['manifesto-release.json']['id']}")
    call('POST', f"https://uploads.github.com/repos/{repo}/releases/{rel['id']}/assets?name=manifesto-release.json", mpath.read_bytes(), ctype='application/json', raw=True)
    if rel.get('draft'):
        rel = call('PATCH', f"{API}/repos/{repo}/releases/{rel['id']}", {'draft': False})
    cfg['release_tag'] = tag
    cfg['release_url'] = rel['html_url']
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (ROOT / 'site/dados').mkdir(exist_ok=True)
    (ROOT / 'site/dados/manifesto-release.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    print('ok', rel['html_url'])


if __name__ == '__main__':
    sys.exit(main())
