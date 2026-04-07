"""mc export — render final video with quality presets."""

import typer
from pathlib import Path
from rich import print as rprint
from ..core.ffmpeg_wrapper import ffmpeg, require_ffmpeg

app = typer.Typer()

QUALITY_PRESETS = {
    "lossless": ["-c:v", "libx264", "-crf", "0", "-preset", "veryslow", "-c:a", "copy"],
    "high":     ["-c:v", "libx264", "-crf", "18", "-preset", "slow", "-c:a", "aac", "-b:a", "192k"],
    "medium":   ["-c:v", "libx264", "-crf", "23", "-preset", "medium", "-c:a", "aac", "-b:a", "128k"],
    "web":      ["-c:v", "libx264", "-crf", "28", "-preset", "fast", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "128k"],
}


@app.command()
def export(
    input: Path = typer.Argument(..., help="Input video file"),
    output: Path = typer.Option(..., "-o", "--output", help="Output file"),
    quality: str = typer.Option("high", "-q", "--quality", help=f"Quality preset: {', '.join(QUALITY_PRESETS)}"),
):
    """Export video with a quality preset. Default 'high' = near-lossless."""
    require_ffmpeg()

    if quality not in QUALITY_PRESETS:
        rprint(f"[red]Unknown quality:[/red] {quality}. Choose: {', '.join(QUALITY_PRESETS)}")
        raise typer.Exit(1)

    args = QUALITY_PRESETS[quality]
    rprint(f"[cyan]Exporting[/cyan] [{quality}] → {output}")
    ffmpeg("-i", str(input), *args, str(output))
    rprint(f"[green]✓[/green] Saved to {output}")
