from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from datetime import datetime
from typing import Optional, List
import os
import uuid
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Register custom fonts
font_dir = os.path.join(os.path.dirname(__file__), '..', 'fonts')
pdfmetrics.registerFont(TTFont('Roboto', os.path.join(font_dir, 'Roboto-Regular.ttf')))
pdfmetrics.registerFont(TTFont('Roboto-Bold', os.path.join(font_dir, 'Roboto-Bold.ttf')))

def create_professional_invoice(
    invoice_data: dict,
    invoice_items: List[dict]
) -> str:
    """
    Create a modern, professional PDF invoice based on Invoice model fields.
    """
    try:
        # Create uploads/invoices directory if it doesn't exist
        invoice_dir = os.path.join("uploads", "invoices")
        os.makedirs(invoice_dir, exist_ok=True)

        # Generate unique filename using UUID
        output_file = os.path.join(invoice_dir, f"{uuid.uuid4()}.pdf")

        # Setup document
        doc = SimpleDocTemplate(output_file, pagesize=letter,
                            topMargin=1*inch, bottomMargin=1*inch,
                            leftMargin=1*inch, rightMargin=1*inch,
                            title=f"Invoice {invoice_data['invoice_number']}")
        elements = []
        styles = getSampleStyleSheet()
        
        # Brand Colors
        BRAND_COLOR = colors.HexColor('#84cc16')  # Lime green
        SECONDARY = colors.HexColor('#1a2e05')    # Dark green
        GRAY = colors.HexColor('#64748b')         # Slate gray
        LIGHT_GRAY = colors.HexColor('#f8fafc')   # Lighter slate

        # Custom styles
        styles.add(ParagraphStyle(
            name='RightAlign',
            parent=styles['Normal'],
            alignment=TA_RIGHT,
            fontName='Roboto',
            fontSize=10
        ))

        # Header with Logo and Invoice Details
        header_data = [[
            Paragraph(f'''<font name="Roboto-Bold" size=32 color={BRAND_COLOR.hexval()}>EPIKDOC</font>''', styles["Normal"]),
            Paragraph(f'''<font name="Roboto-Bold" size=24 color={SECONDARY.hexval()}>INVOICE</font>''', styles["RightAlign"])
        ]]
        
        header_table = Table(header_data, colWidths=[4*inch, 3*inch])
        header_table.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 30),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 30),  # Increased from 10 to 30
        ]))
        elements.append(header_table)

        # Invoice Details Box
        invoice_details = [[
            Paragraph(f'''<font name="Roboto" size=10>Invoice Number: </font>
                         <font name="Roboto-Bold" size=10>#{invoice_data['invoice_number']}</font>''', styles["Normal"]),
            Paragraph(f'''<font name="Roboto" size=10>Date: </font>
                         <font name="Roboto-Bold" size=10>{invoice_data['date'].strftime("%d %B, %Y")}</font>''', styles["RightAlign"])
        ]]
        
        details_table = Table(invoice_details, colWidths=[4*inch, 3*inch])
        details_table.setStyle(TableStyle([
            # ('BACKGROUND', (0, 0), (-1, -1), LIGHT_GRAY),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('ROUNDEDCORNERS', (0, 0), (-1, -1), 6),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.3*inch))

        # Billing Information
        billing_data = [[
            Paragraph(f'''
                <font name="Roboto-Bold" size=11 color={BRAND_COLOR.hexval()}>FROM</font><br/>
                <font name="Roboto-Bold" size=12>Dr. {invoice_data['doctor_name']}</font><br/>
                <font name="Roboto" size=10 color={GRAY.hexval()}>
                Phone: {invoice_data.get('doctor_phone', 'N/A')}<br/>
                Email: {invoice_data.get('doctor_email', 'N/A')}
                </font>
            ''', styles["Normal"]),
            Paragraph(f'''
                <font name="Roboto-Bold" size=11 color={BRAND_COLOR.hexval()}>BILL TO</font><br/>
                <font name="Roboto-Bold" size=12>{invoice_data['patient_name'].strip("'")}</font><br/>
                <font name="Roboto" size=10 color={GRAY.hexval()}>
                Phone: {invoice_data.get('patient_phone', 'N/A').strip("'")}<br/>
                Email: {invoice_data.get('patient_email', 'N/A').strip("'")}
                </font>
            ''', styles["Normal"])
        ]]
        
        billing_table = Table(billing_data, colWidths=[3.5*inch, 3.5*inch])
        billing_table.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 15),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
            ('LEFTPADDING', (0, 0), (-1, -1), 20),
            ('RIGHTPADDING', (0, 0), (-1, -1), 20),
        ]))
        elements.append(billing_table)
        elements.append(Spacer(1, 0.3*inch))

        # Treatment Details Table
        items_data = [[
            Paragraph(f'''<font name="Roboto-Bold" size=10 color={colors.white}>Treatment</font>''', styles["Normal"]),
            Paragraph(f'''<font name="Roboto-Bold" size=10 color={colors.white}>Quantity</font>''', styles["RightAlign"]),
            Paragraph(f'''<font name="Roboto-Bold" size=10 color={colors.white}>Rate (Rs)</font>''', styles["RightAlign"]),
            Paragraph(f'''<font name="Roboto-Bold" size=10 color={colors.white}>Discount (Rs)</font>''', styles["RightAlign"]),
            Paragraph(f'''<font name="Roboto-Bold" size=10 color={colors.white}>Tax (Rs)</font>''', styles["RightAlign"]),
            Paragraph(f'''<font name="Roboto-Bold" size=10 color={colors.white}>Amount (Rs)</font>''', styles["RightAlign"])
        ]]
        
        total = 0
        for item in invoice_items:
            subtotal = item['unit_cost'] * item['quantity']
            discount_amount = item.get('discount', 0) if item.get('discount_type') == "fixed" else (subtotal * item.get('discount', 0) / 100)
            tax_amount = 0 if not item.get('tax_percent') else ((subtotal - discount_amount) * item['tax_percent'] / 100)
            if item.get('invoice_level_tax_discount'):
                tax_amount = tax_amount * (1 - item['invoice_level_tax_discount']/100)
            item_total = subtotal - discount_amount + tax_amount
            total += item_total
            
            items_data.append([
                Paragraph(f'''<font name="Roboto" size=10>{item['treatment_name']}</font>''', styles["Normal"]),
                Paragraph(f'''<font name="Roboto" size=10>{item['quantity']}</font>''', styles["RightAlign"]),
                Paragraph(f'''<font name="Roboto" size=10>{item['unit_cost']:,.2f}</font>''', styles["RightAlign"]),
                Paragraph(f'''<font name="Roboto" size=10>{discount_amount:,.2f}</font>''', styles["RightAlign"]),
                Paragraph(f'''<font name="Roboto" size=10>{tax_amount:,.2f}</font>''', styles["RightAlign"]),
                Paragraph(f'''<font name="Roboto" size=10>{item_total:,.2f}</font>''', styles["RightAlign"])
            ])

        items_table = Table(items_data, colWidths=[2.5*inch, 1*inch, 1.2*inch, 1.2*inch, 1*inch, 1.1*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), BRAND_COLOR),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, LIGHT_GRAY),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 0.2*inch))

        # Summary Box
        summary_data = [
            ['', '', '', '', Paragraph(f'''<font name="Roboto-Bold" size=10>Subtotal:</font>''', styles["RightAlign"]),
             Paragraph(f'''<font name="Roboto" size=10>{total:,.2f} Rs</font>''', styles["RightAlign"])],
            ['', '', '', '', Paragraph(f'''<font name="Roboto-Bold" size=11>Total Amount:</font>''', styles["RightAlign"]),
             Paragraph(f'''<font name="Roboto-Bold" size=11>{total:,.2f} Rs</font>''', styles["RightAlign"])]
        ]

        summary_table = Table(summary_data, colWidths=[2.5*inch, 1*inch, 1.2*inch, 1.2*inch, 1*inch, 1.1*inch])
        summary_table.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LINEABOVE', (-2, -1), (-1, -1), 1, BRAND_COLOR),
        ]))
        elements.append(summary_table)

        # Notes Section
        if invoice_data.get('notes') or invoice_data.get('description'):
            elements.append(Spacer(1, 0.4*inch))
            notes_data = []
            if invoice_data.get('notes'):
                notes_data.append([
                    Paragraph(f'''<font name="Roboto-Bold" size=10 color={BRAND_COLOR.hexval()}>Notes:</font>''', styles["Normal"]),
                    Paragraph(f'''<font name="Roboto" size=9>{invoice_data['notes']}</font>''', styles["Normal"])
                ])
            if invoice_data.get('description'):
                notes_data.append([
                    Paragraph(f'''<font name="Roboto-Bold" size=10 color={BRAND_COLOR.hexval()}>Description:</font>''', styles["Normal"]),
                    Paragraph(f'''<font name="Roboto" size=9>{invoice_data['description']}</font>''', styles["Normal"])
                ])
            
            notes_table = Table(notes_data, colWidths=[1*inch, 7*inch])
            notes_table.setStyle(TableStyle([
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(notes_table)

        # Footer
        elements.append(Spacer(1, 0.5*inch))
        footer = Paragraph(
            f'''<para align=center>
                <font name="Roboto-Bold" size=14 color={BRAND_COLOR.hexval()}>Thank you for choosing Epikdoc</font><br/><br/>
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
