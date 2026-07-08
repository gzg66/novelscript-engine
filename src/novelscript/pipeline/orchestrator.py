from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from novelscript.logging import get_logger
from novelscript.progress import emit

log = get_logger("pipeline")

from novelscript.checkers.base import CheckerReport, passes_gate
from novelscript.checkers.s2 import check_s2_season_map, parse_season_map_md
from novelscript.checkers.s3 import check_s3_episode_list, parse_episode_list_md
from novelscript.index.episode_spec import resolve_episode_spec
from novelscript.checkers.s4 import check_s4_beat_sheet, parse_beat_sheet_md
from novelscript.checkers.s5 import check_s5_script, parse_script_md
from novelscript.config import AppSettings, load_settings
from novelscript.convert.schema import script_md_to_json, to_museframe_handoff, validate_json
from novelscript.index.chapters import index_novel
from novelscript.index.season_plan import (
    check_cross_stage_season_consistency,
    resolve_season_count,
)
from novelscript.gates.fidelity import run_fidelity_audit, save_fidelity_report
from novelscript.index.mapping import map_must_keep_to_episodes, map_must_keep_to_scenes, map_must_keep_to_seasons
from novelscript.index.must_keep import build_must_keep_index, parse_story_engine_names, save_must_keep
from novelscript.io.atomic import atomic_write, write_json
from novelscript.pipeline.cancel import PipelineCancelled, check_cancelled
from novelscript.pipeline.context import ProjectContext, load_project
from novelscript.stages import (
    run_s0_engine,
    run_s1_bible,
    run_s1_premise,
    run_s2_season_map,
    run_s3_episodes,
    run_s4_beats,
    run_s5_script,
)
from novelscript.stages.pre_pipeline import (
    build_decision_queue_from_s2,
    run_p0_preference,
    run_p1_source_cards,
    run_p3_strategy,
    run_p6_pilot_review,
)
from novelscript.stages.stage0_upstream import run_adaptation_brief
from novelscript.stages.source import SourceContextError, ensure_source_context
from novelscript.audit.decision_log import save_decision_queue


def _stage_failed(result: dict[str, Any]) -> bool:
    return result.get("status") in ("best_effort", "failed")


STAGE_ORDER = ("P0", "stage0", "index", "P1", "S0", "brief", "P3", "S1", "S2", "S3", "S4", "S5", "P6")


class PipelineError(Exception):
    pass


