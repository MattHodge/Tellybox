"""Access-log redaction (NF-3): signed media URLs never land in logs whole."""

import logging

from tellybox.web.logging import RedactMediaSignatures

SIGNED = "/media/42/1780000000/AbCdEf12345678901234-_.mp4"
REDACTED = "/media/42/…/<redacted>.mp4"


def _access_record(full_path: str) -> logging.LogRecord:
    # Shaped like uvicorn's access log: '%s - "%s %s HTTP/%s" %d', args (client_addr, method, full_path, http_version, status)
    return logging.LogRecord(
        name="uvicorn.access", level=logging.INFO, pathname=__file__, lineno=1,
        msg='%s - "%s %s HTTP/%s" %d', args=("127.0.0.1:1234", "GET", full_path, "1.1", 200), exc_info=None,
    )


def test_redacts_signed_media_path_in_args():
    record = _access_record(SIGNED)
    assert RedactMediaSignatures().filter(record) is True
    assert record.getMessage() == f'127.0.0.1:1234 - "GET {REDACTED} HTTP/1.1" 200'


def test_redacts_signed_media_path_with_query_string():
    record = _access_record(SIGNED + "?x=1")
    RedactMediaSignatures().filter(record)
    assert record.getMessage() == f'127.0.0.1:1234 - "GET {REDACTED}?x=1 HTTP/1.1" 200'


def test_leaves_unrelated_paths_untouched():
    record = _access_record("/api/kid/home")
    RedactMediaSignatures().filter(record)
    assert record.getMessage() == '127.0.0.1:1234 - "GET /api/kid/home HTTP/1.1" 200'


def test_redacts_in_a_preformatted_message_too():
    record = logging.LogRecord(
        name="uvicorn.access", level=logging.INFO, pathname=__file__, lineno=1,
        msg=f"served {SIGNED}", args=(), exc_info=None,
    )
    RedactMediaSignatures().filter(record)
    assert record.getMessage() == f"served {REDACTED}"


def test_non_string_args_are_left_alone():
    record = logging.LogRecord(
        name="uvicorn.access", level=logging.INFO, pathname=__file__, lineno=1,
        msg="status=%d", args=(200,), exc_info=None,
    )
    assert RedactMediaSignatures().filter(record) is True
    assert record.getMessage() == "status=200"
