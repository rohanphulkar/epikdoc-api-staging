from decouple import config

SMS_API_KEY = config('SMS_API_KEY')
JWT_SECRET = str(config('JWT_SECRET'))
JWT_ALGORITHM = str(config('JWT_ALGORITHM'))

EMAIL_SENDER = str(config('EMAIL_SENDER'))
EMAIL_PASSWORD = str(config('EMAIL_PASSWORD')) 
EMAIL_HOST = str(config('EMAIL_HOST'))
EMAIL_PORT = int(config('EMAIL_PORT'))
EMAIL_SEND_URL = str(config('EMAIL_SEND_URL'))

GOOGLE_API_KEY = str(config('GOOGLE_API_KEY'))

OTP_TEMPLATE_ID = str(config('OTP_TEMPLATE_ID'))
APPOINTMENT_TEMPLATE_ID = str(config('APPOINTMENT_TEMPLATE_ID'))
MSG91_AUTH_KEY = str(config('MSG91_AUTH_KEY'))

