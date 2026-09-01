import pytest

from geno_tt import workspace_schema


@pytest.fixture(autouse=True)
def use_packaged_workspace_schema(monkeypatch, tmp_path):
    """Keep developer-local schema overrides from changing repository tests."""
    monkeypatch.setattr(
        workspace_schema,
        "SCHEMA_PATH",
        tmp_path / "no-user-workspace-schema.yaml",
    )
