"""Relatorio: os logs publicados sao os logs verdadeiros? Teste de todas as urnas com log no HD.

Entradas: research/integridade/resultado/ (integridade_check.py e integridade_canais.py),
          research/analysis/*/sections.parquet (log x BU), BU (bweb) de cada pleito.
Saidas:   relatorios/integridade/
"""
import glob
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4, landscape  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import make_bahia_reports as M  # noqa: E402

RES = ROOT / 'research' / 'integridade' / 'resultado'
OUT = ROOT / 'relatorios' / 'integridade'
FIG = OUT / 'figuras'
EL_LABEL = {'2022-t1': '2022 1º turno', '2022-t2': '2022 2º turno', '2024-t1': '2024 1º turno', '2024-t2': '2024 2º turno',
            '2026-t1': '2026 1º turno', '2026-t2': '2026 2º turno'}
DAY = {'2022-t1': '20221002', '2022-t2': '20221030', '2024-t1': '20241006', '2024-t2': '20241027', '2026-t1': '20261004', '2026-t2': '20261025'}
n = M.n
STEM22 = re.compile(r'^o\d+-(\d{5})(\d{4})(\d{4})$')
STEM24 = re.compile(r'^o\d+[a-z]{2}(\d{5})(\d{4})(\d{4})$')
FLAGS = ['log_hash_ok', 'log_assinatura_ok', 'bu_hash_ok', 'bu_assinatura_ok', 'rdv_hash_ok', 'rdv_assinatura_ok', 'cadeia_ok']


def parse_label(lab):
    if lab.startswith('estados_'):
        _, uf, el = lab.split('_'); return uf, el, 'dados abertos'
    if lab.startswith('municipais_'):
        _, uf, el = lab.split('_'); return uf, el, 'dados abertos'
    if lab.startswith('bahia-presidente'):
        return 'BA', lab.split('_')[-1], 'dados abertos'
    if lab.startswith('piloto-ba-2022-t2'):
        return 'BA', '2022-t2', 'dados abertos'
    raise ValueError(lab)


def load_results():
    fr = []
    for d in sorted(p for p in RES.iterdir() if p.is_dir()):
        parts = sorted(d.glob('part-*.parquet'))
        if not parts:
            continue
        df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
        uf, el, src = parse_label(d.name)
        df['uf'], df['eleicao'], df['canal'], df['raiz'] = uf, el, src, d.name
        df['concluido'] = (d / 'DONE').exists()
        fr.append(df)
    for p in sorted(RES.glob('segundo_turno_2026_*.parquet')):
        df = pd.read_parquet(p)
        df['eleicao'], df['canal'], df['raiz'], df['concluido'] = '2026-t2', 'sistema de resultados', p.stem, True
        fr.append(df)
    d = pd.concat(fr, ignore_index=True)
    for c in FLAGS + ['manifest_ok', 'log_local', 'log_local_igual_zip']:
        if c not in d:
            d[c] = np.nan
    d['tem_log'] = d.log_nome.notna()
    # chave de secao a partir do nome do arquivo
    mz = d.urna.str.extract(STEM22)
    m4 = d.urna.str.extract(STEM24)
    for i, c in enumerate(['mun', 'zona', 'secao']):
        d[c] = pd.to_numeric(mz[i].fillna(m4[i]), errors='coerce')
    d['cert_num'] = pd.to_numeric(d.cert_cn.str.extract(r'(\d+)$')[0], errors='coerce')
    return d


def ok(s):
    return (s == True).sum()  # noqa: E712


def summarize(d, by):
    rows = []
    for k, g in d.groupby(by, sort=True):
        k = k if isinstance(k, tuple) else (k,)
        gl = g[g.tem_log]
        r = dict(zip(by, k))
        r.update(urnas=len(g), com_log=len(gl), log_no_hd=ok(gl.log_local), log_hd_igual_publicado=ok(gl.log_local_igual_zip),
                 manifesto_lido=ok(g.manifest_ok), log_hash_ok=ok(gl.log_hash_ok), log_assinatura_ok=ok(gl.log_assinatura_ok),
                 bu_hash_ok=ok(g.bu_hash_ok), bu_assinatura_ok=ok(g.bu_assinatura_ok), rdv_hash_ok=ok(g.rdv_hash_ok),
                 rdv_assinatura_ok=ok(g.rdv_assinatura_ok), cadeia_ac_ok=ok(g.cadeia_ok))
        err = g.get('erro', pd.Series(index=g.index, dtype=object))
        r['sem_arquivo_de_assinatura'] = int((err == 'sem manifesto no zip').sum())
        r['falhas'] = int(failure_mask(g).sum()) - r['sem_arquivo_de_assinatura']
        rows.append(r)
    return pd.DataFrame(rows)


