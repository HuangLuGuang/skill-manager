"""Audit text keeps its byte limits and exact accepted character set."""
import pytest
from pydantic import ValidationError

from backend.aidr_behavior import safe
from backend.aidr_content import Content


def content(text):
    return Content(kind='command_body', source_field='input.command', block=0,
                   text=text, source_bytes=len(text.encode()), redacted=False, truncated=False)


@pytest.mark.parametrize('codepoint', [*range(32), 32, 127, 128, 159, 0x2028, 0x4e2d, 0x1f600])
def test_character_validation_preserves_controls_and_unicode(codepoint):
    text = 'x' * 1024 + chr(codepoint) + '\n\tend'
    if codepoint < 32 and codepoint not in (9, 10):
        with pytest.raises(ValidationError, match='audit_content_control_invalid'):
            content(text)
        with pytest.raises(ValueError, match='behavior_text_limit'):
            safe(text, 32768, redact=False)
    else:
        assert content(text).text == text
        assert safe(text, 32768, redact=False) == text


def test_byte_limits_and_secret_checks_still_apply():
    text = '😀' * 8192
    assert content(text).text == text
    assert safe(text, 32768, redact=False) == text
    with pytest.raises(ValidationError, match='audit_content_field_invalid'):
        content(text + 'a')
    with pytest.raises(ValueError, match='behavior_text_limit'):
        safe(text + 'a', 32768, redact=False)
    with pytest.raises(ValueError, match='behavior_secret_rejected'):
        safe('password=synthetic-test-value', 32768)
