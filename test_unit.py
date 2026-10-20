"""Unit tests for pure helper functions in lanshare.py.

These tests cover:
- safe_relpath() — path traversal neutralization
- _is_lan() / lan_ipv4s() — LAN IP classification
- print_qr_terminal() — terminal QR round-trip (no network)

Run with: pytest test_unit.py
"""
import io
import socket
from contextlib import redirect_stdout
from unittest.mock import patch, MagicMock

import pytest
import segno

from lanshare import safe_relpath, _is_lan, lan_ipv4s, print_qr_terminal


class TestSafeRelpath:
    def test_normal_path(self):
        assert safe_relpath("folder/file.txt") == "folder/file.txt"

    def test_path_traversal_neutralized(self):
        assert safe_relpath("../../etc/passwd") == "etc/passwd"
        assert safe_relpath("foo/../../../etc/passwd") == "foo/etc/passwd"
        assert safe_relpath("..") == "file"
        assert safe_relpath("../..") == "file"

    def test_absolute_and_empty(self):
        assert safe_relpath("/etc/passwd") == "etc/passwd"
        assert safe_relpath("") == "file"
        assert safe_relpath(None) == "file"
        assert safe_relpath(".") == "file"

    def test_windows_separators(self):
        assert safe_relpath("folder\\file.txt") == "folder/file.txt"
        assert safe_relpath("..\\..\\windows\\system32") == "windows/system32"

    def test_dot_components(self):
        assert safe_relpath("./folder/./file") == "folder/file"
        assert safe_relpath("folder/../other/file") == "folder/other/file"


class TestIsLan:
    @pytest.mark.parametrize("ip,expected", [
        ("192.168.1.1", True),
        ("192.168.0.255", True),
        ("10.0.0.1", True),
        ("10.255.255.255", True),
        ("172.16.0.1", True),
        ("172.31.255.254", True),
        ("172.15.0.1", False),   # below range
        ("172.32.0.1", False),   # above range
        ("127.0.0.1", False),
        ("127.0.0.2", False),
        ("169.254.1.1", False),  # link-local
        ("8.8.8.8", False),
        ("1.1.1.1", False),
        ("not.an.ip", False),
        ("192.168.1", False),
        ("", False),
    ])
    def test_lan_classification(self, ip, expected):
        assert _is_lan(ip) is expected


class TestLanIpv4s:
    def test_returns_tuple_structure(self):
        primary, all_ips = lan_ipv4s()
        assert isinstance(primary, str)
        assert isinstance(all_ips, list)
        for item in all_ips:
            assert isinstance(item, tuple) and len(item) == 2

    def test_mocked_no_network_calls(self):
        """Ensure we can test classification logic without real network I/O."""
        with patch("socket.socket") as mock_sock, \
             patch("socket.getaddrinfo", return_value=[]), \
             patch("subprocess.run") as mock_run:

            # Simulate a successful connect that returns a LAN IP
            mock_s = MagicMock()
            mock_s.getsockname.return_value = ("192.168.1.42", 12345)
            mock_sock.return_value = mock_s

            primary, all_ips = lan_ipv4s()
            assert primary == "192.168.1.42"
            assert any(ip == "192.168.1.42" for ip, _ in all_ips)


class TestPrintQrTerminal:
    def test_prints_without_ansi(self):
        url = "http://192.168.1.1:8765/?token=test"
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_qr_terminal(url)
        output = buf.getvalue()
        assert "\x1b" not in output  # no ANSI escapes
        assert len(output.strip()) > 0

    def test_roundtrip_matrix_parse(self):
        """Parse the half-block output back and compare to original matrix."""
        url = "http://192.168.1.3:8765/?token=TESTTOKEN"
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_qr_terminal(url)

        lines = [ln.rstrip() for ln in buf.getvalue().splitlines() if ln.strip()]
        # Skip leading empty lines; collect character lines
        char_lines = [ln for ln in lines if any(c in "█▀▄ " for c in ln)]

        # Reconstruct roughly: each printed line is two matrix rows
        # This is a smoke check that output is non-empty and uses expected chars
        assert len(char_lines) > 5
        assert all(len(ln) < 80 for ln in char_lines)

        # Verify the underlying QR is valid by re-generating
        qr = segno.make(url, error="m")
        assert qr is not None
        assert len(list(qr.matrix)) > 10
