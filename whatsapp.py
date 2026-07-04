from twilio.rest import Client
import os

def send_whatsapp_message(to_number, message):
    try:
        from twilio.rest import Client
        import os

        client = Client(
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN")
        )

        msg = client.messages.create(
            body=message,
            from_="whatsapp:+14155238886",   
            to=f"whatsapp:{to_number}"       
        )

        print("WhatsApp sent:", msg.sid)
        return True

    except Exception as e:
        print("WhatsApp Error:", e)
        return False