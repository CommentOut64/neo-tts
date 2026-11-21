from __future__ import annotations

from backend.app.services.project_session_service import ProjectSessionService
from backend.tests.unit.test_project_store import payload


def test_project_roundtrip_across_workspace(tmp_path):
    source = ProjectSessionService(user_data_root=tmp_path / "source")
    source_root = source.create_workspace(project_id="project-1", workspace_id="workspace-1")
    assert source.save(payload("project-1")) == 1

    target = ProjectSessionService(user_data_root=tmp_path / "target")
    restored = target.open_project(source_root / "project-1.neo")

    assert restored["project"]["project_id"] == "project-1"
    assert restored["project"]["save_revision"] == 1
    assert restored["project"]["workspace_id"] == target.workspace_id
    assert restored["snapshots"][0]["segments"][0]["segment_id"] == "seg1"
    assert target.session_db.is_file()
