from decouple import config
import requests
from utils.email import send_email, sender_email, sender_password
from utils.config import OTP_TEMPLATE_ID, APPOINTMENT_TEMPLATE_ID, MSG91_AUTH_KEY
from utils.sms import send_sms_template
    
def send_otp(mobile_number: str, otp: str):
    """Send OTP via MSG91 SMS API"""
    try:
        template_id = str(OTP_TEMPLATE_ID)
        mobile_numbers = [mobile_number]
        variables = {"otp": otp}
        response = send_sms_template(template_id, mobile_numbers, variables)
        if response is True:
            return True
        else:
            print(f"Error sending OTP: {response}")
            return False
    except Exception as e:
        print(f"Error sending OTP: {e}")
        return False
    
def send_otp_email(email: str, otp: str):
    """Send OTP via email"""
    try:
        subject = "Your OTP Code"
        body = f"Your OTP code is: {otp}\n\nThis code will expire soon. Please do not share this code with anyone."
        
        return send_email(
            receiver_emails=email,
            subject=subject,
            body=body
        )
    except Exception as e:
        print(f"Error sending OTP email: {e}")
        return False
