"""The existing upload queue must refresh policy without replacing its worker."""

from types import SimpleNamespace

from agent_manager.api import router
from agent_manager.core.manager import AgentManager
from agent_manager.core.vetting import _check_manifest_policy


def test_upload_queue_policy_after_save(tmp_path, monkeypatch):
    original = AgentManager(data_dir=tmp_path / "data")
    monkeypatch.setattr(router, "_manager", original)
    queue = router._get_upload_jobs(original)
    captured = []

    def submit(manager, *args):
        captured.extend(_check_manifest_policy([], "GPL-3.0", manager.policy))
        return SimpleNamespace(model_dump=lambda **kwargs: {})

    monkeypatch.setattr(router, "_submit_directory_for_processing", submit)
    monkeypatch.setattr(
        router, "_policy_path_for_write", lambda: tmp_path / "policy.yaml",
    )
    monkeypatch.setattr(
        router, "AgentManager",
        lambda policy: AgentManager(policy=policy, data_dir=tmp_path / "data"),
    )
    try:
        payload = router.PolicyPayload(**{
            **original.policy.to_dict(),
            "accepted_licenses": ["Apache-2.0", "MIT"],
        })
        router.update_policy(payload)
        assert router.get_manager().policy.to_dict()["accepted_licenses"] == [
            "Apache-2.0", "MIT",
        ]
        router._get_upload_jobs(original)
        session = "a" * 32
        queue.process_item(
            {"session_id": session, "paths": []},
            str(original.registry.data_dir / "upload_import_sessions" / session / "skill"),
        )
        assert "BSD-3-Clause" not in captured[0].message
    finally:
        queue.close()
        router._upload_jobs.pop(original.registry.data_dir, None)


def test_running_upload_keeps_original_manager(tmp_path, monkeypatch):
    import threading

    original = AgentManager(data_dir=tmp_path / "data")
    monkeypatch.setattr(router, "_manager", original)
    monkeypatch.setattr(router, "_policy_path_for_write", lambda: tmp_path / "policy.yaml")
    monkeypatch.setattr(
        router, "AgentManager",
        lambda policy: AgentManager(policy=policy, data_dir=tmp_path / "data"),
    )
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    captured = []

    def submit(manager, *args):
        entered.set()
        assert release.wait(3)
        captured.extend(_check_manifest_policy([], "GPL-3.0", manager.policy))
        completed.set()
        return SimpleNamespace(model_dump=lambda **kwargs: {})

    monkeypatch.setattr(router, "_submit_directory_for_processing", submit)
    queue = router._get_upload_jobs(original)
    session = "b" * 32
    path = str(original.registry.data_dir / "upload_import_sessions" / session / "skill")
    payload = {"session_id": session, "paths": [path]}
    try:
        queue.submit(payload)
        assert entered.wait(3)
        router.update_policy(router.PolicyPayload(**{
            **original.policy.to_dict(), "accepted_licenses": ["MIT"],
        }))
        release.set()
        assert completed.wait(3)
        queue.process_item(payload, path)
        assert "BSD-3-Clause" in captured[0].message
        assert captured[1].params["accepted_licenses"] == ["MIT"]
    finally:
        release.set()
        queue.close()
        router._upload_jobs.pop(original.registry.data_dir, None)
