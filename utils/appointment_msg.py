from datetime import datetime
from sqlalchemy.orm import Session
from appointment.models import Appointment, AppointmentStatus
from patient.models import Patient
from auth.models import User
from utils.email import send_email
import requests
from utils.config import EMAIL_HOST, EMAIL_PORT, EMAIL_SENDER, EMAIL_PASSWORD
from pathlib import Path
from jinja2 import Template
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

async def send_appointment_email(
    db: Session,
    appointment_id: str
) -> tuple[bool, str]:
    """
    Send appointment confirmation email using HTML template
    Args:
        db: Database session
        appointment_id: ID of the appointment
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Get appointment details with error handling
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            print("Appointment not found")
            return False, "Appointment not found"

        # Get patient and doctor details with error handling
        patient = db.query(Patient).filter(Patient.id == appointment.patient_id).first()
        if not patient:
            print("Patient not found")
            return False, "Patient not found"

        doctor = db.query(User).filter(User.id == appointment.doctor_id).first()
        if not doctor:
            print("Doctor not found")
            return False, "Doctor not found"

        # Format email subject
        subject = f"Appointment {appointment.status.value.capitalize()} - {appointment.start_time.strftime('%B %d, %Y')}"

        # Prepare template data
        template_data = {
            "patient": {"name": patient.name},
            "appointment": {
                "status": {"value": appointment.status.value},
                "notes": appointment.notes,
                "appointment_date": appointment.appointment_date.strftime('%Y-%m-%d'),
                "start_time": appointment.start_time.strftime('%I:%M %p'),
                "end_time": appointment.end_time.strftime('%I:%M %p')
            },
            "doctor": {
                "name": doctor.name,
                "email": doctor.email,
                "phone": doctor.phone if doctor.phone else "Not provided"
            }
        }        
        # Path to HTML template
        template_path = "utils/templates/appointment-email.html"

        sender_email = EMAIL_SENDER
        sender_password = EMAIL_PASSWORD
        email_host = EMAIL_HOST
        email_port = EMAIL_PORT
        
        # Create message container
        msg = MIMEMultipart('alternative')
        msg['From'] = sender_email
        msg['To'] = patient.email if patient.email else ""
        msg['Subject'] = subject
        
        # Read the HTML template
        html_content = Path(template_path).read_text()
        
        # Convert string dates to datetime objects if they exist
        if 'appointment' in template_data and 'appointment_date' in template_data['appointment']:
            if isinstance(template_data['appointment']['appointment_date'], str):
                try:
                    date_obj = datetime.strptime(
                        template_data['appointment']['appointment_date'], '%Y-%m-%d'
                    )
                    # Format date as "10 April 2025"
                    template_data['appointment']['appointment_date'] = date_obj.strftime('%d %B %Y')
                except ValueError:
                    pass  # Keep as string if parsing fails
        
        # Format times if they exist
        if 'appointment' in template_data:
            if 'start_time' in template_data['appointment'] and isinstance(template_data['appointment']['start_time'], str):
                try:
                    # Try to parse and format the time as "03:00 PM"
                    time_obj = datetime.strptime(template_data['appointment']['start_time'], '%I:%M %p')
                    template_data['appointment']['start_time'] = time_obj.strftime('%I:%M %p')
                except ValueError:
                    pass  # Keep original format if parsing fails
            
            if 'end_time' in template_data['appointment'] and isinstance(template_data['appointment']['end_time'], str):
                try:
                    # Try to parse and format the time as "03:00 PM"
                    time_obj = datetime.strptime(template_data['appointment']['end_time'], '%I:%M %p')
                    template_data['appointment']['end_time'] = time_obj.strftime('%I:%M %p')
                except ValueError:
                    pass  # Keep original format if parsing fails
        
        template = Template(html_content)
        html_content = template.render(**template_data)
        
        # Attach HTML content
        part = MIMEText(html_content, 'html')
        msg.attach(part)
        
        # Connect to SMTP server
        server = smtplib.SMTP(email_host, email_port)
        server.starttls()  # Secure the connection
        
        # Login to sender email
        server.login(sender_email, sender_password)
        
        # Send email
        server.send_message(msg)
        server.quit()
        
        print(f"Email sent successfully to {patient.email}")
        return True, "Appointment email sent successfully"
    
    except Exception as e:
        print(f"Error sending appointment email: {str(e)}")
        return False, str(e)
