import streamlit as st
import pandas as pd
import gspread
import json
import uuid
from google.oauth2.service_account import Credentials
from datetime import datetime

st.set_page_config(page_title="Sistema de Vendas & Cobranças", layout="wide", page_icon="📊")

COLUNAS_ESPERADAS = ["ID", "Data", "Cliente", "Produto", "Valor Total", "Parcelas", "Dias de Pagamento", "Status"]

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
                dias_pagamento = st.text_input("Dias / Datas de Pagamento", placeholder="Ex: Todo dia 10 / 10/10, 10/11, 10/12")
                status = st.selectbox("Status Inicial", ["A Receber", "Pago"])
            
            submeter = st.form_submit_button("Salvar Venda", type="primary")

            if submeter:
                if cliente.strip() != "" and produto.strip() != "":
                    try:
                        sheet = obter_conexao()
                        venda_id = str(uuid.uuid4())[:8]  # Gera um código curto de 8 dígitos
                        nova_linha = [
                            venda_id,
                            str(data_venda),
                            cliente,
                            produto,
                            float(valor),
                            int(parcelas),
                            dias_pagamento,
                            status
                        ]
                        sheet.append_row(nova_linha)
                        st.success(f"Venda para **{cliente}** salva com sucesso! (ID: {venda_id})")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar na planilha: {e}")
                else:
                    st.warning("Preencha o nome do cliente e do produto.")

    # --- ABA 2: BAIRAR / EDITAR STATUS ---
    with aba_atualizar:
        st.header("Atualizar Pagamento ou Dados da Venda")
        if not df_vendas.empty:
            # Lista de opções formatada para o selectbox
            opcoes_vendas = df_vendas.apply(
                lambda row: f"ID: {row['ID']} | {row['Cliente']} - R$ {row['Valor Total']} ({row['Status']})", axis=1
            ).tolist()
            
            venda_selecionada = st.selectbox("Selecione a venda para atualizar", opcoes_vendas)
            
            # Obter os dados da venda selecionada
            idx_selecionado = opcoes_vendas.index(venda_selecionada)
            dados_venda = df_vendas.iloc[idx_selecionado]

            with st.form("form_atualizar_venda"):
                st.subheader(f"Editando Venda ID: {dados_venda['ID']}")
                
                col1, col2 = st.columns(2)
                with col1:
                    novo_status = st.selectbox(
                        "Status do Pagamento", 
                        ["A Receber", "Pago"], 
                        index=0 if dados_venda['Status'] == "A Receber" else 1
                    )
                    novas_parcelas = st.number_input("Nº Parcelas", min_value=1, value=int(dados_venda.get('Parcelas', 1)))
                
                with col2:
                    novo_valor = st.number_input("Valor Total (R$)", min_value=0.0, value=float(dados_venda['Valor Total']), format="%.2f")
                    novos_dias = st.text_input("Dias/Datas de Pagamento", value=str(dados_venda.get('Dias de Pagamento', '')))

                btn_atualizar = st.form_submit_button("Atualizar no Banco de Dados", type="primary")

                if btn_atualizar:
                    try:
                        sheet = obter_conexao()
                        # Procura a linha correspondente no Google Sheets (+2 considera o cabeçalho e índice 1 do Sheets)
                        linha_sheets = idx_selecionado + 2
                        
                        sheet.update_cell(linha_sheets, 5, novo_valor)        # Coluna E: Valor Total
                        sheet.update_cell(linha_sheets, 6, novas_parcelas)    # Coluna F: Parcelas
                        sheet.update_cell(linha_sheets, 7, novos_dias)        # Coluna G: Dias de Pagamento
                        sheet.update_cell(linha_sheets, 8, novo_status)      # Coluna H: Status
                        
                        st.success("Venda atualizada com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao atualizar planilha: {e}")
        else:
            st.info("Nenhuma venda registrada para atualizar.")

    # --- ABA 3: DASHBOARD & FILTROS ---
    with aba_dash:
        st.header("Análise Financeira e Filtro por Mês")
        if not df_vendas.empty and "Valor Total" in df_vendas.columns:
            # Tratamento de dados
            df_vendas["Valor Total"] = pd.to_numeric(df_vendas["Valor Total"], errors="coerce").fillna(0)
            df_vendas["Data"] = pd.to_datetime(df_vendas["Data"], errors="coerce")
            
            # Criar coluna Ano-Mês
            df_vendas["Ano_Mes"] = df_vendas["Data"].dt.strftime('%Y-%m')

            # Filtro de Mês
            meses_disponiveis = sorted(df_vendas["Ano_Mes"].dropna().unique().tolist(), reverse=True)
            meses_disponiveis.insert(0, "Todos os Meses")
            
            mes_selecionado = st.selectbox("📅 Selecione o Mês para Filtrar Contas a Receber / Faturamento:", meses_disponiveis)

            if mes_selecionado != "Todos os Meses":
                df_filtrado = df_vendas[df_vendas["Ano_Mes"] == mes_selecionado]
            else:
                df_filtrado = df_vendas.copy()

            total_geral = df_filtrado["Valor Total"].sum()
            total_pago = df_filtrado[df_filtrado["Status"] == "Pago"]["Valor Total"].sum()
            total_a_receber = df_filtrado[df_filtrado["Status"] == "A Receber"]["Valor Total"].sum()

            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("Faturamento do Período", f"R$ {total_geral:,.2f}")
            col_m2.metric("Total Já Recebido", f"R$ {total_pago:,.2f}")
            col_m3.metric("📌 Contas A RECEBER", f"R$ {total_a_receber:,.2f}")

            st.divider()
            st.subheader(f"📋 Vendas a Receber ({mes_selecionado})")
            df_pendentes = df_filtrado[df_filtrado["Status"] == "A Receber"]
            if not df_pendentes.empty:
                st.dataframe(
                    df_pendentes[["ID", "Data", "Cliente", "Produto", "Valor Total", "Parcelas", "Dias de Pagamento"]],
                    use_container_width=True
                )
            else:
                st.success("Não há pendências de pagamento para este período!")
        else:
            st.info("Nenhuma venda cadastrada ainda.")

    # --- ABA 4: HISTÓRICO COMPLETO ---
    with aba_historico:
        st.header("Todas as Vendas Registradas")
        if not df_vendas.empty:
            st.dataframe(df_vendas, use_container_width=True)
        else:
            st.info("Nenhum registro encontrado.")
