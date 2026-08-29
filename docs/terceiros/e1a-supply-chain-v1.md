# E1A — deterministic Python and Actions supply chain

## Authority and reproducibility

`pyproject.toml` is the sole dependency declaration. `uv.lock` is its
version-controlled deterministic resolution for Python 3.13 and 3.14. The
repository retains `requirements*.txt` only as hash-pinned, generated
compatibility exports for the protected-base transition. They are not edited
as declarations and their generator command is embedded in each header.

The canonical tool version is `uv 0.12.6`. CI installs with
`uv sync --locked --no-install-project` and executes commands with
`uv run --no-sync`, so a stale or mutated lock fails closed.

## GitHub Actions provenance

The E1A workflow surface uses these official upstream identities:

- `actions/checkout` v4.4.0: `11d5960a326750d5838078e36cf38b85af677262`
- `actions/setup-python` v5.6.0: `a26af69be951a213d495a4c3e4e4022e16d87065`
- `astral-sh/setup-uv` v9.0.0: `c771a70e6277c0a99b617c7a806ffedaca235ff9`

Every checkout disables persisted credentials. No new permission, secret,
token, deployment path, telemetry, or private egress is introduced.

## Advisory scanner disposition

`actionlint 1.7.12` is the syntax gate. `zizmor 1.29.0` is advisory and
contextual. The two `pull_request_target` findings are accepted for the
existing protected-base judges: they retain read-only permissions, exact and
separate base/candidate checkouts, and execute only trusted-base code. The
capability workflow's environment handoff is a strict trusted-base-generated
boolean and remains contextual. E1A does not redesign those trust boundaries.
