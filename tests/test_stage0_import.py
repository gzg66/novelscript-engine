from __future__ import annotations


def test_stage0_upstream_imports_without_cycle() -> None:
    from novelscript.stages.source import ensure_source_context, persist_stage0_hash, stage0_cache_valid
    from novelscript.stages.stage0_upstream import run_stage0_upstream

    assert callable(ensure_source_context)
    assert callable(run_stage0_upstream)
    assert callable(persist_stage0_hash)
    assert callable(stage0_cache_valid)
