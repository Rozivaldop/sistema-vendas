import streamlit as st
import pandas as pd
import gspread
import json
import uuid
from datetime import datetime
from dateutil.relativedelta import relativedelta
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Sistema de Vendas & Cobranças", layout="wide", page_icon="📊")

COLUNAS_ESPERADAS = ["ID", "Data", "Cliente", "Produto", "Valor Total", "Parcelas", "Data 1ª Parcela", "Status"]

# --- CONEXÃO AUTENTICADA COM O GOOGLE SHEETS ---
@st.cache_resource
def obter_conexao():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    service_account_info = json.loads(st.secrets["json_string"])
    creds = Credentials.from_service_account_info(service_account_info, scopes=scope)
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
    except Exception as e:
        return pd.DataFrame(columns=COLUNAS_ESPERADAS)

def gerar_cronograma_parcelas(data_primeira, num_parcelas, valor_total):
    """Gera a lista detalhada com datas de vencimento e valor de cada parcela"""
    if not num_parcelas or num_parcelas < 1:
        num_parcelas = 1
    
    if isinstance(data_primeira, str):
        try:
            data_base = datetime.strptime(data_primeira, "%Y-%m-%d").date()
        except ValueError:
            data_base = datetime.now().date()
    else:
        data_base = data_primeira

    valor_parcela = valor_total / num_parcelas
    cronograma = []
    
    for i in range(num_parcelas):
        data_venc = data_base + relativedelta(months=i)
        cronograma.append({
            "Nº Parcela": f"{i+1}/{num_parcelas}",
            "Data Vencimento": data_venc.strftime("%d/%m/%Y"),
            "Valor Parcela (R$)": f"{valor_parcela:.2f}"
        })
    return pd.DataFrame(cronograma)

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
            if usuario == "rozivaldo" and senha == "1408":
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
        "🔄 Baixar / Editar Venda",
        "📈 Dashboard & Filtros", 
        "📋 Histórico Completo"
    ])

    # --- ABA 1: CADASTRO ---
    with aba_cadastro:
        st.header("Registrar Nova Venda")
        with st.form("form_nova_venda", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            with col_a:
                data_venda = st.date_input("Data da Venda", datetime.now())
                cliente = st.text_input("Nome do Cliente")
                produto = st.text_input("Produto / Serviço Vendido")
                valor = st.number_input("Valor Total (R$)", min_value=0.0, format="%.2f")
            
            with col_b:
                parcelas = st.number_input("Quantidade de Parcelas", min_value=1, value=1, step=1)
                data_primeira_parcela = st.date_input("Data do 1º Vencimento / Parcela", datetime.now())
                status = st.selectbox("Status Inicial", ["A Receber", "Pago"])
            
            submeter = st.form_submit_button("Salvar Venda", type="primary")

            if submeter:
                if cliente.strip() != "" and produto.strip() != "":
                    try:
                        sheet = obter_conexao()
                        venda_id = str(uuid.uuid4())[:8]
                        nova_linha = [
                            venda_id,
                            str(data_venda),
                            cliente,
                            produto,
                            float(valor),
                            int(parcelas),
                            str(data_primeira_parcela),
                            status
                        ]
                        sheet.append_row(nova_linha)
                        st.success(f"Venda para **{cliente}** salva com sucesso! (ID: {venda_id})")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar na planilha: {e}")
                else:
                    st.warning("Preencha o nome do cliente e do produto.")

    # --- ABA 2: EDITAR / DAR BAIXA ---
    with aba_atualizar:
        st.header("Atualizar Pagamento ou Dados da Venda")
        if not df_vendas.empty:
            opcoes_vendas = df_vendas.apply(
                lambda row: f"ID: {row['ID']} | {row['Cliente']} - R$ {row['Valor Total']} ({row['Status']})", axis=1
            ).tolist()
            
            venda_selecionada = st.selectbox("Selecione a venda para atualizar", opcoes_vendas)
            idx_selecionado = opcoes_vendas.index(venda_selecionada)
            dados_venda = df_vendas.iloc[idx_selecionado]

            # Converter data da primeira parcela para date se necessário
            data_1_raw = str(dados_venda.get('Data 1ª Parcela', ''))
            try:
                data_1_parsed = datetime.strptime(data_1_raw, "%Y-%m-%d").date()
            except ValueError:
                data_1_parsed = datetime.now().date()

            col_edit1, col_edit2 = st.columns(2)
            
            with col_edit1:
                with st.form("form_atualizar_venda"):
                    st.subheader(f"Editando Venda ID: {dados_venda['ID']}")
                    
                    novo_status = st.selectbox(
                        "Status do Pagamento", 
                        ["A Receber", "Pago"], 
                        index=0 if dados_venda['Status'] == "A Receber" else 1
                    )
                    novo_valor = st.number_input("Valor Total (R$)", min_value=0.0, value=float(dados_venda['Valor Total']), format="%.2f")
                    novas_parcelas = st.number_input("Nº Parcelas", min_value=1, value=int(dados_venda.get('Parcelas', 1)))
                    nova_data_1 = st.date_input("Data do 1º Vencimento", data_1_parsed)

                    btn_atualizar = st.form_submit_button("Salvar Alterações", type="primary")

                    if btn_atualizar:
                        try:
                            sheet = obter_conexao()
                            linha_sheets = idx_selecionado + 2
                            
                            sheet.update_cell(linha_sheets, 5, novo_valor)          # Valor Total
                            sheet.update_cell(linha_sheets, 6, novas_parcelas)      # Parcelas
                            sheet.update_cell(linha_sheets, 7, str(nova_data_1))     # Data 1ª Parcela
                            sheet.update_cell(linha_sheets, 8, novo_status)        # Status
                            
                            st.success("Venda atualizada com sucesso!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao atualizar planilha: {e}")

            with col_edit2:
                st.subheader("🗓️ Cronograma Calculado das Parcelas")
                st.caption("Visão detalhada de vencimentos e valores:")
                df_cronograma = gerar_cronograma_parcelas(data_1_parsed, int(dados_venda.get('Parcelas', 1)), float(dados_venda['Valor Total']))
                st.dataframe(df_cronograma, use_container_width=True, hide_index=True)

        else:
            st.info("Nenhuma venda registrada para atualizar.")

    # --- ABA 3: DASHBOARD & FILTROS ---
    with aba_dash:
        st.header("Análise Financeira e Filtro por Mês")
        if not df_vendas.empty and "Valor Total" in df_vendas.columns:
            df_vendas["Valor Total"] = pd.to_numeric(df_vendas["Valor Total"], errors="coerce").fillna(0)
            df_vendas["Data"] = pd.to_datetime(df_vendas["Data"], errors="coerce")
            df_vendas["Ano_Mes"] = df_vendas["Data"].dt.strftime('%Y-%m')

            meses_disponiveis = sorted(df_vendas["Ano_Mes"].dropna().unique().tolist(), reverse=True)
            meses_disponiveis.insert(0, "Todos os Meses")
            
            mes_selecionado = st.selectbox("📅 Selecione o Mês de Referência:", meses_disponiveis)

            if mes_selecionado != "Todos os Meses":
                df_filtrado = df_vendas[df_vendas["Ano_Mes"] == mes_selecionado]
            else:
                df_filtrado = df_vendas.copy()

            total_geral = df_filtrado["Valor Total"].sum()
            total_pago = df_filtrado[df_filtrado["Status"] == "Pago"]["Valor Total"].sum()
            total_a_receber = df_filtrado[df_filtrado["Status"] == "A Receber"]["Valor Total"].sum()

            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("Faturamento Registrado", f"R$ {total_geral:,.2f}")
            col_m2.metric("Total Já Recebido", f"R$ {total_pago:,.2f}")
            col_m3.metric("📌 Contas A RECEBER", f"R$ {total_a_receber:,.2f}")

            st.divider()
            st.subheader(f"📋 Vendas com Pendências ({mes_selecionado})")
            df_pendentes = df_filtrado[df_filtrado["Status"] == "A Receber"]
            if not df_pendentes.empty:
                st.dataframe(
                    df_pendentes[["ID", "Data", "Cliente", "Produto", "Valor Total", "Parcelas", "Data 1ª Parcela"]],
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.success("Não há pendências de pagamento para este período!")
        else:
            st.info("Nenhuma venda cadastrada ainda.")

    # --- ABA 4: HISTÓRICO COMPLETO ---
    with aba_historico:
        st.header("Todas as Vendas Registradas")
        if not df_vendas.empty:
            st.dataframe(df_vendas, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum registro encontrado.")
