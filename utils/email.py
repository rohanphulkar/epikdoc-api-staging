import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from decouple import config
from typing import Union, List, Optional
from pathlib import Path

EMAIL_SENDER = str(config('EMAIL_SENDER'))
EMAIL_PASSWORD = str(config('EMAIL_PASSWORD')) 
EMAIL_HOST = str(config('EMAIL_HOST'))
EMAIL_PORT = int(config('EMAIL_PORT'))

def send_email(sender_email: str, sender_password: str, receiver_emails: Union[str, List[str]], 
              subject: str, body: str, attachments: Optional[List[Union[str, Path]]] = None) -> bool:
    try:
        # Convert single email to list if needed
        if isinstance(receiver_emails, str):
            receiver_emails = [receiver_emails]
            
        # Set up the MIME
        message = MIMEMultipart()
        message['From'] = sender_email
        message['To'] = ", ".join(receiver_emails)
        message['Subject'] = subject
        
        # Add the body to the message
        message.attach(MIMEText(body, 'plain'))

        # Add attachments if any
        if attachments:
            for attachment in attachments:
                with open(str(attachment), 'rb') as f:
                    part = MIMEApplication(f.read(), Name=Path(attachment).name)
                    part['Content-Disposition'] = f'attachment; filename="{Path(attachment).name}"'
                    message.attach(part)
        
        # Create SMTP session for sending the mail
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.ehlo()  # Identify yourself to the server
        server.starttls()  # Enable SSL/TLS security
        server.ehlo()  # Re-identify yourself over TLS connection
        
        # Login with the sender's email and password
        server.login(sender_email, sender_password)
        
        # Send the email
        text = message.as_string()
        server.sendmail(sender_email, receiver_emails, text)
        
        # Terminate the session
        server.quit()
        print("Email sent successfully!")
        return True
        
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

# Use the configured email credentials
sender_email = EMAIL_SENDER
sender_password = EMAIL_PASSWORD

def send_forgot_password_email(receiver_email: str, link: str) -> bool:
    try:    
        subject = "Password Reset Request for Your Account"
        body = f"""
Dear User,

We received a request to reset the password for your account. If you didn't make this request, please ignore this email.

To reset your password, please click on the following link or copy and paste it into your browser:

{link}

This link will expire in 3 hours for security reasons.

If you have any issues or need assistance, please don't hesitate to contact our support team.

Best regards,
Backup Doc
"""
        return send_email(sender_email, sender_password, receiver_email, subject, body)
    except Exception as e:
        print(f"Failed to send forgot password email: {e}")
        return False

def contact_us_email(first_name: str, last_name: str, email: str, topic: str, 
                    company_name: str, company_size: str, query: str) -> bool:
    try:
        subject = f"New Contact Us Query from {first_name} {last_name}"
        body = f"""
Dear Support Team,

You have received a new contact us query. Here are the details:

First Name: {first_name}
Last Name: {last_name}
Email: {email}
Topic: {topic}
Company Name: {company_name}
Company Size: {company_size}
Query: {query}

Please address this query at your earliest convenience.

Best regards,
Your Automated Email System
"""
        return send_email(sender_email, sender_password, EMAIL_SENDER, subject, body)
    except Exception as e:
        print(f"Failed to send contact us email: {e}")
        return False

def send_feedback_email(email: str, feedback) -> bool:
    try:
        subject = "New Feedback from User"
        body = f"""
Dear Support Team,

A new feedback has been submitted with the following details:

User Email: {email}
Rating: {feedback.rating}/5
Feedback: {feedback.feedback}
Suggestions: {feedback.suggestions if feedback.suggestions else 'No suggestions provided'}

Submitted at: {feedback.created_at.strftime('%B %d, %Y at %I:%M %p')}

"""
        receivers = ["rohan@epikdoc.com"]  # Hardcoded receivers
        success = True
        for receiver_email in receivers:
            if not send_email(sender_email, sender_password, receiver_email, subject, body):
                success = False
        return success
    except Exception as e:
        print(f"Failed to send feedback email: {e}")
        return False
    

def send_invoice_email(invoice_number: str, customer_name: str, customer_email: str, 
                      customer_phone: str, items: list, subtotal: float, discount: float, 
                      status: str, output_file: Union[str, Path]) -> bool:
    try:
        subject = f"Invoice {invoice_number} for {customer_name}"
        body = f"""Dear {customer_name},

Thank you for your business. Please find attached your invoice {invoice_number}.

If you have any questions, please don't hesitate to contact us at support@epikdoc.com.

Best regards,
Epikdoc AI Team"""

        # Send email with attachment
        return send_email(
            sender_email, 
            sender_password,
            customer_email,
            subject,
            body,
            attachments=[output_file]
        )
    except Exception as e:
        print(f"Failed to send invoice email: {e}")
        return False
    
def send_support_ticket_email(user_email: str, title: str, description: str, priority: str, status: str) -> bool:
    try:
        subject = f"Support Ticket Confirmation - {title}"
        body = f"""Dear User,

Thank you for submitting a support ticket. We have received your request and will get back to you as soon as possible.

Ticket Details:
--------------
Title: {title}
Description: {description}
Priority Level: {priority}
Current Status: {status}

We will keep you updated on the status of your ticket via email. If you have any additional information to provide, please reply to this email.

Best regards,
Epikdoc Support Team"""

        # Send confirmation to user
        user_notification = send_email(sender_email, sender_password, user_email, subject, body)
        
        # Send notification to support team
        support_subject = f"New Support Ticket: {title} - {priority} Priority"
        support_body = f"""New support ticket submitted:

User Email: {user_email}
Title: {title}
Description: {description}
Priority: {priority}
Status: {status}

Please review and take appropriate action."""

        support_email = "rohan@epikdoc.com"
        support_notification = send_email(sender_email, sender_password, support_email, support_subject, support_body)
        
        return user_notification and support_notification

    except Exception as e:
        print(f"Failed to send support ticket email: {e}")
        return False