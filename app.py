import json
import re
import uuid
from datetime import datetime
import gspread
from dateutil.relativedelta import relativedelta
from google.oauth2.service_account import Credentials
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Sistema de Vendas & Cobranças", layout="wide", page_icon="📊"
)

COLUNAS_ESPERADAS = [
    "ID",
    "Data",
    "Cliente",
    "Produto",
    "Valor Total",
    "Valor Pago",
    "Parcelas",
    "Data 1ª Parcela",
    "Status",
]


# --- CONEXÃO AUTENTICADA COM O GOOGLE SHEETS ---
@st.cache_resource
def obter_conexao():
  scope = [
      "https://www.googleapis.com/auth/spreadsheets",
      "https://www.googleapis.com/auth/drive",
  ]
  service_account_info = json.loads(st.secrets["json_string"])
  creds = Credentials.from_service_account_info(
      service_account_info, scopes=scope
  )
  client = gspread.authorize(creds)

  url = st.secrets["connections"]["gsheets"]["spreadsheet"]
  return client.open_by_url(url).sheet1


def carregar_dados():
  try:
    sheet = obter_conexao()
    dados = sheet.get_all_records()
    df = pd.DataFrame(dados)
    if df.empty:
      return pd.DataFrame(columns=COLUNAS_ESPERADAS)
    return df
  except Exception:
    return pd.DataFrame(columns=COLUNAS_ESPERADAS)


def parse_data_br(data_str):
  """Converte strings de data em objeto date"""
  if isinstance(data_str, datetime):
    return data_str.date()
  if not isinstance(data_str, str) or not data_str.strip():
    return datetime.now().date()

  for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
    try:
      return datetime.strptime(data_str.strip(), fmt).date()
    except ValueError:
      pass
  return datetime.now().date()


def safe_float(val, default=0.0):
  """Converte valor para float de forma segura preservando decimais"""
  try:
    if pd.isna(val) or val == "":
      return default
    if isinstance(val, (int, float)):
      return float(val)

    s = str(val).strip()
    # Se contiver virgula e ponto (ex: 1.200,50), remove ponto e troca virgula por ponto
    if "," in s and "." in s:
      s = s.replace(".", "").replace(",", ".")
    elif "," in s:
      s = s.replace(",", ".")

    return float(s)
  except (ValueError, TypeError):
    return default


def safe_int(val, default=1):
  """Converte valor para inteiro extraindo apenas os dígitos numéricos"""
  try:
    if pd.isna(val) or val == "":
      return default
    numeros = re.findall(r"\d+", str(val))
    if numeros:
      return int(numeros[0])
    return default
  except (ValueError, TypeError):
    return default


