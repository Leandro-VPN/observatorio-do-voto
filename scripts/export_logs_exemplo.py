"""Exporta o log completo de 11 urnas (texto) para leitura, com indice e o .jez original.

Escolha: 10 urnas sorteadas (semente fixa) entre as que passaram em todas as conferencias de
integridade, uma por pleito/UF variado, mais 1 urna de contingencia que recuperou a memoria de
votacao da urna original. Saida: relatorios/logs_exemplo/ e relatorios/logs_exemplo_11_urnas.zip
"""
import hashlib
import io
import re
import shutil
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from auditabr import logs  # noqa: E402

OUT = ROOT / 'relatorios' / 'logs_exemplo'
SEED = 20261027
# (eleicao, uf, filtro extra)
ESCOLHA = [('2022-t1', 'SP', None), ('2022-t2', 'RJ', None), ('2022-t2', 'BA', None),
           ('2024-t1', 'PE', None), ('2024-t2', 'RS', None), ('2026-t1', 'MG', None),
           ('2026-t1', 'PA', 'ecdsa'), ('2026-t1', 'BA', None), ('2026-t2', 'CE', None),
           ('2026-t2', 'SP', 'apos19h')]
CONTINGENCIA = ('2026-t1', 'SP', 'o03220sp7107204180073-log.jez')
NOME = [re.compile(r'^o0*(?P<pl>\d+)-(?P<mun>\d{5})(?P<zona>\d{4})(?P<sec>\d{4})'),
        re.compile(r'^o0*(?P<pl>\d+)[a-z]{2}(?P<mun>\d{5})(?P<zona>\d{4})(?P<sec>\d{4})')]


def pasta_logs(el, uf):
    r = ROOT / 'research'
    if el == '2026-t2':
        return r / 'segundo_turno_2026' / 'logs' / uf
    if uf == 'BA' and el == '2022-t2':
        return r / 'piloto-ba-2022-t2' / 'logs'
    if uf == 'BA' and el in ('2022-t1', '2026-t1'):
        return r / 'bahia-presidente-2022-2026' / el / 'logs'
    if el.startswith('2024'):
        return r / 'municipais' / uf / el / 'logs'
    return r / 'estados' / uf / el / 'logs'