class Pipeline:
    def __init__(self, ctx: ProjectContext, settings: AppSettings | None = None) -> None:
        self.ctx = ctx
        self.settings = settings or load_settings()

    def _abort_if_cancelled(self) -> None:
        check_cancelled(self.ctx.root)

    def run(
        self,
        *,
        through: str | None = None,
        from_stage: str | None = None,
        episode: str | None = None,
        skip_llm: bool = False,
        auto_approve: bool = True,
        stop_after_pilot: bool = False,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {"stages": {}}
        try:
            return self._run_impl(
                results,
                through=through,
                from_stage=from_stage,
                episode=episode,
                skip_llm=skip_llm,
                auto_approve=auto_approve,
                stop_after_pilot=stop_after_pilot,
            )
        except PipelineCancelled:
            emit("⏹ 用户已中断精编")
            log.info("Pipeline cancelled by user")
            results["cancelled"] = True
            return results

    def _run_impl(
        self,
        results: dict[str, Any],
        *,
        through: str | None,
        from_stage: str | None,
        episode: str | None,
        skip_llm: bool,
        auto_approve: bool,
        stop_after_pilot: bool,
    ) -> dict[str, Any]:
        emit(
            f"流水线启动 | 项目={self.ctx.root} 目标={through or '全部'} "
            f"从={from_stage or '开头'} skip_llm={skip_llm} 人工审批={not auto_approve}"
            + (" 试播测试=仅EP01-03" if stop_after_pilot else "")
        )
        log.info(
            "Pipeline start project=%s through=%s from=%s skip_llm=%s auto_approve=%s stop_after_pilot=%s",
            self.ctx.root,
            through,
            from_stage,
            skip_llm,
            auto_approve,
            stop_after_pilot,
        )

        if self._should_run_early_block(from_stage):
            self._abort_if_cancelled()
            emit("▶ P0：模式与口味校准")
            log.info("Stage P0: project preference")
            try:
                if not skip_llm:
                    results["stages"]["P0"] = run_p0_preference(self.ctx, self.settings, skip_llm=False)
                else:
                    results["stages"]["P0"] = run_p0_preference(self.ctx, self.settings, skip_llm=True)
            except SourceContextError as exc:
                raise PipelineError(str(exc)) from exc
            self._abort_if_cancelled()
            try:
                emit("▶ stage0：检查/生成故事大纲与角色库…")
                ensure_source_context(self.ctx, self.settings, skip_llm=skip_llm)
            except SourceContextError as exc:
                raise PipelineError(str(exc)) from exc
            self._abort_if_cancelled()
            emit("▶ 索引：正在建立章节索引…")
            log.info("Stage index: building chapter index")
            results["stages"]["index"] = self._run_index(rebuild_must_keep=False)
            emit(f"  ✓ 索引：共 {results['stages']['index'].get('total_chapters')} 章")
            if not skip_llm:
                self._abort_if_cancelled()
                emit("▶ P1：素材拆解")
                log.info("Stage P1: source cards")
                results["stages"]["P1"] = run_p1_source_cards(self.ctx, self.settings, skip_llm=False)
            if not skip_llm:
                self._abort_if_cancelled()
                emit("▶ S0：故事引擎")
                log.info("Stage S0: story engine")
                results["stages"]["S0"] = run_s0_engine(self.ctx, self.settings)
                self._abort_if_cancelled()
                emit("▶ brief：改编简报")
                log.info("Stage brief: adaptation brief")
                results["stages"]["brief"] = run_adaptation_brief(self.ctx, self.settings)
                emit("▶ P3：创作策略")
                log.info("Stage P3: adaptation strategy")
                results["stages"]["P3"] = run_p3_strategy(self.ctx, self.settings, skip_llm=False)
                emit("▶ S1：系列命题")
                log.info("Stage S1: premise")
                results["stages"]["S1_premise"] = run_s1_premise(self.ctx, self.settings)
                emit("▶ S1：人物圣经")
                log.info("Stage S1: character bible")
                results["stages"]["S1_bible"] = run_s1_bible(self.ctx, self.settings)
            else:
                emit("▶ S0–S1：从样板填充（skip_llm）")
                ensure_source_context(self.ctx, self.settings, skip_llm=True)
                log.info("Stage S0-S1: seeding from sample fixtures")
                self._seed_from_samples()
                self._rebuild_must_keep_index()
                run_p0_preference(self.ctx, self.settings, skip_llm=True)
                run_p3_strategy(self.ctx, self.settings, skip_llm=True)

        if self._should_run("S2", through, from_stage):
            self._abort_if_cancelled()
            if not skip_llm:
                emit("▶ S2：季图谱")
                log.info("Stage S2: season map")
                results["stages"]["S2"] = run_s2_season_map(self.ctx, self.settings)
            blocked = self._pass_gate("S2", wait_approval=not auto_approve)
            if blocked:
                results["blocked"] = blocked
                emit(f"⏸ 已暂停：{blocked}")
                log.warning("Blocked at S2: %s", blocked)
                return results
            queue = build_decision_queue_from_s2(self.ctx)
            if queue:
                save_decision_queue(self.ctx.audit_dir, queue)
                emit(f"  ✓ 决策队列：{len(queue)} 个待拍板问题")

        if self._should_run("S3", through, from_stage):
            self._abort_if_cancelled()
            if skip_llm:
                emit("▶ S3：从样板填充分集清单")
                log.info("Stage S3: seeding episode lists from fixtures")
                self._seed_season_episodes()
            else:
                seasons = self._load_seasons()
                emit(f"▶ S3：分集清单（{', '.join(seasons)}）")
                log.info("Stage S3: episode lists for %s", ", ".join(seasons))
                with ThreadPoolExecutor(max_workers=self.ctx.max_workers) as pool:
                    futures = {pool.submit(run_s3_episodes, self.ctx, s, self.settings): s for s in seasons}
                    try:
                        for fut in as_completed(futures):
                            self._abort_if_cancelled()
                            sid = futures[fut]
                            stage_result = fut.result()
                            results["stages"][f"S3_{sid}"] = stage_result
                            if _stage_failed(stage_result):
                                raise PipelineError(
                                    f"S3_{sid} failed: {(stage_result.get('issues') or [])[:3]}"
                                )
                            emit(f"  ✓ S3_{sid}: {stage_result.get('status')}")
                            log.info("Stage S3_%s: done (%s)", sid, stage_result.get("status"))
                    except PipelineCancelled:
                        for fut in futures:
                            fut.cancel()
                        raise
            self._update_must_keep_after_s3()
            cross = self._check_season_cross_episode("S1")
            if cross.issues:
                results.setdefault("cross_episode", {})["S3"] = {
                    "passed": cross.passed,
                    "issues": cross.issues,
                }
                if cross.hard_fail:
                    raise PipelineError(f"S3 cross-episode check failed: {cross.issues[:3]}")
                for issue in cross.issues:
                    log.warning("S3 cross-episode: %s", issue)

        if episode:
            emit(f"▶ 单集：{episode}")
            log.info("Running single episode %s", episode)
            return self._run_single_episode(episode, results, skip_llm=skip_llm)

        if self._should_run("S4", through, from_stage) or self._should_run("S5", through, from_stage):
            self._abort_if_cancelled()
            pilot_only = not self.ctx.is_approved("s1_pilot")
            eps = self._episodes_for_s4_s5("S1")
            if not eps and pilot_only and self._pilot_scripts_complete():
                emit("  ✓ 试播集已完成，无需重复生成")
                log.info("Pilot episodes already complete; skipping S4/S5")
                return results
            if eps:
                self._run_s4_s5_episodes(eps, results, skip_llm=skip_llm)
            if pilot_only:
                self._post_pilot_s4_s5(results, skip_llm=skip_llm)
                if stop_after_pilot:
                    emit("  ✓ 试播测试：已生成 EP01–03，流水线结束")
                    log.info("Pilot test run complete; stopping after EP01-03")
                    return results
                if not skip_llm and not auto_approve:
                    blocked = "试播集 EP01–03 已生成，请审阅后批准继续"
                    results["blocked"] = blocked
                    emit(f"⏸ 已暂停：{blocked}")
                    log.warning("Blocked after pilot S4/S5: awaiting s1_pilot approval")
                    return results
                if auto_approve:
                    self._approve("s1_pilot")
                    emit("  ✓ 试播集：已自动审批")
                    log.info("Pilot episodes auto-approved")
                    remaining = self._remaining_episodes("S1")
                    if remaining:
                        self._run_s4_s5_episodes(remaining, results, skip_llm=skip_llm)
                        self._post_full_s4_s5(results)
            else:
                self._post_full_s4_s5(results)

        emit(f"流水线结束 | 已完成阶段：{', '.join(results.get('stages', {}))}")
        log.info("Pipeline finished stages=%s", list(results.get("stages", {}).keys()))
        return results

    def check(self, stage: str) -> CheckerReport:
        stage = stage.upper()
        if stage == "S0":
            from novelscript.checkers.cross_stage import check_p1_s0_rulings, check_s0_redundant_refs
            from novelscript.checkers.s0 import check_s0_story_engine
            from novelscript.stages.source import load_source_cards_index

            md = (self.ctx.root / "S0_story_engine.md").read_text(encoding="utf-8")
            cards = load_source_cards_index(self.ctx)
            report = check_s0_story_engine(md, source_cards=cards or None)
            if cards:
                for cross in (check_p1_s0_rulings(cards, md), check_s0_redundant_refs(md, cards)):
                    report.issues.extend(cross.issues)
                    if cross.hard_fail:
                        report.hard_fail = True
                        report.passed = False
            return report
        if stage == "S1":
            from novelscript.checkers.s1 import check_s1_bible, check_s1_premise

            total = self._total_chapters()
            season_count = self._season_count(total)
            premise = (self.ctx.root / "S1_series_premise.md").read_text(encoding="utf-8")
            bible = (self.ctx.root / "S1_character_bible.md").read_text(encoding="utf-8")
            r1 = check_s1_premise(premise, expected_seasons=season_count)
            r2 = check_s1_bible(bible)
            brief_path = self.ctx.root / "S0_adaptation_brief.md"
            if brief_path.exists() and (self.ctx.root / "S2_season_map.md").exists():
                cross = check_cross_stage_season_consistency(
                    brief_md=brief_path.read_text(encoding="utf-8"),
                    s1_md=premise,
                    s2_md=(self.ctx.root / "S2_season_map.md").read_text(encoding="utf-8"),
                    total_chapters=total,
                )
                if cross.hard_fail:
                    r1.issues.extend(cross.issues)
                    r1.hard_fail = True
                    r1.passed = False
            if r1.passed and r2.passed:
                return r1
            merged = CheckerReport(stage="S1", passed=False, hard_fail=r1.hard_fail or r2.hard_fail)
            merged.issues.extend(r1.issues + r2.issues)
            return merged
        if stage == "S2":
            from novelscript.checkers.s2 import check_s2_season_map_md

            md = (self.ctx.root / "S2_season_map.md").read_text(encoding="utf-8")
            total = self._total_chapters()
            season_count = self._season_count(total)
            report = check_s2_season_map_md(
                md,
                total_chapters=total,
                expected_seasons=season_count,
                must_keep=self._load_must_keep(),
            )
            brief_path = self.ctx.root / "S0_adaptation_brief.md"
            if brief_path.exists() and (self.ctx.root / "S1_series_premise.md").exists():
                cross = check_cross_stage_season_consistency(
                    brief_md=brief_path.read_text(encoding="utf-8"),
                    s1_md=(self.ctx.root / "S1_series_premise.md").read_text(encoding="utf-8"),
                    s2_md=md,
                    total_chapters=total,
                )
                report.issues.extend(cross.issues)
                if cross.hard_fail:
                    report.hard_fail = True
                    report.passed = False
            return report
        if stage == "S3":
            md = (self.ctx.season_dir("S1") / "episode_list.md").read_text(encoding="utf-8")
            episodes = parse_episode_list_md(md, season_id="S1")
            seasons = parse_season_map_md((self.ctx.root / "S2_season_map.md").read_text(encoding="utf-8"))
            s1 = next((s for s in seasons if s["season_id"] == "S1"), None)
            ch_range = s1["chapter_range"] if s1 else list(range(1, 31))
            return check_s3_episode_list(
                episodes,
                season_chapters=ch_range,
                must_keep=self._load_must_keep(),
                episode_spec=resolve_episode_spec(self.ctx),
            )
        if stage == "S4":
            md = (self.ctx.episode_dir("S1", 1) / "beat_sheet.md").read_text(encoding="utf-8")
            data = parse_beat_sheet_md(md, episode_id="S1E01")
            return check_s4_beat_sheet(data)
        if stage == "S5":
            script_path = self.ctx.episode_dir("S1", 1) / "script.json"
            script = json.loads(script_path.read_text(encoding="utf-8"))
            return check_s5_script(script, episode_chapters=script.get("source_chapters"))
        raise PipelineError(f"Unknown check stage: {stage}")

    def export_museframe(self, episode_id: str = "S1E01") -> Path:
        ep_num = int(episode_id.split("E")[-1])
        script_path = self.ctx.episode_dir("S1", ep_num) / "script.json"
        script = json.loads(script_path.read_text(encoding="utf-8"))
        handoff = to_museframe_handoff(script, visual_tone="哈利波特式质朴基调")
        out = self.ctx.root / "export" / f"{episode_id}_museframe.json"
        write_json(out, handoff)
        schema_errors = validate_json(handoff, self.settings.schemas_dir / "museframe_scene.v1.json")
        if schema_errors:
            raise PipelineError(f"Export schema validation failed: {schema_errors[:3]}")
        return out

    def verify(self, *, export_pilot: bool = True, strict: bool = False) -> dict[str, Any]:
        """Run index, all gate checkers, fidelity, and pilot exports."""
        summary: dict[str, Any] = {"checks": {}, "exports": [], "quality": {}}
        summary["index"] = self._run_index()
        if (self.ctx.root / "S2_season_map.md").exists():
            self._update_must_keep_after_s3()
        for ep in (1, 2, 3):
            script_path = self.ctx.episode_dir("S1", ep) / "script.json"
            if script_path.exists():
                self._update_must_keep_after_s5(json.loads(script_path.read_text(encoding="utf-8")))
        for stage in ("S0", "S1", "S2", "S3", "S4", "S5"):
            report = self.check(stage)
            summary["checks"][stage] = {"passed": report.passed, "issues": report.issues}
            if not report.passed:
                raise PipelineError(f"{stage} check failed: {report.issues[:3]}")
        summary["fidelity"] = self.run_fidelity_audit("S1", episode_ids=[f"S1E{ep:02d}" for ep in (1, 2, 3)])
        if summary["fidelity"].get("verdict") != "pass":
            raise PipelineError(f"Fidelity failed: {summary['fidelity'].get('issues', [])[:3]}")
        if strict:
            from novelscript.quality.rubric import check_script_quality

            for ep in (1, 2, 3):
                script_path = self.ctx.episode_dir("S1", ep) / "script.json"
                if not script_path.exists():
                    continue
                script = json.loads(script_path.read_text(encoding="utf-8"))
                qr = check_script_quality(script, tier="production")
                summary["quality"][f"S1E{ep:02d}"] = {"passed": qr.passed, "issues": qr.issues}
                if not qr.passed:
                    raise PipelineError(f"Quality bar not met for S1E{ep:02d}: {qr.issues[:3]}")
        if export_pilot:
            for ep in (1, 2, 3):
                eid = f"S1E{ep:02d}"
                path = self.export_museframe(eid)
                summary["exports"].append(str(path))
        return summary

    def run_fidelity_audit(self, season_id: str = "S1", *, episode_ids: list[str] | None = None) -> dict[str, Any]:
        must_keep = self._load_must_keep()
        eps_path = self.ctx.season_dir(season_id) / "episode_list.md"
        episodes = parse_episode_list_md(eps_path.read_text(encoding="utf-8"), season_id=season_id) if eps_path.exists() else []
        engines = parse_story_engine_names(
            (self.ctx.root / "S0_story_engine.md").read_text(encoding="utf-8")
        ) if (self.ctx.root / "S0_story_engine.md").exists() else []
        if len(engines) < 4:
            engines = ["逆袭", "双男主拉扯", "命定之恋", "身世之谜"]
        scripts: dict[str, dict[str, Any]] = {}
        for ep in episodes:
            ep_num = int(ep["episode_id"].split("E")[-1])
            script_path = self.ctx.episode_dir(season_id, ep_num) / "script.json"
            if script_path.exists():
                scripts[ep["episode_id"]] = json.loads(script_path.read_text(encoding="utf-8"))
        if episode_ids:
            scripts = {ep_id: script for ep_id, script in scripts.items() if ep_id in episode_ids}
            episodes = [ep for ep in episodes if ep["episode_id"] in episode_ids]
        audit_episodes = [ep for ep in episodes if ep["episode_id"] in scripts] or episodes
        report = run_fidelity_audit(
            must_keep=must_keep,
            story_engines=engines,
            episodes=audit_episodes,
            scripts=scripts,
            season_id=season_id,
            scope_episode_ids=episode_ids,
        )
        save_fidelity_report(report, self.ctx.audit_dir, name=f"season_{season_id.lower()}")
        return report

    def _approve(self, gate: str) -> None:
        self.ctx.approved_dir.mkdir(parents=True, exist_ok=True)
        (self.ctx.approved_dir / f"{gate}.approved").write_text("", encoding="utf-8")

    def _pass_gate(self, gate: str, *, wait_approval: bool) -> str | None:
        """Return a block message, or None when the gate is satisfied."""
        if self.ctx.is_approved(gate):
            return None
        if gate == "S2":
            report = self.check("S2")
            if not report.passed:
                if wait_approval:
                    return (
                        f"等待人工审批：approved/{gate}.approved — "
                        f"校验提示：{report.issues[:3]}"
                    )
                return f"S2 校验失败：{report.issues[:3]}"
        if wait_approval:
            return (
                f"等待人工审批：approved/{gate}.approved — "
                "审完后在项目页点击「审核通过」继续，或创建该文件后 CLI 续跑"
            )
        self._approve(gate)
        emit(f"  ✓ {gate}：已自动审批通过")
        log.info("Gate %s: auto-approved", gate)
        return None

    def _run_index(self, *, rebuild_must_keep: bool = True) -> dict[str, Any]:
        self._abort_if_cancelled()
        result = index_novel(self.ctx.novel_path(), self.ctx.index_dir)
        if rebuild_must_keep:
            self._rebuild_must_keep_index()
        return result

    def _rebuild_must_keep_index(self) -> None:
        engine_path = self.ctx.root / "S0_story_engine.md"
        if engine_path.exists():
            build_must_keep_index(
                engine_path,
                self.ctx.index_dir,
                cards_path=self.ctx.root / "source_cards" / "index.json",
                strategy_path=self.ctx.root / "adaptation_strategy.md",
            )

    def _sample_project(self) -> Path:
        for name in ("full-run", "dragons-ice-live"):
            path = self.settings.project_root / "projects" / name
            if path.exists():
                return path
        return self.settings.project_root / "projects" / "full-run"

    def _seed_from_samples(self) -> None:
        sample = self._sample_project()
        if not sample.exists() or sample.resolve() == self.ctx.root.resolve():
            return
        for name in (
            "S0_adaptation_brief.md",
            "S0_story_engine.md",
            "S1_series_premise.md",
            "S1_character_bible.md",
            "S2_season_map.md",
        ):
            src = sample / name
            if src.exists():
                shutil.copy2(src, self.ctx.root / name)
        stage0_src = sample / "input" / "stage0"
        if stage0_src.is_dir():
            dst = self.ctx.input_dir / "stage0"
            dst.mkdir(parents=True, exist_ok=True)
            for item in stage0_src.iterdir():
                if item.is_file():
                    shutil.copy2(item, dst / item.name)
        s3_src = sample / "seasons" / "s1" / "episode_list.md"
        if not s3_src.exists():
            s3_src = sample / "S3_episode_list_s1.md"
        if s3_src.exists():
            dst_dir = self.ctx.season_dir("S1")
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s3_src, dst_dir / "episode_list.md")
        for ep in (1, 2, 3):
            ep_dir = self.ctx.episode_dir("S1", ep)
            ep_dir.mkdir(parents=True, exist_ok=True)
            src_ep = sample / "seasons" / "s1" / f"ep{ep:02d}"
            beat_src = src_ep / "beat_sheet.md" if (src_ep / "beat_sheet.md").exists() else sample / "S4_beat_sheet_ep01-03.md"
            script_src = src_ep / "script.md" if (src_ep / "script.md").exists() else sample / f"S5_script_ep{ep:02d}.md"
            if beat_src.exists():
                shutil.copy2(beat_src, ep_dir / "beat_sheet.md")
            if script_src.exists():
                shutil.copy2(script_src, ep_dir / "script.md")
                script = script_md_to_json(script_src, episode_id=f"S1E{ep:02d}", global_episode_id=f"EP{ep:03d}")
                write_json(ep_dir / "script.json", script)

    def _seed_season_episodes(self) -> None:
        sample = self._sample_project()
        if not sample.exists() or sample.resolve() == self.ctx.root.resolve():
            return
        s3_src = sample / "seasons" / "s1" / "episode_list.md"
        if not s3_src.exists():
            s3_src = sample / "S3_episode_list_s1.md"
        if s3_src.exists():
            dst_dir = self.ctx.season_dir("S1")
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s3_src, dst_dir / "episode_list.md")
        for ep in (1, 2, 3):
            ep_dir = self.ctx.episode_dir("S1", ep)
            ep_dir.mkdir(parents=True, exist_ok=True)
            src_ep = sample / "seasons" / "s1" / f"ep{ep:02d}"
            beat_src = src_ep / "beat_sheet.md" if (src_ep / "beat_sheet.md").exists() else sample / "S4_beat_sheet_ep01-03.md"
            script_src = src_ep / "script.md" if (src_ep / "script.md").exists() else sample / f"S5_script_ep{ep:02d}.md"
            if beat_src.exists():
                shutil.copy2(beat_src, ep_dir / "beat_sheet.md")
            if script_src.exists():
                shutil.copy2(script_src, ep_dir / "script.md")
                script = script_md_to_json(script_src, episode_id=f"S1E{ep:02d}", global_episode_id=f"EP{ep:03d}")
                write_json(ep_dir / "script.json", script)

    def _run_episode_pipeline(self, ep: str, skip_llm: bool) -> dict[str, Any]:
        ep_num = int(ep.split("E")[-1])
        season = ep.split("E")[0]
        ep_dir = self.ctx.episode_dir(season, ep_num)
        if skip_llm and not (ep_dir / "script.md").exists() and not (ep_dir / "script.json").exists():
            return {"episode": ep, "status": "skipped_no_fixture"}
        out: dict[str, Any] = {"episode": ep}
        if not skip_llm:
            out["S4"] = run_s4_beats(self.ctx, season, ep_num, self.settings)
            if _stage_failed(out["S4"]):
                raise PipelineError(f"{ep} S4 failed: {(out['S4'].get('issues') or [])[:3]}")
            out["S5"] = run_s5_script(self.ctx, season, ep_num, self.settings)
            if _stage_failed(out["S5"]):
                raise PipelineError(f"{ep} S5 failed: {(out['S5'].get('issues') or [])[:3]}")
        self._validate_episode(ep_num)
        return out

    def _run_single_episode(self, episode: str, results: dict[str, Any], *, skip_llm: bool) -> dict[str, Any]:
        results["episode"] = self._run_episode_pipeline(episode, skip_llm)
        return results

    def _validate_episode(self, ep_num: int) -> None:
        script_path = self.ctx.episode_dir("S1", ep_num) / "script.json"
        if not script_path.exists():
            md_path = self.ctx.episode_dir("S1", ep_num) / "script.md"
            if md_path.exists():
                script = script_md_to_json(md_path, episode_id=f"S1E{ep_num:02d}", global_episode_id=f"EP{ep_num:03d}")
                write_json(script_path, script)
        script = json.loads(script_path.read_text(encoding="utf-8"))
        report = check_s5_script(script)
        if not passes_gate(report):
            raise PipelineError(f"S5 check failed for EP{ep_num:02d}: {report.issues[:3]}")
        errors = validate_json(script, self.settings.schemas_dir / "script.schema.v1.json")
        if errors:
            raise PipelineError(f"Schema validation failed: {errors[:3]}")
        self._update_must_keep_after_s5(script)

    def _update_must_keep_after_s5(self, script: dict[str, Any]) -> None:
        path = self.ctx.index_dir / "must_keep_scenes.json"
        if not path.exists():
            return
        must_keep = json.loads(path.read_text(encoding="utf-8"))
        must_keep = map_must_keep_to_scenes(must_keep, script)
        save_must_keep(path, must_keep)

    def _should_run(self, stage: str, through: str | None, from_stage: str | None) -> bool:
        stage_norm = stage.upper()
        if stage_norm in STAGE_ORDER:
            stage_idx = STAGE_ORDER.index(stage_norm)
        elif stage.lower() in STAGE_ORDER:
            stage_idx = STAGE_ORDER.index(stage.lower())
        else:
            return False
        if through:
            through_norm = through.upper().split("_")[0]
            if through_norm in STAGE_ORDER:
                through_idx = STAGE_ORDER.index(through_norm)
            elif through.lower() in STAGE_ORDER:
                through_idx = STAGE_ORDER.index(through.lower())
            else:
                through_idx = None
            if through_idx is not None and stage_idx > through_idx:
                return False
        if from_stage:
            from_norm = from_stage.upper().split("_")[0]
            if from_norm in STAGE_ORDER:
                from_idx = STAGE_ORDER.index(from_norm)
            elif from_stage.lower() in STAGE_ORDER:
                from_idx = STAGE_ORDER.index(from_stage.lower())
            else:
                from_idx = None
            if from_idx is not None and stage_idx < from_idx:
                return False
            if from_idx is None and from_norm not in STAGE_ORDER and from_norm > stage:
                return False
        return True

    def _should_run_early_block(self, from_stage: str | None) -> bool:
        if from_stage is None:
            return True
        from_norm = from_stage.upper().split("_")[0]
        if from_norm in STAGE_ORDER:
            return STAGE_ORDER.index(from_norm) <= STAGE_ORDER.index("S1")
        if from_stage.lower() in STAGE_ORDER:
            return STAGE_ORDER.index(from_stage.lower()) <= STAGE_ORDER.index("S1")
        return from_norm <= "S1"

    def _season_count(self, total_chapters: int | None = None) -> int:
        total = total_chapters or self._total_chapters()
        brief_path = self.ctx.root / "S0_adaptation_brief.md"
        brief_md = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""
        return resolve_season_count(brief_md=brief_md or None, total_chapters=total)

    def _total_chapters(self) -> int:
        chapters_path = self.ctx.index_dir / "chapters.json"
        if chapters_path.exists():
            data = json.loads(chapters_path.read_text(encoding="utf-8"))
            return int(data.get("total", 130))
        return 130

    def _check_season_cross_episode(self, season_id: str) -> CheckerReport:
        from novelscript.checkers.cross_episode import run_season_cross_checks

        return run_season_cross_checks(self.ctx.season_dir(season_id), season_id=season_id)

    def _load_seasons(self) -> list[str]:
        md = (self.ctx.root / "S2_season_map.md").read_text(encoding="utf-8")
        return [s["season_id"] for s in parse_season_map_md(md)]

    def _load_must_keep(self) -> list[dict[str, Any]]:
        path = self.ctx.index_dir / "must_keep_scenes.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return []

    def _pilot_scripts_complete(self) -> bool:
        return all(
            (self.ctx.episode_dir("S1", ep) / "script.json").exists() for ep in (1, 2, 3)
        )

    def _pilot_episodes(self) -> list[str]:
        return ["S1E01", "S1E02", "S1E03"]

    def _remaining_episodes(self, season: str) -> list[str]:
        pilot = set(self._pilot_episodes())
        return [ep for ep in self._all_episodes(season) if ep not in pilot]

    def _episodes_for_s4_s5(self, season: str = "S1") -> list[str]:
        if self.ctx.meta.get("pilot_test") and self._pilot_scripts_complete():
            return []
        if not self.ctx.is_approved("s1_pilot"):
            return self._pilot_episodes()
        return self._remaining_episodes(season)

    def _run_s4_s5_episodes(self, eps: list[str], results: dict[str, Any], *, skip_llm: bool) -> None:
        emit(f"▶ S4/S5：共 {len(eps)} 集（{', '.join(eps)}）")
        log.info("Stage S4/S5: %s episodes (%s)", len(eps), ", ".join(eps))
        with ThreadPoolExecutor(max_workers=self.ctx.max_workers) as pool:
            futures = {pool.submit(self._run_episode_pipeline, ep, skip_llm): ep for ep in eps}
            try:
                for fut in as_completed(futures):
                    self._abort_if_cancelled()
                    ep = futures[fut]
                    results["stages"][f"ep_{ep}"] = fut.result()
                    emit(f"  ✓ {ep}：完成")
                    log.info("Episode %s: done", ep)
            except PipelineCancelled:
                for fut in futures:
                    fut.cancel()
                raise

    def _post_pilot_s4_s5(self, results: dict[str, Any], *, skip_llm: bool) -> None:
        for ep in (1, 2, 3):
            script_path = self.ctx.episode_dir("S1", ep) / "script.json"
            if script_path.exists():
                self._update_must_keep_after_s5(json.loads(script_path.read_text(encoding="utf-8")))
        cross = self._check_season_cross_episode("S1")
        if cross.issues:
            results.setdefault("cross_episode", {})["S5_pilot"] = {
                "passed": cross.passed,
                "issues": cross.issues,
            }
            if cross.hard_fail:
                raise PipelineError(f"S5 cross-episode check failed: {cross.issues[:3]}")
            for issue in cross.issues:
                log.warning("S5 cross-episode (pilot): %s", issue)
        emit("▶ 忠实度审计：S1 试播集")
        log.info("Running fidelity audit for S1 pilot episodes")
        pilot_ids = [f"S1E{ep:02d}" for ep in (1, 2, 3)]
        results["stages"]["fidelity_S1_pilot"] = self.run_fidelity_audit("S1", episode_ids=pilot_ids)
        if not skip_llm:
            emit("▶ P6：试播集观感卡")
            results["stages"]["P6"] = run_p6_pilot_review(self.ctx, self.settings, skip_llm=False)

    def _post_full_s4_s5(self, results: dict[str, Any]) -> None:
        cross = self._check_season_cross_episode("S1")
        if cross.issues:
            results.setdefault("cross_episode", {})["S5"] = {
                "passed": cross.passed,
                "issues": cross.issues,
            }
            if cross.hard_fail:
                raise PipelineError(f"S5 cross-episode check failed: {cross.issues[:3]}")
            for issue in cross.issues:
                log.warning("S5 cross-episode: %s", issue)
        emit("▶ 忠实度审计：S1")
        log.info("Running fidelity audit for S1")
        results["stages"]["fidelity_S1"] = self.run_fidelity_audit("S1")

    def _update_must_keep_after_s3(self) -> None:
        path = self.ctx.index_dir / "must_keep_scenes.json"
        if not path.exists():
            return
        must_keep = json.loads(path.read_text(encoding="utf-8"))
        s2_md = (self.ctx.root / "S2_season_map.md").read_text(encoding="utf-8")
        must_keep = map_must_keep_to_seasons(must_keep, s2_md)
        s1_eps_path = self.ctx.season_dir("S1") / "episode_list.md"
        if s1_eps_path.exists():
            episodes = parse_episode_list_md(s1_eps_path.read_text(encoding="utf-8"), season_id="S1")
            must_keep = map_must_keep_to_episodes(must_keep, episodes)
        save_must_keep(path, must_keep)

    def _all_episodes(self, season: str) -> list[str]:
        md_path = self.ctx.season_dir(season) / "episode_list.md"
        if not md_path.exists():
            return self._pilot_episodes()
        eps = parse_episode_list_md(md_path.read_text(encoding="utf-8"))
        return [e["episode_id"] for e in eps]
