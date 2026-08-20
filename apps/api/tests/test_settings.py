"""`Settings` and `.env.example` must describe the same configuration.

`api/settings.py` says it "mirrors `.env.example` exactly — every var there has a field
here". That claim was true by discipline and checked by nothing, and the failure it guards
against is quiet in both directions: a field with no documented variable is configuration
nobody knows exists, and a documented variable with no field is one a fresh clone sets and
the app ignores.
"""

from __future__ import annotations

import re
from pathlib import Path

from api.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# Optional settings are listed commented-out in the example file, since a `.env` copied
# from it should not set them to an empty string.
VAR_PATTERN = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def documented_variables() -> set[str]:
    return set(VAR_PATTERN.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))


def test_the_example_file_exists_and_is_actually_parsed():
    """Guards the two tests below from passing vacuously: a regex that matched nothing
    would make both set differences empty and report perfect agreement."""
    assert ENV_EXAMPLE.is_file(), ENV_EXAMPLE
    found = documented_variables()
    assert len(found) > 5
    assert {"DATABASE_URL", "EXECUTOR_URL", "ANTHROPIC_API_KEY"} <= found


def test_every_documented_variable_has_a_field():
    undocumented = documented_variables() - {name.upper() for name in Settings.model_fields}
    assert not undocumented, f"in .env.example but not in Settings: {sorted(undocumented)}"


def test_every_field_is_documented():
    missing = {name.upper() for name in Settings.model_fields} - documented_variables()
    assert not missing, f"in Settings but not in .env.example: {sorted(missing)}"
