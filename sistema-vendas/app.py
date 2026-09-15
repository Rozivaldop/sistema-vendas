import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

# Configuração da página
st.set_page_config(page_title="Sistema de Vendas", layout="wide", page_icon="📊")

# --- CONEXÃO COM O GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def carregar_dados():
    try:
        df = conn.read(ttl=0)
        return df
    except Exception:
        return pd.DataFrame(columns=["Data", "Cliente", "Produto", "Valor", "Status"])

# --- SISTEMA DE LOGIN ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    st.title("🔒 Login do Sistema de Vendas")
    col1, col2 = st.columns([1, 2])
    with col1:
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        if st.button("Entrar", type="primary"):
            # DEFINA SEU USUÁRIO E SENHA AQUI
            if usuario == "admin" and senha == "1234":
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")
else:
    # --- ÁREA LOGADA ---
    st.sidebar.title("Opções")
    if st.sidebar.button("Sair / Logout"):
        st.session_state.autenticado = False
        st.rerun()

    st.title("📊 Painel de Controle de Vendas")
    
    # Carregar dados atualizados
    df_vendas = carregar_dados()

    # Criar as Abas do Sistema
    aba_cadastro, aba_dash, aba_historico = st.tabs(["➕ Cadastrar Venda", "📈 Resumo de Vendas", "📋 Histórico Completo"])

    # --- ABA 1: CADASTRO ---
    with aba_cadastro:
        st.header("Registrar Nova Venda")
        with st.form("form_nova_venda"):
            data_venda = st.date_input("Data da Venda")
            cliente = st.text_input("Nome do Cliente")
            produto = st.text_input("Produto / Serviço Vendido")
            valor = st.number_input("Valor da Venda (R$)", min_value=0.0, format="%.2f")
            status = st.selectbox("Status do Pagamento", ["Pago", "A Receber"])
            
            submeter = st.form_submit_button("Salvar no Banco de Dados")

            if submeter:
                if cliente != "" and produto != "":
                    # Criar nova linha de dados
                    nova_venda = pd.DataFrame([{
                        "Data": str(data_venda),
                        "Cliente": cliente,
                        "Produto": produto,
                        "Valor": float(valor),
                        "Status": status
                    }])

                    # Adicionar aos dados antigos
                    df_atualizado = pd.concat([df_vendas, nova_venda], ignore_index=True)
                    
                    # Salvar no Google Sheets
                    conn.update(data=df_atualizado)
                    st.success("Venda salva com sucesso!")
                    st.rerun()
                else:
                    st.warning("Preencha o nome do cliente e do produto.")

    # --- ABA 2: RESUMO E MÉTRICAS ---
    with aba_dash:
        st.header("Métricas Globais")
        if not df_vendas.empty and "Valor" in df_vendas.columns:
            # Converter coluna valor para número
            df_vendas["Valor"] = pd.to_numeric(df_vendas["Valor"], errors="coerce").fillna(0)
            
            total_vendido = df_vendas["Valor"].sum()
            total_pago = df_vendas[df_vendas["Status"] == "Pago"]["Valor"].sum()
            total_a_receber = df_vendas[df_vendas["Status"] == "A Receber"]["Valor"].sum()

            c1, c2, c3 = st.columns(3)
            c1.metric("Faturamento Total", f"R$ {total_vendido:,.2f}")
            c2.metric("Total Recebido", f"R$ {total_pago:,.2f}")
            c3.metric("Total A Receber", f"R$ {total_a_receber:,.2f}")
        else:
            st.info("Nenhuma venda registrada ainda.")

    # --- ABA 3: HISTÓRICO ---
    with aba_historico:
        st.header("Todas as Vendas Salvas")
        st.dataframe(df_vendas, use_container_width=True)