from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from datetime import datetime
from typing import Optional
import os
import uuid
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Register custom fonts
pdfmetrics.registerFont(TTFont('Roboto', '../fonts/Roboto-Regular.ttf'))
pdfmetrics.registerFont(TTFont('Roboto-Bold', '../fonts/Roboto-Bold.ttf'))

def create_professional_invoice(
    id: str,
    date: datetime,
    patient_id: str,
    doctor_id: str,
    patient_number: str,
    patient_name: str,
    doctor_name: str,
    invoice_number: str,
    treatment_name: str,
    unit_cost: float,
    quantity: int,
    discount: float = 0.0,
    discount_type: str = "fixed",
    type: Optional[str] = None,
    invoice_level_tax_discount: Optional[float] = None,
    tax_name: Optional[str] = None,
    tax_percent: Optional[float] = None,
    notes: Optional[str] = None,
    description: Optional[str] = None,
    output_file: Optional[str] = None
) -> str:
    """
    Create a modern, professional PDF invoice based on Invoice model fields.
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

        # Setup document
        doc = SimpleDocTemplate(output_file, pagesize=letter,
                            topMargin=0.5*inch, bottomMargin=0.5*inch,
                            leftMargin=0.5*inch, rightMargin=0.5*inch,
                            title=f"Invoice {invoice_number}")
        elements = []
        styles = getSampleStyleSheet()
        
        # Brand Colors
        BRAND_COLOR = colors.HexColor('#84cc16')  # Lime green
        SECONDARY = colors.HexColor('#1a2e05')    # Dark green
        GRAY = colors.HexColor('#64748b')         # Slate gray
        LIGHT_GRAY = colors.HexColor('#f1f5f9')   # Light slate
        
        # Custom styles
        styles.add(ParagraphStyle(
            name='RightAlign',
            parent=styles['Normal'],
            alignment=TA_RIGHT,
            fontName='Roboto',
            fontSize=10,
            spaceAfter=12
        ))

        # Header
        header_data = [
            [Paragraph(f'''<font name="Roboto-Bold" size=28 color={BRAND_COLOR.hexval()}>EPIKDOC</font>''', styles["Normal"]),
             Paragraph(f'''<font name="Roboto-Bold" size=16 color={SECONDARY.hexval()}># {invoice_number}</font>''', styles["RightAlign"])],
            [Paragraph(f'''<font name="Roboto" size=10 color={GRAY.hexval()}>
                Generated: {date.strftime("%d %B, %Y")}<br/>
                Invoice ID: {id}
                </font>''', styles["Normal"]), ""]
        ]
        
        header_table = Table(header_data, colWidths=[4*inch, 3*inch])
        header_table.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 20),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 20),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.3*inch))

        # Doctor and Patient Details
        details_data = [[
            Paragraph(f'''<font name="Roboto-Bold" size=12 color={BRAND_COLOR.hexval()}>HEALTHCARE PROVIDER</font>''', styles["Normal"]),
            Paragraph(f'''<font name="Roboto-Bold" size=12 color={BRAND_COLOR.hexval()}>PATIENT INFORMATION</font>''', styles["Normal"])
        ], [
            Paragraph(f'''<font name="Roboto" size=10>
                Dr. {doctor_name}<br/>
                Doctor ID: {doctor_id}
                </font>''', styles["Normal"]),
            Paragraph(f'''<font name="Roboto" size=10>
                {patient_name}<br/>
                Patient ID: {patient_id}<br/>
                Patient #: {patient_number}
                </font>''', styles["Normal"])
        ]]
        
        details_table = Table(details_data, colWidths=[3.5*inch, 3.5*inch])
        details_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), LIGHT_GRAY),
            ('TOPPADDING', (0, 0), (-1, -1), 15),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
            ('LEFTPADDING', (0, 0), (-1, -1), 15),
            ('RIGHTPADDING', (0, 0), (-1, -1), 15),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.3*inch))

        # Treatment Details
        subtotal = unit_cost * quantity
        discount_amount = discount if discount_type == "fixed" else (subtotal * discount / 100)
        tax_amount = 0 if not tax_percent else ((subtotal - discount_amount) * tax_percent / 100)
        if invoice_level_tax_discount:
            tax_amount = tax_amount * (1 - invoice_level_tax_discount/100)
        total = subtotal - discount_amount + tax_amount

        items_data = [
            ['Treatment', 'Quantity', 'Unit Cost', 'Amount'],
            [treatment_name, str(quantity), f"Rs. {unit_cost:,.2f}", f"Rs. {subtotal:,.2f}"]
        ]
        
        items_table = Table(items_data, colWidths=[3*inch, 1*inch, 1.5*inch, 1.5*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), BRAND_COLOR),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Roboto-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, LIGHT_GRAY),
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 0.2*inch))

        # Summary
        summary_data = []
        summary_data.append(['Subtotal:', '', '', f"Rs. {subtotal:,.2f}"])
        if discount:
            summary_data.append([f'Discount ({discount}{"%" if discount_type=="percentage" else ""}):', 
                               '', '', f"Rs. {discount_amount:,.2f}"])
        if tax_percent:
            tax_label = f'{tax_name} ({tax_percent}%)'
            if invoice_level_tax_discount:
                tax_label += f' (Discount: {invoice_level_tax_discount}%)'
            summary_data.append([tax_label, '', '', f"Rs. {tax_amount:,.2f}"])
        summary_data.append(['Total:', '', '', f"Rs. {total:,.2f}"])

        summary_table = Table(summary_data, colWidths=[3*inch, 1*inch, 1.5*inch, 1.5*inch])
        summary_table.setStyle(TableStyle([
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, -1), (-1, -1), 'Roboto-Bold'),
            ('LINEABOVE', (0, -1), (-1, -1), 1, BRAND_COLOR),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(summary_table)

        if type or notes or description:
            elements.append(Spacer(1, 0.3*inch))
            if type:
                elements.append(Paragraph(f'''<font name="Roboto-Bold" size=10 color={BRAND_COLOR.hexval()}>Invoice Type:</font>''', styles["Normal"]))
                elements.append(Paragraph(f'''<font name="Roboto" size=9>{type}</font>''', styles["Normal"]))
            if notes:
                elements.append(Spacer(1, 0.2*inch))
                elements.append(Paragraph(f'''<font name="Roboto-Bold" size=10 color={BRAND_COLOR.hexval()}>Notes:</font>''', styles["Normal"]))
                elements.append(Paragraph(f'''<font name="Roboto" size=9>{notes}</font>''', styles["Normal"]))
            if description:
                elements.append(Spacer(1, 0.2*inch))
                elements.append(Paragraph(f'''<font name="Roboto-Bold" size=10 color={BRAND_COLOR.hexval()}>Description:</font>''', styles["Normal"]))
                elements.append(Paragraph(f'''<font name="Roboto" size=9>{description}</font>''', styles["Normal"]))

        # Footer
        elements.append(Spacer(1, 0.5*inch))
        footer = Paragraph(
            f'''<para align=center>
                <font name="Roboto-Bold" size=12 color={BRAND_COLOR.hexval()}>Thank you for choosing Epikdoc</font><br/>
                <font name="Roboto" size=9 color={GRAY.hexval()}>For any questions, please contact support@epikdoc.com</font>
            </para>''',
            styles["Normal"]
        )
        elements.append(footer)

        # Build PDF
        doc.build(elements)
        return output_file

    except Exception as e:
        raise Exception(f"Failed to generate invoice: {str(e)}")

