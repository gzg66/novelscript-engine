from __future__ import annotations

from pathlib import Path

import click

from novelscript.config import load_settings
from novelscript.llm.client import LLMClient
from novelscript.logging import setup_logging
from novelscript.pipeline.context import ensure_project, init_project, load_project, project_root_for_novel
from novelscript.pipeline.orchestrator import Pipeline, PipelineError
from novelscript.progress import emit


def _resolve_novel(novel: Path, project_dir: Path | None) -> tuple[Path, Path]:
    novel = novel.resolve()
    if project_dir is not None:
        return project_dir.resolve(), novel
    return project_root_for_novel(novel), novel


def _resolve_from_legacy_project(project_dir: Path) -> tuple[Path, Path]:
    project_dir = project_dir.resolve()
    novel_path = project_dir / "input" / "novel.txt"
    if not novel_path.exists():
        raise click.ClickException(
            f"未找到小说文件 {novel_path}。请直接传入小说路径，例如：\n"
            f"  novelscript run path/to/novel.txt"
        )
    click.echo(
        f"提示：--project 已弃用，请直接传入小说路径；项目目录会自动创建（如 {project_root_for_novel(novel_path)}）",
        err=True,
    )
    return project_dir, novel_path


@click.group()
@click.option(
    "--env-file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Dotenv path (default: museframe4video/.env if present)",
)
@click.pass_context
def main(ctx: click.Context, env_file: Path | None) -> None:
    """NovelScript Engine CLI."""
    if env_file:
        import os

        os.environ["NOVELSCRIPT_DOTENV"] = str(env_file)
    ctx.ensure_object(dict)
    ctx.obj["env_file"] = env_file


