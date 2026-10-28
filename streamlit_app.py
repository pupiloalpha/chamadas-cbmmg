# streamlit_app.py
# -------------------------------------------------------------
# Dashboard CBMMG - Chamadas Ativas (COBOM-BH)
# Fonte: API CAD (https://apicadbm.bombeiros.mg.gov.br)
#        naturezas.json (catálogo DIAO / ITO 25)  → via API
#        unidade.csv (cadastro de unidades)        → via API
# -------------------------------------------------------------

import json
import os
import re
import time
from pathlib import Path

import folium
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_autorefresh import st_autorefresh
from streamlit_folium import st_folium

# -------------------------------------------------------------
# Configuração da página
# -------------------------------------------------------------
st.set_page_config(
    page_title="CBMMG | Chamadas Ativas",
    page_icon="🚒",
    layout="wide",
)

# ---- Autorefresh a cada 10 minutos ----
st_autorefresh(interval=10 * 60 * 1000, key="data_refresh")

# ---- Detecção do tema ativo (light / dark) ----
try:
    TEMA_BASE = (st.get_option("theme.base") or "light").lower()
except Exception:
    TEMA_BASE = "light"

TEMA_ESCURO = (TEMA_BASE == "dark")

# -------------------------------------------------------------
# Estilos customizados (cabeçalho, cards, legenda)
# -------------------------------------------------------------
st.markdown("""
    <style>
    /* ---- Cabeçalho principal ---- */
    .cbmmg-header {
        background: linear-gradient(135deg, #B71C1C 0%, #7F0000 100%);
        padding: 26px 22px;
        border-radius: 14px;
        text-align: center;
        margin-bottom: 6px;
        box-shadow: 0 6px 18px rgba(0,0,0,0.20);
    }
    .cbmmg-header h1 {
        color: #FFFFFF;
        font-size: 26px;
        font-weight: 800;
        letter-spacing: 1.6px;
        margin: 0;
        text-transform: uppercase;
        line-height: 1.35;
    }
    .cbmmg-subtitle {
        text-align: center;
        color: var(--text-color, #555);
        opacity: 0.85;
        font-size: 15.5px;
        font-style: italic;
        margin: 12px 0 26px 0;
    }
    /* ---- Cards de KPI ---- */
    .metric-card {
        border-radius: 14px;
        padding: 20px 16px;
        text-align: center;
        color: #FFFFFF;
        box-shadow: 0 4px 12px rgba(0,0,0,0.14);
        min-height: 122px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        transition: transform 0.15s ease;
    }
    .metric-card:hover { transform: translateY(-3px); }
    .metric-card .valor {
        font-size: 38px;
        font-weight: 800;
        line-height: 1;
        letter-spacing: 0.5px;
    }
    .metric-card .rotulo {
        font-size: 12.5px;
        text-transform: uppercase;
        letter-spacing: 0.9px;
        margin-top: 12px;
        opacity: 0.96;
        font-weight: 700;
    }
    /* ---- Legenda do mapa (theme-aware) ---- */
    .legenda-titulo {
        text-align: center;
        font-size: 14px;
        font-weight: 700;
        color: var(--text-color, #333);
        text-transform: uppercase;
        letter-spacing: 1px;
        margin: 18px 0 6px 0;
    }
    .legenda-container {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        justify-content: center;
        padding: 14px 12px;
        background: var(--secondary-background-color, #FAFAFA);
        border-radius: 12px;
        border: 1px solid rgba(128,128,128,0.25);
        margin-bottom: 10px;
    }
    .legenda-item {
        display: flex;
        align-items: center;
        gap: 8px;
        background: var(--background-color, #FFFFFF);
        padding: 6px 14px;
        border-radius: 20px;
        border: 1px solid rgba(128,128,128,0.30);
        font-size: 12.5px;
        color: var(--text-color, #333);
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .legenda-swatch {
        display: inline-block;
        width: 14px;
        height: 14px;
        border-radius: 50%;
        border: 1px solid rgba(128,128,128,0.65);
        flex-shrink: 0;
    }
    </style>
""", unsafe_allow_html=True)


# -------------------------------------------------------------
# Dicionários de tradução de códigos
# -------------------------------------------------------------
ORIGEM_CHAMADA = {
    "L": "Ligação (Telefone)",
    "I": "Integração",
    "B": "Bombeiro / Interno",
    "A": "Automático",
}

SITUACAO_CHAMADA = {
    "E": "Em andamento",
    "A": "Aguardando / Em aberto",
}

SITUACAO_ATENDIMENTO = {
    "AO": "Atribuída ao Órgão",
    "DP": "Despachada",
    "AC": "A Caminho",
    "NL": "No Local",
    "EC": "Em Controle",
    "ED": "Em Direção",
    "LI": "Local intermediário",
    "ER": "Em Retorno",
    "EN": "Encerrada",
    "TR": "Terminada",
    "SU": "Suspensa",
    "CL": "Classificada",
}

TIPO_SERVICO = {
    "B": "Bombeiro",
    "P": "Polícia (apoio)",
}

