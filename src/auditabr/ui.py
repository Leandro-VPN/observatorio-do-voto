"""Read-only research UI over immutable snapshots; writes only explicit report exports."""
from __future__ import annotations

import json
from typing import Any, Literal, cast

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from auditabr.analytics import ALTERNATIVES, Thresholds
from auditabr.catalog import Catalog, family
from auditabr.domain import YEARS, offices, temporal_status
from auditabr.queries import Group, Scope, analysis, geography, historical, operational, turnout, votes, where
from auditabr.reporting import create_report
from auditabr.storage import current_manifest, reader, rows
from auditabr.utils import digest, read_json, storage_root, utcnow, write_json

st.set_page_config(page_title="AUDITA-BR · Observatório eleitoral", page_icon="◉", layout="wide")
root = storage_root()
st.markdown("""<style>
.block-container {padding-top:4rem; max-width:1500px}
[data-testid="stMetric"] {background:white;border:1px solid #dbe5e7;padding:18px;border-radius:10px}
[data-testid="stMetricValue"] {font-size:clamp(1.1rem,2vw,1.5rem);line-height:1.3}
.eyebrow {font-size:12px;letter-spacing:3px;color:#087e8b;font-weight:700}
.hero {font-size:38px;line-height:1.12;font-weight:750;letter-spacing:-1.4px;margin:8px 0 12px}
.sub {color:#59747c;margin-bottom:24px;font-size:16px}
</style>""", unsafe_allow_html=True)

PAGES = ["Visão geral", "Piloto BA/2022/T2", "Geografia", "Resultados", "Abstenção", "Horários", "Habilitação",
         "Histórico", "Cruzamentos", "Casos", "Fontes e qualidade", "Metodologia"]


def fmt(value, percent=False):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "Indisponível"
    return (f"{value*100:.2f}%" if percent else f"{value:,.0f}").replace(",", "_").replace(".", ",").replace("_", ".")


def table(data, **kwargs):
    labels = {"uf":"UF", "municipality":"Município TSE", "municipality_name":"Município",
              "zone":"Zona", "place":"Local", "place_name":"Nome do local", "section":"Seção",
              "sections":"Seções", "eligible":"Aptos", "present":"Comparecimento", "absent":"Abstenções",
              "abstention_rate":"Taxa de abstenção", "mean_section_rate":"Média das taxas das seções",
              "candidate_name":"Candidatura", "candidate_number":"Número", "votes":"Votos",
              "nominal_share":"Participação nos votos nominais", "office":"Cargo", "year":"Eleição",
              "round":"Turno", "vote_events":"Eventos de conclusão", "unknown":"Indeterminados"}
    st.dataframe(pd.DataFrame(data).rename(columns=labels), hide_index=True, width="stretch", **kwargs)


def chart(fig):
    fig.update_layout(template="plotly_white", font=dict(family="Arial", color="#143b43"),
                      paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=20,r=20,t=30,b=20),
                      colorway=["#087e8b", "#e0a458", "#244d65", "#7aa095"])
    for axis in ("xaxis", "yaxis"):
        title = (getattr(fig.layout, axis).title.text or "").lower()
        if "abstenção" in title:
            getattr(fig.layout, axis).update(tickformat=".0%")
    st.plotly_chart(fig, width="stretch")


def no_data(message="Não há dados publicados deste recorte nesta instalação."):
    st.info(message)
    st.caption("Fontes e qualidade apresenta o catálogo, as partições carregadas e as limitações.")


with st.sidebar:
    st.markdown("## ◉ AUDITA-BR")
    st.caption("OBSERVATÓRIO ELEITORAL")
    page = st.radio("Explorar", PAGES, index=1 if st.query_params.get('study') == 'pilot' else 0, label_visibility="collapsed")

if page == "Piloto BA/2022/T2":
    from auditabr.pilot_ui import render
    render()
    st.stop()

