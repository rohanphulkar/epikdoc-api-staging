from decouple import config
import requests
    
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