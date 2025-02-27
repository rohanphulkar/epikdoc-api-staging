from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from datetime import datetime
from typing import List, Tuple, Optional
import os
import uuid
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Register custom fonts
pdfmetrics.registerFont(TTFont('Roboto', '../fonts/Roboto-Regular.ttf'))
pdfmetrics.registerFont(TTFont('Roboto-Bold', '../fonts/Roboto-Bold.ttf'))

def create_professional_invoice(
    invoice_number: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str,
    items: List[Tuple[str, float]],
    subtotal: float,
    discount: float = 0.0,
    status: str = "PENDING",
    output_file: Optional[str] = None
) -> str:
    """
    Create a modern, professional PDF invoice for Epikdoc AI Technologies.

    Args:
        invoice_number: Invoice number
        customer_name: Customer's name
        customer_email: Customer's email
        customer_phone: Customer's phone
        items: List of tuples (description, amount)
        subtotal: Subtotal amount
        discount: Discount amount (optional)
        status: Invoice status (PENDING/PAID)
        output_file: Output PDF filename

    Returns:
        str: Path to the generated PDF file

    Raises:
        Exception: If PDF generation fails
    """
    try:
        # Create uploads/invoices directory if it doesn't exist
        invoice_dir = os.path.join("uploads", "invoices")
        os.makedirs(invoice_dir, exist_ok=True)

        # Generate unique filename using UUID if not provided
        if not output_file:
            output_file = os.path.join(invoice_dir, f"{uuid.uuid4()}.pdf")
        else:
            output_file = os.path.join(invoice_dir, output_file)

        # Setup document with modern margins and title
        doc = SimpleDocTemplate(output_file, pagesize=letter,
                            topMargin=0.25*inch, bottomMargin=0.25*inch,
                            leftMargin=0.25*inch, rightMargin=0.25*inch,
                            title=f"Invoice {invoice_number}")
        elements = []
        styles = getSampleStyleSheet()
        
        # Color scheme with violet accent
        VIOLET = colors.HexColor('#7F00FF')
        BLACK = colors.HexColor('#000000')
        DARK_GRAY = colors.HexColor('#333333')
        MEDIUM_GRAY = colors.HexColor('#666666')
        LIGHT_GRAY = colors.HexColor('#f8f8f8')
        WHITE = colors.white
        
        # Status color
        status = status.upper()
        STATUS_COLOR = VIOLET
        
        # Custom styles
        styles.add(ParagraphStyle(
            name='RightAlign',
            parent=styles['Normal'],
            alignment=TA_RIGHT,
            textColor=DARK_GRAY,
            fontName='Roboto',
            fontSize=10,
            spaceAfter=12
        ))

        styles.add(ParagraphStyle(
            name='Amount',
            parent=styles['Normal'],
            alignment=TA_RIGHT,
            textColor=DARK_GRAY,
            fontName='Roboto',
            fontSize=10
        ))
        
        # Header section
        current_date = datetime.now().strftime("%d %b, %Y")
        
        header_data = [
            [Paragraph(f'''<font name="Roboto-Bold" size=24 color={VIOLET.hexval()}>Epikdoc AI</font>''', styles["Normal"]),
             Paragraph(f'''<font name="Roboto-Bold" size=20 color={BLACK.hexval()}>INVOICE</font><br/>
                          <font name="Roboto-Bold" size=14 color={VIOLET.hexval()}>{status}</font>''', styles["RightAlign"])],
            [Paragraph(f'''<font name="Roboto" size=10 color={MEDIUM_GRAY.hexval()}>
                Epikdoc AI Technologies<br/>
                Website: backupdoc.ai<br/>
                Email: support@epikdoc.com
                </font>''', styles["Normal"]),
             Paragraph(f'''<font name="Roboto" size=10 color={MEDIUM_GRAY.hexval()}>
                Invoice #: {invoice_number}<br/>
                Date: {current_date}
                </font>''', styles["RightAlign"])]
        ]
        
        header_table = Table(header_data, colWidths=[4*inch, 3*inch])
        header_table.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 30),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 30),
            ('LEFTPADDING', (0, 0), (-1, -1), 20),
            ('RIGHTPADDING', (0, 0), (-1, -1), 20),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.4*inch))

        # Customer Details section
        customer_data = [[
            Paragraph(f'''<font name="Roboto-Bold" size=12 color={VIOLET.hexval()}>CUSTOMER DETAILS</font>''', styles["Normal"])
        ], [
            Paragraph(f'''<font name="Roboto" size=10 color={DARK_GRAY.hexval()}>
                {customer_name}<br/>
                Email: {customer_email}<br/>
                Phone: {customer_phone}
                </font>''', styles["Normal"])
        ]]
        
        customer_table = Table(customer_data, colWidths=[7*inch])
        customer_table.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 20),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 20),
            ('LEFTPADDING', (0, 0), (-1, -1), 20),
            ('RIGHTPADDING', (0, 0), (-1, -1), 20),
            ('BACKGROUND', (0, 0), (-1, -1), LIGHT_GRAY),
        ]))
        elements.append(customer_table)
        elements.append(Spacer(1, 0.4*inch))

        # Items table
        table_data = [[
            Paragraph('<font name="Roboto-Bold" color=white>Description</font>', styles["Normal"]),
            Paragraph('<font name="Roboto-Bold" color=white>Amount</font>', styles["Amount"])
        ]]
        for description, amount in items:
            table_data.append([
                Paragraph(description, styles["Normal"]),
                Paragraph(f'''Rs. {amount:,.2f}''', styles["Amount"])
            ])

        items_table = Table(table_data, colWidths=[5*inch, 2*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), VIOLET),
            ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
            ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Roboto-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 15),
            ('BACKGROUND', (0, 1), (-1, -1), WHITE),
            ('TEXTCOLOR', (0, 1), (-1, -1), DARK_GRAY),
            ('GRID', (0, 0), (-1, -1), 1, LIGHT_GRAY),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 20),
            ('RIGHTPADDING', (0, 0), (-1, -1), 20),
            ('TOPPADDING', (0, 0), (-1, -1), 15),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
        ]))
        elements.append(items_table)

        # Calculate total
        total = subtotal - discount

        # Summary table
        summary_data = [[
            Paragraph('Subtotal:', styles["Normal"]),
            Paragraph(f'''Rs. {subtotal:,.2f}''', styles["Amount"])
        ], [
            Paragraph('Discount:', styles["Normal"]),
            Paragraph(f'''Rs. {discount:,.2f}''', styles["Amount"])
        ], [
            Paragraph(f'''<font name="Roboto-Bold" size=12 color={VIOLET.hexval()}>Total:</font>''', styles["Normal"]),
            Paragraph(f'''<font name="Roboto-Bold" size=12 color={VIOLET.hexval()}>Rs. {total:,.2f}</font>''', styles["Amount"])
        ]]
        
        summary_table = Table(summary_data, colWidths=[5*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('TEXTCOLOR', (0, 0), (-1, -2), DARK_GRAY),
            ('FONTSIZE', (0, 0), (-1, -2), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('LINEABOVE', (0, -1), (-1, -1), 1, VIOLET),
            ('RIGHTPADDING', (0, 0), (-1, -1), 20),
            ('LEFTPADDING', (0, 0), (-1, -1), 20),
        ]))
        elements.append(Spacer(1, 0.3*inch))
        elements.append(summary_table)
        elements.append(Spacer(1, 0.6*inch))

        # Thank you note
        thank_you = Paragraph(
            f'''<para align=center>
                <font name="Roboto-Bold" size=14 color={VIOLET.hexval()}>Thank You</font>
                <font name="Roboto" size=10 color={DARK_GRAY.hexval()}>For any questions, please contact support@epikdoc.com</font>
            </para>''',
            styles["Normal"]
        )
        elements.append(thank_you)

        # Build PDF
        doc.build(elements)
        return output_file

    except Exception as e:
        raise

def generate_invoice_number() -> str:
    """
    Generate a professional invoice number with format: EPIK-YYYY-MMXXXXX
    where YYYY is current year, MM is current month, XXXXX is a sequential number
    
    Returns:
        str: Generated invoice number
    """
    current_date = datetime.now()
    year = current_date.strftime('%Y')
    month = current_date.strftime('%m')
    # In production, this should come from a database sequence
    sequence = str(hash(current_date.isoformat()) % 100000).zfill(5)
    return f"EPIK-{year}-{month}{sequence}"