with st.sidebar:
    st.divider()
    year = st.selectbox("Eleição", list(reversed(YEARS)), index=2)
    office = st.selectbox("Cargo", offices(year))
    round = st.selectbox("Turno", [1,2], format_func=lambda n:f"{n}º turno")
    snapshots = sorted([m for p in (root / "manifests" / "snapshots").glob("*.json")
                        if (m := read_json(p)).get("scope_offices") == ["PRESIDENTE", "PREFEITO"]
                        and m.get("status")=="PUBLISHED"],
                       key=lambda m:m["published_at"], reverse=True)
    selected_snapshot = st.selectbox("Versão dos dados", [None]+[m["snapshot_id"] for m in snapshots],
                                    format_func=lambda s: "Mais recente" if s is None else s[:12])
    pinned = current_manifest(root, selected_snapshot)
    filters: dict[str, Any] = {"year": year, "round": round, "snapshot": pinned["snapshot_id"] if pinned else None}
    for key, label in [("uf", "UF"), ("municipality", "Município TSE"), ("zone", "Zona"), ("place", "Local"), ("section", "Seção")]:
        if key != "uf" and not filters.get({"municipality":"uf","zone":"municipality","place":"zone","section":"zone"}[key]):
            continue
        options = geography(root, Scope(**filters), key)["data"]
        values = [None] + [r["code"] for r in options]
        value = st.selectbox(label, values, key=f"{year}-{round}-{selected_snapshot}-{key}-"+str({k:v for k,v in filters.items() if k!='snapshot'}),
                             format_func=lambda x: "Todos" if x is None else x)
        if value is not None:
            filters[key] = value
    st.caption("Fonte: Tribunal Superior Eleitoral. Esta ferramenta não é um produto do TSE.")

scope = Scope(**filters, office=cast(Literal["PRESIDENTE","PREFEITO"],office))
manifest = current_manifest(root, scope.snapshot)
overview = turnout(root, scope, "uf")
meta = overview["meta"]
coverage = meta["source_coverage"]

st.markdown('<div class="eyebrow">DADOS PÚBLICOS · MÉTODO ABERTO · EVIDÊNCIA RASTREÁVEL</div>', unsafe_allow_html=True)
st.markdown(f'<div class="hero">{page}</div>', unsafe_allow_html=True)
st.markdown('<div class="sub">Das contagens à compreensão. Explore os dados e conheça os limites de cada leitura.</div>', unsafe_allow_html=True)
if manifest and manifest["mode"] == "demo":
    st.error("DEMONSTRAÇÃO — dados sintéticos. Estes números não representam uma eleição real.")
if temporal_status(year, round) == "FUTURE":
    st.warning("FUTURE · Este turno ainda não ocorreu na data atual. Não existem resultados carregáveis para ele.")
st.caption(f"{year} · {round}º turno · {scope.uf or 'Norte e Nordeste'} · "
           f"{coverage['sections_observed']:,} seções de apuração carregadas · "
           f"{coverage['operational_sections']:,} seções com logs lidos · Universo esperado: não validado".replace(",", "."))
st.caption(f"Snapshot: {manifest['snapshot_id'] if manifest else 'nenhum publicado'} · "
           f"Cobertura {meta['availability_status']} · Extração: {manifest['published_at'][:19] if manifest else 'não disponível'}")
if coverage["sections_observed"]:
    st.info("Cobertura parcial: os totais representam somente as partições carregadas. Logs lidos podem ter relógio ou taxonomia pendentes de validação.")
if coverage.get("excluded_sections_in_uf_scope"):
    st.warning(f"{coverage['excluded_sections_in_uf_scope']} registros de comparecimento inconsistentes foram excluídos dos totais deste ano/turno na UF selecionada (ou no conjunto das UFs). Os registros originais estão preservados para revisão.")