# -------------------------------------------------------------
# Caminhos e configuração da API
# -------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

# Token: lê de st.secrets ou variável de ambiente
try:
    TOKEN = st.secrets["CBM_API_TOKEN"]
except (KeyError, FileNotFoundError):
    TOKEN = os.environ.get("CBM_API_TOKEN")

if not TOKEN:
    st.error(
        "❌ Token da API não configurado. "
        "Defina `CBM_API_TOKEN` em `.streamlit/secrets.toml` ou como variável de ambiente."
    )
    st.stop()

BASE_URL = "https://apicadbm.bombeiros.mg.gov.br"

# Intervalos (segundos)
INTERVALO_MINIMO_ENTRE_CHAMADAS = 5
INTERVALO_OPERACAO = 30  # não usado diretamente, pois o cache cuida disso
TTL_DADOS_OPERACIONAIS = 600  # 10 minutos
TTL_CATALOGOS = 86400  # 24 horas (auxiliares)

# Sessão HTTP com header de autenticação
_sessao = requests.Session()
_sessao.headers["Authorization"] = f"Bearer {TOKEN}"
_ultima_chamada = 0.0


# -------------------------------------------------------------
# Funções de API
# -------------------------------------------------------------
class TokenInvalido(Exception):
    pass


class ConjuntoAusente(Exception):
    pass


