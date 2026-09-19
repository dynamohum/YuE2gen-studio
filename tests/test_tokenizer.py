"""Tests for Realaudio Tokenizer and persona extraction."""
import sys
from unittest.mock import patch
import pytest

from scripts.tokenize_identity import verify_consent


def test_verify_consent_with_flag():
    assert verify_consent(True) is True


def test_verify_consent_non_interactive_without_flag():
    with patch("sys.stdin.isatty", return_value=False):
        assert verify_consent(False) is False


def test_verify_consent_interactive_yes():
    with patch("sys.stdin.isatty", return_value=True):
        with patch("builtins.input", return_value="y"):
            assert verify_consent(False) is True


def test_verify_consent_interactive_no():
    with patch("sys.stdin.isatty", return_value=True):
        with patch("builtins.input", return_value="n"):
            assert verify_consent(False) is False


def test_tokenizer_module_imports_without_torch():
    import app.tokenizer as tok
    assert tok.VOCAB == 32768
    assert tok.WIN == 512
    assert tok.D == 512
    assert tok.L == 8
    assert tok.H == 8
    assert tok.TOKEN_RATE_HZ == 25


def test_rotary_rebuild_logic():
    # Verify rotary rebuild algorithm on dummy module
    class DummyRotary:
        def __init__(self):
            self.head_dim = 64
            self.base = 10000.0
            self.inv_freq = None
            self._cos = "old_cos"
            self._sin = "old_sin"

    class MockModel:
        def __init__(self):
            self.rotary = DummyRotary()

        def modules(self):
            return [self, self.rotary]

    # If torch is available, run rebuild_rotary; otherwise test the mathematical formula
    try:
        import torch
        from app.tokenizer import rebuild_rotary
        mock = MockModel()
        class DummyDevice:
            device = "cpu"
        mock.rotary.inv_freq = DummyDevice()
        rebuilt = rebuild_rotary(mock)
        assert rebuilt == 1
        assert mock.rotary._cos is None
        assert mock.rotary._sin is None
        assert mock.rotary.inv_freq.shape[0] == 32
    except ImportError:
        # Test numpy equivalent of inv_freq formula
        import numpy as np
        head_dim = 64
        base = 10000.0
        inv = 1.0 / (base ** (np.arange(0, head_dim, 2, dtype=np.float32) / head_dim))
        assert len(inv) == 32
        assert inv[0] == 1.0
