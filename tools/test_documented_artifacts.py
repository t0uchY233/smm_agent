from pathlib import Path


REQUIRED_ARTIFACTS = [
    Path("n8n.json"),
    Path("n8n-wordpress-publisher.json"),
    Path("n8n-migration.md"),
    Path("smm-schedule-template.xlsx"),
]


def test_documented_operational_artifacts_exist():
    missing = [str(path) for path in REQUIRED_ARTIFACTS if not path.exists()]

    assert missing == []
