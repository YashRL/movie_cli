"""mc trim — cut video by timestamps."""

import typer
from pathlib import Path
from rich import print as rprint
from ..core.timeline import parse_ts, fmt_ts
from ..core.ffmpeg_wrapper import ffmpeg, require_ffmpeg

app = typer.Typer()


@app.command()
def trim(
    input: Path = typer.Argument(..., help="Input video file"),
    start: str = typer.Argument(..., help="Start timestamp (HH:MM:SS or MM:SS)"),
    end: str = typer.Argument(..., help="End timestamp (HH:MM:SS or MM:SS)"),
    output: Path = typer.Option(None, "-o", "--output", help="Output file (default: input_trimmed.mp4)"),
):
    """Trim video between two timestamps with no quality loss."""
    require_ffmpeg()

    t_start = parse_ts(start)
    t_end = parse_ts(end)
    if t_end <= t_start:
        rprint(f"[red]Error:[/red] end ({end}) must be after start ({start})")
        raise typer.Exit(1)

    out = output or input.with_stem(input.stem + "_trimmed")
    duration = t_end - t_start

    rprint(f"[cyan]Trimming[/cyan] {fmt_ts(t_start)} → {fmt_ts(t_end)} ({duration:.1f}s)")
    ffmpeg(
        "-ss", str(t_start),
        "-i", str(input),
        "-t", str(duration),
        "-c", "copy",          # stream copy = lossless, instant
        str(out),
    )
    rprint(f"[green]✓[/green] Saved to {out}")
