import json
import re
import urllib.parse
import uuid
import calendar
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Sistema de Vendas & Cobranças", layout="wide", page_icon="📊"
)

# --- INICIALIZAÇÃO DE ESTADOS DA SESSÃO ---
if "versao_pagto" not in st.session_state:
    st.session_state.versao_pagto = 0

if "carrinho" not in st.session_state:
    st.session_state.carrinho = []

COLUNAS_VENDAS = [
    "ID",
    "Data",
    "Telefone",
    "Cliente",
    "Categoria",
    "Produto",
    "Valor Total",
    "Valor Pago",
    "Parcelas",
    "Data 1ª Parcela",
    "Status",
]


# --- FUNÇÃO INFALÍVEL PARA SOMAR MESES ---
def adicionar_meses(data_origem, meses):
    """
    Adiciona meses garantindo tratamento de estouro de dias usando relativedelta.
    Sempre retorna um objeto datetime.date válido.
    """
    try:
        # Se for None ou inválido, assume a data atual
        if data_origem is None or pd.isna(data_origem):
            dt_base = datetime.now().date()
        elif isinstance(data_origem, datetime):
            dt_base = data_origem.date()
        elif isinstance(data_origem, date):
            dt_base = data_origem
        else:
            # Caso venha como string ou outro formato, tenta parsear
            dt_base = parse_data_br(data_origem)

        # relativedelta trata automaticamente dias 29, 30, 31 em meses menores
        nova_data = dt_base + relativedelta(months=int(meses))
        return nova_data
    except Exception:
        # Fallback de segurança máxima caso ocorra qualquer erro inesperado
        return datetime.now().date()


# --- CONEXÃO COM O GOOGLE SHEETS ---
def obter_client_gspread():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    service_account_info = json.loads(st.secrets["json_string"])
    creds = Credentials.from_service_account_info(
        service_account_info, scopes=scope
    )
    return gspread.authorize(creds)


def obter_aba_vendas():
    client = obter_client_gspread()
    url = st.secrets["connections"]["gsheets"]["spreadsheet"]
    return client.open_by_url(url).sheet1


def obter_aba_clientes():
    client = obter_client_gspread()
    url = st.secrets["connections"]["gsheets"]["spreadsheet"]
    doc = client.open_by_url(url)
    try:
        sheet_cli = doc.worksheet("Clientes")
    except Exception:
        sheet_cli = doc.add_worksheet(title="Clientes", rows="100", cols="2")
        sheet_cli.append_row(["Nome", "Telefone"])
    return sheet_cli


def carregar_dados_vendas():
    try:
        sheet = obter_aba_vendas()
        dados = sheet.get_all_values()
        if not dados or len(dados) <= 1:
            return pd.DataFrame(columns=COLUNAS_VENDAS)

        cabeçalho = [str(c).strip() for c in dados[0]]
        df = pd.DataFrame(dados[1:], columns=cabeçalho)

        df = df.loc[:, df.columns != ""]
        df = df.loc[:, ~df.columns.duplicated()]

        if "Telenone" in df.columns and "Telefone" not in df.columns:
            df = df.rename(columns={"Telenone": "Telefone"})

        for col in COLUNAS_VENDAS:
            if col not in df.columns:
                df[col] = ""

        return df[COLUNAS_VENDAS]
    except Exception as e:
        st.error(f"Erro ao carregar vendas do Google Sheets: {e}")
        return pd.DataFrame(columns=COLUNAS_VENDAS)


def carregar_dados_clientes():
    try:
        sheet_cli = obter_aba_clientes()
        dados = sheet_cli.get_all_values()
        if not dados or len(dados) <= 1:
            return pd.DataFrame(columns=["Nome", "Telefone"])

        df_cli = pd.DataFrame(dados[1:], columns=[str(c).strip() for c in dados[0]])
        for col in ["Nome", "Telefone"]:
            if col not in df_cli.columns:
                df_cli[col] = ""

        df_cli = df_cli[df_cli["Nome"].str.strip() != ""]
        return df_cli[["Nome", "Telefone"]]
    except Exception as e:
        st.error(f"Erro ao carregar clientes: {e}")
        return pd.DataFrame(columns=["Nome", "Telefone"])


