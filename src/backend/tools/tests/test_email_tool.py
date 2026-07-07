from backend.tools.email_tool import execute_email_tool_stub


def test_email_stub_matches_real_success_message_shape(monkeypatch):
    monkeypatch.setenv("BOYNTON_EMAIL_RECIPIENT", "someone@example.com")
    result = execute_email_tool_stub("Test subject", "<p>body</p>")
    assert result == "Email sent to someone@example.com: 'Test subject'"
