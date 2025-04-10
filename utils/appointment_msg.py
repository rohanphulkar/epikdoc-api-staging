from datetime import datetime
from sqlalchemy.orm import Session
from appointment.models import Appointment, AppointmentStatus
from patient.models import Patient
from auth.models import User
from utils.email import send_email
import requests
from utils.config import SMS_API_KEY, EMAIL_SENDER, EMAIL_PASSWORD

async def send_appointment_email(
    db: Session,
    appointment_id: str
) -> tuple[bool, str]:
    """
    Send appointment confirmation email
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

        # Format email message with better structure
        message = f"""
Dear {patient.name},

Your appointment has been {appointment.status.value} with Dr. {doctor.name}.

Appointment Details:
------------------
Notes: {appointment.notes}
Date: {appointment.appointment_date.strftime('%B %d, %Y')}
Time: {appointment.start_time.strftime('%I:%M %p')} - {appointment.end_time.strftime('%I:%M %p')}

Doctor Details:
-------------
Name: Dr. {doctor.name}
Email: {doctor.email}
Phone: {doctor.phone if doctor.phone else "Not provided"}

Important Notes:
--------------
- Please arrive 10 minutes before your scheduled time
- Bring any relevant medical records or test results
- If you need to cancel or reschedule, please contact us at least 24 hours in advance

If you have any questions or concerns, please don't hesitate to contact us.

Best regards,
Dr. {doctor.name}
"""
        # Use the centralized email sending function
        return send_email(
            receiver_emails=patient.email if patient.email else [],
            subject=subject,
            body=message
        ), "Appointment email sent successfully"

    except Exception as e:
        print(f"Error sending appointment email: {str(e)}")
        return False, str(e)


def send_appointment_sms(db: Session, mobile_number: str, appointment_id: str) -> tuple[bool, str]:
    """
    Send SMS notification about appointment status to the patient's mobile number
    using 2Factor.in SMS API service.
    
    Args:
        db: Database session
        mobile_number: Patient's mobile number
        appointment_id: ID of the appointment
        
    Returns:
        Tuple of (success_status, message)
    """
    try:        
        url = f"https://2factor.in/API/V1/{SMS_API_KEY}/ADDON_SERVICES/SEND/TSMS"

        # Fetch appointment details
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            print("Appointment not found")
            return False, "Appointment not found"
        
        # Get doctor information
        doctor = db.query(User).filter(User.id == appointment.doctor_id).first()
        doctor_name = f"Dr. {doctor.name}" if doctor else "Dr. Unknown"
        
        # Format appointment details
        status = appointment.status.value.capitalize()
        date = appointment.appointment_date.strftime('%B %d, %Y')
        time = appointment.start_time.strftime('%I:%M %p')
        
        # Prepare SMS payload with template variables
        payload = {
            'From': 'EPKDOC',
            'To': mobile_number,
            'TemplateName': 'EPKDCAPPT',
            'VAR1': doctor_name,
            'VAR2': status,
            'VAR3': date,
            'VAR4': time,
            'Msg': f'Your appointment with {doctor_name} is {status}.\n📅 Date: {date}\n⏰ Time: {time}'
        }

        # Send SMS request
        response = requests.post(url, data=payload)
        response.raise_for_status()  # Raise exception for HTTP errors
        
        return True, "Appointment SMS sent successfully"
    except requests.exceptions.RequestException as e:
        print(f"SMS API request error: {str(e)}")
        return False, f"SMS API error: {str(e)}"
    except Exception as e:
        print(f"Error sending appointment SMS: {str(e)}")
        return False, str(e)