def parse_data_br(data_raw):
    if data_raw is None or pd.isna(data_raw):
        return datetime.now().date()

    if isinstance(data_raw, datetime):
        return data_raw.date()
    if isinstance(data_raw, date):
        return data_raw

    s = str(data_raw).strip()
    if not s:
        return datetime.now().date()

    formatos = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"]
    for fmt in formatos:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass

    return datetime.now().date()


def safe_float(val, default=0.0):
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
    try:
        if pd.isna(val) or val == "" or val is None:
            return default
        num_float = safe_float(val, float(default))
        return max(1, int(round(num_float)))
    except (ValueError, TypeError):
        return default


def limpar_telefone(tel_str):
    if not tel_str or pd.isna(tel_str):
        return ""
    num = re.sub(r"\D", "", str(tel_str))
    if len(num) >= 10 and not num.startswith("55"):
        num = "55" + num
    return num


def gerar_link_whatsapp(telefone, cliente, produto, detalhe_parcela, valor, vencimento):
    num_limpo = limpar_telefone(telefone)
    if not num_limpo:
        return None

    msg = (
        f"Olá, *{cliente}*! Espero que esteja bem.\n\n"
        f"Estou passando para enviar o lembrete de pagamento referente ao mês *{vencimento}*.\n\n"
        f"📦 *Itens/Parcelas:* {detalhe_parcela}\n"
        f"💰 *Valor Total do Mês:* R$ {valor:,.2f}\n\n"
        f"Se já tiver efetuado o pagamento, por favor desconsidere esta mensagem. "
        f"Caso precise da chave PIX ou tenha qualquer dúvida, me avise por aqui!"
    )

    msg_encoded = urllib.parse.quote(msg)
    return f"https://wa.me/{num_limpo}?text={msg_encoded}"


