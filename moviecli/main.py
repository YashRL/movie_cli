"""MovieCLI — terminal-first video editing."""

import typer
from typing import Optional
from rich import print as rprint
from .commands import trim, effects, text_overlay, clip, export

app = typer.Typer(
    name="mc",
    help="MovieCLI — run `mc` to start the interactive session, or use subcommands directly.",
    no_args_is_help=False,
    invoke_without_command=True,
)

# Sub-command groups (kept for power users who prefer one-shot commands)
effect_app = typer.Typer(help="Apply visual effects (one-shot).", no_args_is_help=True)
effect_app.command("blur")(effects.blur)
effect_app.command("spotlight")(effects.spotlight)

clip_app = typer.Typer(help="Clip operations (one-shot).", no_args_is_help=True)
clip_app.command("insert")(clip.insert)
clip_app.command("concat")(clip.concat)

app.command("trim")(trim.trim)
app.add_typer(effect_app, name="effect")
app.command("text")(text_overlay.text)
app.add_typer(clip_app, name="clip")
app.command("export")(export.export)


@app.command("info")
def info(input: str = typer.Argument(..., help="Video file to inspect")):
    """Show video metadata (resolution, fps, duration)."""
    from .core.ffmpeg_wrapper import video_info
    from .core.timeline import fmt_ts
    v = video_info(input)
    rprint(f"[bold]{input}[/bold]")
    rprint(f"  Resolution : {v['width']}x{v['height']}")
    rprint(f"  FPS        : {v['fps']:.2f}")
    rprint(f"  Duration   : {fmt_ts(v['duration'])}")


@app.callback(invoke_without_command=True)
def default(
    ctx: typer.Context,
    file: Optional[str] = typer.Argument(None, help="Video file to load immediately"),
):
    """Start the interactive MovieCLI session. Optionally pass a video file to load it right away."""
    if ctx.invoked_subcommand is None:
        from .repl import run_repl
        run_repl(initial_file=file)


def main():
    app()


if __name__ == "__main__":
    main()
