"""Email notifier via SMTP.

Env vars:
- SMTP_HOST
- SMTP_PORT (optional, default 587)
- SMTP_USERNAME
- SMTP_PASSWORD
- EMAIL_FROM
- EMAIL_TO
"""

from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText


class EmailNotifier:
    def __init__(self):
        self.host = os.getenv("SMTP_HOST")
        self.port = int(os.getenv("SMTP_PORT", "587"))
        self.username = os.getenv("SMTP_USERNAME")
        self.password = os.getenv("SMTP_PASSWORD")
        self.email_from = os.getenv("EMAIL_FROM")
        self.email_to = os.getenv("EMAIL_TO")

    def enabled(self) -> bool:
        return all([self.host, self.username, self.password, self.email_from, self.email_to])

    def send(self, title: str, message: str) -> None:
        if not self.enabled():
            return

        msg = MIMEText(message, "plain", "utf-8")
        msg["Subject"] = title
        msg["From"] = self.email_from
        msg["To"] = self.email_to

        with smtplib.SMTP(self.host, self.port, timeout=20) as server:
            server.starttls()
            server.login(self.username, self.password)
            server.sendmail(self.email_from, [self.email_to], msg.as_string())
