from twilio.rest import Client
from decouple import config

def send_otp_via_phone(phone_number: str, otp: str):
    try:
        client = Client(config("TWILIO_ACCOUNT_SID"), config("TWILIO_AUTH_TOKEN"))
        client.messages.create(
            to=phone_number,
            from_=config("TWILIO_PHONE_NUMBER"),
            body=f"Your OTP for two factor authentication is {otp}"
        )
        return True
    except Exception as e:
        print(e)
        return False
    