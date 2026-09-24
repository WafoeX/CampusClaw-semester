from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = (ROOT / "docs" / "operations.md").read_text()
README = (ROOT / "README.md").read_text()


def test_operations_guide_covers_startup_and_runtime_boundaries() -> None:
    required_sections = (
        "## Runtime topology",
        "## Prepare server configuration",
        "## Demo startup",
        "## Production startup",
        "## Migrations and health",
        "## Provision real accounts",
        "## HTTPS, cookies, and secrets",
        "## Volume lifecycle",
    )
    assert all(section in OPERATIONS for section in required_sections)
    assert "docs/operations.md" in README
    assert "only service with a host `ports` mapping" in OPERATIONS
    assert "SESSION_COOKIE_SECURE=true" in OPERATIONS


def test_operations_guide_covers_coordinated_backup_restore() -> None:
    required_terms = (
        "## Coordinated backup and restore",
        "maintenance window",
        "pg_dump",
        "pg_restore",
        "materials.tar.gz",
        "SHA256SUMS",
        "check_backup_restore.py",
        "storage_key`/SHA-256",
    )
    assert all(term in OPERATIONS for term in required_terms)


def test_operations_guide_matches_semester_non_goals() -> None:
    required_limits = (
        "one API writer",
        "local named-volume file storage",
        "content parsing",
        "malware scanning",
        "content execution",
        "inline rendering",
        "material search",
        "question answering",
        "intelligent conversation",
        "assignment submission",
        "registration",
        "password recovery",
        "skill/feature toggles",
        "single-class membership",
    )
    assert all(limit in OPERATIONS for limit in required_limits)
