from everrun_agent.demo import run_crash_recovery_demo


def test_crash_demo_end_to_end(tmp_path):
    result = run_crash_recovery_demo(tmp_path, total=40, crash_at=17)
    assert result.completed == 40
    assert result.unique_outputs == 40
    assert result.duplicates == 0
    assert result.chain_valid
    assert result.side_effect_count == 1