def gerar_cronograma_recalculado(
    data_primeira, num_parcelas, valor_total, valor_pago
):
  """Gera o cronograma recalculado com base no novo valor total e valor pago"""
  num_parcelas = max(1, safe_int(num_parcelas, 1))
  valor_total = safe_float(valor_total, 0.0)
  valor_pago = safe_float(valor_pago, 0.0)

  data_base = parse_data_br(data_primeira)
  saldo_devedor = max(0.0, valor_total - valor_pago)
  valor_original_parcela = valor_total / num_parcelas if num_parcelas > 0 else 0

  parcelas_quitadas = (
      int(valor_pago // valor_original_parcela)
      if valor_original_parcela > 0
      else 0
  )
  if parcelas_quitadas >= num_parcelas:
    parcelas_quitadas = num_parcelas

  parcelas_restantes = num_parcelas - parcelas_quitadas

  if parcelas_restantes > 0 and saldo_devedor > 0:
    novo_valor_parcela = saldo_devedor / parcelas_restantes
  else:
    novo_valor_parcela = 0.0

  cronograma = []

  for i in range(num_parcelas):
    data_venc = data_base + relativedelta(months=i)
    data_str = data_venc.strftime("%d/%m/%Y")

    if i < parcelas_quitadas:
      st_parc = "✅ Quitada"
      val_parc = valor_original_parcela
    elif saldo_devedor == 0:
      st_parc = "✅ Quitada"
      val_parc = 0.0
    else:
      st_parc = "⏳ Pendente"
      val_parc = novo_valor_parcela

    cronograma.append({
        "Nº Parcela": f"{i+1}/{num_parcelas}",
        "Vencimento": data_str,
        "Valor da Parcela (R$)": f"{val_parc:.2f}",
        "Situação": st_parc,
    })

  return pd.DataFrame(cronograma), saldo_devedor


# --- SISTEMA DE LOGIN ---
if "autenticado" not in st.session_state:
  st.session_state.autenticado = False

if not st.session_state.autenticado:
  st.title("🔒 Login do Sistema de Vendas")
  col1, _ = st.columns([1, 2])
  with col1:
    usuario = st.text_input("Usuário")
    senha = st.text_input("Senha", type="password")
    if st.button("Entrar", type="primary"):
      if usuario == "admin" and senha == "1234":
        st.session_state.autenticado = True
        st.rerun()
      else:
        st.error("Usuário ou senha incorretos.")
else:
  st.sidebar.title("Opções")
  if st.sidebar.button("Sair / Logout"):
    st.session_state.autenticado = False
    st.rerun()

  st.title("📊 Gestão de Vendas & Recebimentos")
  df_vendas = carregar_dados()

  aba_cadastro, aba_atualizar, aba_dash, aba_historico = st.tabs([
      "➕ Cadastrar Venda",
      "🔄 Registrar Pagamento / Editar",
      "📈 Dashboard & Filtros",
      "📋 Histórico Completo",
  ])

  # --- ABA 1: CADASTRO ---
  with aba_cadastro:
    st.header("Registrar Nova Venda")
    with st.form("form_nova_venda", clear_on_submit=True):
      col_a, col_b = st.columns(2)
      with col_a:
        data_venda = st.date_input(
            "Data da Venda", datetime.now(), format="DD/MM/YYYY"
        )
        cliente = st.text_input("Nome do Cliente")
        produto = st.text_input("Produto / Serviço Vendido")
        valor_total = st.number_input(
            "Valor Total (R$)", min_value=0.0, format="%.2f", step=1.0
        )

      with col_b:
        valor_pago_inicial = st.number_input(
            "Valor Já Pago na Entrada (R$)",
            min_value=0.0,
            value=0.0,
            format="%.2f",
            step=1.0,
        )
        parcelas = st.number_input(
            "Quantidade Total de Parcelas", min_value=1, value=1, step=1
        )
        data_primeira_parcela = st.date_input(
            "Data do 1º Vencimento / Parcela",
            datetime.now(),
            format="DD/MM/YYYY",
        )

      submeter = st.form_submit_button("Salvar Venda", type="primary")

      if submeter:
        if cliente.strip() != "" and produto.strip() != "":
          try:
            sheet = obter_conexao()
            venda_id = str(uuid.uuid4())[:8]

            if (
                valor_pago_inicial >= valor_total
                and valor_total > 0
            ):
              status_inicial = "Pago"
            elif valor_pago_inicial > 0:
              status_inicial = "Parcial"
            else:
              status_inicial = "A Receber"

            nova_linha = [
                venda_id,
                data_venda.strftime("%d/%m/%Y"),
                cliente,
                produto,
                float(valor_total),
                float(valor_pago_inicial),
                int(parcelas),
                data_primeira_parcela.strftime("%d/%m/%Y"),
                status_inicial,
            ]
            sheet.append_row(nova_linha)
            st.success(
                f"Venda para **{cliente}** salva com sucesso! (ID: {venda_id})"
            )
            st.rerun()
          except Exception as e:
            st.error(f"Erro ao salvar na planilha: {e}")
        else:
          st.warning("Preencha o nome do cliente e do produto.")

  # --- ABA 2: EDITAR / REGISTRAR PAGAMENTO ---
  with aba_atualizar:
    st.header("Registrar Pagamento / Editar Venda")
    if not df_vendas.empty:
      opcoes_vendas = df_vendas.apply(
          lambda row: (
              f"ID: {row.get('ID', '')} | {row.get('Cliente', '')} - Total: R$"
              f" {safe_float(row.get('Valor Total', 0)):.2f} | Pago: R$"
              f" {safe_float(row.get('Valor Pago', 0)):.2f}"
          ),
          axis=1,
      ).tolist()

      venda_selecionada = st.selectbox(
          "Selecione a venda para gerenciar", opcoes_vendas
      )
      idx_selecionado = opcoes_vendas.index(venda_selecionada)
      dados_venda = df_vendas.iloc[idx_selecionado]
      venda_id_alvo = str(dados_venda.get("ID", ""))

      val_total_atual = safe_float(dados_venda.get("Valor Total", 0))
      val_pago_atual = safe_float(dados_venda.get("Valor Pago", 0))
      parcelas_atual = safe_int(dados_venda.get("Parcelas", 1), 1)
      data_1_parsed = parse_data_br(dados_venda.get("Data 1ª Parcela", ""))

      col_edit1, col_edit2 = st.columns(2)

      with col_edit1:
        st.subheader(f"Cliente: {dados_venda.get('Cliente', '')}")

        novo_valor_total = st.number_input(
            "Valor Total da Venda (R$)",
            min_value=0.0,
            value=float(val_total_atual),
            format="%.2f",
            step=1.0,
            key="in_total",
        )

        novo_valor_pago = st.number_input(
            "Valor ACUMULADO Já Pago pelo Cliente (R$)",
            min_value=0.0,
            value=min(float(val_pago_atual), float(novo_valor_total)),
            format="%.2f",
            step=1.0,
            key="in_pago",
        )

        novas_parcelas = st.number_input(
            "Quantidade Total de Parcelas",
            min_value=1,
            value=int(parcelas_atual),
            step=1,
            key="in_parc",
        )

        nova_data_1 = st.date_input(
            "Data do 1º Vencimento",
            data_1_parsed,
            format="DD/MM/YYYY",
            key="in_dt1",
        )

        saldo_restante_calc = novo_valor_total - novo_valor_pago
        if saldo_restante_calc <= 0 and novo_valor_total > 0:
          status_sugerido = "Pago"
        elif novo_valor_pago > 0:
          status_sugerido = "Parcial"
        else:
          status_sugerido = "A Receber"

        novo_status = st.selectbox(
            "Status do Pagamento",
            ["A Receber", "Parcial", "Pago"],
            index=["A Receber", "Parcial", "Pago"].index(status_sugerido),
            key="in_status",
        )

        btn_atualizar = st.button(
            "Salvar Alterações e Recalcular", type="primary"
        )

        if btn_atualizar:
          try:
            sheet = obter_conexao()
            cell = sheet.find(str(venda_id_alvo))

            if cell:
              linha_sheets = cell.row

              # Atualiza a linha exata encontrada pelo ID
              sheet.update_cell(
                  linha_sheets, 5, float(novo_valor_total)
              )  # E: Valor Total
              sheet.update_cell(
                  linha_sheets, 6, float(novo_valor_pago)
              )  # F: Valor Pago
              sheet.update_cell(
                  linha_sheets, 7, int(novas_parcelas)
              )  # G: Parcelas
              sheet.update_cell(
                  linha_sheets, 8, nova_data_1.strftime("%d/%m/%Y")
              )  # H: Data 1ª Parcela
              sheet.update_cell(
                  linha_sheets, 9, str(novo_status)
              )  # I: Status

              st.success(
                  f"Venda {venda_id_alvo} atualizada com sucesso para R$"
                  f" {novo_valor_total:.2f}!"
              )
              st.rerun()
            else:
              st.error(
                  f"Não foi possível localizar o ID {venda_id_alvo} na planilha."
              )
          except Exception as e:
            st.error(f"Erro ao atualizar planilha: {e}")

      with col_edit2:
        st.subheader("🗓️ Cronograma Atualizado")

        # Exibe as métricas com base no que você está alterando no formulário em tempo real
        saldo_div_prev = max(0.0, novo_valor_total - novo_valor_pago)
        c_m1, c_m2 = st.columns(2)
        c_m1.metric("Total Pago Até Agora", f"R$ {novo_valor_pago:,.2f}")
        c_m2.metric("Saldo Devedor Restante", f"R$ {saldo_div_prev:,.2f}")

        df_cronograma_prev, _ = gerar_cronograma_recalculado(
            nova_data_1, novas_parcelas, novo_valor_total, novo_valor_pago
        )
        st.dataframe(
            df_cronograma_prev, use_container_width=True, hide_index=True
        )

    else:
      st.info("Nenhuma venda registrada para atualizar.")

  # --- ABA 3: DASHBOARD & FILTROS ---
  with aba_dash:
    st.header("Análise Financeira e Contas a Receber")
    if not df_vendas.empty:
      df_vendas["Valor Total"] = df_vendas["Valor Total"].apply(
          lambda x: safe_float(x, 0.0)
      )
      df_vendas["Valor Pago"] = df_vendas["Valor Pago"].apply(
          lambda x: safe_float(x, 0.0)
      )
      df_vendas["Saldo Devedor"] = (
          df_vendas["Valor Total"] - df_vendas["Valor Pago"]
      ).clip(lower=0)

      df_vendas["Data_Parsed"] = df_vendas["Data"].apply(parse_data_br)
      df_vendas["Ano_Mes"] = df_vendas["Data_Parsed"].apply(
          lambda d: d.strftime("%m/%Y")
      )

      meses_disponiveis = sorted(
          df_vendas["Ano_Mes"].dropna().unique().tolist(), reverse=True
      )
      meses_disponiveis.insert(0, "Todos os Meses")

      mes_selecionado = st.selectbox(
          "📅 Selecione o Mês de Referência (MM/AAAA):", meses_disponiveis
      )

      if mes_selecionado != "Todos os Meses":
        df_filtrado = df_vendas[df_vendas["Ano_Mes"] == mes_selecionado]
      else:
        df_filtrado = df_vendas.copy()

      total_geral = df_filtrado["Valor Total"].sum()
      total_pago = df_filtrado["Valor Pago"].sum()
      total_a_receber = df_filtrado["Saldo Devedor"].sum()

      col_m1, col_m2, col_m3 = st.columns(3)
      col_m1.metric("Faturamento Total Vendido", f"R$ {total_geral:,.2f}")
      col_m2.metric("Total Efetivamente Recebido", f"R$ {total_pago:,.2f}")
      col_m3.metric("📌 Saldo Pendente A RECEBER", f"R$ {total_a_receber:,.2f}")

      st.divider()
      st.subheader(f"📋 Clientes com Pendência/Saldo Devedor ({mes_selecionado})")
      df_pendentes = df_filtrado[df_filtrado["Saldo Devedor"] > 0]
      if not df_pendentes.empty:
        colunas_exibir = [
            c
            for c in [
                "ID",
                "Data",
                "Cliente",
                "Produto",
                "Valor Total",
                "Valor Pago",
                "Saldo Devedor",
                "Parcelas",
                "Status",
            ]
            if c in df_pendentes.columns
        ]
        st.dataframe(
            df_pendentes[colunas_exibir],
            use_container_width=True,
            hide_index=True,
        )
      else:
        st.success("Nenhuma pendência de pagamento encontrada!")
    else:
      st.info("Nenhuma venda cadastrada ainda.")

  # --- ABA 4: HISTÓRICO COMPLETO ---
  with aba_historico:
    st.header("Todas as Vendas Registradas")
    if not df_vendas.empty:
      st.dataframe(df_vendas, use_container_width=True, hide_index=True)
    else:
      st.info("Nenhum registro encontrado.")
