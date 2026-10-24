import os
import bcrypt
import pytest
os.environ["DATABASE_URL"] = "sqlite:///./test-knownest.db"

from app.services.agent import safe_calculate
from app.services.auth import hash_password, verify_password
from app.services.parser import ChunkingConfig, split_document, split_text


def test_split_text_keeps_order_and_metadata():
    chunks = split_text("# Title\n\n" + "hello " * 1000, target_chars=200, overlap=20)
    assert chunks
    assert chunks[0].sequence == 0
    assert chunks[0].char_start == 0
    assert all(item.content for item in chunks)


def test_chunking_auto_prefers_markdown_headings_and_reports_profile():
    text = "# Guide\n\n" + ("Installation details. " * 60) + "\n\n## Usage\n\n" + ("Usage details. " * 60)
    chunks, stats = split_document(text, ChunkingConfig(chunk_size=180, chunk_overlap=20, enable_parent_child=False))
    assert chunks
    assert stats["selected_strategy"] == "heading"
    assert stats["profile"]["heading_count"] == 2
    assert any(chunk.heading_path == ["Guide"] for chunk in chunks)


def test_chunking_config_rejects_invalid_overlap():
    try:
        ChunkingConfig(chunk_size=100, chunk_overlap=100)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid overlap accepted")


def test_calculator_rejects_code():
    assert safe_calculate("2 + 3 * 4") == 14
    try:
        safe_calculate("__import__('os').system('whoami')")
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe expression accepted")


def test_password_hash_supports_multibyte_passwords():
    password = "密码" * 12
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password(password + "!", hashed)


@pytest.mark.parametrize("prefix", ["knownest-sha256$", "weknora-sha256$"])
def test_password_hash_remains_compatible_after_rebranding(prefix):
    password = "existing-account-password"
    current = hash_password(password)
    assert current.startswith("knownest-sha256$")
    stored = prefix + current.split("$", 1)[1]
    assert verify_password(password, stored)
    assert not verify_password("wrong-password", stored)


def test_legacy_bcrypt_password_still_works():
    password = "existing-bcrypt-password"
    stored = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    assert verify_password(password, stored)
    assert not verify_password("wrong-password", stored)