def main():
    df = pd.read_parquet(ROOT / 'relatorios/integridade/integridade_todas_urnas.parquet')
    ok = df[df.log_hash_ok.eq(True) & df.log_assinatura_ok.eq(True) & df.cadeia_ok.eq(True)
            & df.bu_hash_ok.eq(True) & df.bu_assinatura_ok.eq(True)]
    sel = []
    for el, uf, extra in ESCOLHA:
        c = ok[(ok.eleicao == el) & (ok.uf == uf)]
        if extra == 'ecdsa':
            c = c[c.cert_alg != 'Ed521']
        if extra == 'apos19h':
            c = c[c.assinado_em.str[9:11].astype(int) >= 19]
        r = c.sample(1, random_state=SEED).iloc[0].to_dict()
        r['motivo'] = {'ecdsa': 'urna modelo antigo (AC URNA, ECDSA)',
                       'apos19h': 'seção que ficou aberta até as 19h no 2º turno (prorrogação)'}.get(extra, 'sorteio')
        sel.append(r)
    el, uf, nm = CONTINGENCIA
    r = df[(df.eleicao == el) & (df.uf == uf) & (df.log_nome == nm)].iloc[0].to_dict()
    r['motivo'] = 'urna de contingência que recuperou os votos da urna original'
    sel.append(r)

    for p in sorted(OUT.rglob('*'), reverse=True) if OUT.exists() else []:  # limpa sem apagar a pasta (pode estar aberta)
        p.unlink() if p.is_file() else p.rmdir()
    (OUT / 'originais_jez').mkdir(parents=True, exist_ok=True)
    idx = []
    for k, r in enumerate(sel, 1):
        src = pasta_logs(r['eleicao'], r['uf']) / r['log_nome']
        raw = src.read_bytes()
        txt = logs.read_log(src).decode('latin-1').replace('\r\n', '\n')
        m = next(p.match(r['log_nome']) for p in NOME if p.match(r['log_nome']))
        base = f"{k:02d}_{r['eleicao']}_{r['uf']}_mun{m['mun']}_zona{m['zona']}_secao{m['sec']}"
        (OUT / f'{base}.txt').write_text(txt, encoding='utf-8')
        shutil.copy2(src, OUT / 'originais_jez' / r['log_nome'])
        if raw[:2] == b'PK':  # log de outra urna arquivado no pacote (contingencia): ...ME.jez
            z = zipfile.ZipFile(io.BytesIO(raw))
            for me in [n for n in z.namelist() if n.endswith('ME.jez')]:
                orig = zipfile.ZipFile(io.BytesIO(z.read(me))).read('logd.dat').decode('latin-1').replace('\r\n', '\n')
                urna = orig.split('\t', 3)[2]
                (OUT / f'{base}_log_da_urna_original_{urna}.txt').write_text(orig, encoding='utf-8')
        linhas = txt.splitlines()
        idx.append(dict(n=k, arquivo=f'{base}.txt', eleicao=r['eleicao'], uf=r['uf'], municipio_tse=m['mun'],
                        zona=m['zona'], secao=m['sec'], por_que=r['motivo'], linhas=len(linhas),
                        votos_no_dia=sum(x.startswith(linhas[-1][:10]) and 'O voto do eleitor foi computado' in x
                                         for x in linhas),
                        primeira_linha=linhas[0][:19] if linhas else '', ultima_linha=linhas[-1][:19] if linhas else '',
                        arquivo_original=r['log_nome'], canal=r['canal'], certificado_urna=r['cert_cn'],
                        ac_emissora=r['cert_emissor'], algoritmo=r['cert_alg'], assinado_em=r['assinado_em'],
                        hash_confere=r['log_hash_ok'], assinatura_confere=r['log_assinatura_ok'],
                        cadeia_confere=r['cadeia_ok'], sha512_jez=hashlib.sha512(raw).hexdigest()))
    ix = pd.DataFrame(idx)
    ix.to_csv(OUT / 'indice.csv', index=False, encoding='utf-8-sig', sep=';')
    leia = ['LOGS COMPLETOS DE 11 URNAS', '',
            'Cada .txt é o arquivo logd.dat da urna, inteiro e sem cortes, convertido de Latin-1 para UTF-8.',
            'Colunas de cada linha (separadas por TAB): data e hora | tipo do evento | número interno da urna |',
            'aplicativo | mensagem | código de 16 caracteres (encadeamento SipHash do TSE, não verificável por terceiros).',
            'A pasta originais_jez tem o arquivo exatamente como o TSE publica (7z ou zip), para quem quiser conferir o hash.',
            'Todas as 11 tiveram o hash e a assinatura da urna conferidos (ver indice.csv e relatorios/integridade).',
            'O log começa na carga da urna, dias antes da eleição. No 2º turno, a mesma urna guarda também o 1º turno;',
            'por isso a contagem abaixo considera só os votos do dia da eleição. A urna de contingência (nº 11) não',
            'recebeu votos: os votos foram registrados na urna original; esta leu a memória de votação (MV) dela',
            'e gerou o boletim (ver as linhas "RECUPERADOR DE DADOS" e "Detectada MV em Urna de contingência").',
            'O log da urna original (02001951), com os 265 votos do dia, vem dentro do pacote oficial da contingência',
            '(arquivo 022762820410202619543001ME.jez, que a contingência marcou como "log corrompido da ME" e arquivou);',
            'ele está extraído em 11_..._log_da_urna_original_02001951.txt.', '']
    for r in idx:
        leia += [f"{r['n']:02d}. {r['eleicao']} {r['uf']} município {r['municipio_tse']} zona {r['zona']} seção {r['secao']}"
                 f" - {r['por_que']}; {r['linhas']} linhas, {r['votos_no_dia']} votos no dia da eleição,"
                 f" {r['primeira_linha']} a {r['ultima_linha']}"]
    (OUT / 'LEIA-ME.txt').write_text('\n'.join(leia) + '\n', encoding='utf-8')
    print(ix[['n', 'eleicao', 'uf', 'por_que', 'linhas', 'votos_no_dia', 'primeira_linha', 'ultima_linha']].to_string())
    empacota()


def empacota():
    zp = OUT.parent / 'logs_exemplo_11_urnas.zip'
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.rglob('*')):
            if p.is_file():
                z.write(p, Path('logs_exemplo') / p.relative_to(OUT))
    print(zp, zp.stat().st_size)


if __name__ == '__main__':
    main()
