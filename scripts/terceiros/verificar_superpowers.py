import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/terceiros/superpowers-manifest.json"
LICENSE = ROOT / ".agents/third-party/superpowers/LICENSE"
EXECUTABLE_SUFFIXES = {".py", ".js", ".cjs", ".mjs", ".ts", ".sh", ".ps1"}
NETWORK_PATTERN = re.compile(r"https?://|\bcurl\b|\bwget\b|\bfetch\s*\(", re.IGNORECASE)


def _hash(path):
    return subprocess.run(
        ["git", "hash-object", str(path)], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def verificar():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors = []
    expected = set(data["blobs"])
    actual = set()
    for skill in data["skill_trees"]:
        folder = ROOT / ".agents/skills" / skill
        actual.update(path.relative_to(ROOT).as_posix() for path in folder.rglob("*") if path.is_file())
    if actual != expected:
        errors.append(f"FILE_SET expected={sorted(expected)} actual={sorted(actual)}")
    for relative, blob in data["blobs"].items():
        path = ROOT / relative
        if not path.is_file() or _hash(path) != blob:
            errors.append(f"BLOB {relative}")
        elif path.suffix.lower() in EXECUTABLE_SUFFIXES:
            if NETWORK_PATTERN.search(path.read_text(encoding="utf-8")):
                errors.append(f"EXECUTABLE_EGRESS {relative}")
    if not LICENSE.is_file() or _hash(LICENSE) != data["license_blob"]:
        errors.append("LICENSE")
    policy = json.loads((ROOT / ".agents/superpowers-policy.json").read_text(encoding="utf-8"))
    if policy.get("allow_external_egress") is not False or policy.get("egress_default") != "DENY":
        errors.append("EGRESS_DEFAULT")
    if policy.get("telemetry_default") != "DISABLED":
        errors.append("TELEMETRY_DEFAULT")
    return errors


if __name__ == "__main__":
    failures = verificar()
    if failures:
        raise SystemExit("SUPERPOWERS_INTEGRITY_FAILED\n" + "\n".join(failures))
    print("SUPERPOWERS_INTEGRITY=100%")
    print("SUPERPOWERS_TELEMETRY_DEFAULT=DISABLED")
    print("SUPERPOWERS_EGRESS_DEFAULT=DENY")
