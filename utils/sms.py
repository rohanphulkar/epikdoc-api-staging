import http.client
import json
from decouple import config
from typing import Dict, List, Any, Union
from utils.config import MSG91_AUTH_KEY

def send_sms_template(template_id: str, mobile_numbers: List[str], variables: Dict[str, str]) -> Union[bool, Dict[str, Any]]:
    """
    Send SMS using MSG91 template API
    
    Args:
        mobile_numbers: List of mobile numbers (with country code)
        template_id: MSG91 template ID
        variables: Dictionary of variables to be replaced in the template
        
    Returns:
        True if successful, False if failed, or API response as dictionary
    """
    try:
        conn = http.client.HTTPSConnection("control.msg91.com")
        
        # Prepare recipients data
        recipients = []
        for mobile in mobile_numbers:
            recipient_data = {"mobiles": f"91{mobile}"}
            recipient_data.update(variables)
            recipients.append(recipient_data)
        
        # Prepare payload
        payload_data = {
            "template_id": template_id,
            "short_url": "0",
            "recipients": recipients
        }
        
        payload = json.dumps(payload_data)
        
        # Get auth key from environment variables
        auth_key = str(MSG91_AUTH_KEY)
        
        headers = {
            'authkey': auth_key,
            'accept': "application/json",
            'content-type': "application/json"
        }
        
        conn.request("POST", "/api/v5/flow", payload, headers)
        
        res = conn.getresponse()
        data = res.read()
        
        result = json.loads(data.decode("utf-8"))
        if result.get("type") == "success":
            return True
        else:
            print(f"Error sending SMS: {result}")
            return False
    except Exception as e:
        print(f"Error sending SMS: {e}")
        return False
