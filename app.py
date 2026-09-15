import streamlit as st
import pandas as pd
from datetime import datetime

# Configuração da página do Streamlit
st.set_page_config(
    page_title="Sistema de Vendas",
    layout="wide",
    page_icon="📊"
)

# Colunas padrão esperadas na planilha
COLUNAS_ESPERADAS = ["Data", "Cliente", "Produto", "Valor", "Status"]

# --- FUNÇÃO PARA CARREGAR DADOS ---
def carregar_dados():
    try:
        url = st.secrets["connections"]["gsheets"]["spreadsheet"]
        # Extrai o ID da planilha do Google a partir do link das Secrets
        sheet_id = url.split("/d/")[1].split("/")[0]
        csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        
        # Lê a planilha usando Pandas
        df = pd.read_csv(csv_url)
        
        # Garante que as colunas estejam corretas mesmo se a planilha tiver menos colunas
        if len(df.columns) == len(COLUNAS_ESPERADAS):
            df.columns = COLUNAS_ESPERADAS
        else:
            # Caso a planilha venha sem cabeçalho ou com colunas a menos
            df = pd.DataFrame(columns=COLUNAS_ESPERADAS)
            
        return df
    except Exception as e:
        # Retorna DataFrame vazio configurado caso falhe ao ler
        return pd.DataFrame(columns=COLUNAS_ESPERADAS)


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
            if usuario == "rozivaldo" and senha == "1408":
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
    
    # Carrega os dados da planilha
    df_vendas = carregar_dados()

    # Navegação por abas
    aba_cadastro, aba_dash, aba_historico = st.tabs([
        "➕ Cadastrar Venda", 
        "📈 Resumo de Vendas", 
        "📋 Histórico Completo"
    ])

    # --- ABA 1: CADASTRO DE VENDAS ---
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
                        # Cria o novo registro exatamente com as 5 colunas necessárias
                        nova_linha = pd.DataFrame(
                            [[str(data_venda), cliente, produto, float(valor), status]], 
                            columns=COLUNAS_ESPERADAS
                        )
                        
                        # Concatena a nova venda ao histórico
                        if df_vendas.empty:
                            df_atualizado = nova_linha
                        else:
                            df_atualizado = pd.concat([df_vendas, nova_linha], ignore_index=True)
                        
                        st.success(f"Venda para **{cliente}** registrada com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar registro: {e}")
                else:
                    st.warning("Por favor, preencha o nome do cliente e do produto.")

    # --- ABA 2: RESUMO E MÉTRICAS ---
    with aba_dash:
        st.header("Métricas Globais")
        
        if not df_vendas.empty and "Valor" in df_vendas.columns:
            # Tratamento de valores para garantir cálculo numérico
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
            st.info("Nenhum dado cadastrado para exibição.")