if page in ("Visão geral", "Geografia"):
    data = overview["data"]
    n = sum(r["eligible"] for r in data) if data else None
    p = sum(r["present"] for r in data) if data else None
    a = sum(r["absent"] for r in data) if data else None
    for col, label, value, pct in zip(st.columns(4), ["Eleitores aptos", "Comparecimento", "Abstenções", "Taxa de abstenção"],
                                     [n, p, a, a/n if n else None], [False,False,False,True], strict=True):
        col.metric(label, fmt(value, pct))
    st.caption("Taxa = soma das abstenções ÷ soma dos aptos. Comparecimento é contado uma única vez por seção.")
    group = st.selectbox("Agrupar por", ["uf", "municipality", "zone", "place", "section"],
                         index=1 if scope.uf else 0,
                         format_func=lambda s:{"uf":"UF","municipality":"Município","zone":"Zona","place":"Local","section":"Seção"}[s])
    result = turnout(root, scope, cast(Group,group), 1000)
    if result["data"]:
        df = pd.DataFrame(result["data"])
        label = "municipality_name" if group == "municipality" else group
        col1, col2 = st.columns([3,2])
        with col1:
            st.subheader("Abstenção no território")
            chart(px.bar(df.head(40), x=label, y="abstention_rate", labels={label:"", "abstention_rate":"Taxa de abstenção"}))
            st.caption("Gráfico: primeiros 40 grupos. A tabela mostra até 1.000; exportação inclui todos.")
        with col2:
            st.subheader("O que estes dados permitem")
            st.write("Compare taxas, tamanhos e fontes. Uma diferença pode refletir perfil do eleitorado, condições de acesso, alterações cadastrais ou cobertura incompleta.")
            st.write("Use a navegação lateral para chegar à seção. O código do município é do TSE; ele não é o código IBGE.")
        table(result["data"])
    else:
        no_data()

elif page == "Resultados":
    st.subheader(f"{office.title()} · votos publicados")
    group = "municipality" if office == "PREFEITO" else "uf"
    result = votes(root, scope, cast(Group,group), 1000)
    if result["data"]:
        df = pd.DataFrame(result["data"])
        nominal = df[df.vote_class == "NOMINAL"].copy()
        chart(px.bar(nominal.head(25), x="candidate_name", y="votes", color=group,
                     labels={"candidate_name":"Candidatura", "votes":"Votos nominais"}))
        st.caption("Percentual nominal = votos da candidatura / soma nominal no grupo. Não representa percentual de eleitores. Situação jurídica ausente não é inferida.")
        table(result["data"])
    else:
        no_data("Não há votação publicada para o cargo e recorte selecionados nesta instalação.")

