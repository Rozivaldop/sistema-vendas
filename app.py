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


# --- CONEXÃO COM O GOOGLE SHEETS ---
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
  """Lê a planilha diretamente do Google Sheets sem cache"""
  try:
    sheet = obter_conexao()
    dados = sheet.get_all_values()
    if not dados or len(dados) <= 1:
      return pd.DataFrame(columns=COLUNAS_ESPERADAS)

    cabeçalho = [str(c).strip() for c in dados[0]]
    df = pd.DataFrame(dados[1:], columns=cabeçalho)
    return df
  except Exception as e:
    st.error(f"Erro ao conectar com Google Sheets: {e}")
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
  """Suporta vírgula BR (72,90), ponto (72.90) e prefixo R$"""
  try:
    if pd.isna(val) or val == "" or val is None:
      return default
    if isinstance(val, (int, float)):
      return float(val)

    s = str(val).strip()
    s = re.sub(r"[^\d.,-]", "", s)

    if not s:
      return default

    if "," in s and "." in s:
      s = s.replace(".", "").replace(",", ".")
    elif "," in s:
      s = s.replace(",", ".")

    return float(s)
  except (ValueError, TypeError):
    return default


def safe_int(val, default=1):
  """Converte quantidade de parcelas tratando decimais ex: 3,00 -> 3"""
  try:
    if pd.isna(val) or val == "" or val is None:
      return default

    num_float = safe_float(val, float(default))
    return max(1, int(round(num_float)))
  except (ValueError, TypeError):
    return default


def gerar_cronograma_recalculado(
    data_primeira, num_parcelas, valor_total, valor_pago
):
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
        "Data_Venc_Obj": data_venc,
        "Ano_Mes": data_venc.strftime("%m/%Y"),
        "Valor Parcela (R$)": round(val_parc, 2),
        "Situação": st_parc,
    })

  return pd.DataFrame(cronograma), saldo_devedor


def expandir_todas_parcelas(df_vendas):
  """Expande todas as vendas em parcelas individuais com suas respectivas datas de vencimento"""
  lista_parcelas = []

  for _, row in df_vendas.iterrows():
    venda_id = row.get("ID", "")
    cliente = row.get("Cliente", "")
    produto = row.get("Produto", "")
    val_total = safe_float(row.get("Valor Total", 0))
    val_pago = safe_float(row.get("Valor Pago", 0))
    num_parc = safe_int(row.get("Parcelas", 1), 1)
    dt_1 = row.get("Data 1ª Parcela", row.get("Data", ""))

    df_crono, _ = gerar_cronograma_recalculado(
        dt_1, num_parc, val_total, val_pago
    )

    for _, p in df_crono.iterrows():
      lista_parcelas.append({
          "ID Venda": venda_id,
          "Cliente": cliente,
          "Produto": produto,
          "Nº Parcela": p["Nº Parcela"],
          "Vencimento": p["Vencimento"],
          "Data_Venc_Obj": p["Data_Venc_Obj"],
          "Ano_Mes": p["Ano_Mes"],
          "Valor Parcela": p["Valor Parcela (R$)"],
          "Situação": p["Situação"],
      })

  return pd.DataFrame(lista_parcelas)


