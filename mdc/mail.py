"""Sign-in codes by email (SERVER.md, Phase 6).

Sent through SES's SMTP interface as IAM `mdc-ses`, on the `rvanegas.co`
identity that thefloor and famdirectorio share, through configuration set
`mdc`, so its bounces and complaints are told apart (rvanegas-site's
PROJECTS.md). Configured from the environment, the box's ~/mdc/.env:
MDC_SMTP_HOST, MDC_SMTP_PORT (587), MDC_SMTP_USER, MDC_SMTP_PASSWORD,
MDC_MAIL_FROM, MDC_SES_CONFIGURATION_SET.

Without MDC_SMTP_HOST nothing is sent, and sign-in says mail is unavailable;
MDC_MAIL_LOG=1 prints the code to stderr instead, for a local server.
"""

from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage


class MailUnavailable(RuntimeError):
    pass


def send_code(to: str, code: str, client_name: str) -> None:
    env = os.environ.get
    host = env("MDC_SMTP_HOST")
    if not host:
        if env("MDC_MAIL_LOG") == "1":
            print(f"mdc sign-in code for {to}: {code}", file=sys.stderr, flush=True)
            return
        raise MailUnavailable("sign-in mail is not configured on this server")
    message = EmailMessage()
    message["From"] = env("MDC_MAIL_FROM", "mdc <mdc@rvanegas.co>")
    message["To"] = to
    message["Subject"] = f"mdc sign-in code: {code}"
    message["X-SES-CONFIGURATION-SET"] = env("MDC_SES_CONFIGURATION_SET", "mdc")
    message.set_content(
        f"Your code to sign in to mdc is {code}.\n\n"
        f"{client_name} asked for it. It works for ten minutes, once.\n\n"
        "If you did not ask to sign in, ignore this message: nothing happens without the code.\n"
    )
    try:
        with smtplib.SMTP(host, int(env("MDC_SMTP_PORT", "587")), timeout=20) as smtp:
            smtp.starttls()
            smtp.login(env("MDC_SMTP_USER", ""), env("MDC_SMTP_PASSWORD", ""))
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailUnavailable(f"the sign-in mail could not be sent: {exc}") from exc