elif page in ("Abstenção", "Cruzamentos", "Casos"):
    with st.expander("Parâmetros exploratórios", expanded=False):
        a,b,c = st.columns(3)
        min_n = a.number_input("Mínimo de aptos", min_value=1, value=50)
        min_peers = b.number_input("Mínimo de seções comparadoras", min_value=2, value=5)
        threshold = c.number_input("Limiar de |z|", min_value=0.5, value=3.0, step=0.5)
    result = analysis(root, scope, Thresholds(min_n,min_peers,threshold),
                      limit=max(1, coverage["sections_observed"]))
    if result["data"]:
        df = pd.DataFrame(result["data"])
        st.caption("Método exploratório: comparador municipal, com recuo à UF, sempre excluindo a própria seção. Sobredispersão por momentos. Sem p-value ou probabilidade de irregularidade.")
        if page == "Abstenção":
            left,right = st.columns(2)
            with left:
                chart(px.histogram(df, x="abstention_rate", nbins=40, labels={"abstention_rate":"Taxa da seção"}))
            with right:
                plotted = df.sample(n=8000, random_state=0) if len(df) > 8000 else df
                fig = px.scatter(plotted, x="eligible", y="abstention_rate", color="status", opacity=.5,
                                 labels={"eligible":"Aptos", "abstention_rate":"Abstenção"})
                # Bounds differ per comparator; show them as points instead of implying one universal curve.
                fig.add_trace(go.Scatter(x=plotted.eligible, y=plotted.lower_band, mode="markers", marker=dict(size=2,color="#7aa095"), name="Limite inferior exploratório"))
                fig.add_trace(go.Scatter(x=plotted.eligible, y=plotted.upper_band, mode="markers", marker=dict(size=2,color="#e0a458"), name="Limite superior exploratório"))
                chart(fig)
                if len(df) > len(plotted):
                    st.caption("Dispersão: amostra aleatória reprodutível de 8.000 seções. Histograma e cálculo usam todas as seções do recorte.")
            st.caption(f"Análise: {len(df):,} seções. Tabela limitada às primeiras 10.000; a API oferece paginação.")
            table(df.head(10000))
        elif page == "Cruzamentos":
            ops = operational(root, scope, limit=10000)["data"]
            if not ops:
                no_data("Há abstenção; faltam logs validados para cruzar métricas operacionais.")
            else:
                joined = df.merge(pd.DataFrame(ops), on="section_id", suffixes=("","_log"))
                st.warning("Associação entre agregados não identifica escolhas individuais. Não é calculado score combinado.")
                table(joined)
        else:
            selected = df[df.signal.notna()]
            st.subheader(f"{len(selected)} sinais para revisão documental")
            table(selected)
            st.write("Explicações alternativas: " + "; ".join(ALTERNATIVES) + ".")
            if not selected.empty and manifest:
                sid = st.selectbox("Ficha da seção", selected.section_id.tolist())
                record = selected[selected.section_id == sid].iloc[0].to_dict()
                st.json(record)
                review = st.selectbox("Estado de revisão", ["UNREVIEWED","EXPLAINED","UNRESOLVED","DATA_ERROR","REQUIRES_OFFICIAL_CLARIFICATION"])
                note = st.text_area("Anotações documentais")
                if st.button("Salvar investigação reproduzível"):
                    case_id = digest([manifest["snapshot_id"], sid])[:24]
                    write_json(root / "reports" / "investigations" / f"{case_id}.json", {"snapshot_id":manifest["snapshot_id"],
                        "section_id":sid,"scope":scope.model_dump(),"thresholds":vars(Thresholds(min_n,min_peers,threshold)),
                        "review_status":review,"note":note,"saved_at":utcnow(),"alternative_explanations":ALTERNATIVES})
                    st.success("Investigação salva com snapshot e parâmetros.")
    else:
        no_data()

elif page in ("Horários", "Habilitação"):
    result = operational(root, scope, "times" if page == "Horários" else "habilitation", 1000)
    if not result["data"]:
        no_data("Não há logs lidos e vinculados a este recorte. Métricas operacionais permanecem indisponíveis.")
    else:
        data = result["data"]
        st.warning("Amostras operacionais: verifique relógio, taxonomia e cobertura. Valores nulos significam validação pendente.")
        if page == "Horários":
            hourly: list[dict] = []
            for item in data:
                hourly.extend({"section":item["section_id"],"hour":h,"events":n} for h,n in json.loads(item["hourly"]).items())
            if hourly:
                chart(px.bar(pd.DataFrame(hourly), x="hour", y="events", color="section", labels={"hour":"Hora civil registrada (sem correção de relógio)","events":"Eventos de conclusão"}))
            st.caption("Último voto, encerramento da votação, emissão de BU e transmissão são eventos diferentes. Horário tardio pode ser compatível com fila.")
            table([{k:r[k] for k in ("section_id","vote_events","first_vote","last_vote","closure","bu","after_cutoff","clock_quality","timezone")} for r in data])
        else:
            st.caption("Procedimento manual não equivale a assinatura no caderno e não determina voto. Solicitação sem aprovação não é manual confirmado.")
            table([{k:r[k] for k in ("section_id","vote_events","biometric","manual","no_enrollment","biographic","unknown","conflict","classification_coverage","taxonomy_status")} for r in data])

elif page == "Histórico":
    years = st.multiselect("Pleitos a comparar", YEARS, default=[2012,2016,2020,2024] if year%4==0 else [2014,2018,2022,2026])
    result = historical(root, scope, years)
    st.caption("Comparação de abstenção por município/UF. Não pressupõe permanência da composição do eleitorado ou do local de votação.")
    if result["meta"]["availability_status"] == "NOT_COMPARABLE":
        no_data("Sem vínculo histórico validado para esta seção/local. Remova os filtros de zona, local e seção para comparar o território.")
    elif result["data"]:
        df = pd.DataFrame(result["data"])
        chart(px.line(df, x="year", y="abstention_rate", markers=True, labels={"year":"Eleição", "abstention_rate":"Abstenção ponderada"}))
        table(df)