def gerar_cronograma_recalculado(data_primeira, num_parcelas, valor_total, valor_pago):
    num_parcelas = max(1, safe_int(num_parcelas, 1))
    valor_total = safe_float(valor_total, 0.0)
    valor_pago = safe_float(valor_pago, 0.0)

    data_base = parse_data_br(data_primeira)

    saldo_devedor = max(0.0, valor_total - valor_pago)
    valor_original_parcela = valor_total / num_parcelas if num_parcelas > 0 else 0

    if valor_original_parcela > 0:
        parcelas_quitadas = int(valor_pago // valor_original_parcela)
    else:
        parcelas_quitadas = 0

    if parcelas_quitadas >= num_parcelas or saldo_devedor == 0:
        parcelas_quitadas = num_parcelas

    parcelas_restantes = num_parcelas - parcelas_quitadas

    if parcelas_restantes > 0 and saldo_devedor > 0:
        novo_valor_parcela_pendente = saldo_devedor / parcelas_restantes
    else:
        novo_valor_parcela_pendente = 0.0

    cronograma = []

    for i in range(num_parcelas):
        data_venc = adicionar_meses(data_base, i)
        data_str = data_venc.strftime("%d/%m/%Y")

        if i < parcelas_quitadas:
            st_parc = "✅ Quitada"
            val_parc = valor_original_parcela
        else:
            st_parc = "⏳ Pendente"
            val_parc = novo_valor_parcela_pendente

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
    lista_parcelas = []

    for _, row in df_vendas.iterrows():
        venda_id = row.get("ID", "")
        cliente = row.get("Cliente", "")
        telefone = str(row.get("Telefone", "")).strip()
        categoria = row.get("Categoria", "")
        produto = row.get("Produto", "")
        val_total = safe_float(row.get("Valor Total", 0))
        val_pago = safe_float(row.get("Valor Pago", 0))
        num_parc = safe_int(row.get("Parcelas", 1), 1)

        dt_1_raw = row.get("Data 1ª Parcela", "")
        if not dt_1_raw or str(dt_1_raw).strip() == "":
            dt_1_raw = row.get("Data", "")

        df_crono, _ = gerar_cronograma_recalculado(
            dt_1_raw, num_parc, val_total, val_pago
        )

        for _, p in df_crono.iterrows():
            lista_parcelas.append({
                "ID Venda": venda_id,
                "Cliente": cliente,
                "Telefone": telefone,
                "Categoria": categoria,
                "Produto": produto,
                "Nº Parcela": p["Nº Parcela"],
                "Vencimento": p["Vencimento"],
                "Data_Venc_Obj": p["Data_Venc_Obj"],
                "Ano_Mes": p["Ano_Mes"],
                "Valor Parcela": p["Valor Parcela (R$)"],
                "Situação": p["Situação"],
            })

    return pd.DataFrame(lista_parcelas)


# --- TELA DE LOGIN ---
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
    st.sidebar.title("⚙️ Opções")
    if st.sidebar.button("🔄 Recarregar Dados"):
        st.cache_data.clear()
        st.rerun()

    if st.sidebar.button("🚪 Sair / Logout"):
        st.session_state.autenticado = False
        st.rerun()

    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        st.title("📊 Gestão de Vendas & Recebimentos")
    with col_t2:
        if st.button("🔄 Sincronizar", type="secondary"):
            st.cache_data.clear()
            st.rerun()

    df_vendas = carregar_dados_vendas()
    df_clientes = carregar_dados_clientes()

    aba_cadastro, aba_clientes_tab, aba_atualizar, aba_dash, aba_historico = st.tabs([
        "➕ Cadastrar Venda",
        "👤 Cadastro de Clientes",
        "🔄 Registrar Pagamento / Editar",
        "📈 Dashboard & Contas a Receber",
        "📋 Histórico por Cliente",
    ])

    # --- ABA 1: CADASTRO MULTI-ITENS ---
    with aba_cadastro:
        st.header("➕ Registrar Nova Venda")

        st.subheader("1️⃣ Adicionar Itens à Sacola")
        col_c1, col_c2, col_c3 = st.columns(3)

        with col_c1:
            categoria_sel = st.selectbox(
                "🏷️ Categoria / Marca",
                [
                    "Roupas Sarru",
                    "Roupas Crosby",
                    "Lingerie Del Rayssa",
                    "Produtos Sexshop",
                    "Outros",
                ],
            )

        with col_c2:
            if categoria_sel in ["Roupas Sarru", "Roupas Crosby"]:
                sub_item = st.selectbox(
                    "👕 Tipo de Peça",
                    ["Camisa", "Bermuda", "Calça", "Short", "Outros"],
                )
            elif categoria_sel == "Lingerie Del Rayssa":
                sub_item = st.selectbox(
                    "👙 Tipo de Peça",
                    [
                        "Calcinha",
                        "Cueca Adulto",
                        "Cueca Infantil",
                        "Pijama",
                        "Baby Doll",
                        "Outros",
                    ],
                )
            else:
                sub_item = "Produto Diverso"

        with col_c3:
            detalhe_extra = st.text_input(
                "📝 Detalhes / Modelo / Cor / Tam",
                placeholder="Ex: M, Cor Preta",
            )

        col_p1, col_p2, col_p3 = st.columns([1, 1, 1])
        with col_p1:
            qtd_item = st.number_input("Quantidade", min_value=1, value=1, step=1)
        with col_p2:
            valor_unitario = st.number_input(
                "Valor Unitário (R$)", min_value=0.0, format="%.2f", step=5.0
            )
        with col_p3:
            st.write("")
            st.write("")
            btn_add_carrinho = st.button("➕ Adicionar à Sacola", type="secondary")

        if btn_add_carrinho:
            if categoria_sel == "Produtos Sexshop" and detalhe_extra:
                desc_prod = detalhe_extra
            elif detalhe_extra:
                desc_prod = f"{sub_item} ({detalhe_extra})"
            else:
                desc_prod = sub_item

            subtotal = valor_unitario * qtd_item

            st.session_state.carrinho.append({
                "Categoria": categoria_sel,
                "Produto": desc_prod,
                "Qtd": qtd_item,
                "Valor Unit.": valor_unitario,
                "Subtotal": subtotal,
            })
            st.success(f"Item '{desc_prod}' adicionado à sacola!")

        if st.session_state.carrinho:
            st.subheader("🛍️ Itens na Sacola")
            df_carrinho = pd.DataFrame(st.session_state.carrinho)
            st.dataframe(df_carrinho, use_container_width=True, hide_index=True)

            val_total_sacola = df_carrinho["Subtotal"].sum()
            st.markdown(f"### 💰 **Total da Sacola: R$ {val_total_sacola:,.2f}**")

            if st.button("🗑️ Esvaziar Sacola"):
                st.session_state.carrinho = []
                st.rerun()

            st.divider()

            st.subheader("2️⃣ Finalizar Cadastro da Venda")

            lista_nomes = sorted(df_clientes["Nome"].unique().tolist()) if not df_clientes.empty else []
            opcoes_cliente = ["➕ NOME NÃO LISTADO (Cadastrar Novo)"] + lista_nomes

            col_a, col_b = st.columns(2)

            with col_a:
                data_venda = st.date_input("Data da Venda", datetime.now().date(), format="DD/MM/YYYY")
                cliente_selecionado = st.selectbox("👤 Selecionar Cliente Cadastrado", opcoes_cliente)

                if cliente_selecionado == "➕ NOME NÃO LISTADO (Cadastrar Novo)":
                    cliente_nome = st.text_input("Nome do Novo Cliente")
                    cliente_tel = st.text_input("Telefone / WhatsApp (ex: 84999998888)")
                    salvar_novo_cli_junto = True
                else:
                    cliente_nome = cliente_selecionado
                    tel_encontrado = df_clientes[df_clientes["Nome"] == cliente_selecionado]["Telefone"].values
                    tel_padrao = str(tel_encontrado[0]) if len(tel_encontrado) > 0 else ""
                    cliente_tel = st.text_input("Telefone / WhatsApp", value=tel_padrao)
                    salvar_novo_cli_junto = False

            with col_b:
                valor_pago_inicial = st.number_input(
                    "Valor Já Pago na Entrada (R$)",
                    min_value=0.0,
                    value=0.0,
                    format="%.2f",
                    step=1.0,
                )
                parcelas = st.number_input("Quantidade Total de Parcelas", min_value=1, value=1, step=1)
                data_primeira_parcela = st.date_input("Data do 1º Vencimento / Parcela", datetime.now().date(), format="DD/MM/YYYY")

            if st.button("💾 Finalizar e Salvar Venda", type="primary"):
                if cliente_nome.strip() != "":
                    try:
                        if salvar_novo_cli_junto:
                            sheet_cli = obter_aba_clientes()
                            sheet_cli.append_row([cliente_nome.strip(), str(cliente_tel).strip()], value_input_option="USER_ENTERED")

                        sheet_vendas = obter_aba_vendas()
                        venda_id = str(uuid.uuid4())[:8]

                        cats_unicas = list(set([item["Categoria"] for item in st.session_state.carrinho]))
                        string_categorias = ", ".join(cats_unicas)

                        prods_formatados = [
                            f"{item['Qtd']}x [{item['Categoria']}] {item['Produto']}"
                            for item in st.session_state.carrinho
                        ]
                        string_produtos = " | ".join(prods_formatados)

                        if valor_pago_inicial >= val_total_sacola and val_total_sacola > 0:
                            status_inicial = "Pago"
                        elif valor_pago_inicial > 0:
                            status_inicial = "Parcial"
                        else:
                            status_inicial = "A Receber"

                        nova_linha = [
                            venda_id,
                            data_venda.strftime("%d/%m/%Y"),
                            str(cliente_tel).strip(),
                            cliente_nome.strip(),
                            string_categorias,
                            string_produtos,
                            str(float(val_total_sacola)),
                            str(float(valor_pago_inicial)),
                            str(int(parcelas)),
                            data_primeira_parcela.strftime("%d/%m/%Y"),
                            status_inicial,
                        ]
                        sheet_vendas.append_row(nova_linha, value_input_option="USER_ENTERED")

                        st.session_state.carrinho = []
                        st.success(f"Venda para **{cliente_nome}** cadastrada com sucesso!")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar na planilha: {e}")
                else:
                    st.warning("Preencha o nome do cliente.")
        else:
            st.info("💡 Adicione pelo menos um item à sacola para prosseguir com o cadastro.")

    # --- ABA 2: GERENCIADOR DE CLIENTES ---
    with aba_clientes_tab:
        st.header("👤 Base de Clientes")

        col_c1, col_c2 = st.columns([1, 2])

        with col_c1:
            st.subheader("➕ Cadastrar Novo Cliente")
            with st.form("form_novo_cliente", clear_on_submit=True):
                nome_novo = st.text_input("Nome Completo do Cliente")
                tel_novo = st.text_input("Telefone / WhatsApp")
                btn_cli = st.form_submit_button("💾 Cadastrar Cliente", type="primary")

                if btn_cli:
                    if nome_novo.strip():
                        try:
                            sheet_cli = obter_aba_clientes()
                            sheet_cli.append_row([nome_novo.strip(), str(tel_novo).strip()], value_input_option="USER_ENTERED")
                            st.success(f"Cliente **{nome_novo}** cadastrado!")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao salvar cliente: {e}")
                    else:
                        st.warning("Digite o nome do cliente.")

        with col_c2:
            st.subheader("📋 Clientes Cadastrados")
            if not df_clientes.empty:
                st.dataframe(df_clientes, use_container_width=True, hide_index=True)
            else:
                st.info("Nenhum cliente cadastrado ainda.")

    # --- ABA 3: EDITAR / REGISTRAR PAGAMENTO ---
    with aba_atualizar:
        st.header("🔄 Registrar Pagamento / Editar Venda")

        if not df_vendas.empty and len(df_vendas) > 0:
            opcoes_vendas = df_vendas.apply(
                lambda row: (
                    f"ID: {row.get('ID', '')} | {row.get('Cliente', '')} - "
                    f"Data: {row.get('Data', '')} | Total: R$ {safe_float(row.get('Valor Total', 0)):.2f}"
                ),
                axis=1,
            ).tolist()

            venda_selecionada = st.selectbox("Selecione a venda para gerenciar", opcoes_vendas)
            idx_selecionado = opcoes_vendas.index(venda_selecionada)
            dados_venda = df_vendas.iloc[idx_selecionado]
            venda_id_alvo = str(dados_venda.get("ID", ""))

            val_total_atual = safe_float(dados_venda.get("Valor Total", 0))
            val_pago_atual = safe_float(dados_venda.get("Valor Pago", 0))
            parcelas_atual = safe_int(dados_venda.get("Parcelas", 1), 1)

            dt_1_str = dados_venda.get("Data 1ª Parcela", "")
            if not dt_1_str or str(dt_1_str).strip() == "":
                dt_1_str = dados_venda.get("Data", "")
            data_1_parsed = parse_data_br(dt_1_str)

            key_pagto_hoje = f"novo_pagto_{venda_id_alvo}_{st.session_state.versao_pagto}"

            col_edit1, col_edit2 = st.columns(2)

            with col_edit1:
                st.subheader(f"👤 Cliente: {dados_venda.get('Cliente', '')}")
                st.caption(f"📦 Produtos: **[{dados_venda.get('Categoria', '')}] {dados_venda.get('Produto', '')}**")

                novo_valor_total = st.number_input(
                    "Valor Total desta Venda (R$)",
                    min_value=0.0,
                    value=float(val_total_atual),
                    format="%.2f",
                    step=1.0,
                    key=f"total_{venda_id_alvo}",
                )

                st.info(f"💵 **Valor Já Pago Nesta Venda:** R$ {val_pago_atual:,.2f}")

                valor_novo_pagamento = st.number_input(
                    "➕ Valor Pago HOJE nesta compra (Adicionar ao total já pago)",
                    min_value=0.0,
                    value=0.0,
                    format="%.2f",
                    step=5.0,
                    key=key_pagto_hoje,
                )

                ajustar_manual = st.checkbox(
                    "⚙️ Precisa redefinir o valor pago acumulado manualmente?",
                    key=f"chk_{venda_id_alvo}",
                )

                if ajustar_manual:
                    novo_valor_pago_final = st.number_input(
                        "Definir Novo Valor Total Pago (R$)",
                        min_value=0.0,
                        value=float(val_pago_atual),
                        format="%.2f",
                        step=1.0,
                        key=f"manual_pago_{venda_id_alvo}",
                    )
                else:
                    novo_valor_pago_final = min(val_pago_atual + valor_novo_pagamento, novo_valor_total)

                novas_parcelas = st.number_input(
                    "Quantidade Total de Parcelas",
                    min_value=1,
                    value=int(parcelas_atual),
                    step=1,
                    key=f"parc_{venda_id_alvo}",
                )

                nova_data_1 = st.date_input(
                    "Data do 1º Vencimento",
                    value=data_1_parsed,
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

                btn_atualizar = st.button("💾 Salvar Pagamento / Alterações", type="primary")

                if btn_atualizar:
                    try:
                        sheet = obter_aba_vendas()
                        cell = sheet.find(str(venda_id_alvo))

                        if cell:
                            linha_sheets = cell.row

                            sheet.update_cell(linha_sheets, 7, str(round(float(novo_valor_total), 2)))
                            sheet.update_cell(linha_sheets, 8, str(round(float(novo_valor_pago_final), 2)))
                            sheet.update_cell(linha_sheets, 9, int(novas_parcelas))
                            sheet.update_cell(linha_sheets, 10, parse_data_br(nova_data_1).strftime("%d/%m/%Y"))
                            sheet.update_cell(linha_sheets, 11, str(novo_status))

                            st.session_state.versao_pagto += 1
                            st.success("✅ Alterações salvas com sucesso!")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"Não foi possível localizar a venda com ID {venda_id_alvo}.")
                    except Exception as e:
                        st.error(f"Erro ao salvar na planilha: {e}")

            with col_edit2:
                st.subheader("🗓️ Cronograma Desta Venda")

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
                cols_crono_preview = ["Nº Parcela", "Vencimento", "Valor Parcela (R$)", "Situação"]
                st.dataframe(df_cronograma_prev[cols_crono_preview], use_container_width=True, hide_index=True)

        else:
            st.info("Nenhuma venda registrada até o momento.")

    # --- ABA 4: DASHBOARD & CONTAS A RECEBER ---
    with aba_dash:
        st.header("📈 Análise Financeira e Contas a Receber")

        if not df_vendas.empty and len(df_vendas) > 0:
            df_parcelas = expandir_todas_parcelas(df_vendas)

            if not df_parcelas.empty:
                df_parcelas_ordenadas = df_parcelas.sort_values(by="Data_Venc_Obj")
                meses_vencimento = df_parcelas_ordenadas["Ano_Mes"].dropna().unique().tolist()
                meses_opcoes = ["Todos os Meses de Vencimento"] + meses_vencimento

                mes_selecionado = st.selectbox("📅 Selecione o Mês de Vencimento das Parcelas (MM/AAAA):", meses_opcoes)

                if mes_selecionado != "Todos os Meses de Vencimento":
                    df_parc_filtrado = df_parcelas[df_parcelas["Ano_Mes"] == mes_selecionado]
                else:
                    df_parc_filtrado = df_parcelas.copy()

                total_a_receber_mes = df_parc_filtrado[df_parc_filtrado["Situação"] == "⏳ Pendente"]["Valor Parcela"].sum()
                total_já_recebido_mes = df_parc_filtrado[df_parc_filtrado["Situação"] == "✅ Quitada"]["Valor Parcela"].sum()
                total_geral_mes = df_parc_filtrado["Valor Parcela"].sum()

                col_m1, col_m2, col_m3 = st.columns(3)
                col_m1.metric("Total Previsto no Mês", f"R$ {total_geral_mes:,.2f}")
                col_m2.metric("✅ Já Recebido / Quitado", f"R$ {total_já_recebido_mes:,.2f}")
                col_m3.metric("📌 A RECEBER no Mês", f"R$ {total_a_receber_mes:,.2f}")

                st.divider()

                st.subheader(f"👥 Cobranças Agrupadas por Cliente ({mes_selecionado})")

                df_pendentes_mes = df_parc_filtrado[df_parc_filtrado["Situação"] == "⏳ Pendente"]

                if not df_pendentes_mes.empty:
                    agrupado_cliente = []
                    for (cliente_nome, tel), grupo in df_pendentes_mes.groupby(["Cliente", "Telefone"]):
                        val_total_cli = grupo["Valor Parcela"].sum()
                        detalhes_parcs = " + ".join([f"Parc. {row['Nº Parcela']} ({row['Produto']})" for _, row in grupo.iterrows()])

                        link_wa = gerar_link_whatsapp(
                            tel,
                            cliente_nome,
                            detalhes_parcs,
                            detalhes_parcs,
                            val_total_cli,
                            mes_selecionado,
                        )

                        agrupado_cliente.append({
                            "Cliente": cliente_nome,
                            "Telefone": tel,
                            "Compras Diferentes no Mês": len(grupo),
                            "Detalhamento das Parcelas": detalhes_parcs,
                            "Valor Total a Pagar no Mês (R$)": f"R$ {val_total_cli:,.2f}",
                            "Enviar Cobrança Única": link_wa,
                        })

                    df_agrupado = pd.DataFrame(agrupado_cliente)

                    st.dataframe(
                        df_agrupado,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Enviar Cobrança Única": st.column_config.LinkColumn(
                                "Enviar Cobrança Única",
                                display_text="📲 Enviar Zap Único",
                            )
                        },
                    )
                else:
                    st.success("🎉 Nenhuma cobrança pendente para este mês!")

                st.divider()
                st.subheader("📋 Detalhamento Individual de Parcelas")
                st.dataframe(
                    df_parc_filtrado[["Cliente", "Produto", "Nº Parcela", "Vencimento", "Valor Parcela", "Situação"]],
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.info("Nenhuma venda cadastrada ainda.")

    # --- ABA 5: HISTÓRICO COMPLETO POR CLIENTE ---
    with aba_historico:
        st.header("📋 Ficha do Cliente & Histórico de Compras")

        if not df_vendas.empty and len(df_vendas) > 0:
            clientes_lista = sorted(df_vendas["Cliente"].dropna().unique().tolist())
            cliente_sel = st.selectbox("🔍 Escolha um Cliente para ver o Histórico:", ["Todos os Clientes"] + clientes_lista)

            if cliente_sel != "Todos os Clientes":
                df_cli = df_vendas[df_vendas["Cliente"] == cliente_sel]

                total_comprado = sum([safe_float(v) for v in df_cli["Valor Total"]])
                total_pago = sum([safe_float(v) for v in df_cli["Valor Pago"]])
                saldo_devedor_cli = max(0.0, total_comprado - total_pago)

                c1, c2, c3 = st.columns(3)
                c1.metric("Total de Compras Histórico", f"R$ {total_comprado:,.2f}")
                c2.metric("Total Já Pago", f"R$ {total_pago:,.2f}")
                c3.metric("Saldo Devedor Atual", f"R$ {saldo_devedor_cli:,.2f}")

                st.subheader(f"📦 Compras de {cliente_sel}")
                st.dataframe(df_cli, use_container_width=True, hide_index=True)
            else:
                st.dataframe(df_vendas, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum registro encontrado.")
