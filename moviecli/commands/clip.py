"""mc clip — insert, concat, and manage video clips."""

import typer
import tempfile
from pathlib import Path
from rich import print as rprint
from ..core.timeline import parse_ts, fmt_ts
from ..core.ffmpeg_wrapper import ffmpeg, video_info, require_ffmpeg

app = typer.Typer()


@app.command()
def insert(
    base: Path = typer.Argument(..., help="Base video file"),
    clip: Path = typer.Argument(..., help="Clip to insert"),
    at: str = typer.Argument(..., help="Timestamp to insert at (HH:MM:SS)"),
    output: Path = typer.Option(None, "-o", "--output"),
):
    """Insert a clip into a video at a given timestamp."""
    require_ffmpeg()
    t = parse_ts(at)
    out = output or base.with_stem(base.stem + "_inserted")

    with tempfile.TemporaryDirectory() as tmp:
        part1 = Path(tmp) / "part1.mp4"
        part2 = Path(tmp) / "part2.mp4"
        concat_list = Path(tmp) / "list.txt"

        # Split base at insertion point
        info = video_info(str(base))
        ffmpeg("-ss", "0", "-i", str(base), "-t", str(t), "-c", "copy", str(part1))
        ffmpeg("-ss", str(t), "-i", str(base), "-t", str(info["duration"] - t), "-c", "copy", str(part2))

        concat_list.write_text(
            f"file '{part1}'\nfile '{clip.resolve()}'\nfile '{part2}'\n"
        )
        rprint(f"[cyan]Inserting[/cyan] {clip.name} at {fmt_ts(t)}")
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(out))

    rprint(f"[green]✓[/green] Saved to {out}")


@app.command()
def concat(
    clips: list[Path] = typer.Argument(..., help="Video files to concatenate in order"),
    output: Path = typer.Option(..., "-o", "--output", help="Output file"),
):
    """Concatenate multiple video clips in order."""
    require_ffmpeg()

    with tempfile.TemporaryDirectory() as tmp:
        concat_list = Path(tmp) / "list.txt"
        concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in clips) + "\n")

        rprint(f"[cyan]Concatenating[/cyan] {len(clips)} clips")
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(output))

    rprint(f"[green]✓[/green] Saved to {output}")
