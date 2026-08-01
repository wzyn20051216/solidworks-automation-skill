from pathlib import Path
import importlib.util


MODULE_PATH = Path(__file__).parents[1] / "subskills" / "autocad-automation" / "scripts" / "acad_session.py"
SPEC = importlib.util.spec_from_file_location("acad_session_script_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_script_backend_rejects_arbitrary_commands():
    result = MODULE.run_whitelisted_script_command(object(), "(command \"._ERASE\")")
    assert result["status"] == "blocked"
    assert result["error_code"] == "SCRIPT_COMMAND_NOT_ALLOWED"


def test_script_backend_sends_only_known_command(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.commands = []

        def send_command(self, command):
            self.commands.append(command)

    session = FakeSession()
    result = MODULE.run_whitelisted_script_command(session, "regen")
    assert result["status"] == "pilot"
    assert session.commands == ["_.REGEN\n"]