elif page == "Fontes e qualidade":
    st.subheader("Partições publicadas")
    if manifest:
        table(manifest["partitions"])
    st.subheader("Catálogo oficial")
    resources = Catalog(root).resources(year)
    kind = st.selectbox("Família", ["Todas","turnout","votes","logs","candidates","places","bu","other"])
    table([{k:r.get(k) for k in ("id","name","url","dataset_id","license","retrieved_at")} for r in resources if kind=="Todas" or family(r)==kind])
    st.caption("Catalogado não significa baixado. Os hashes abaixo pertencem somente aos arquivos efetivamente adquiridos.")
    if manifest:
        table([{k:r.get(k) for k in ("resource_id","sha256","bytes","acquisition","member","source_url")} for r in manifest["sources"]])
    sql,params=where(scope,"s")
    with reader(root,scope.snapshot) as db:
        issues=rows(db,"SELECT * FROM quality_issue WHERE section_id LIKE ? LIMIT 1000",
                    [f"BR-{year}-%-T{round}:{scope.uf or '%'}:{scope.municipality or '%'}:{scope.zone or '%'}:{scope.section or '%'}"])
    st.subheader("Divergências e avisos")
    table(issues)
    observations = [read_json(p) for p in (root / "coverage").glob("*.json")]
    observations = [o for o in observations if o["year"] == year and o["round"] == round
                    and (scope.uf is None or o["uf"] == scope.uf)]
    if observations:
        st.subheader("Últimas tentativas de coleta")
        st.caption("Registro operacional atual, independente da versão dos dados selecionada.")
        table(observations)

else:
    st.subheader("Cada número precisa de origem e denominador")
    st.write("O AUDITA-BR usa arquivos públicos do TSE. O catálogo CKAN identifica as fontes; os bytes adquiridos recebem SHA-256 e as transformações geram versões imutáveis. Hash local verifica integridade, não substitui assinatura digital oficial.")
    st.latex(r"p_{S}=\frac{\sum_{i\in S}ausentes_i}{\sum_{i\in S}aptos_i}")
    st.write("Comparecimento é um fato por seção e turno. Votos são fatos por cargo e candidatura. As duas tabelas não são somadas em um join que multiplique eleitores.")
    st.latex(r"z_i=\frac{p_i-p_{-i}}{\sqrt{p_{-i}(1-p_{-i})/n_i+\tau^2_{-i}}}")
    st.write("O score é exploratório. A heterogeneidade é estimada entre pares, excluindo a própria seção. Os limites do funil não são intervalos preditivos calibrados. A correção FDR só se aplica a p-values válidos de um modelo validado, não a estes scores.")
    st.write("Faltas de fonte, relógio não validado e habilitação desconhecida permanecem explícitas. Nenhum evento é associado a candidato ou identidade. Mesmo número de seção em anos diferentes não estabelece vínculo histórico.")
    st.info("Uma diferença estatística pode refletir composição do eleitorado, infraestrutura, filas, erro de registro ou cobertura incompleta. Requer verificação independente.")
    st.link_button("Catálogo do TSE", "https://dadosabertos.tse.jus.br/")

st.divider()
with st.expander("Exportar este recorte com fontes e manifesto"):
    st.write("Exportação de apuração e abstenção. Inclui CSV, JSON, Parquet, Markdown e HTML, com snapshot fixo.")
    if st.button("Gerar relatório", disabled=manifest is None):
        report = create_report(root, scope, "section" if scope.section else "municipality")
        st.session_state["report_id"] = report["report_id"]
    report_id = st.session_state.get("report_id")
    if report_id:
        folder = root / "reports" / report_id
        st.caption(f"Relatório salvo: {report_id}. Os filtros constam do manifesto; nova seleção requer gerar novo relatório.")
        for filename in ("data.csv","data.json","data.parquet","report.md","report.html","manifest.json"):
            path = folder / filename
            if path.exists():
                st.download_button(filename, path.read_bytes(), file_name=filename, key=filename)
