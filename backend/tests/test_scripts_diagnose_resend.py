"""Guard test for scripts/diagnose_resend.py (SPEC-048).

The script is a manual, network-touching diagnostic run through `infisical run`.
The one thing worth pinning here is that it exits cleanly with guidance — not a
traceback — when it's run without `RESEND_API_KEY` (i.e. not through infisical).
"""

import importlib


def test_main_exits_1_with_guidance_when_api_key_is_missing(monkeypatch, capsys):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    mod = importlib.import_module("scripts.diagnose_resend")

    rc = mod.main()

    out = capsys.readouterr().out
    assert rc == 1
    assert "RESEND_API_KEY is not set" in out


def test_mask_hides_local_part_of_an_email():
    mod = importlib.import_module("scripts.diagnose_resend")

    assert mod._mask("receipts@negolah.my").endswith("@negolah.my")
    assert "receipts" not in mod._mask("receipts@negolah.my")
    assert mod._mask(None) == "<unset>"
    # "Name <addr>" display forms are not secret and pass through untouched.
    assert mod._mask("Nego-Lah <x@y.my>") == "Nego-Lah <x@y.my>"