# --- AUTENTICAÇÃO E LOGIN ---
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
  # BARRA LATERAL
  st.sidebar.title("Opções")
  if st.sidebar.button("🔄 Recarregar Dados do Sheets"):
    st.cache_data.clear()
    st.rerun()

  if st.sidebar.button("Sair / Logout"):
    st.session_state.autenticado = False
    st.rerun()

  # CABEÇALHO PRINCIPAL
  col_t1, col_t2 = st.columns([3, 1])
  with col_t1:
    st.title("📊 Gestão de Vendas & Recebimentos")
  with col_t2:
    if st.button("🔄 Sincronizar Agora", type="secondary"):
      st.rerun()

  df_vendas = carregar_dados()

  aba_cadastro, aba_atualizar, aba_dash, aba_historico = st.tabs([
      "➕ Cadastrar Venda",
      "🔄 Registrar Pagamento / Editar",
      "📈 Dashboard & Contas a Receber",
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

            if valor_pago_inicial >= valor_total and valor_total > 0:
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
            sheet.append_row(nova_linha, value_input_option="USER_ENTERED")
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
              f" {safe_float(row.get('Valor Total', 0)):.2f} | Pago Atual: R$"
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
            key=f"total_{venda_id_alvo}",
        )

        st.info(
            "💵 **Valor Pago Registrado Anteriormente:** R$"
            f" {val_pago_atual:,.2f}"
        )

        key_novo_pagto = f"novo_pagto_{venda_id_alvo}"
        if key_novo_pagto not in st.session_state:
          st.session_state[key_novo_pagto] = 0.0

        valor_novo_pagamento = st.number_input(
            "➕ Registrar NOVO Pagamento (Somar ao que já foi pago)",
            min_value=0.0,
            format="%.2f",
            step=5.0,
            key=key_novo_pagto,
            help=(
                "Digite o valor pago HOJE. Ele será somado ao valor já pago"
                " anterior."
            ),
        )

        ajustar_manual = st.checkbox(
            "⚙️ Precisa corrigir o valor total pago manualmente?",
            key=f"chk_{venda_id_alvo}",
        )

        if ajustar_manual:
          novo_valor_pago_final = st.number_input(
              "Definir Valor Total Pago Acumulado (R$)",
              min_value=0.0,
              value=float(val_pago_atual),
              format="%.2f",
              step=1.0,
              key=f"manual_pago_{venda_id_alvo}",
          )
        else:
          novo_valor_pago_final = min(
              val_pago_atual + valor_novo_pagamento, novo_valor_total
          )

        if valor_novo_pagamento > 0 and not ajustar_manual:
          st.success(
              f"💡 Soma calculada: R$ {val_pago_atual:,.2f} + R$"
              f" {valor_novo_pagamento:,.2f} = **Novo Total Pago: R$"
              f" {novo_valor_pago_final:,.2f}**"
          )

        novas_parcelas = st.number_input(
            "Quantidade Total de Parcelas",
            min_value=1,
            value=int(parcelas_atual),
            step=1,
            key=f"parc_{venda_id_alvo}",
        )

        nova_data_1 = st.date_input(
            "Data do 1º Vencimento",
            data_1_parsed,
            format="DD/MM/YYYY",
            key=f"dt1_{venda_id_alvo}",
        )

        saldo_restante_calc = novo_valor_total - novo_valor_pago_final
        if saldo_restante_calc <= 0 and novo_valor_total > 0:
          status_sugerido = "Pago"
        elif novo_valor_pago_final > 0:
          status_sugerido = "Parcial"
        else:
          status_sugerido = "A Receber"

        novo_status = st.selectbox(
            "Status do Pagamento",
            ["A Receber", "Parcial", "Pago"],
            index=["A Receber", "Parcial", "Pago"].index(status_sugerido),
            key=f"status_{venda_id_alvo}",
        )

        btn_atualizar = st.button(
            "💾 Salvar Pagamento / Alterações", type="primary"
        )

        if btn_atualizar:
          try:
            sheet = obter_conexao()
            cell = sheet.find(str(venda_id_alvo))

            if cell:
              linha_sheets = cell.row

              sheet.update_cell(linha_sheets, 5, float(novo_valor_total))
              sheet.update_cell(linha_sheets, 6, float(novo_valor_pago_final))
              sheet.update_cell(linha_sheets, 7, int(novas_parcelas))
              sheet.update_cell(
                  linha_sheets, 8, nova_data_1.strftime("%d/%m/%Y")
              )
              sheet.update_cell(linha_sheets, 9, str(novo_status))

              st.session_state[key_novo_pagto] = 0.0

              st.success(
                  f"✅ Sucesso! Novo Valor Total Pago registrado: R$"
                  f" {novo_valor_pago_final:,.2f}"
              )
              st.rerun()
            else:
              st.error(
                  f"Não foi possível localizar o ID {venda_id_alvo} na planilha."
              )
          except Exception as e:
            st.error(f"Erro ao atualizar planilha: {e}")

      with col_edit2:
        st.subheader("🗓️ Cronograma Recalculado")

        saldo_div_prev = max(0.0, novo_valor_total - novo_valor_pago_final)
        c_m1, c_m2 = st.columns(2)
        c_m1.metric("Novo Total Pago", f"R$ {novo_valor_pago_final:,.2f}")
        c_m2.metric("Saldo Devedor Restante", f"R$ {saldo_div_prev:,.2f}")

        df_cronograma_prev, _ = gerar_cronograma_recalculado(
            nova_data_1,
            novas_parcelas,
            novo_valor_total,
            novo_valor_pago_final,
        )
        # Exibe colunas limpas para a prévia
        cols_crono_preview = [
            "Nº Parcela",
            "Vencimento",
            "Valor Parcela (R$)",
            "Situação",
        ]
        st.dataframe(
            df_cronograma_prev[cols_crono_preview],
            use_container_width=True,
            hide_index=True,
        )

    else:
      st.info("Nenhuma venda registrada para atualizar.")

  # --- ABA 3: DASHBOARD & CONTAS A RECEBER POR MÊS DE VENCIMENTO ---
  with aba_dash:
    st.header("Análise Financeira e Contas a Receber")

    if not df_vendas.empty:
      # Gera a base expandida por parcela
      df_parcelas = expandir_todas_parcelas(df_vendas)

      # Ordena os meses cronologicamente para o filtro
      df_parcelas_ordenadas = df_parcelas.sort_values(by="Data_Venc_Obj")
      meses_vencimento = (
          df_parcelas_ordenadas["Ano_Mes"].dropna().unique().tolist()
      )

      meses_opcoes = ["Todos os Meses de Vencimento"] + meses_vencimento

      mes_selecionado = st.selectbox(
          "📅 Selecione o Mês de Vencimento das Parcelas (MM/AAAA):",
          meses_opcoes,
      )

      if mes_selecionado != "Todos os Meses de Vencimento":
        df_parc_filtrado = df_parcelas[
            df_parcelas["Ano_Mes"] == mes_selecionado
        ]
      else:
        df_parc_filtrado = df_parcelas.copy()

      # Cálculo dos totais
      total_a_receber_mes = df_parc_filtrado[
          df_parc_filtrado["Situação"] == "⏳ Pendente"
      ]["Valor Parcela"].sum()

      total_já_recebido_mes = df_parc_filtrado[
          df_parc_filtrado["Situação"] == "✅ Quitada"
      ]["Valor Parcela"].sum()

      total_geral_mes = df_parc_filtrado["Valor Parcela"].sum()

      col_m1, col_m2, col_m3 = st.columns(3)
      col_m1.metric("Total Previsto no Mês", f"R$ {total_geral_mes:,.2f}")
      col_m2.metric("✅ Já Recebido / Quitado", f"R$ {total_já_recebido_mes:,.2f}")
      col_m3.metric("📌 A RECEBER no Mês", f"R$ {total_a_receber_mes:,.2f}")

      st.divider()

      # Exibição das parcelas com opção de filtro por Pendentes ou Todas
      st.subheader(
          f"📋 Detalhamento de Parcelas ({mes_selecionado})"
      )

      tipo_filtro_situacao = st.radio(
          "Filtrar Situação das Parcelas:",
          ["Apenas Pendentes (A Receber)", "Todas as Parcelas (Quitadas + Pendentes)"],
          horizontal=True,
      )

      if "Apenas Pendentes" in tipo_filtro_situacao:
        df_exibir = df_parc_filtrado[
            df_parc_filtrado["Situação"] == "⏳ Pendente"
        ].copy()
      else:
        df_exibir = df_parc_filtrado.copy()

      if not df_exibir.empty:
        # Formata valor para exibição bonita
        df_exibir_tabela = df_exibir[[
            "Cliente",
            "Produto",
            "Nº Parcela",
            "Vencimento",
            "Valor Parcela",
            "Situação",
            "ID Venda",
        ]].copy()
        df_exibir_tabela["Valor Parcela (R$)"] = df_exibir_tabela[
            "Valor Parcela"
        ].apply(lambda x: f"R$ {x:,.2f}")
        df_exibir_tabela = df_exibir_tabela.drop(columns=["Valor Parcela"])

        st.dataframe(
            df_exibir_tabela, use_container_width=True, hide_index=True
        )
      else:
        st.success("Nenhuma parcela pendente encontrada para este período!")

    else:
      st.info("Nenhuma venda cadastrada ainda.")

  # --- ABA 4: HISTÓRICO COMPLETO ---
  with aba_historico:
    st.header("Todas as Vendas Registradas")
    if not df_vendas.empty:
      st.dataframe(df_vendas, use_container_width=True, hide_index=True)
    else:
      st.info("Nenhum registro encontrado.")
