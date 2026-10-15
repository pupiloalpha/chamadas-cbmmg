# CBMMG | Chamadas Ativas

Dashboard operacional em Streamlit para acompanhamento das chamadas ativas do Corpo de Bombeiros Militar de Minas Gerais (CBMMG).

O painel consolida dados de chamadas, natureza do atendimento, unidade responsável, status operacional e localização geográfica em uma interface web rápida e fácil de usar.

## Visão geral

Este projeto foi desenvolvido para monitorar o cenário operacional em tempo real a partir dos arquivos de dados exportados da API CAD e do catálogo de naturezas.

Ele oferece:

- painel com KPIs de chamadas ativas;
- mapa geográfico com pontos das ocorrências;
- filtros por COB, BBM e CIA IND;
- indicadores por natureza, situação, origem e prioridade;
- distribuição temporal das aberturas;
- tabela detalhada com exportação em CSV.

## Funcionalidades

### 1. Mapa das ocorrências
- exibe chamadas com coordenadas geográficas válidas;
- organiza os pontos em cluster no mapa;
- destaca a situação de atendimento por cor;
- mostra popup com dados da ocorrência.

### 2. Filtros operacionais
- filtro por unidade (COB / BBM / CIA IND);
- recálculo automático dos KPIs e gráficos após a seleção;
- suporte para cenários de análise por região e comando.

### 3. Indicadores
- total de chamadas ativas;
- chamadas em atendimento e aguardando;
- equipes empenhadas;
- número de ocorrências por natureza;
- consolidação por origem, prioridade e tipo de serviço;
- evolução das aberturas por hora.

### 4. Dados e exportação
- carregamento de arquivos locais em JSON/CSV;
- enriquecimento com catálogo de naturezas;
- associação da unidade responsável via cadastro de unidades;
- download do conjunto filtrado em CSV.

## Estrutura do projeto

```text
.
├── streamlit_app.py
├── README.md
├── data/
│   ├── Chamadas_Ativas.json
│   ├── naturezas.json
│   └── unidade.csv
└── pyproject.toml
```

## Requisitos

- Python 3.11+
- uv
- dependências do projeto

## Instalação

Se ainda não tiver o `uv` instalado:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

No diretório do projeto, instale as dependências:

```bash
uv sync
```

## Execução

Inicie o dashboard:

```bash
uv run streamlit run streamlit_app.py
```

A aplicação será aberta no navegador padrão do Streamlit.

## Arquivos de dados esperados

O dashboard procura os arquivos abaixo na pasta `data/` ou na raiz do projeto:

- `Chamadas_Ativas.json`
- `naturezas.json`
- `unidade.csv`

Também é possível apontar outro diretório via variável de ambiente:

```bash
export DATA_DIR=/caminho/para/os/dados
uv run streamlit run streamlit_app.py
```

## Observações importantes

- Se algum arquivo de dados não for encontrado, o app entra em modo vazio e exibe uma mensagem informando o caminho esperado.
- A leitura dos dados é otimizada para os formatos exportados do CAD e do catálogo de naturezas.
- O dashboard usa classificação e enriquecimento para mapear unidades em COB, BBM e CIA IND.

## Tecnologias

- Python
- Streamlit
- Pandas
- Plotly
- Folium
- Streamlit Folium

## Licença

Este projeto foi desenvolvido para uso interno/operacional e pode ser adaptado conforme a necessidade da equipe responsável pela análise e monitoramento do CBMMG.

## Desenvolvimento

Para ajustar filtros, novos gráficos, métricas ou campos exibidos, edite o arquivo principal:

```bash
streamlit_app.py
```

Se a aplicação precisar de novos indicadores ou regras de classificação, a lógica principal está concentrada nesse arquivo.
