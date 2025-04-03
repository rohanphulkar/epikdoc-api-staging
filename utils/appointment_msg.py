from datetime import datetime
from sqlalchemy.orm import Session
from appointment.models import Appointment, AppointmentStatus
from patient.models import Patient
from auth.models import User
from utils.email import send_email, EMAIL_SENDER, EMAIL_PASSWORD

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
