from backend.tools.bash_tool import execute_bash_stub


def test_bash_stub_does_not_fabricate_output():
    result = execute_bash_stub("rm -rf /")
    assert "not executed" in result
    assert "rm -rf /" in result
