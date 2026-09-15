import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# Configuração da página
st.set_page_config(page_title="Sistema de Vendas", layout="wide", page_icon="📊")

COLUNAS_ESPERADAS = ["Data", "Cliente", "Produto", "Valor", "Status"]

# --- CONEXÃO AUTENTICADA COM O GOOGLE SHEETS ---
@st.cache_resource
def obter_conexao():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    # Carrega as credenciais da Service Account configuradas nos Secrets
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    
    # Abre a planilha pelo link fornecido nas Secrets
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

# --- CONTROLE DE LOGIN ---
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
    # --- ÁREA INTERNA LOGADA ---
    st.sidebar.title("Opções")
    if st.sidebar.button("Sair / Logout"):
        st.session_state.autenticado = False
        st.rerun()

    st.title("📊 Painel de Controle de Vendas")
    df_vendas = carregar_dados()

    aba_cadastro, aba_dash, aba_historico = st.tabs([
        "➕ Cadastrar Venda", 
        "📈 Resumo de Vendas", 
        "📋 Histórico Completo"
    ])

    # --- ABA 1: CADASTRO ---
    with aba_cadastro:
        st.header("Registrar Nova Venda")
        with st.form("form_nova_venda", clear_on_submit=True):
            data_venda = st.date_input("Data da Venda", datetime.now())
            cliente = st.text_input("Nome do Cliente")
            produto = st.text_input("Produto / Serviço Vendido")
            valor = st.number_input("Valor da Venda (R$)", min_value=0.0, format="%.2f")
            status = st.selectbox("Status do Pagamento", ["Pago", "A Receber"])
            
            submeter = st.form_submit_button("Salvar no Banco de Dados", type="primary")

            if submeter:
                if cliente.strip() != "" and produto.strip() != "":
                    try:
                        sheet = obter_conexao()
                        nova_linha = [str(data_venda), cliente, produto, float(valor), status]
                        # Adiciona a linha diretamente na aba da planilha
                        sheet.append_row(nova_linha)
                        st.success(f"Venda para **{cliente}** salva com sucesso na planilha!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar na planilha: {e}")
                else:
                    st.warning("Preencha o nome do cliente e do produto.")

    # --- ABA 2: RESUMO E DASHBOARD ---
    with aba_dash:
        st.header("Métricas Globais")
        if not df_vendas.empty and "Valor" in df_vendas.columns:
            df_vendas["Valor"] = pd.to_numeric(df_vendas["Valor"], errors="coerce").fillna(0)
            
            total_vendido = df_vendas["Valor"].sum()
            total_pago = df_vendas[df_vendas["Status"] == "Pago"]["Valor"].sum()
            total_a_receber = df_vendas[df_vendas["Status"] == "A Receber"]["Valor"].sum()

            c1, c2, c3 = st.columns(3)
            c1.metric("Faturamento Total", f"R$ {total_vendido:,.2f}")
            c2.metric("Total Recebido", f"R$ {total_pago:,.2f}")
            c3.metric("Total A Receber", f"R$ {total_a_receber:,.2f}")
        else:
            st.info("Nenhuma venda registrada até o momento.")

    # --- ABA 3: HISTÓRICO COMPLETO ---
    with aba_historico:
        st.header("Todas as Vendas Salvas")
        if not df_vendas.empty:
            st.dataframe(df_vendas, use_container_width=True)
        else:
            st.info("Nenhum registro encontrado na planilha.")
