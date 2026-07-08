"""Send alerts through whichever channel(s) you've configured via env vars.

All channels are optional and independent — set the env vars for the ones you
want and leave the rest unset. Nothing is sent if none are configured (the run
just logs to stdout, which is handy for testing).

  EMAIL (SMTP):
    ALERT_EMAIL_TO, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
    (For Gmail, use an App Password, not your normal password.)
  PHONE PUSH (ntfy.sh — free, install the ntfy app and subscribe to a topic):
    NTFY_TOPIC   (e.g. "bc-salmon-a7f3" — pick something unguessable)
    NTFY_SERVER  (optional, defaults to https://ntfy.sh)
  DISCORD:
    DISCORD_WEBHOOK_URL
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.text import MIMEText

import requests

from .analyze import Assessment


def _enabled_channels() -> list[str]:
    ch = []
    if os.getenv("ALERT_EMAIL_TO") and os.getenv("SMTP_HOST"):
        ch.append("email")
    if os.getenv("NTFY_TOPIC"):
        ch.append("ntfy")
    if os.getenv("DISCORD_WEBHOOK_URL"):
        ch.append("discord")
    return ch


def build_message(alerts: list[Assessment]) -> tuple[str, str]:
    """Return (subject, body) for the given alertable assessments."""
    n = len(alerts)
    subject = f"🎣 {n} BC river{'s' if n != 1 else ''} looking good for salmon"
    lines = []
    for a in sorted(alerts, key=lambda x: x.verdict):
        lines.append(f"{a.emoji} {a.river}")
        lines.append(f"    {a.headline}")
        if a.outlook:
            lines.append(f"    Outlook: {a.outlook}")
        if a.best_time:
            lines.append(f"    Best time: {a.best_time}")
        lines.append("")
    return subject, "\n".join(lines).strip()


def send(alerts: list[Assessment]) -> None:
    if not alerts:
        return
    subject, body = build_message(alerts)
    channels = _enabled_channels()
    if not channels:
        print("[notify] No channel configured. Would have sent:\n")
        print(subject)
        print(body)
        return
    for ch in channels:
        try:
            _SENDERS[ch](subject, body)
            print(f"[notify] sent via {ch}")
        except Exception as e:  # never let one channel break the run
            print(f"[notify] {ch} failed: {e}")


def _send_email(subject: str, body: str) -> None:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.getenv("SMTP_USER", os.environ["ALERT_EMAIL_TO"])
    msg["To"] = os.environ["ALERT_EMAIL_TO"]
    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        if os.getenv("SMTP_USER"):
            server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        server.send_message(msg)


def _send_ntfy(subject: str, body: str) -> None:
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    topic = os.environ["NTFY_TOPIC"]
    requests.post(
        f"{server}/{topic}",
        data=body.encode("utf-8"),
        headers={"Title": subject, "Tags": "fishing,ocean", "Priority": "default"},
        timeout=30,
    ).raise_for_status()


def _send_discord(subject: str, body: str) -> None:
    requests.post(
        os.environ["DISCORD_WEBHOOK_URL"],
        json={"content": f"**{subject}**\n```\n{body}\n```"},
        timeout=30,
    ).raise_for_status()


_SENDERS = {"email": _send_email, "ntfy": _send_ntfy, "discord": _send_discord}
