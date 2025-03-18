import google.generativeai as genai
from decouple import config
from fastapi.responses import JSONResponse
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import smtplib
from datetime import datetime

genai.configure(api_key=str(config("GOOGLE_API_KEY")))
model = genai.GenerativeModel("gemini-1.5-flash")  # Updated to pro model for better results

def report_generate(prediction_str, doctor_name, doctor_email, doctor_phone, patient_name, patient_age, patient_gender, patient_phone, date, notes):
    report_template = f"""You are a Dentist. Give me a detailed dental radiology report about the following pathologies found on the patient's uploaded X-ray:

{prediction_str}

Please format the report in markdown with the following sections:

# **Dental Radiology Report**

**Patient Details:**
- **Patient Name:** {patient_name}
- **Patient Age:** {patient_age}
- **Patient Gender:** {patient_gender}
- **Patient Contact:** {patient_phone}

**Doctor Details:**
- **Doctor Name:** {doctor_name}
- **Doctor Email:** {doctor_email}
- **Doctor Contact:** {doctor_phone}

**Notes:**
{notes}

**Report Date:** {date}

**Findings:**
[List findings here with severity levels]

**Analysis:**
[Detailed analysis of each pathology]


Please include:
1. Analysis of each detected pathology with severity level
2. Present the information in clear sections with bullet points where appropriate
3. And don't give it any title or heading
"""
    try:
        # Set safety settings and parameters for better results
        response = model.generate_content(
            report_template,
        )

        if response and response.text:
            return response.text
        return "Unable to generate report. Please try again."

    except Exception as e:
        print(f"Error generating report with Gemini API: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Failed to generate report",
                "details": str(e)
            }
        )


def create_dental_radiology_report(patient_name, report_content):
    try:
        # Create reports directory if it doesn't exist
        reports_dir = os.path.join("uploads", "reports")
        os.makedirs(reports_dir, exist_ok=True)
        
        # Sanitize patient name for filename
        safe_patient_name = "".join(c for c in patient_name if c.isalnum() or c in (' ', '-', '_')).strip()
        file_path = os.path.join(reports_dir, f"{safe_patient_name}_report.pdf")
        
        # Create document
        doc = SimpleDocTemplate(
            file_path,
            pagesize=letter,
            rightMargin=50,
            leftMargin=50,
            topMargin=50,
            bottomMargin=50
        )
        
        # Get styles
        styles = getSampleStyleSheet()
        
        # Create custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=20,
            spaceAfter=30,
            alignment=1,  # Center alignment
            textColor=colors.HexColor('#2c3e50'),
            fontName='Helvetica-Bold'
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            spaceAfter=15,
            textColor=colors.HexColor('#34495e'),
            fontName='Helvetica-Bold',
            borderPadding=10,
            borderWidth=1,
            borderColor=colors.HexColor('#bdc3c7'),
            borderRadius=5
        )
        
        subheading_style = ParagraphStyle(
            'CustomSubHeading',
            parent=styles['Heading3'],
            fontSize=14,
            spaceAfter=10,
            textColor=colors.HexColor('#7f8c8d'),
            fontName='Helvetica-Bold'
        )
        
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=11,
            spaceAfter=8,
            leading=14,
            fontName='Helvetica',
            textColor=colors.HexColor('#2c3e50')
        )
        
        # Build content
        story = []
        
        # Add logo/header (if available)
        # story.append(Image("path/to/logo.png", width=2*inch, height=1*inch))
        
        # Add title with styling
        story.append(Paragraph("Dental Radiology Report", title_style))
        
        # Add metadata table
        current_date = datetime.now().strftime("%B %d, %Y")
        report_id = f"DR{datetime.now().strftime('%Y%m%d%H%M')}"
        
        metadata = [
            ['Report ID:', report_id, 'Date:', current_date],
            ['Patient Name:', patient_name, 'Report Type:', 'Dental Radiology']
        ]
        
        metadata_table = Table(metadata, colWidths=[1.2*inch, 2*inch, 1.2*inch, 2*inch])
        metadata_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f6fa')),
            ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#f5f6fa')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2c3e50')),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        
        story.append(metadata_table)
        story.append(Spacer(1, 20))
        
        # Process markdown content with enhanced styling
        paragraphs = report_content.split('\n')
        for para in paragraphs:
            if para.strip():
                if para.startswith('# '):
                    story.append(Paragraph(para[2:].strip(), heading_style))
                elif para.startswith('## '):
                    story.append(Paragraph(para[3:].strip(), subheading_style))
                elif '**' in para:
                    para = para.replace('**', '<b>', 1)
                    para = para.replace('**', '</b>', 1)
                    story.append(Paragraph(para, normal_style))
                elif para.strip().startswith('-'):
                    story.append(Paragraph(f"• {para[1:].strip()}", normal_style))
                else:
                    story.append(Paragraph(para, normal_style))
                
                story.append(Spacer(1, 6))
        
        # Add footer
        footer_text = "This report is generated by BackupDoc.AI - Confidential Medical Document"
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#95a5a6'),
            alignment=1
        )
        story.append(Spacer(1, 30))
        story.append(Paragraph(footer_text, footer_style))
        
        # Build PDF
        doc.build(story)
        return file_path
        
    except Exception as e:
        print(f"Error creating PDF: {str(e)}")
        return None

def send_email_with_attachment(to_email, patient_name, pdf_file_path):
    try:
        # Email configuration for Office 365
        smtp_server = str(config('EMAIL_HOST'))
        smtp_port = int(config('EMAIL_PORT'))
        smtp_username = str(config('EMAIL_SENDER'))
        smtp_password = str(config('EMAIL_PASSWORD'))

        # Create message
        msg = MIMEMultipart()
        msg['From'] = smtp_username
        msg['To'] = to_email
        msg['Subject'] = f"Dental Radiology Report - {patient_name}"

        # Add body
        body = f"""Dear Doctor,

Attached is the dental radiology report for patient {patient_name}.

Best regards,
BackupDoc.AI Team"""
        msg.attach(MIMEText(body, 'plain'))

        # Verify and attach PDF
        if not os.path.exists(pdf_file_path):
            raise FileNotFoundError(f"Report PDF not found at: {pdf_file_path}")

        with open(pdf_file_path, "rb") as attachment:
            part = MIMEBase('application', 'pdf')
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{os.path.basename(pdf_file_path)}"'
            )
            msg.attach(part)

        # Send email with SSL/TLS
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()  # Identify to the SMTP server
            server.starttls()  # Enable TLS encryption
            server.ehlo()  # Re-identify over TLS connection
            server.login(smtp_username, smtp_password)
            server.send_message(msg)

        return True

    except FileNotFoundError as e:
        print(f"PDF file error: {str(e)}")
        return False
    except smtplib.SMTPException as e:
        print(f"SMTP error: {str(e)}")
        return False
    except Exception as e:
        print(f"Unexpected error sending email: {str(e)}")
        return False