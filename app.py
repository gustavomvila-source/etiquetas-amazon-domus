import streamlit as st
import pdfplumber
import re
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from io import BytesIO


def extrair_dados_guia(guia_pdf_bytes):
    """Extrai Order ID, quantidade, SKU e descricao de cada pedido da guia de remessa."""
    pedidos = {}
    with pdfplumber.open(BytesIO(guia_pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""

            order_match = re.search(r"ID do pedido:\s*([\d\-]+)", text)
            if not order_match:
                continue

            order_id = order_match.group(1)
            sku = ""
            qty = ""
            desc = ""

            sku_match = re.search(r"SKU:\s*(\S+)", text)
            if sku_match:
                sku = sku_match.group(1)

            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row and row[0] and row[0].strip().isdigit():
                        qty = row[0].strip()
                        if row[1]:
                            # Pega as primeiras linhas da descricao (antes de SKU/ASIN)
                            raw = row[1].split("\n")
                            desc_lines = []
                            for line in raw:
                                line_stripped = line.strip()
                                if line_stripped.startswith(("SKU:", "ASIN:", "Condi", "ID do item")):
                                    break
                                if line_stripped:
                                    desc_lines.append(line_stripped)
                            desc = " ".join(desc_lines)

            pedidos[order_id] = {
                "order": order_id,
                "qty": qty,
                "sku": sku,
                "desc": desc,
            }
    return pedidos


def identificar_order_id_etiqueta(page_index, reader, guia_pedidos):
    """
    Tenta extrair o Order ID do texto da etiqueta.
    Se nao houver texto extraivel, tenta match por indice.
    """
    page = reader.pages[page_index]
    text = page.extract_text() or ""

    # Tenta diferentes formatos de Order ID
    patterns = [
        r"Order\s*Id\s*([\d\-]+)",
        r"Order\s*ID:\s*([\d\-]+)",
        r"(7\d{2}-\d{7}-\d{7})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            order_id = match.group(1)
            if order_id in guia_pedidos:
                return order_id

    # Fallback: match por indice (ordem das etiquetas = ordem da guia)
    guia_keys = list(guia_pedidos.keys())
    if page_index < len(guia_keys):
        return guia_keys[page_index]

    return None


def criar_pagina_info(data, page_width, page_height):
    """Cria uma pagina PDF com as informacoes do produto."""
    packet = BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_width, page_height))

    center_y = page_height / 2 + 80
    margin_left = 50
    box_width = page_width - 100

    # Titulo
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(page_width / 2, center_y + 100, "INFORMACOES DO PRODUTO")

    # Linha horizontal
    c.setLineWidth(2)
    c.line(margin_left, center_y + 85, page_width - margin_left, center_y + 85)

    # Caixa
    box_top = center_y + 70
    box_height = 170
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(1.5)
    c.roundRect(
        margin_left - 10,
        box_top - box_height,
        box_width + 20,
        box_height,
        8,
        stroke=1,
        fill=0,
    )

    y = box_top - 30
    line_spacing = 35

    # Pedido
    c.setFont("Helvetica", 11)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(margin_left + 5, y, "Pedido:")
    c.setFont("Helvetica-Bold", 13)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(margin_left + 110, y, data["order"])

    y -= line_spacing

    # Quantidade
    c.setFont("Helvetica", 11)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(margin_left + 5, y, "Quantidade:")
    c.setFont("Helvetica-Bold", 22)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(margin_left + 110, y - 4, data["qty"])

    y -= line_spacing

    # SKU
    c.setFont("Helvetica", 11)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(margin_left + 5, y, "SKU:")
    c.setFont("Helvetica-Bold", 13)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(margin_left + 110, y, data["sku"])

    y -= line_spacing + 5

    # Separador
    c.setLineWidth(1)
    c.setStrokeColorRGB(0.7, 0.7, 0.7)
    c.line(margin_left, y + 15, page_width - margin_left, y + 15)

    # Produto
    y -= 15
    c.setFont("Helvetica", 11)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(margin_left + 5, y, "Produto:")

    c.setFont("Helvetica-Bold", 12)
    c.setFillColorRGB(0, 0, 0)

    # Quebra de linha automatica
    desc = data["desc"]
    max_width = box_width - 10
    words = desc.split()
    lines = []
    current_line = ""
    for word in words:
        test = current_line + " " + word if current_line else word
        if c.stringWidth(test, "Helvetica-Bold", 12) < max_width:
            current_line = test
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    y -= 22
    for line in lines:
        c.drawString(margin_left + 5, y, line)
        y -= 18

    # Rodape
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(
        page_width / 2, 30, "Domus Oficial - Etiqueta complementar de produto"
    )

    c.save()
    packet.seek(0)
    return packet


def processar_pdfs(etiquetas_bytes, guia_bytes):
    """Processa os dois PDFs e gera o PDF final com paginas de info intercaladas."""
    # Extrair dados da guia
    pedidos = extrair_dados_guia(guia_bytes)

    if not pedidos:
        return None, "Nao foi possivel extrair dados da guia de remessa."

    # Ler etiquetas
    reader = PdfReader(BytesIO(etiquetas_bytes))
    writer = PdfWriter()

    matched = []
    unmatched_labels = []

    for i, page in enumerate(reader.pages):
        media_box = page.mediabox
        page_width = float(media_box.width)
        page_height = float(media_box.height)

        # Adiciona etiqueta original
        writer.add_page(page)

        # Encontra o pedido correspondente
        order_id = identificar_order_id_etiqueta(i, reader, pedidos)

        if order_id and order_id in pedidos:
            data = pedidos[order_id]
            info_packet = criar_pagina_info(data, page_width, page_height)
            info_reader = PdfReader(info_packet)
            writer.add_page(info_reader.pages[0])
            matched.append(order_id)
        else:
            unmatched_labels.append(i + 1)

    # Gerar PDF
    output = BytesIO()
    writer.write(output)
    output.seek(0)

    # Montar relatorio
    total_etiquetas = len(reader.pages)
    total_matched = len(matched)
    report = f"Processadas {total_matched} de {total_etiquetas} etiquetas."

    if unmatched_labels:
        report += f"\nEtiquetas sem correspondencia na guia: paginas {', '.join(str(p) for p in unmatched_labels)}"

    pedidos_sem_etiqueta = [
        oid for oid in pedidos if oid not in matched
    ]
    if pedidos_sem_etiqueta:
        report += f"\nPedidos na guia sem etiqueta correspondente: {', '.join(pedidos_sem_etiqueta)}"

    return output, report


# ===================== INTERFACE STREAMLIT =====================

st.set_page_config(
    page_title="Etiquetas Amazon - Domus Oficial",
    page_icon="📦",
    layout="centered",
)

st.title("📦 Gerador de Etiquetas com Info do Produto")
st.markdown("Faca upload do **PDF de etiquetas** e da **guia de remessa** para gerar as etiquetas com as informacoes do produto.")

st.divider()

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Etiquetas de envio")
    etiquetas_file = st.file_uploader(
        "PDF com as etiquetas da Amazon",
        type=["pdf"],
        key="etiquetas",
        help="O arquivo PDF que voce baixou com as etiquetas de envio",
    )

with col2:
    st.subheader("2. Guia de remessa")
    guia_file = st.file_uploader(
        "PDF da guia de remessa da Amazon",
        type=["pdf"],
        key="guia",
        help="O arquivo PDF da guia de remessa (packing slip) com os detalhes dos produtos",
    )

st.divider()

if etiquetas_file and guia_file:
    if st.button("🚀 Gerar Etiquetas", type="primary", use_container_width=True):
        with st.spinner("Processando PDFs..."):
            etiquetas_bytes = etiquetas_file.read()
            guia_bytes = guia_file.read()

            resultado, report = processar_pdfs(etiquetas_bytes, guia_bytes)

        if resultado:
            st.success("PDF gerado com sucesso!")
            st.info(report)

            st.download_button(
                label="📥 Baixar PDF com Etiquetas + Info do Produto",
                data=resultado,
                file_name="etiquetas_com_produto.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
        else:
            st.error(f"Erro: {report}")
else:
    st.warning("Envie os dois arquivos PDF para continuar.")

st.divider()
st.caption("Domus Oficial - Ferramenta interna para processamento de etiquetas")
