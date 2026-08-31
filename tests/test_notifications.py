from unittest.mock import patch, MagicMock
import pytest
from app.services.notifications import send_telegram_message, send_email_message, notify_sync_result
from app.core.config import Settings


@patch("requests.post")
def test_send_telegram_message_success(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response
    
    send_telegram_message("my_bot_token", "my_chat_id", "Hello World")
    
    mock_post.assert_called_once_with(
        "https://api.telegram.org/botmy_bot_token/sendMessage",
        json={"chat_id": "my_chat_id", "text": "Hello World", "parse_mode": "HTML"},
        timeout=10
    )


@patch("requests.post")
def test_send_telegram_message_failure(mock_post):
    mock_post.side_effect = Exception("Network timeout")
    
    with pytest.raises(Exception) as exc:
        send_telegram_message("my_bot_token", "my_chat_id", "Hello World")
    assert "Network timeout" in str(exc.value)


@patch("smtplib.SMTP")
def test_send_email_message_smtp(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value = mock_smtp
    
    send_email_message(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="user@gmail.com",
        smtp_password="pwd",
        email_from="sender@gmail.com",
        email_to="receiver@gmail.com",
        subject="My Subject",
        html_body="<h1>Hello</h1>"
    )
    
    mock_smtp.ehlo.assert_called()
    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once_with("user@gmail.com", "pwd")
    mock_smtp.sendmail.assert_called_once()
    mock_smtp.quit.assert_called_once()


@patch("app.services.notifications.send_telegram_message")
@patch("app.services.notifications.send_email_message")
@patch("app.services.notifications.get_settings")
def test_notify_sync_result_both_enabled(mock_get_settings, mock_send_email, mock_send_telegram):
    # Configurar mock de settings
    mock_settings = Settings()
    mock_settings.telegram_enabled = True
    mock_settings.telegram_bot_token = "tok"
    mock_settings.telegram_chat_id = "chat"
    mock_settings.email_enabled = True
    mock_settings.smtp_host = "smtp.host"
    mock_settings.email_from = "from@mail.com"
    mock_settings.email_to = "to@mail.com"
    mock_get_settings.return_value = mock_settings
    
    result = {"issues_seen": 10, "issues_upserted": 2, "worklogs_upserted": 5}
    notify_sync_result(result, None)
    
    mock_send_telegram.assert_called_once()
    mock_send_email.assert_called_once()
    
    telegram_args = mock_send_telegram.call_args[0]
    assert telegram_args[0] == "tok"
    assert telegram_args[1] == "chat"
    assert "Sincronización Exitosa" in telegram_args[2]
    
    email_args = mock_send_email.call_args[0]
    assert email_args[4] == "from@mail.com"
    assert email_args[5] == "to@mail.com"
    assert "Sincronización Exitosa" in email_args[6]


@patch("app.services.notifications.send_telegram_message")
@patch("app.services.notifications.send_email_message")
@patch("app.services.notifications.get_settings")
def test_notify_sync_result_error(mock_get_settings, mock_send_email, mock_send_telegram):
    mock_settings = Settings()
    mock_settings.telegram_enabled = True
    mock_settings.telegram_bot_token = "tok"
    mock_settings.telegram_chat_id = "chat"
    mock_settings.email_enabled = True
    mock_settings.smtp_host = "smtp.host"
    mock_settings.email_from = "from@mail.com"
    mock_settings.email_to = "to@mail.com"
    mock_get_settings.return_value = mock_settings
    
    notify_sync_result(None, ValueError("Jira API returned 500"))
    
    mock_send_telegram.assert_called_once()
    mock_send_email.assert_called_once()
    
    assert "Sincronización Fallida" in mock_send_telegram.call_args[0][2]
    assert "Jira API returned 500" in mock_send_telegram.call_args[0][2]
    assert "Sincronización Fallida" in mock_send_email.call_args[0][6]
