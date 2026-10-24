"""Read-only view of the separately scoped BA2022T2 research pilot."""
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


def render():
    root = Path(__file__).resolve().parents[2] / 'research/piloto-ba-2022-t2'
    out = root / 'analysis'
    st.title('Bahia · 2022 · Segundo turno')
    st.caption('Presidente e governador • logs e boletins oficiais do TSE • análise exploratória')
    if not (out / 'summary.json').exists():
        st.info('A leitura completa dos logs está em processamento. Os resultados serão exibidos quando a consolidação terminar.')
        st.write('Plano fixado em research/PLANO_ANALISE_A_PRIORI.md. Os indicadores confirmatórios dependem das validações documentadas.')
        return
    summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
    st.warning('Horários são os registrados nas urnas. Os grupos abaixo são exploratórios: não equivalem aos indicadores A/B/C/D confirmados nem demonstram irregularidade.')
    office = st.selectbox('Disputa', ['Presidente', 'Governador'])
    other = 'PL' if office == 'Presidente' else 'UNIÃO'
    totals = summary['log_totals']
    cols = st.columns(3)
    for col, title, value in zip(cols,
        ['Logs processados', 'Votos após 17h registradas', 'Após 17h com sequência manual'],
        [totals['files'], totals['after_17_recorded'], totals['after_17_manual_sequence']]):
        col.metric(title, f'{value:,}'.replace(',', '.'))
    st.caption('Contagens acima incluem todos os logs, inclusive os que não puderam ser vinculados com segurança ao BU. Eventos de conclusão abrangem a sessão de votação, não votos de um cargo específico.')
    high = next(x for x in summary['raw_high_late'] if x['office'] == office)
    st.subheader('Seções com proporção elevada de votos tardios registrados')
    st.write(f"Critério: acima do P99 ({100*summary['raw_late_p99']:.2f}%) e pelo menos 20 votos após 17h; identificação inequívoca, contagem conciliada com presidente e sem reversão temporal detectada. Exclusões especiais e calibração dos relógios ainda pendentes.")
    st.write(f"{high['sections']} seções, {high['zones']} zonas e {high['municipalities']} municípios. Nessas seções, {high['after_17_recorded']:,} votos após 17h, dos quais {high['after_17_manual_sequence']:,} com sequência manual completa.".replace(',', '.'))
    st.write(f"Nas seções inteiras desse grupo: PT {high['pt_share_pct']:.2f}% dos válidos; {other} {100-high['pt_share_pct']:.2f}%. Diferença PT − {other}: {high['pt_minus_other_pp']:.2f} p.p.")
    st.caption('Não é possível saber em quem votaram os eleitores habilitados manualmente ou após 17h. Sequência manual não é excesso manual ajustado (C).')
    for case in summary.get('high_late_sections', []):
        if case['office'] == office:
            st.write(f"**{case['municipality_name']} · zona {case['zone']} · seção {case['section']}** — último voto às {case['last_vote']}; {case['after_17_recorded']} votos tardios e {case['after_17_manual_sequence']} tardios com sequência manual.")
            st.caption(f"Mediana dos intervalos tardios: {case['late_interval_median_seconds']} segundos. Contagem manual do dia: {case['manual_sequence_votes']}; campo correspondente do BU: {case['biometric_nh_bu']}.")
    contrast = next(x for x in summary['unadjusted_exploratory_contrast'] if x['office'] == office)
    if contrast['ci95_zone_bootstrap'] is not None:
        low, high_ci = contrast['ci95_zone_bootstrap']
        st.write(f"Comparação exploratória sem controles: diferença na participação do PT de {contrast['effect_pp']:.2f} p.p. entre as seções com horário elevado e as demais elegíveis; IC95% por zona [{low:.2f}; {high_ci:.2f}] p.p.")
        st.caption('Proporções por seção ponderadas por aptos; 2.000 reamostragens de zonas. Não é pareamento nem teste ajustado da hipótese histórica. Difere da margem agregada entre candidatos mostrada acima.')
    else:
        st.info(f"Intervalo de confiança indisponível: {contrast['valid_replicates']} de 2.000 réplicas válidas, abaixo do mínimo de 95%. O grupo de horário elevado está em apenas uma zona; não há teste confirmatório de associação partidária.")
    geo = st.radio('Detalhamento', ['Municípios', 'Zonas', 'Município e zona', 'Seções'], horizontal=True)
    filenames = {'Municípios': 'municipalities.csv', 'Zonas': 'zones.csv',
                 'Município e zona': 'municipality_zones.csv', 'Seções': 'sections.csv'}
    frame = pd.read_csv(out / filenames[geo], sep=';', low_memory=False)
    frame = frame[frame.office == office]
    labels = {
        'municipality':'Município TSE','municipality_name':'Município','zone':'Zona','section':'Seção',
        'office':'Cargo','sections':'Seções','eligible':'Aptos','attendance':'Comparecimento',
        'turnout':'Taxa de comparecimento','valid_votes':'Votos válidos','pt_votes':'Votos PT',
        'other_votes':f'Votos {other}','raw_high_late':'Horário elevado (exploratório)',
        'raw_high_turnout':'Comparecimento elevado (exploratório)',
        'after_17_recorded':'Votos após 17h registradas','manual_sequence_votes':'Sequência manual completa',
        'after_17_manual_sequence':'Após 17h com sequência manual',
        'raw_high_late_sections':'Seções com horário elevado','raw_high_turnout_sections':'Seções com comparecimento elevado',
        'high_late_sections_with_manual':'Seções de horário elevado com evento tardio manual',
        'high_late_recorded_votes':'Votos tardios no grupo elevado','high_late_manual_votes':'Tardios manuais no grupo elevado',
        'high_late_pt_pct':'PT no grupo elevado (%)','high_late_pt_margin_pp':f'Diferença PT−{other} (p.p.)',
        'high_late_valid_votes':'Votos válidos no grupo elevado','high_late_pt_votes':'Votos PT no grupo elevado',
        'high_late_other_votes':f'Votos {other} no grupo elevado',
        'raw_operational_eligible_sections':'Seções com cobertura operacional elegível',
        'identity_status':'Identidade do log','clock_reversals':'Reversões de relógio',
        'contingency_documented':'Contingência documentada',
    }
    if geo == 'Seções':
        names = sorted(frame.municipality_name.unique())
        highlighted = next((x['municipality_name'] for x in summary.get('high_late_sections', []) if x['office']==office), names[0])
        city = st.selectbox('Município', names, index=names.index(highlighted))
        frame = frame[frame.municipality_name == city]
        frame = frame.sort_values('after_17_manual_sequence', ascending=False)
        columns = ['municipality_name','zone','section','eligible','attendance','turnout',
                   'raw_high_turnout','raw_high_late','after_17_recorded','manual_sequence_votes',
                   'after_17_manual_sequence','valid_votes','pt_votes','other_votes',
                   'identity_status','clock_reversals','contingency_documented']
        st.dataframe(frame[columns].rename(columns=labels), hide_index=True, width='stretch')
    else:
        if st.checkbox('Mostrar apenas territórios com seções de votação tardia elevada', value=True):
            frame = frame[frame.raw_high_late_sections > 0]
        st.dataframe(frame.rename(columns=labels), hide_index=True, width='stretch')
        if geo == 'Municípios' and not frame.empty:
            chart = px.bar(frame.head(15), x='municipality_name', y='high_late_manual_votes',
                labels={'municipality_name': 'Município', 'high_late_manual_votes': 'Votos tardios com sequência manual'},
                title='Volume nas seções com votação tardia elevada · BA/2022/T2')
            st.plotly_chart(chart, width='stretch')
    st.download_button('Baixar tabela exibida (CSV)', frame.to_csv(index=False, sep=';').encode('utf-8-sig'),
                       file_name=f'ba2022t2-{filenames[geo]}', mime='text/csv')
    with st.expander('Conferência independente: sequência manual no log × campo do BU'):
        st.dataframe(pd.DataFrame(summary['manual_bu_validation']), hide_index=True)
        st.caption('QT_ELEITORES_BIOMETRIA_NH: eleitores com biometria que não foram habilitados por ela, segundo o dicionário oficial. Diferenças permanecem registradas.')
    with st.expander('Comparecimento elevado: cálculo exploratório antes das exclusões'):
        coverage = next(x for x in summary['coverage'] if x['office'] == office)
        st.write(f"{coverage['raw_high_turnout']} unidades atendem à fórmula bruta: mais de 3 MAD acima da mediana estadual e ao menos 10 pontos percentuais acima da mediana municipal. Seções especiais, trânsito e agregações ainda precisam ser verificados; não é a classificação A confirmada.")
        st.dataframe(pd.DataFrame(summary['turnout_reference']), hide_index=True)
    with st.expander('Método, lacunas e arquivos para reprodução'):
        st.write('A hipótese histórica de associação partidária ainda não foi testada. Faltam exclusões, controles completos e vínculos históricos; nenhum p-valor ajustado ou efeito causal é apresentado.')
        st.json(summary['coverage'])
        st.caption(f"Plano SHA-256: {summary['plan_sha256']}")
        st.download_button('Plano de análise', (root.parent/'PLANO_ANALISE_A_PRIORI.md').read_bytes(), 'PLANO_ANALISE_A_PRIORI.md')
        st.download_button('Manifesto e resultados', (out/'summary.json').read_bytes(), 'summary.json')
