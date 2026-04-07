"""mc text — animated text overlay by timestamp range."""

import typer
from pathlib import Path
from rich import print as rprint
from ..core.timeline import parse_ts, fmt_ts
from ..core.ffmpeg_wrapper import ffmpeg, require_ffmpeg

app = typer.Typer()


@app.command()
def text(
    input: Path = typer.Argument(..., help="Input video file"),
    content: str = typer.Argument(..., help="Text to display"),
    from_ts: str = typer.Option(..., "--from", help="Start timestamp"),
    to_ts: str = typer.Option(..., "--to", help="End timestamp"),
    x: str = typer.Option("100", "--x", help="X position (pixels or 'center')"),
    y: str = typer.Option("100", "--y", help="Y position (pixels or 'center' or 'bottom')"),
    font: str = typer.Option("Arial", "--font", help="Font name"),
    size: int = typer.Option(48, "--size", "-s", help="Font size"),
    color: str = typer.Option("white", "--color", "-c", help="Text color (name or hex #RRGGBB)"),
    bg: bool = typer.Option(False, "--bg", help="Add semi-transparent background box"),
    output: Path = typer.Option(None, "-o", "--output"),
):
    """Overlay text on video between two timestamps."""
    require_ffmpeg()
    t0, t1 = parse_ts(from_ts), parse_ts(to_ts)
    out = output or input.with_stem(input.stem + "_text")

    # Resolve convenience aliases
    x_expr = "(w-text_w)/2" if x == "center" else x
    if y == "center":
        y_expr = "(h-text_h)/2"
    elif y == "bottom":
        y_expr = "h-text_h-30"
    else:
        y_expr = y

    box_opts = ":box=1:boxcolor=black@0.5:boxborderw=8" if bg else ""
    drawtext = (
        f"drawtext=text='{content}'"
        f":fontfile=/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
        f":fontsize={size}:fontcolor={color}"
        f":x={x_expr}:y={y_expr}"
        f"{box_opts}"
        f":enable='between(t,{t0},{t1})'"
    )

    rprint(f"[cyan]Text[/cyan] '{content}' at ({x},{y}) | {fmt_ts(t0)} → {fmt_ts(t1)}")
    ffmpeg("-i", str(input), "-vf", drawtext, "-c:a", "copy", str(out))
    rprint(f"[green]✓[/green] Saved to {out}")