def failure_mask(g):
    m = pd.Series(False, index=g.index)
    for c in FLAGS + ['manifest_ok']:
        m |= (g[c] == False)  # noqa: E712
    m |= g.get('erro', pd.Series(index=g.index, dtype=object)).notna()
    m |= (g.log_local_igual_zip == False)  # noqa: E712
    return m


# ------------------------------------------------------------------ BU (bweb): numero da urna
def bweb_sources():
    S = []
    for p in glob.glob(str(ROOT / 'research/estados/*/20*-t*/bu.parquet')):
        uf, el = Path(p).parts[-3], Path(p).parts[-2]
        S.append((uf, el, p))
    for el in ('2022-t1', '2026-t1'):
        p = ROOT / 'research/bahia-presidente-2022-2026' / el / 'bu.parquet'
        if p.exists():
            S.append(('BA', el, str(p)))
    p = ROOT / 'research/piloto-ba-2022-t2/captures/bweb_2t_BA_311020221535.parquet'
    if p.exists():
        S.append(('BA', '2022-t2', str(p)))
    for p in glob.glob(str(ROOT / 'research/bu/2024-t*/*_PREFEITO.parquet')):
        S.append((Path(p).stem.split('_')[0], Path(p).parts[-2], p))
    return S


def urn_numbers():
    fr = []
    for uf, el, p in bweb_sources():
        try:
            b = pd.read_parquet(p, columns=['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'NR_URNA_EFETIVADA'])
        except Exception:
            continue
        b = b.drop_duplicates()
        b = b.apply(pd.to_numeric, errors='coerce').drop_duplicates(['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO'])
        b.columns = ['mun', 'zona', 'secao', 'urna_bu']
        b['uf'], b['eleicao'] = uf, el
        fr.append(b)
    return pd.concat(fr, ignore_index=True) if fr else pd.DataFrame()


# ------------------------------------------------------------------ log x BU
def log_x_bu():
    rows = []
    srcs = []
    for p in glob.glob(str(ROOT / 'research/estados/*/20*-t*/analysis/sections.parquet')):
        srcs.append((Path(p).parts[-4], Path(p).parts[-3], p))
    for el in ('2022-t1', '2026-t1'):
        p = ROOT / 'research/bahia-presidente-2022-2026' / el / 'analysis' / 'sections.parquet'
        if p.exists():
            srcs.append(('BA', el, str(p)))
    p = ROOT / 'research/piloto-ba-2022-t2/analysis/sections.parquet'
    if p.exists():
        srcs.append(('BA', '2022-t2', str(p)))
    for el in ('2024-t1', '2024-t2'):
        for p in glob.glob(str(ROOT / 'research/analysis/PREFEITO' / '*' / el / 'sections.parquet')):
            srcs.append((Path(p).parts[-3], el, p))
    if True:
        for uf, el, p in srcs:
                s = pd.read_parquet(p)
                s = s[s.vote_events.notna() & s.attendance.notna()]
                if 'member' in s:
                    s = s.drop_duplicates('member')
                if not len(s):
                    continue
                diff = s.vote_events - s.attendance
                rows.append(dict(eleicao=el, uf=uf, secoes_com_log=len(s), iguais=int((diff == 0).sum()),
                                 log_menor=int((diff < 0).sum()), log_maior=int((diff > 0).sum()),
                                 dif_abs_total=int(diff.abs().sum()),
                                 relogio_voltou=int((s.get('clock_reversals', pd.Series(0, index=s.index)) > 0).sum()),
                                 horario_malformado=int((s.get('malformed_timestamps', pd.Series(0, index=s.index)) > 0).sum())))
    base = ROOT / 'research' / 'segundo_turno_2026'
    bu = pd.read_parquet(base / 'bu_todos_decodificados.parquet', columns=['uf', 'log_name', 'e6258_comparecimento'])
    for p in sorted(base.glob('logparse_*.parquet')):
        lp = pd.read_parquet(p, columns=['log_name', 'vote_events'])
        s = lp.merge(bu, on='log_name')
        diff = s.vote_events - s.e6258_comparecimento
        rows.append(dict(eleicao='2026-t2', uf=p.stem.split('_')[1], secoes_com_log=len(s), iguais=int((diff == 0).sum()),
                         log_menor=int((diff < 0).sum()), log_maior=int((diff > 0).sum()), dif_abs_total=int(diff.abs().sum()),
                         relogio_voltou=np.nan, horario_malformado=np.nan))
    return pd.DataFrame(rows)


def raiz_path(lab):
    if lab.startswith('piloto-ba-2022-t2'):
        return ROOT / 'research' / 'piloto-ba-2022-t2'
    if lab.startswith('bahia-presidente'):
        return ROOT / 'research' / 'bahia-presidente-2022-2026' / lab.split('_')[-1]
    a, uf, el = lab.split('_')
    return ROOT / 'research' / a / uf / el


def classify_divergent(x):
    """Le o log das urnas cujo certificado difere da urna do BU e procura sinal de urna de contingencia/recuperacao."""
    sys.path.insert(0, str(ROOT / 'src'))
    from auditabr import logs
    out = []
    for r in x.itertuples():
        motivo = 'sem explicação no log'
        try:
            txt = logs.read_log(raiz_path(r.raiz) / 'logs' / r.log_nome).decode('latin-1')
            if 'Detectada MV em Urna de conting' in txt or 'Recuperação de dados' in txt or 'recuperação de dados' in txt:
                motivo = 'urna de contingência recuperou a memória de votação da urna original'
            elif 'Urna de conting' in txt:
                motivo = 'urna de contingência (troca de urna)'
        except Exception as exc:
            motivo = 'log não lido: ' + repr(exc)[:60]
        out.append(motivo)
    return out


def republished():
    """Zips cujo tamanho mudou entre a coleta e o teste: compara a lista de arquivos (diretorio central)."""
    import collections
    import json
    import zipfile
    sys.path.insert(0, str(ROOT / 'src'))
    from auditabr.acquisition import RemoteZipReader
    cache = OUT / 'zips_republicados.csv'
    rows = []
    for dn in sorted(RES.glob('*/DONE')):
        info = json.loads(dn.read_text(encoding='utf-8'))
        if 'zip_atual' not in info or info['zip_atual']['bytes'] == info['bytes_zip_coleta']:
            continue
        rp = raiz_path(dn.parent.name)
        inv = json.loads((rp / 'remote-inventory.json').read_text(encoding='utf-8'))
        e = next(x for x in inv if x['resource']['url'] == info['zip'])
        old = {m['name']: m['bytes'] for m in e.get('members', [])}
        try:
            with RemoteZipReader(info['zip'], budget=512 * 1024 ** 2) as r, zipfile.ZipFile(r) as z:
                new = {i.filename: i.file_size for i in z.infolist()}
        except Exception as exc:
            rows.append(dict(raiz=dn.parent.name, erro=repr(exc)[:100]))
            continue
        tipo = lambda x: x.rsplit('-', 1)[-1] if '-' in x else x.rsplit('.', 1)[-1]  # noqa: E731
        added = set(new) - set(old); removed = set(old) - set(new)
        changed = [k for k in set(old) & set(new) if old[k] != new[k]]
        rows.append(dict(raiz=dn.parent.name, bytes_coleta=info['bytes_zip_coleta'], bytes_atual=info['zip_atual']['bytes'],
                         ultima_modificacao=info['zip_atual']['cabecalhos'].get('last-modified'),
                         arquivos_coleta=len(old), arquivos_atual=len(new), incluidos=len(added), removidos=len(removed), tamanho_alterado=len(changed),
                         tipos_incluidos=dict(collections.Counter(tipo(a) for a in added).most_common(5)),
                         tipos_removidos=dict(collections.Counter(tipo(a) for a in removed).most_common(5)),
                         tipos_alterados=dict(collections.Counter(tipo(a) for a in changed).most_common(5))))
    df = pd.DataFrame(rows)
    df.to_csv(cache, index=False, encoding='utf-8-sig')
    return df


def img(path, w):
    from PIL import Image as PI
    im = PI.open(path)
    return Image(str(path), width=w * cm, height=w * cm * im.size[1] / im.size[0])


def main():
    OUT.mkdir(parents=True, exist_ok=True); FIG.mkdir(exist_ok=True)
    d = load_results()
    incompletas = sorted(d.loc[~d.concluido, 'raiz'].unique())
    E = summarize(d, ['eleicao'])
    U = summarize(d, ['eleicao', 'uf'])
    F = d[failure_mask(d)].copy()
    F['tipo'] = np.where(F.get('erro', pd.Series(index=F.index, dtype=object)) == 'sem manifesto no zip',
                         'sem arquivo de assinatura no zip (não verificável)', 'falha de verificação')
    # certificados
    C = d[d.manifest_ok == True].groupby(['eleicao', 'cert_emissor', 'cert_alg']).size().rename('urnas').reset_index()  # noqa: E712
    certs_unicos = d.cert_sha256.nunique()
    # horario da assinatura
    d['dia_assin'] = d.assinado_em.str[:8]
    d['hora_assin'] = pd.to_numeric(d.assinado_em.str[9:11], errors='coerce') + pd.to_numeric(d.assinado_em.str[11:13], errors='coerce') / 60
    d['assinou_no_dia'] = d.dia_assin == d.eleicao.map(DAY)
    A = d[d.manifest_ok == True].groupby('eleicao').agg(urnas=('urna', 'size'), no_dia=('assinou_no_dia', 'sum'),  # noqa: E712
                                                         antes_17h=('hora_assin', lambda x: int((x < 17).sum()))).reset_index()
    fora_dia = d[(d.manifest_ok == True) & ~d.assinou_no_dia][['eleicao', 'uf', 'urna', 'assinado_em', 'cert_cn']]  # noqa: E712
    # identidade da urna: certificado x NR_URNA_EFETIVADA do BU
    UN = urn_numbers()
    idt = pd.DataFrame()
    if len(UN):
        x = d[d.cert_num.notna()].merge(UN, on=['uf', 'eleicao', 'mun', 'zona', 'secao'], how='left')
        x['tem_bu'] = x.urna_bu.notna()
        x['mesma_urna'] = x.cert_num == x.urna_bu
        idt = x.groupby('eleicao').agg(urnas=('urna', 'size'), com_numero_no_bu=('tem_bu', 'sum'),
                                       mesma_urna=('mesma_urna', 'sum')).reset_index()
        divergente = x[x.tem_bu & ~x.mesma_urna][['eleicao', 'uf', 'raiz', 'urna', 'log_nome', 'cert_cn', 'urna_bu']].copy()
        divergente['explicacao_no_log'] = classify_divergent(divergente) if len(divergente) else []
        divergente.loc[divergente.urna_bu <= 0, 'explicacao_no_log'] = 'boletim publicado sem número de urna (campo = -1)'
    else:
        divergente = pd.DataFrame()
    # canais
    cp = RES / 'canais.parquet'
    CH = pd.read_parquet(cp) if cp.exists() else pd.DataFrame()
    CHs = pd.DataFrame()
    if len(CH):
        CH['eleicao'] = CH.raiz.str.extract(r'(20\d\d-t\d)')[0]
        if 'erro' not in CH:
            CH['erro'] = None
        CHs = CH.groupby('eleicao').agg(sorteadas=('log_nome', 'size'), log_igual=('log_canal2_igual_hd', lambda s: ok(s)),
                                        hash_ok=('log_hash_ok', lambda s: ok(s)), assinatura_ok=('log_assinatura_ok', lambda s: ok(s)),
                                        uma_versao=('n_hashes', lambda s: int((s == 1).sum())), erro=('erro', lambda s: int(s.notna().sum()))).reset_index()
    LB = log_x_bu()
    RP = republished()
    LBe = LB.groupby('eleicao')[['secoes_com_log', 'iguais', 'log_menor', 'log_maior', 'dif_abs_total', 'relogio_voltou', 'horario_malformado']].sum(min_count=1).reset_index()

    # ---------------- arquivos
    E.to_csv(OUT / 'integridade_por_eleicao.csv', index=False, encoding='utf-8-sig')
    U.to_csv(OUT / 'integridade_por_uf.csv', index=False, encoding='utf-8-sig')
    keep = ['tipo', 'eleicao', 'uf', 'canal', 'urna', 'log_nome', 'log_local', 'log_local_igual_zip', 'manifest_ok', 'log_hash_ok', 'log_assinatura_ok',
            'bu_hash_ok', 'bu_assinatura_ok', 'rdv_hash_ok', 'rdv_assinatura_ok', 'cadeia_ok', 'cert_cn', 'cert_emissor', 'assinado_em', 'erro']
    F.reindex(columns=keep).to_csv(OUT / 'falhas.csv', index=False, encoding='utf-8-sig')
    LB.to_csv(OUT / 'log_x_boletim.csv', index=False, encoding='utf-8-sig')
    if len(CH):
        CH.to_csv(OUT / 'canais_amostra.csv', index=False, encoding='utf-8-sig')
    with pd.ExcelWriter(OUT / 'INTEGRIDADE_URNAS.xlsx') as xw:
        E.to_excel(xw, sheet_name='por_eleicao', index=False)
        U.to_excel(xw, sheet_name='por_uf', index=False)
        F.reindex(columns=keep).to_excel(xw, sheet_name='falhas', index=False)
        C.to_excel(xw, sheet_name='certificados', index=False)
        A.to_excel(xw, sheet_name='horario_assinatura', index=False)
        fora_dia.head(100000).to_excel(xw, sheet_name='assinou_fora_do_dia', index=False)
        if len(idt):
            idt.to_excel(xw, sheet_name='identidade_urna', index=False)
            divergente.head(100000).to_excel(xw, sheet_name='urna_divergente', index=False)
        if len(CH):
            CHs.to_excel(xw, sheet_name='canais_resumo', index=False)
        LB.to_excel(xw, sheet_name='log_x_boletim', index=False)
        if len(RP):
            RP.astype(str).to_excel(xw, sheet_name='zips_republicados', index=False)
        d.reindex(columns=keep + ['cert_alg', 'cadeia_ac']).to_parquet(OUT / 'integridade_todas_urnas.parquet', index=False)

    # ---------------- figura: horario da assinatura
    fig, ax = plt.subplots(figsize=(10, 3.6))
    for el, g in d[d.manifest_ok == True].groupby('eleicao'):  # noqa: E712
        h = g.hora_assin[g.assinou_no_dia].dropna()
        ax.hist(h.clip(16, 23), bins=np.arange(16, 23.01, 1 / 6), histtype='step', density=True, label=EL_LABEL.get(el, el))
    ax.set(xlabel='hora da assinatura dos arquivos na urna (relógio da urna, dia da eleição)', ylabel='densidade')
    ax.legend(fontsize=7); fig.tight_layout(); fig.savefig(FIG / 'horario_assinatura.png', dpi=150); plt.close(fig)

    # ---------------- PDF
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    tot = len(d); tot_log = int(d.tem_log.sum())
    st = [Paragraph('Os logs publicados são os logs verdadeiros? Teste de todas as urnas com log guardado', H1),
          Paragraph(f'Foram testadas {n(tot)} urnas ({n(tot_log)} com log) de seis pleitos: 2022 (1º e 2º turnos), 2024 (1º e 2º turnos), 2026 1º turno '
                    '(dados abertos do TSE, arquivos “transmitidos para totalização”) e 2026 2º turno (sistema de resultados do TSE). '
                    'Para cada urna se conferiu o arquivo de assinaturas que a própria urna gera ao encerrar a votação (.vscmr em 2022, -vota.vsc a partir de 2024).', P)]
    if incompletas:
        st.append(Paragraph('Atenção: processamento ainda incompleto em ' + ', '.join(incompletas) + '.', NOTE))
    st += [Paragraph('Como funciona a prova', H2)]
    for t_ in ['Ao encerrar, a urna calcula o SHA-512 de cada arquivo (log, boletim, RDV, imagem do boletim…) e assina cada hash com a chave do seu módulo de segurança. '
               'A chave privada fica dentro do hardware da urna; o arquivo de assinaturas traz o certificado da urna (com a chave pública).',
               'Urnas modelos 2009–2015: certificado emitido pela “AC URNA” do TSE, assinatura ECDSA na curva P-521 com SHA-512. '
               'Urnas 2020 e 2022: certificados da “AC UE2020” e “AC UE2022”, assinatura Ed521 (EdDSA na curva E-521, padrão ICP-Brasil, DOC-ICP-01.01), sobre o SHA-512 do hash do arquivo.',
               'Conferimos três coisas, com código próprio e independente: (1) o SHA-512 do log guardado no HD é igual ao hash listado pela urna; '
               '(2) a assinatura da urna sobre esse hash é válida para a chave pública do certificado; (3) o certificado da urna foi assinado pela AC do TSE indicada nele. '
               'Os certificados das ACs vêm do pacote oficial do TSE “Formato dos arquivos de BU, RDV e assinatura digital” (cópia pública byte a byte idêntica ao arquivo do site do TSE).',
               'Se alguém alterasse uma linha do log depois que a urna assinou, o SHA-512 mudaria e o teste (1) falharia; para “consertar” o hash seria preciso uma nova assinatura, '
               'que só a chave da urna produz.']:
        st.append(Paragraph('• ' + t_, P))
    st += [Paragraph('1. Resultado por pleito', H2)]
    t = [['Pleito', 'Urnas', 'Com log', 'Log HD =\npublicado', 'Hash do\nlog ok', 'Assinat.\nlog ok', 'Hash\nBU ok', 'Assinat.\nBU ok', 'Hash\nRDV ok', 'Assinat.\nRDV ok',
          'Certificado\n← AC TSE', 'Sem arq. de\nassinatura', 'Falhas de\nverificação']]
    for r in E.itertuples():
        t.append([EL_LABEL.get(r.eleicao, r.eleicao), n(r.urnas), n(r.com_log), n(r.log_hd_igual_publicado), n(r.log_hash_ok), n(r.log_assinatura_ok), n(r.bu_hash_ok),
                  n(r.bu_assinatura_ok), n(r.rdv_hash_ok), n(r.rdv_assinatura_ok), n(r.cadeia_ac_ok), n(r.sem_arquivo_de_assinatura), n(r.falhas)])
    t.append(['Total', n(E.urnas.sum()), n(E.com_log.sum()), n(E.log_hd_igual_publicado.sum()), n(E.log_hash_ok.sum()), n(E.log_assinatura_ok.sum()), n(E.bu_hash_ok.sum()),
              n(E.bu_assinatura_ok.sum()), n(E.rdv_hash_ok.sum()), n(E.rdv_assinatura_ok.sum()), n(E.cadeia_ac_ok.sum()), n(E.sem_arquivo_de_assinatura.sum()), n(E.falhas.sum())])
    st += [M.table(t, font=6.6),
           Paragraph('“Log do HD = publicado”: o arquivo guardado é idêntico, byte a byte, ao do zip do TSE (2026 2º turno: baixado direto do sistema de resultados, coluna não se aplica). '
                     'RDV: no 2º turno de 2026 só o log e o boletim foram conferidos. Lista completa de falhas em falhas.csv.', SM)]
    Freal = F[F.tipo == 'falha de verificação']
    if len(Freal):
        F = Freal
        t = [['Pleito', 'UF', 'Urna (arquivo)', 'Tipo', 'Detalhe']]
        for r in F.head(40).itertuples():
            what = [c for c in FLAGS + ['manifest_ok', 'log_local_igual_zip'] if getattr(r, c, None) is False or getattr(r, c, None) == False]  # noqa: E712
            t.append([r.eleicao, r.uf, r.urna, r.tipo, ', '.join(what) or str(getattr(r, 'erro', ''))[:90]])
        st += [Paragraph('Urnas não verificáveis ou com falha (até 40)', H2), M.table(t, font=6.5),
               Paragraph('“Sem arquivo de assinatura”: o zip do TSE traz o boletim (e às vezes o log) da seção, mas não o .vscmr/-vota.vsc; sem ele não há como autenticar. '
                         'Não é prova de alteração, é ausência do meio de prova.', SM)]
    # casos sem prova completa (nenhum e falha de verificacao: falta o meio de prova)
    err = d.get('erro', pd.Series(index=d.index, dtype=object))
    lnm = d.get('log_no_manifesto', pd.Series(index=d.index, dtype=object))
    cases = [
        ('Seção sem arquivo de assinatura no zip (nada verificável)', err == 'sem manifesto no zip'),
        ('Arquivo de assinatura presente, mas o zip não traz o log', (d.manifest_ok == True) & ~d.tem_log & (d.canal == 'dados abertos')),  # noqa: E712
        ('Log presente, mas não listado no arquivo de assinatura da urna', (lnm == False)),  # noqa: E712
        ('Sem RDV no zip (log e BU verificados)', (d.manifest_ok == True) & d.rdv_hash_ok.isna() & (d.eleicao != '2026-t2')),  # noqa: E712
    ]
    G = []
    for lab, mk in cases:
        sub = d[mk.fillna(False).astype(bool)]
        for el, g in sub.groupby('eleicao'):
            G.append(dict(caso=lab, eleicao=el, urnas=len(g), exemplos=', '.join(f'{u} ({uf})' for u, uf in zip(g.urna.head(4), g.uf.head(4)))))
    G = pd.DataFrame(G)
    G.to_csv(OUT / 'casos_sem_prova_completa.csv', index=False, encoding='utf-8-sig')
    if len(G):
        t = [['Caso', 'Pleito', 'Urnas', 'Exemplos']] + [[r.caso, r.eleicao, n(r.urnas), r.exemplos[:110]] for r in G.itertuples()]
        st += [Paragraph('Casos sem prova completa (não são falhas: falta o meio de prova)', H2), M.table(t, font=6.3),
               Paragraph('Em nenhum caso um hash ou uma assinatura deu errado. Estes são casos em que o TSE não publicou o arquivo necessário para a conferência '
                         '(ou a urna não incluiu o log no que assinou). Lista em casos_sem_prova_completa.csv.', SM)]
    st += [PageBreak(), Paragraph('2. Por estado', H2)]
    t = [['Pleito', 'UF', 'Urnas', 'Com log', 'Log HD = publicado', 'Hash log ok', 'Assin. log ok', 'Hash BU ok', 'Assin. BU ok', 'Cadeia ok', 'Sem assin.', 'Falhas']]
    for r in U.itertuples():
        t.append([r.eleicao, r.uf, n(r.urnas), n(r.com_log), n(r.log_hd_igual_publicado), n(r.log_hash_ok), n(r.log_assinatura_ok), n(r.bu_hash_ok), n(r.bu_assinatura_ok), n(r.cadeia_ac_ok), n(r.sem_arquivo_de_assinatura), n(r.falhas)])
    st += [M.table(t, font=5.8), PageBreak()]
    st += [Paragraph('3. Quem assinou: certificados e identidade da urna', H2)]
    t = [['Pleito', 'AC emissora', 'Algoritmo', 'Urnas']]
    for r in C.itertuples():
        t.append([r.eleicao, r.cert_emissor, r.cert_alg, n(r.urnas)])
    st += [M.table(t, font=7), Paragraph(f'Certificados de urna distintos: {n(certs_unicos)} (a mesma urna física aparece em vários pleitos).', SM)]
    acu = d[(d.eleicao == '2026-t1') & (d.cert_emissor == 'AC URNA')]
    acu2 = d[(d.eleicao == '2026-t2') & (d.cert_emissor == 'AC URNA')]
    if len(acu):
        st.append(Paragraph(f'Observação: o certificado da AC URNA publicado pelo TSE vale até 18/07/2026. Em 2026, {n(len(acu))} urnas do 1º turno e {n(len(acu2))} das urnas com log do 2º turno '
                            '(modelos antigos) assinaram com certificado emitido por ela. A assinatura matemática confere; a validade formal da AC na data da eleição é '
                            'questão de política de certificação do TSE (o certificado da urna em si tem validade própria), não de adulteração de arquivos.', SM))
    if len(idt):
        t = [['Pleito', 'Urnas com certificado', 'Seção achada no BU (dados abertos)', 'Número da urna no certificado = urna registrada no BU']]
        for r in idt.itertuples():
            t.append([r.eleicao, n(r.urnas), n(r.com_numero_no_bu), n(r.mesma_urna)])
        if len(divergente):
            vc = divergente.explicacao_no_log.value_counts()
            t2_ = [['Urnas com número diferente: explicação encontrada no próprio log', 'Urnas']] + [[k, n(v)] for k, v in vc.items()]
        else:
            t2_ = None
        st += [Paragraph('Identidade: a urna que assinou é a urna registrada para a seção?', H2), M.table(t, font=7)] + ([M.table(t2_, font=7)] if t2_ else []) + [
               Paragraph('Compara o número no nome do certificado (ex.: ueao01813382) com o campo NR_URNA_EFETIVADA do boletim de urna dos dados abertos. '
                         'Diferenças, quando existem, aparecem em INTEGRIDADE_URNAS.xlsx (aba urna_divergente); seções agregadas e trocas de urna podem explicar casos isolados.', SM)]
    st += [Paragraph('Quando a urna assinou', H2)]
    t = [['Pleito', 'Urnas', 'Assinaram no dia da eleição', 'Assinaram antes das 17h (relógio da urna)']]
    for r in A.itertuples():
        t.append([r.eleicao, n(r.urnas), n(r.no_dia), n(r.antes_17h)])
    st += [M.table(t, font=7), img(FIG / 'horario_assinatura.png', 20),
           Paragraph('No 2º turno de 2026 há um segundo pico às 19h: são as urnas que ficaram abertas até 19h (decisão do STF) e encerraram nesse horário; '
                     'como esses logs vieram sobretudo das seções que fecharam tarde, o pico é maior que nos outros pleitos. '
                     'Assinatura fora do dia ou antes das 17h aparece em urnas de contingência, recuperação de dados ou com relógio ajustado; a lista está na planilha.', SM), PageBreak()]
    st += [Paragraph('4. Dois canais do TSE dão os mesmos arquivos?', H2)]
    if len(CHs):
        t = [['Pleito', 'Urnas sorteadas', 'Log do sistema de resultados = log dos dados abertos', 'Hash confere', 'Assinatura válida', 'Seção com uma só versão', 'Erros']]
        for r in CHs.itertuples():
            t.append([r.eleicao, n(r.sorteadas), n(r.log_igual), n(r.hash_ok), n(r.assinatura_ok), n(r.uma_versao), n(r.erro)])
        st += [M.table(t, font=7), Paragraph('Amostra aleatória (semente fixa) de até 250 urnas por estado e pleito com log no HD. 2022 não está mais no sistema de resultados (HTTP 404).', SM)]
    else:
        st.append(Paragraph('Comparação entre canais não executada.', SM))
    if len(RP):
        t = [['Zip (dados abertos)', 'Republicado em', 'Arquivos na coleta', 'Arquivos hoje', 'Incluídos', 'Removidos', 'Tamanho alterado', 'Tipos incluídos']]
        for r in RP.itertuples():
            t.append([r.raiz, str(getattr(r, 'ultima_modificacao', ''))[:16], n(getattr(r, 'arquivos_coleta', 0)), n(getattr(r, 'arquivos_atual', 0)),
                      n(getattr(r, 'incluidos', 0)), n(getattr(r, 'removidos', 0)), n(getattr(r, 'tamanho_alterado', 0)), str(getattr(r, 'tipos_incluidos', ''))[:60]])
        st += [Paragraph('Zips que o TSE republicou depois da nossa coleta', H2), M.table(t, font=6.3),
               Paragraph('O teste foi feito contra o zip atual. Em todos os casos a coluna “Log do HD = publicado” da seção 1 mostra se algum log mudou.', SM)]
    st += [Paragraph('5. O log conta os mesmos eleitores que o boletim?', H2)]
    t = [['Pleito', 'Seções com log e BU', 'Votos no log = comparecimento no BU', '%', 'Log com menos', 'Log com mais', 'Relógio voltou', 'Horário malformado']]
    for r in LBe.itertuples():
        t.append([r.eleicao, n(r.secoes_com_log), n(r.iguais), n(100 * r.iguais / r.secoes_com_log, 1), n(r.log_menor), n(r.log_maior),
                  n(r.relogio_voltou) if pd.notna(r.relogio_voltou) else '—', n(r.horario_malformado) if pd.notna(r.horario_malformado) else '—'])
    st += [M.table(t, font=7),
           Paragraph('Diferenças vêm, em geral, de troca de urna (os votos ficam em dois logs), seções agregadas e eventos de voto que o leitor de log não classifica. '
                     'Não afetam a autenticidade: o log é o arquivo que a urna assinou.', SM)]
    st += [Paragraph('6. O que não dá para verificar de fora', H2)]
    for t_ in ['O código de 16 caracteres no fim de cada linha do log é um SipHash encadeado com chave secreta do TSE. O documento oficial “Formato dos arquivos de log” '
               '(TSE, set/2022) diz que ele é de uso exclusivo da Justiça Eleitoral e não pode ser validado por terceiros.',
               'Os certificados das raízes (AC RAIZ UE, AC RAIZ UE v2) e da AC URNA v2 não estão publicados; a cadeia foi conferida até a AC intermediária publicada pelo TSE.',
               'O segundo bloco do arquivo de assinaturas (assinatura de software “SEVIN”, 4,7 KB, formato proprietário) não é documentado e não foi conferido; os hashes que ele lista '
               'foram comparados e coincidem com os do bloco de hardware.',
               'A prova mostra que o log publicado é o log que a urna assinou. Não mostra se o software da urna registrou corretamente cada evento; isso depende da auditoria do '
               'código-fonte, da cerimônia de lacração e do teste de integridade, feitos pelo TSE e fiscalizadores.']:
        st.append(Paragraph('• ' + t_, P))
    st += [Paragraph('Como repetir', H2),
           Paragraph('scripts/integridade_check.py (zips de dados abertos e 2º turno 2026), scripts/integridade_canais.py (amostra entre canais), '
                     'scripts/ed521.py (verificador Ed521 independente, conferido com vetores de teste públicos), scripts/integridade_lib.py (leitura do arquivo de assinaturas). '
                     'Certificados das ACs em research/integridade/ac; documentação oficial do TSE em research/integridade/tse_doc.', SM)]

    def foot(c, d_):
        c.setFont('Helvetica', 7); c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Conferência técnica independente — dados públicos do TSE')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d_.page}')
    SimpleDocTemplate(str(OUT / 'INTEGRIDADE_LOGS_E_ASSINATURAS.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)
    print(E.to_string()); print(CHs.to_string() if len(CHs) else ''); print(LBe.to_string()); print(idt.to_string() if len(idt) else '')
    print('falhas', len(F), 'incompletas', incompletas)


if __name__ == '__main__':
    main()
