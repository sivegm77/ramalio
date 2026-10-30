"""Regression test: tmux subprocess errors must not leak secrets (E7-S2 R14).

``TmuxRunner`` runs external ``tmux`` commands whose stderr is untrusted and may
echo secrets.  Any failing tmux operation must sanitize that stderr through the
central ``redact_diagnostic`` before embedding it in an error message, exactly
like the Docker Compose driver does.
"""

from __future__ import annotations

import subprocess

import pytest

from ramalio.capabilities.tmux.runtime import TmuxRunner
from ramalio.core.errors import TmuxOperationFailedError


@pytest.mark.parametrize(
    ("op", "args"),
    [
        ("new_session", ("sess",)),
        ("kill_session", ("sess",)),
        ("set_session_env", ("sess", "RAMALIO_TARGET", "feat-a")),
    ],
)
def test_tmux_error_redacts_secret_in_stderr(monkeypatch, op, args) -> None:
    runner = TmuxRunner()

    # Force the underlying tmux invocation to "fail" with a secret on stderr.
    def _fake_run(*_a, **_k):
        return subprocess.CompletedProcess(
            [], 1, "", "API_KEY=super-secret-value tmux boom"
        )

    monkeypatch.setattr(runner, "_run", _fake_run)

    with pytest.raises(TmuxOperationFailedError) as exc:
        getattr(runner, op)(*args)

    message = str(exc.value)
    assert "super-secret-value" not in message, f"secret leaked: {message!r}"
    assert "API_KEY=***" in message, (
        f"expected the secret assignment to be masked, got: {message!r}"
    )