@main.command()
@click.argument("novel", type=click.Path(exists=True, path_type=Path))
@click.option("--project-dir", type=click.Path(path_type=Path), default=None, help="Override auto project dir")
@click.option("--mode", default="M1")
@click.option("--brief", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--stage0", type=click.Path(exists=True, path_type=Path), default=None)
def init(novel: Path, project_dir: Path | None, mode: str, brief: Path | None, stage0: Path | None) -> None:
    """Initialize a project directory for a novel (optional; run does this automatically)."""
    project = project_dir or project_root_for_novel(novel)
    project.mkdir(parents=True, exist_ok=True)
    stage0_src = stage0
    if stage0_src is None:
        candidate = novel.parent / "stage0"
        if candidate.is_dir():
            stage0_src = candidate
    ctx = init_project(project, novel_src=novel, mode=mode, stage0_src=stage0_src)
    if brief:
        import shutil

        shutil.copy2(brief, ctx.brief_path())
    click.echo(f"Initialized project at {project}")


@main.command()
@click.argument("novel", required=False, type=click.Path(exists=True, path_type=Path))
@click.option(
    "--project",
    "--project-dir",
    "project_dir",
    type=click.Path(path_type=Path),
    default=None,
    hidden=True,
    help="Deprecated: pass the novel file path instead",
)
@click.option("--through", default=None, help="Run through stage e.g. S5")
@click.option("--from", "from_stage", default=None, help="Resume from stage e.g. S3")
@click.option("--episode", default=None, help="Run single episode e.g. S1E07")
@click.option("--skip-llm", is_flag=True, help="Use sample fixtures, no LLM calls")
@click.option("--wait-approval", is_flag=True, help="Pause at S2 / pilot gates for manual approval")
@click.option("-v", "--verbose", is_flag=True, help="Debug logging")
def run(
    novel: Path | None,
    project_dir: Path | None,
    through: str | None,
    from_stage: str | None,
    episode: str | None,
    skip_llm: bool,
    wait_approval: bool,
    verbose: bool,
) -> None:
    """Run the pipeline. Pass the novel file; project dir is created under projects/."""
    if novel is None and project_dir is None:
        raise click.ClickException(
            "请传入小说文件路径，例如：\n"
            "  novelscript run path/to/novel.txt --through S5"
        )
    if novel is None:
        project_path, novel_path = _resolve_from_legacy_project(project_dir)  # type: ignore[arg-type]
    else:
        project_path, novel_path = _resolve_novel(novel, project_dir)

    ctx = ensure_project(novel_path, project_root=project_path)
    setup_logging(project_root=ctx.root, verbose=verbose)
    emit(f"小说：{novel_path}")
    emit(f"项目目录：{ctx.root}")
    emit(f"日志文件：{ctx.root / 'pipeline.log'}")

    settings = load_settings()
    pipe = Pipeline(ctx, settings)
    try:
        result = pipe.run(
            through=through,
            from_stage=from_stage,
            episode=episode,
            skip_llm=skip_llm,
            auto_approve=not wait_approval,
        )
    except PipelineError as exc:
        raise click.ClickException(str(exc)) from exc

    if result.get("blocked"):
        raise click.ClickException(str(result["blocked"]))
    stages = list(result.get("stages", {}).keys())
    click.echo(f"完成 | 项目={ctx.root}")
    click.echo(f"阶段：{', '.join(stages) if stages else '（无）'}")
    click.echo(f"日志：{ctx.root / 'pipeline.log'}")


def _project_from_args(novel: Path | None, project_dir: Path | None) -> Path:
    if novel is not None:
        root, _ = _resolve_novel(novel, project_dir)
        return root
    if project_dir is not None:
        return _resolve_from_legacy_project(project_dir)[0]
    raise click.ClickException("Pass the novel file path.")


@main.command()
@click.argument("novel", required=False, type=click.Path(exists=True, path_type=Path))
@click.option("--project", "--project-dir", "project_dir", type=click.Path(path_type=Path), default=None, hidden=True)
@click.option("--stage", default=None, help="S0-S5; omit to run verify")
def check(novel: Path | None, project_dir: Path | None, stage: str | None) -> None:
    """Run deterministic checker(s) for a project."""
    project_path = _project_from_args(novel, project_dir)
    ctx = load_project(project_path)
    pipe = Pipeline(ctx)
    if stage is None:
        summary = pipe.verify(export_pilot=False)
        click.echo("ALL CHECKS PASS")
        click.echo(f"  index: {summary['index']['total_chapters']} chapters")
        click.echo(f"  fidelity: {summary['fidelity']['verdict']}")
        return
    report = pipe.check(stage.upper())
    if report.passed:
        click.echo(f"{stage}: PASS")
    else:
        click.echo(f"{stage}: FAIL")
        for issue in report.issues:
            click.echo(f"  - {issue}")
        raise SystemExit(1)


@main.command()
@click.argument("novel", required=False, type=click.Path(exists=True, path_type=Path))
@click.option("--project", "--project-dir", "project_dir", type=click.Path(path_type=Path), default=None, hidden=True)
@click.option("--format", "fmt", default="museframe")
@click.option("--episode", default="S1E01")
def export(novel: Path | None, project_dir: Path | None, fmt: str, episode: str) -> None:
    """Export handoff package."""
    if fmt != "museframe":
        raise click.ClickException(f"Unsupported format: {fmt}")
    ctx = load_project(_project_from_args(novel, project_dir))
    pipe = Pipeline(ctx)
    out = pipe.export_museframe(episode)
    click.echo(f"Exported to {out}")


@main.command("index")
@click.argument("novel", required=False, type=click.Path(exists=True, path_type=Path))
@click.option("--project", "--project-dir", "project_dir", type=click.Path(path_type=Path), default=None, hidden=True)
def index_cmd(novel: Path | None, project_dir: Path | None) -> None:
    """Build chapters.json and source_lines index."""
    if novel is None and project_dir is None:
        raise click.ClickException("Pass the novel file path.")
    if novel is None:
        project_path, novel_path = _resolve_from_legacy_project(project_dir)  # type: ignore[arg-type]
    else:
        project_path, novel_path = _resolve_novel(novel, project_dir)
    ctx = ensure_project(novel_path, project_root=project_path)
    setup_logging(project_root=ctx.root)
    pipe = Pipeline(ctx)
    result = pipe._run_index()
    click.echo(f"Indexed {result['total_chapters']} chapters -> {ctx.root}")


@main.command("fidelity")
@click.argument("novel", required=False, type=click.Path(exists=True, path_type=Path))
@click.option("--project", "--project-dir", "project_dir", type=click.Path(path_type=Path), default=None, hidden=True)
@click.option("--season", default="S1")
def fidelity_cmd(novel: Path | None, project_dir: Path | None, season: str) -> None:
    """Run Gate3 fidelity audit for a season."""
    ctx = load_project(_project_from_args(novel, project_dir))
    pipe = Pipeline(ctx)
    report = pipe.run_fidelity_audit(season)
    click.echo(f"verdict: {report['verdict']}")
    if report.get("issues"):
        for issue in report["issues"]:
            click.echo(f"  - {issue}")
        raise SystemExit(1)


@main.command()
@click.argument("novel", required=False, type=click.Path(exists=True, path_type=Path))
@click.option("--project", "--project-dir", "project_dir", type=click.Path(path_type=Path), default=None, hidden=True)
@click.option("--strict", is_flag=True, help="Apply production quality bar (above sample)")
def verify(novel: Path | None, project_dir: Path | None, strict: bool) -> None:
    """Full MVP acceptance: index + gates + fidelity + pilot export."""
    ctx = load_project(_project_from_args(novel, project_dir))
    pipe = Pipeline(ctx)
    summary = pipe.verify(export_pilot=True, strict=strict)
    click.echo("VERIFY OK")
    click.echo(f"  chapters: {summary['index']['total_chapters']}")
    click.echo(f"  fidelity: {summary['fidelity']['verdict']}")
    if strict:
        click.echo("  quality: all pilot episodes pass production bar")
    for path in summary["exports"]:
        click.echo(f"  export: {path}")


@main.command("llm-test")
@click.option("--env-file", type=click.Path(exists=True, path_type=Path), default=None)
def llm_test(env_file: Path | None) -> None:
    """Smoke-test LLM connectivity via Support API."""
    if env_file:
        import os

        os.environ["NOVELSCRIPT_DOTENV"] = str(env_file)
    settings = load_settings()
    client = LLMClient(settings)
    text = client.generate_text(system="Reply with OK only.", user="ping", stream=False)
    click.echo(f"LLM OK: {text[:80].strip()}")


@main.command()
def doctor() -> None:
    """Verify config and LLM connectivity."""
    settings = load_settings()
    click.echo(f"llm_core: {settings.llm_core_path} ({'ok' if settings.llm_core_path.exists() else 'MISSING'})")
    click.echo(f"support_api: {settings.support_api.base_url} token={'set' if settings.support_api.token else 'MISSING'}")
    click.echo(f"llm: {settings.llm.provider}/{settings.llm.model}")
    try:
        from novelscript.llm.client import LLMClient

        client = LLMClient(settings, llm_config=settings.conversion_llm)
        reply = client.generate_text(
            system="Reply with exactly: ok",
            user="ping",
            stream=False,
        )
        click.echo(f"llm_ping: {reply.strip()[:80]}")
    except Exception as exc:
        click.echo(f"llm_ping: FAILED ({exc})")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
