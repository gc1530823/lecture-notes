"""메일 보내기 (비밀번호 찾기 · 이메일 확인 인증번호). 무료: 서버 주인의 Gmail 계정 + 앱 비밀번호로 Gmail SMTP.

설정은 서버 주인이 앱의 설정 화면에서 넣는다 (DB 의 app_settings). 서버 환경 변수 SMTP_USER / SMTP_PASSWORD 가 있으면 그것을 쓴다.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

HOST, PORT = "smtp.gmail.com", 465


def account(db) -> tuple[str, str] | None:
    user = os.environ.get("SMTP_USER") or db.get_setting("smtp_user")
    password = os.environ.get("SMTP_PASSWORD") or db.get_setting("smtp_password")
    return (user, password) if user and password else None


def send(db, to: str, subject: str, text: str) -> None:
    """보내지 못하면 RuntimeError (이유를 사람이 읽을 수 있게)"""
    acc = account(db)
    if acc is None:
        raise RuntimeError("메일 보내기가 아직 설정되지 않았어요. 서버 주인이 설정에서 Gmail 을 넣어야 해요.")
    user, password = acc
    msg = EmailMessage()
    msg["From"] = formataddr(("LUNE", user))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    try:
        with smtplib.SMTP_SSL(HOST, PORT, context=ssl.create_default_context(), timeout=20) as smtp:
            smtp.login(user, password.replace(" ", ""))
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError("Gmail 로그인이 안 돼요. 앱 비밀번호(16자리)가 맞는지 확인해 주세요.") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise RuntimeError(f"메일을 보내지 못했어요: {exc}") from exc