def _chamar_api(rota: str) -> dict:
    """Faz uma chamada à API com timeout maior e retry com backoff."""
    global _ultima_chamada

    # Aumentamos o timeout para 60s para redes mais lentas
    TIMEOUT_SEGUNDOS = 60 
    
    for tentativa in range(4):  # Aumentamos para 4 tentativas
        espera = INTERVALO_MINIMO_ENTRE_CHAMADAS - (time.monotonic() - _ultima_chamada)
        if espera > 0:
            time.sleep(espera)

        _ultima_chamada = time.monotonic()
        
        # Adicionamos um backoff exponencial para ser mais paciente
        if tentativa > 0:
            time.sleep(2 ** tentativa) 

        try:
            resp = _sessao.get(BASE_URL + rota, timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.ConnectTimeout:
            # Se for a última tentativa, levanta o erro para o app tratar
            if tentativa == 3:
                raise RuntimeError(
                    f"Não foi possível conectar a {BASE_URL}. "
                    "Verifique se a API está acessível a partir do Streamlit Cloud."
                )
            continue # Tenta novamente
        except requests.RequestException as exc:
            if tentativa == 3:
                raise RuntimeError(f"Falha de rede persistente em {rota}: {exc}")
            continue

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 401:
            raise TokenInvalido("Credencial inválida. Verifique o token da API.")
        if resp.status_code == 404:
            raise ConjuntoAusente(f"Conjunto {rota} ainda não foi gravado na API.")
        if resp.status_code == 429:
            retry = float(resp.headers.get("Retry-After", 30))
            time.sleep(max(retry, INTERVALO_MINIMO_ENTRE_CHAMADAS))
            continue
        if resp.status_code == 503:
            time.sleep(120)
            continue
        resp.raise_for_status()

    raise RuntimeError(f"{rota}: sem resposta válida após tentativas espaçadas.")


@st.cache_data(ttl=TTL_DADOS_OPERACIONAIS, show_spinner="Carregando chamadas ativas da API…")
def buscar_chamadas_api() -> dict:
    """Busca o payload de /ativos/chamadas (com cache de 10 min)."""
    return _chamar_api("/ativos/chamadas")


@st.cache_data(ttl=TTL_CATALOGOS, show_spinner="Carregando naturezas…")
def buscar_naturezas_api() -> dict:
    """Busca o catálogo de naturezas (cache de 24 h)."""
    return _chamar_api("/dados-auxiliares/naturezas")


@st.cache_data(ttl=TTL_CATALOGOS, show_spinner="Carregando unidades…")
def buscar_unidades_api() -> dict:
    """Busca o cadastro de unidades (cache de 24 h)."""
    return _chamar_api("/dados-auxiliares/unidades-servico")


# -------------------------------------------------------------
# Utilidades genéricas (mantidas do código original)
# -------------------------------------------------------------
def to_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        return [x]
    return []


def ms_to_dt(value):
    if value in (None, "", "0"):
        return pd.NaT
    try:
        return (
            pd.to_datetime(int(value), unit="ms", utc=True)
            .tz_convert("America/Sao_Paulo")
        )
    except (ValueError, TypeError):
        return pd.NaT


def safe_float(value):
    if value in (None, "", "0"):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _achar_lista_chamadas(payload: dict):
    """Localiza a lista de chamadas independentemente do aninhamento."""
    candidatos = [
        ("dados", "response", "dadosVigentesChamadas", "dadosVigentesChamadaV1"),
        ("dados", "response", "dadosVigentesChamadaV1"),
        ("response", "dadosVigentesChamadas", "dadosVigentesChamadaV1"),
        ("response", "dadosVigentesChamadaV1"),
    ]
    for caminho in candidatos:
        node = payload
        ok = True
        for chave in caminho:
            if isinstance(node, dict) and chave in node:
                node = node[chave]
            else:
                ok = False
                break
        if ok and node is not None:
            if isinstance(node, list):
                return node
            if isinstance(node, dict):
                return [node]
    return []


# -------------------------------------------------------------
# Colunas garantidas do DataFrame final
# -------------------------------------------------------------
COLUNAS_FINAIS = [
    "id", "numeroChamada", "origem_codigo", "origem",
    "situacao_codigo", "situacao",
    "dataHoraInclusao", "latitude", "longitude",
    "descricaoLocalizacao", "referenciaLocalFato", "estabelecimentoLocalFato",
    "nomeUsuarioInclusao", "idOrgao", "idUnidadeServicoResponsavel",
    "idRecursoPrincipal",
    "alerta", "destaque", "envolveAutoridade",
    "natureza_id", "natureza_codigo", "natureza_descricao", "natureza_label",
    "natureza_prioridade", "natureza_tipo_servico",
    "naturezas_ids", "naturezas_prioridades", "naturezas_tipos_servico",
    "situacoes_atendimento", "situacao_atendimento_principal",
    "situacao_atendimento_principal_desc",
    "qtd_atendimentos", "qtd_naturezas", "qtd_historicos", "qtd_envolvidos",
    "solicitante_nome", "solicitante_telefone",
    "natureza_tipo_servico_desc", "prioridade_desc",
]


# -------------------------------------------------------------
# Processamento dos dados (adaptado para receber payload da API)
# -------------------------------------------------------------
@st.cache_data(show_spinner=False)
def processar_dados(payload_chamadas: dict, payload_naturezas: dict):
    """Transforma os payloads da API no DataFrame final enriquecido."""

    # 1) Catálogo de naturezas
    naturezas_lookup = {}
    for nat in payload_naturezas.get("dados", {}).get("value", []):
        nat_id = nat.get("id")
        if nat_id is None:
            continue
        naturezas_lookup[str(nat_id)] = {
            "codigo": (nat.get("codigo") or "").strip(),
            "descricao": (nat.get("descricao") or "").strip(),
        }

    # 2) Chamadas
    atualizado_em = payload_chamadas.get("atualizado_em")
    total_api = payload_chamadas.get("total")
    chamadas = _achar_lista_chamadas(payload_chamadas)

    registros = []
    for ch in chamadas:
        atendimentos = to_list(
            ch.get("dadosVigentesAtendimentosChamada", {})
              .get("dadosVigentesAtendimentoChamadaV1")
        )
        naturezas = to_list(
            ch.get("dadosVigentesNaturezasChamada", {})
              .get("dadosVigentesNaturezaChamadaV1")
        )
        historicos = to_list(
            ch.get("dadosVigentesHistoricosChamada", {})
              .get("dadosVigentesHistoricoChamadaV1")
        )
        envolvidos = to_list(
            ch.get("dadosVigentesEnvolvidosChamada", {})
              .get("dadosVigentesEnvolvidoChamadaV1")
        )

        nat0 = naturezas[0] if naturezas else {}

        sits_atend = [
            a.get("codigoSituacaoAtendimentoChamada")
            for a in atendimentos
            if a.get("codigoSituacaoAtendimentoChamada")
        ]
        nat_ids = [n.get("idNatureza") for n in naturezas if n.get("idNatureza")]
        nat_prioridades = sorted({
            n.get("codigoPrioridade") for n in naturezas if n.get("codigoPrioridade")
        })
        nat_tipos = {n.get("codigoTipoServico") for n in naturezas if n.get("codigoTipoServico")}

        solicitante = ch.get("solicitanteChamada") or {}

        nat_principal_id = nat0.get("idNatureza")
        nat_principal_id_str = str(nat_principal_id) if nat_principal_id else None
        nat_info = naturezas_lookup.get(nat_principal_id_str, {}) if nat_principal_id_str else {}
        nat_codigo = nat_info.get("codigo", "")
        nat_descricao = nat_info.get("descricao", "")
        if nat_codigo and nat_descricao:
            nat_label = f"{nat_codigo} — {nat_descricao}"
        elif nat_codigo:
            nat_label = nat_codigo
        elif nat_descricao:
            nat_label = nat_descricao
        elif nat_principal_id_str:
            nat_label = f"(sem catálogo) ID {nat_principal_id_str}"
        else:
            nat_label = "—"

        registros.append({
            "id": ch.get("id"),
            "numeroChamada": ch.get("numeroChamada"),
            "origem_codigo": ch.get("codigoOrigemChamada"),
            "origem": ORIGEM_CHAMADA.get(ch.get("codigoOrigemChamada"), ch.get("codigoOrigemChamada")),
            "situacao_codigo": ch.get("codigoSituacaoChamada"),
            "situacao": SITUACAO_CHAMADA.get(ch.get("codigoSituacaoChamada"), ch.get("codigoSituacaoChamada")),
            "dataHoraInclusao": ms_to_dt(ch.get("dataHoraInclusao")),
            "latitude": safe_float(ch.get("latitude")),
            "longitude": safe_float(ch.get("longitude")),
            "descricaoLocalizacao": ch.get("descricaoLocalizacao"),
            "referenciaLocalFato": ch.get("referenciaLocalFato"),
            "estabelecimentoLocalFato": ch.get("estabelecimentoLocalFato"),
            "nomeUsuarioInclusao": ch.get("nomeUsuarioInclusao"),
            "idOrgao": (atendimentos[0].get("idOrgao") if atendimentos else None),
            "idUnidadeServicoResponsavel": (
                atendimentos[0].get("idUnidadeServicoResponsavel") if atendimentos else None
            ),
            "idRecursoPrincipal": (
                atendimentos[0].get("idRecursoPrincipal") if atendimentos else None
            ),
            "alerta": (atendimentos[0].get("alerta") if atendimentos else None),
            "destaque": (atendimentos[0].get("destaque") if atendimentos else None),
            "envolveAutoridade": (atendimentos[0].get("envolveAutoridade") if atendimentos else None),
            "natureza_id": nat_principal_id,
            "natureza_codigo": nat_codigo,
            "natureza_descricao": nat_descricao,
            "natureza_label": nat_label,
            "natureza_prioridade": nat0.get("codigoPrioridade"),
            "natureza_tipo_servico": nat0.get("codigoTipoServico"),
            "naturezas_ids": ",".join(str(x) for x in nat_ids),
            "naturezas_prioridades": ",".join(nat_prioridades),
            "naturezas_tipos_servico": ",".join(sorted(nat_tipos)),
            "situacoes_atendimento": ",".join(sits_atend),
            "situacao_atendimento_principal": (sits_atend[0] if sits_atend else None),
            "situacao_atendimento_principal_desc": SITUACAO_ATENDIMENTO.get(
                sits_atend[0] if sits_atend else None, "—"
            ),
            "qtd_atendimentos": len(atendimentos),
            "qtd_naturezas": len(naturezas),
            "qtd_historicos": len(historicos),
            "qtd_envolvidos": len(envolvidos),
            "solicitante_nome": solicitante.get("nomeSolicitante"),
            "solicitante_telefone": solicitante.get("telefoneSolicitante"),
        })

    df = pd.DataFrame(registros)
    for col in COLUNAS_FINAIS:
        if col not in df.columns:
            df[col] = pd.Series(dtype="object")
    df = df[COLUNAS_FINAIS]

    df["natureza_tipo_servico_desc"] = (
        df["natureza_tipo_servico"].map(TIPO_SERVICO).fillna("—")
    )
    df["prioridade_desc"] = (
        df["natureza_prioridade"]
        .map({"1": "1 - Alta", "2": "2 - Média", "3": "3 - Baixa"})
        .fillna("—")
    )

    return df, atualizado_em, total_api


# =============================================================
# UNIDADES — carregamento e classificação (COB / BBM / CIA IND)
# =============================================================
RE_COB = re.compile(r"^\s*\d+\s*COB\b", re.IGNORECASE)
RE_BBM = re.compile(r"^\s*\d+\s*BBM\b", re.IGNORECASE)
RE_CIA_IND = re.compile(r"^\s*\d+\s*CIA\s*IND\b", re.IGNORECASE)


def classificar_tipo_unidade(nome: str) -> str:
    if not isinstance(nome, str) or not nome.strip():
        return "Outros"
    n = nome.strip()
    if RE_COB.search(n):
        return "COB"
    if RE_BBM.search(n):
        return "BBM"
    if RE_CIA_IND.search(n):
        return "CIA IND"
    return "Outros"


@st.cache_data(show_spinner="Processando unidades…")
def processar_unidades(payload_unidades: dict) -> dict:
    """Converte o JSON de unidades em lookup (mesma lógica do CSV original)."""
    itens = payload_unidades.get("dados", {}).get("value", [])
    lookup = {}
    for row in itens:
        uid = row.get("id")
        if not uid:
            continue
        nome = row.get("nome") or ""
        tipo = classificar_tipo_unidade(nome)

        dir_nome = row.get("unidadeDirecaoNome") or ""
        dir_id = row.get("unidadeDirecaoId") or ""
        if classificar_tipo_unidade(dir_nome) == "COB":
            cob_id, cob_nome = dir_id, dir_nome
        elif tipo == "COB":
            cob_id, cob_nome = uid, nome
        else:
            cob_id, cob_nome = None, None

        princ_nome = row.get("unidadePrincipalNome") or ""
        princ_id = row.get("unidadePrincipalId") or ""
        tipo_princ = classificar_tipo_unidade(princ_nome)

        if tipo_princ == "BBM":
            bbm_id, bbm_nome = princ_id, princ_nome
        elif tipo == "BBM":
            bbm_id, bbm_nome = uid, nome
        else:
            bbm_id, bbm_nome = None, None

        if tipo_princ == "CIA IND":
            cia_id, cia_nome = princ_id, princ_nome
        elif tipo == "CIA IND":
            cia_id, cia_nome = uid, nome
        else:
            cia_id, cia_nome = None, None

        lookup[str(uid)] = {
            "nome": nome,
            "tipo": tipo,
            "cob_id": cob_id, "cob_nome": cob_nome,
            "bbm_id": bbm_id, "bbm_nome": bbm_nome,
            "cia_ind_id": cia_id, "cia_ind_nome": cia_nome,
        }
    return lookup


def enriquecer_com_unidades(df: pd.DataFrame, lookup: dict) -> pd.DataFrame:
    if not lookup:
        for c in ["unidade_nome", "unidade_tipo",
                  "cob_id", "cob_nome",
                  "bbm_id", "bbm_nome",
                  "cia_ind_id", "cia_ind_nome"]:
            df[c] = None
        return df

    def get(uid, campo):
        return lookup.get(str(uid), {}).get(campo) if uid is not None else None

    df["unidade_nome"]  = df["idUnidadeServicoResponsavel"].apply(lambda x: get(x, "nome"))
    df["unidade_tipo"]  = df["idUnidadeServicoResponsavel"].apply(lambda x: get(x, "tipo"))
    df["cob_id"]        = df["idUnidadeServicoResponsavel"].apply(lambda x: get(x, "cob_id"))
    df["cob_nome"]      = df["idUnidadeServicoResponsavel"].apply(lambda x: get(x, "cob_nome"))
    df["bbm_id"]        = df["idUnidadeServicoResponsavel"].apply(lambda x: get(x, "bbm_id"))
    df["bbm_nome"]      = df["idUnidadeServicoResponsavel"].apply(lambda x: get(x, "bbm_nome"))
    df["cia_ind_id"]    = df["idUnidadeServicoResponsavel"].apply(lambda x: get(x, "cia_ind_id"))
    df["cia_ind_nome"]  = df["idUnidadeServicoResponsavel"].apply(lambda x: get(x, "cia_ind_nome"))
    return df


# -------------------------------------------------------------
# Validação e carga dos dados
# -------------------------------------------------------------
try:
    payload_chamadas = buscar_chamadas_api()
    payload_naturezas = buscar_naturezas_api()
    payload_unidades = buscar_unidades_api()
except TokenInvalido as exc:
    st.error(f"🔐 {exc}")
    st.stop()
except ConjuntoAusente as exc:
    st.warning(f"⚠️ {exc}")
    st.stop()
except Exception as exc:
    st.error(f"❌ Erro ao consultar a API: {exc}")
    st.stop()

df, atualizado_em, total_api = processar_dados(payload_chamadas, payload_naturezas)

unidade_lookup = processar_unidades(payload_unidades) if payload_unidades else {}
df = enriquecer_com_unidades(df, unidade_lookup)
tem_unidades = bool(unidade_lookup)

# -------------------------------------------------------------
# Sidebar — cabeçalho + filtro de UNIDADE + botão de atualização
# -------------------------------------------------------------
st.sidebar.title("🚒 CBMMG — Chamadas Ativas")
st.sidebar.caption(f"Atualizado em: **{atualizado_em}**")
st.sidebar.caption(f"Total reportado pela API: **{total_api}**")

# Botão “Atualizar agora”
if st.sidebar.button("🔄 Atualizar agora", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

f_cob: list = []
f_bbm: list = []
f_cia: list = []

if tem_unidades:
    with st.sidebar.expander("🏢 Filtrar por Unidade", expanded=True):
        st.caption("Cascata: COB → BBM → CIA IND")

        cobs_disponiveis = sorted({
            v["cob_nome"] for v in unidade_lookup.values() if v.get("cob_nome")
        })
        f_cob = st.multiselect(
            "COB (Coordenadoria Operacional)",
            options=cobs_disponiveis,
            default=[],
            placeholder="Todos",
            key="f_cob",
        )

        pool_bbm = list(unidade_lookup.values())
        if f_cob:
            pool_bbm = [v for v in pool_bbm if v.get("cob_nome") in f_cob]
        bbms_disponiveis = sorted({
            v["bbm_nome"] for v in pool_bbm if v.get("bbm_nome")
        })
        f_bbm = st.multiselect(
            "BBM (Batalhão)",
            options=bbms_disponiveis,
            default=[],
            placeholder="Todos",
            key="f_bbm",
        )

        pool_cia = list(unidade_lookup.values())
        if f_cob:
            pool_cia = [v for v in pool_cia if v.get("cob_nome") in f_cob]
        if f_bbm:
            pool_cia = [v for v in pool_cia if v.get("bbm_nome") in f_bbm]
        cia_disponiveis = sorted({
            v["cia_ind_nome"] for v in pool_cia if v.get("cia_ind_nome")
        })
        f_cia = st.multiselect(
            "CIA IND (Companhia Independente)",
            options=cia_disponiveis,
            default=[],
            placeholder="Todas",
            key="f_cia",
        )

        if f_cob or f_bbm or f_cia:
            st.caption(
                f"🔎 Filtro ativo — "
                f"COB: {len(f_cob) or 'todos'} · "
                f"BBM: {len(f_bbm) or 'todos'} · "
                f"CIA IND: {len(f_cia) or 'todas'}"
            )
else:
    st.sidebar.info("Filtro por unidade indisponível (dados de unidades não carregados).")

# -------------------------------------------------------------
# Aplicação do filtro de unidade
# -------------------------------------------------------------
mascara_unidade = pd.Series(True, index=df.index)
if f_cob:
    mascara_unidade &= df["cob_nome"].isin(f_cob)
if f_bbm:
    mascara_unidade &= df["bbm_nome"].isin(f_bbm)
if f_cia:
    mascara_unidade &= df["cia_ind_nome"].isin(f_cia)

df_filt = df[mascara_unidade].copy()

st.sidebar.markdown(f"**Chamadas após filtros:** `{len(df_filt)}`")


# =============================================================
# CABEÇALHO DE DESTAQUE
# =============================================================
st.markdown("""
    <div class="cbmmg-header">
        <h1>🚒 Chamadas Ativas do Corpo de Bombeiros Militar de Minas Gerais</h1>
    </div>
""", unsafe_allow_html=True)

st.markdown(
    '<div class="cbmmg-subtitle">Painel operacional de acompanhamento das chamadas ativas</div>',
    unsafe_allow_html=True,
)


# =============================================================
# CARDS DE DESTAQUE (KPIs)
# =============================================================
def render_metric_card(col, valor, rotulo, cor_fundo: str):
    col.markdown(f"""
        <div class="metric-card" style="background:{cor_fundo};">
          <div class="valor">{valor}</div>
          <div class="rotulo">{rotulo}</div>
        </div>
    """, unsafe_allow_html=True)


total_ativas = len(df_filt)
total_em_atend = int((df_filt["situacao_codigo"] == "E").sum())
total_aguard = int((df_filt["situacao_codigo"] == "A").sum())

campo_recurso = "idRecursoPrincipal"
if df_filt["idRecursoPrincipal"].notna().sum() == 0:
    campo_recurso = "idUnidadeServicoResponsavel"

equipes_empenhadas = int(
    df_filt.loc[df_filt["situacao_codigo"] == "E", campo_recurso]
    .dropna()
    .nunique()
)

c1, c2, c3, c4 = st.columns(4)
render_metric_card(
    c1, f"{total_ativas:,}".replace(",", "."),
    "Total de Chamadas Ativas",
    "linear-gradient(135deg, #B71C1C 0%, #7F0000 100%)",
)
render_metric_card(
    c2, f"{total_em_atend:,}".replace(",", "."),
    "Chamadas em Atendimento",
    "linear-gradient(135deg, #EF6C00 0%, #E65100 100%)",
)
render_metric_card(
    c3, f"{total_aguard:,}".replace(",", "."),
    "Chamadas Aguardando",
    "linear-gradient(135deg, #1565C0 0%, #0D47A1 100%)",
)
render_metric_card(
    c4, f"{equipes_empenhadas:,}".replace(",", "."),
    "Equipes Empenhadas",
    "linear-gradient(135deg, #2E7D32 0%, #1B5E20 100%)",
)

st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)


# =============================================================
# ABAS — Mapa (principal) e Indicadores
# =============================================================
aba_mapa, aba_indicadores = st.tabs(["🗺️ Mapa", "📊 Indicadores"])


# -------------------------------------------------------------
# Cores por situação de atendimento
# -------------------------------------------------------------
CORES_ATENDIMENTO = {
    "AO": "#2ca02c", "DP": "#bcbd22", "ED": "#e377c2",
    "NL": "#d62728", "AC": "#1f77b4", "EC": "#d62728",
    "LI": "#17becf", "ER": "#aec7e8", "EN": "#98df8a",
    "TR": "#8c564b", "SU": "#ff7f0e", "CL": "#9467bd",
}


# =============================================================
# ABA 1 — MAPA
# =============================================================
with aba_mapa:
    st.markdown("### Distribuição geográfica das chamadas ativas")

    df_mapa = df_filt.dropna(subset=["latitude", "longitude"]).copy()
    df_mapa = df_mapa[
        df_mapa["latitude"].between(-23.5, -14.0)
        & df_mapa["longitude"].between(-51.5, -39.5)
    ]

    if df_mapa.empty:
        st.warning("Nenhuma chamada com coordenadas válidas para exibir no mapa.")
    else:
        st.caption(f"Exibindo **{len(df_mapa)}** chamadas com coordenadas válidas.")

        df_mapa["cor"] = (
            df_mapa["situacao_atendimento_principal"]
            .map(CORES_ATENDIMENTO).fillna("#cccccc")
        )

        centro_mg = [-18.5, -44.5]
        mapa = folium.Map(
            location=centro_mg,
            zoom_start=6,
            tiles="OpenStreetMap",
            attr="Leaflet | © OpenStreetMap contributors",
            control_scale=True,
        )

        cluster = MarkerCluster(name="Chamadas").add_to(mapa)

        for _, row in df_mapa.iterrows():
            cor = row["cor"]
            nat_line = (
                f"{row['natureza_codigo']} — {row['natureza_descricao']}"
                if row['natureza_codigo'] or row['natureza_descricao']
                else f"ID {row['natureza_id']}"
            )
            unidade_line = row.get("unidade_nome") or "—"
            popup_html = f"""
            <div style="font-family:Arial;font-size:13px;min-width:320px;
                        color:#222;background:#fff;padding:2px 4px;">
              <b>Chamada:</b> {row['numeroChamada']}<br>
              <b>Situação:</b> {row['situacao']}<br>
              <b>Atendimento:</b> {row['situacao_atendimento_principal_desc']}<br>
              <b>Natureza:</b> {nat_line}<br>
              <b>Prioridade:</b> {row['prioridade_desc']}<br>
              <b>Unidade:</b> {unidade_line}<br>
              <b>COB:</b> {row.get('cob_nome') or '—'}<br>
              <b>BBM:</b> {row.get('bbm_nome') or '—'}<br>
              <b>CIA IND:</b> {row.get('cia_ind_nome') or '—'}<br>
              <b>Local:</b> {row['descricaoLocalizacao'] or '—'}<br>
              <b>Abertura:</b> {row['dataHoraInclusao']}<br>
            </div>
            """
            folium.CircleMarker(
                location=[row["latitude"], row["longitude"]],
                radius=7, color=cor, fill=True,
                fill_color=cor, fill_opacity=0.9,
                popup=folium.Popup(popup_html, max_width=380),
                tooltip=f"{row['numeroChamada']} — {row['situacao_atendimento_principal_desc']}",
            ).add_to(cluster)

        st_folium(mapa, width=None, height=680, returned_objects=[])

        st.markdown(
            '<div class="legenda-titulo">Legenda — Situação do Atendimento</div>',
            unsafe_allow_html=True,
        )
        itens_html = "".join(
            f'<div class="legenda-item">'
            f'<span class="legenda-swatch" '
            f'style="background:{CORES_ATENDIMENTO.get(codigo, "#cccccc")};"></span>'
            f'<span><b>{codigo}</b> — {descricao}</span>'
            f'</div>'
            for codigo, descricao in SITUACAO_ATENDIMENTO.items()
        )
        st.markdown(
            f'<div class="legenda-container">{itens_html}</div>',
            unsafe_allow_html=True,
        )

        st.markdown("#### Pontos plotados")
        cols_mapa = [
            "numeroChamada", "situacao", "situacao_atendimento_principal_desc",
            "natureza_codigo", "natureza_descricao",
            "unidade_nome", "cob_nome", "bbm_nome", "cia_ind_nome",
            "descricaoLocalizacao", "latitude", "longitude", "dataHoraInclusao",
        ]
        cols_mapa = [c for c in cols_mapa if c in df_mapa.columns]
        st.dataframe(
            df_mapa[cols_mapa].sort_values("dataHoraInclusao", ascending=False),
            use_container_width=True, hide_index=True,
        )


# =============================================================
# ABA 2 — INDICADORES
# =============================================================
with aba_indicadores:
    st.markdown("### Visão geral das chamadas ativas")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("#### Chamadas ativas por natureza (DIAO / ITO 25)")
        nat_count = (
            df_filt["natureza_label"]
            .dropna().astype(str)
            .value_counts()
            .rename_axis("Natureza").reset_index(name="qtd")
            .sort_values("qtd", ascending=False)
        )
        nat_count = nat_count[nat_count["Natureza"] != "—"]

        if nat_count.empty:
            st.info("Sem naturezas para exibir.")
        else:
            top_n = st.slider(
                "Exibir top N naturezas",
                min_value=5,
                max_value=min(40, len(nat_count)),
                value=min(20, len(nat_count)),
                step=1,
                key="top_n_naturezas",
            )
            nat_plot = nat_count.head(top_n)
            fig_nat = px.bar(
                nat_plot, x="qtd", y="Natureza", orientation="h",
                text="qtd", color="qtd", color_continuous_scale="Blues",
            )
            fig_nat.update_layout(
                yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
                height=max(420, 26 * len(nat_plot) + 80),
                coloraxis_showscale=False,
                margin=dict(l=10, r=10, t=10, b=10),
            )
            fig_nat.update_traces(textposition="outside")
            st.plotly_chart(fig_nat, use_container_width=True)

            with st.expander("Ver tabela completa"):
                st.dataframe(nat_count, use_container_width=True, hide_index=True)

    with col_b:
        st.markdown("#### Chamadas ativas por status")

        st.caption("Situação macro da chamada")
        sitch_count = (
            df_filt["situacao"].value_counts()
            .rename_axis("Situação").reset_index(name="qtd")
        )
        fig_sitch = px.pie(
            sitch_count, names="Situação", values="qtd", hole=0.45,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig_sitch.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_sitch, use_container_width=True)

        st.caption("Situação do atendimento principal")
        sitat_count = (
            df_filt["situacao_atendimento_principal_desc"].value_counts()
            .rename_axis("Situação do atendimento").reset_index(name="qtd")
        )
        fig_sitat = px.bar(
            sitat_count, x="qtd", y="Situação do atendimento",
            orientation="h", text="qtd", color="qtd",
            color_continuous_scale="Oranges",
        )
        fig_sitat.update_layout(
            yaxis=dict(autorange="reversed"),
            height=380, coloraxis_showscale=False,
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig_sitat, use_container_width=True)

    st.divider()

    col_c, col_d, col_e = st.columns(3)

    with col_c:
        st.markdown("#### Por origem")
        origem_count = (
            df_filt["origem"].value_counts().rename_axis("Origem").reset_index(name="qtd")
        )
        fig_orig = px.bar(
            origem_count, x="Origem", y="qtd", text="qtd",
            color="Origem", color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig_orig.update_layout(showlegend=False, height=340, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_orig, use_container_width=True)

    with col_d:
        st.markdown("#### Por prioridade")
        prio_count = (
            df_filt["prioridade_desc"].value_counts()
            .rename_axis("Prioridade").reset_index(name="qtd")
        )
        fig_prio = px.bar(
            prio_count, x="Prioridade", y="qtd", text="qtd",
            color="Prioridade", color_discrete_sequence=px.colors.qualitative.Safe,
        )
        fig_prio.update_layout(showlegend=False, height=340, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_prio, use_container_width=True)

    with col_e:
        st.markdown("#### Por tipo de serviço")
        tipo_count = (
            df_filt["natureza_tipo_servico_desc"].value_counts()
            .rename_axis("Tipo").reset_index(name="qtd")
        )
        fig_tipo = px.bar(
            tipo_count, x="Tipo", y="qtd", text="qtd",
            color="Tipo", color_discrete_sequence=px.colors.qualitative.Vivid,
        )
        fig_tipo.update_layout(showlegend=False, height=340, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_tipo, use_container_width=True)

    if tem_unidades and not df_filt.empty:
        st.divider()
        st.markdown("#### Chamadas por unidade responsável (top 15)")
        unid_count = (
            df_filt["unidade_nome"].dropna().astype(str)
            .value_counts().head(15)
            .rename_axis("Unidade").reset_index(name="qtd")
        )
        fig_unid = px.bar(
            unid_count, x="qtd", y="Unidade", orientation="h",
            text="qtd", color="qtd", color_continuous_scale="Teal",
        )
        fig_unid.update_layout(
            yaxis=dict(autorange="reversed"),
            height=460, coloraxis_showscale=False,
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig_unid, use_container_width=True)

    st.divider()
    st.markdown("#### Evolução das aberturas (hora)")
    df_temp = df_filt.dropna(subset=["dataHoraInclusao"]).copy()
    if not df_temp.empty:
        df_temp["hora"] = df_temp["dataHoraInclusao"].dt.floor("h")
        serie = df_temp.groupby("hora").size().rename("chamadas").reset_index()
        fig_serie = px.line(serie, x="hora", y="chamadas", markers=True)
        fig_serie.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_serie, use_container_width=True)

    st.divider()
    st.markdown("#### Detalhamento")
    colunas_exib = [
        "numeroChamada", "situacao", "situacao_atendimento_principal_desc",
        "natureza_codigo", "natureza_descricao",
        "prioridade_desc", "natureza_tipo_servico_desc",
        "unidade_nome", "cob_nome", "bbm_nome", "cia_ind_nome",
        "descricaoLocalizacao", "nomeUsuarioInclusao",
        "dataHoraInclusao", "solicitante_nome", "solicitante_telefone",
    ]
    colunas_exib = [c for c in colunas_exib if c in df_filt.columns]

    st.dataframe(
        df_filt[colunas_exib].sort_values("dataHoraInclusao", ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={
            "dataHoraInclusao": st.column_config.DatetimeColumn(
                "Abertura", format="DD/MM/YYYY HH:mm"
            ),
            "natureza_codigo": st.column_config.TextColumn("Código"),
            "natureza_descricao": st.column_config.TextColumn("Descrição da natureza"),
            "unidade_nome": st.column_config.TextColumn("Unidade responsável"),
            "cob_nome": st.column_config.TextColumn("COB"),
            "bbm_nome": st.column_config.TextColumn("BBM"),
            "cia_ind_nome": st.column_config.TextColumn("CIA IND"),
        },
    )

    csv = df_filt.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Baixar chamadas filtradas (CSV)",
        data=csv,
        file_name="chamadas_ativas_filtradas.csv",
        mime="text/csv",
    )


# -------------------------------------------------------------
# Rodapé da sidebar
# -------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.caption(
    "Dashboard operacional · Fonte: API CAD / CBMMG · "
    "Catálogo de naturezas: DIAO / ITO 25 · "
    "Cadastro de unidades: API de unidades · "
    "Desenvolvido para o COBOM-BH."
)
