from decouple import config
import requests
from utils.email import send_email, sender_email, sender_password
    
def send_otp(mobile_number: str, otp: str):
    """Send OTP via 2Factor.in SMS API"""
    try:
        url = f'https://2factor.in/API/V1/{config("SMS_API_KEY")}/SMS/{mobile_number}/{otp}/BUD'
        
        response = requests.get(url)
        response.raise_for_status()
        
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error sending OTP: {e}")
        return False
    
def send_otp_email(email: str, otp: str):
    """Send OTP via email"""
    try:
        subject = "Your OTP Code"
        body = f"Your OTP code is: {otp}\n\nThis code will expire soon. Please do not share this code with anyone."
        
        return send_email(
            sender_email=sender_email,
            sender_password=sender_password,
            receiver_emails=email,
            subject=subject,
            body=body
        )
    except Exception as e:
        print(f"Error sending OTP email: {e}")
        return False
