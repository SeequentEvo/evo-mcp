# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_python_license_headers.py"


def _load_checker_module():
    spec = importlib.util.spec_from_file_location("check_python_license_headers", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_has_required_license_header_accepts_standard_header(tmp_path):
    checker = _load_checker_module()
    path = tmp_path / "sample.py"
    path.write_text(
        "# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated\n"
        "#\n"
        "# SPDX-License-Identifier: Apache-2.0\n"
        "\n"
        "print('ok')\n",
        encoding="utf-8",
    )

    assert checker.has_required_license_header(path) is True


def test_has_required_license_header_accepts_shebang_before_header(tmp_path):
    checker = _load_checker_module()
    path = tmp_path / "script.py"
    path.write_text(
        "#!/usr/bin/env python3\n\n"
        "# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated\n"
        "#\n"
        "# SPDX-License-Identifier: Apache-2.0\n"
        "\n"
        "print('ok')\n",
        encoding="utf-8",
    )

    assert checker.has_required_license_header(path) is True


def test_find_missing_license_headers_reports_files_without_header(tmp_path):
    checker = _load_checker_module()
    good = tmp_path / "good.py"
    bad = tmp_path / "bad.py"
    good.write_text(
        "# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated\n#\n# SPDX-License-Identifier: Apache-2.0\n",
        encoding="utf-8",
    )
    bad.write_text("print('missing')\n", encoding="utf-8")

    missing = checker.find_missing_license_headers([str(good), str(bad)])

    assert missing == [bad.resolve()]


def test_main_returns_non_zero_when_missing_headers_found(tmp_path, capsys):
    checker = _load_checker_module()
    bad = tmp_path / "bad.py"
    bad.write_text("print('missing')\n", encoding="utf-8")

    result = checker.main([str(bad)])

    assert result == 1
    assert "Missing required SPDX header" in capsys.readouterr().out


def test_add_required_license_header_inserts_header_at_top(tmp_path):
    checker = _load_checker_module()
    bad = tmp_path / "bad.py"
    bad.write_text("\nprint('missing')\n", encoding="utf-8")

    changed = checker.add_required_license_header(bad)

    assert changed is True
    assert bad.read_text(encoding="utf-8") == (
        "# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated\n"
        "#\n"
        "# SPDX-License-Identifier: Apache-2.0\n"
        "\n"
        "print('missing')\n"
    )


def test_add_required_license_header_preserves_shebang(tmp_path):
    checker = _load_checker_module()
    bad = tmp_path / "script.py"
    bad.write_text("#!/usr/bin/env python3\n\nprint('missing')\n", encoding="utf-8")

    changed = checker.add_required_license_header(bad)

    assert changed is True
    assert bad.read_text(encoding="utf-8") == (
        "#!/usr/bin/env python3\n"
        "\n"
        "# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated\n"
        "#\n"
        "# SPDX-License-Identifier: Apache-2.0\n"
        "\n"
        "print('missing')\n"
    )


def test_main_fix_mode_adds_header_and_returns_zero(tmp_path):
    checker = _load_checker_module()
    bad = tmp_path / "bad.py"
    bad.write_text("print('missing')\n", encoding="utf-8")

    result = checker.main(["--fix", str(bad)])

    assert result == 0
    assert checker.has_required_license_header(bad) is True
