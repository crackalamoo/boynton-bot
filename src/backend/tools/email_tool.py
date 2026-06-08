import os
import smtplib
from email.message import EmailMessage

from bs4 import BeautifulSoup

EMAIL_TOOL = {
    "type": "function",
    "function": {
        "name": "send_email",
        "description": "Send an email to the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "The email subject line.",
                },
                "body": {
                    "type": "string",
                    "description": (
                        "The body of the email as HTML."
                    ),
                },
            },
            "required": ["subject", "body"],
        },
    },
}

def execute_email_tool(subject: str, body: str) -> str:
    address = os.environ["EMAIL_ADDRESS"]
    password = os.environ["EMAIL_PASSWORD"]
    host = os.environ.get("EMAIL_SMTP_HOST", "smtp.hostinger.com")
    port = int(os.environ.get("EMAIL_SMTP_PORT", "465"))
    recipient = os.environ["EMAIL_RECIPIENT"]

    plain_text = BeautifulSoup(body, "html.parser").get_text()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = recipient
    msg.set_content(plain_text)
    msg.add_alternative(body, subtype="html")

    with smtplib.SMTP_SSL(host, port) as smtp:
        _ = smtp.login(address, password)
        _ = smtp.send_message(msg)

    return f"Email sent to {recipient}: {subject!r}"

