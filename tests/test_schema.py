import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).parent.parent
SCHEMA = json.loads((ROOT / "schema" / "extract.json").read_text())
FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("name", ["claude_ok.json", "claude_irrelevant.json"])
def test_fixtures_validate(name):
    jsonschema.validate(json.loads((FIX / name).read_text()), SCHEMA)


def test_bad_direction_rejected():
    bad = json.loads((FIX / "claude_ok.json").read_text())
    bad["incidents"][0]["direction"] = "sideways"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)


def test_prompt_has_placeholders():
    text = (ROOT / "prompts" / "extract.md").read_text()
    for ph in ("{{KNOWN_ACTORS}}", "{{ARTICLE_META}}", "{{ARTICLE_TEXT}}"):
        assert ph in text
