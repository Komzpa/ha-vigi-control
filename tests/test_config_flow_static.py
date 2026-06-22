from pathlib import Path

CONFIG_FLOW = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "vigi_control"
    / "config_flow.py"
)


def test_frigate_config_reads_run_in_executor():
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    frigate_step = source[
        source.index("    async def async_step_frigate")
        : source.index("    async def async_step_frigate_camera")
    ]

    assert "async_add_executor_job(find_existing_frigate_config)" in frigate_step
    assert "async_add_executor_job(\n                    load_frigate_candidates," in frigate_step
    assert "candidates = load_frigate_candidates(path)" not in frigate_step
