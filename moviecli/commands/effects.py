"""mc effect — blur, spotlight effects by timestamp range."""

import typer
from pathlib import Path
from rich import print as rprint
from ..core.timeline import parse_ts, fmt_ts
from ..core.ffmpeg_wrapper import ffmpeg, video_info, require_ffmpeg

app = typer.Typer()


@app.command()
def blur(
    input: Path = typer.Argument(..., help="Input video file"),
    from_ts: str = typer.Option(..., "--from", help="Start timestamp"),
    to_ts: str = typer.Option(..., "--to", help="End timestamp"),
    intensity: int = typer.Option(10, "--intensity", "-i", help="Blur strength (1-50)"),
    output: Path = typer.Option(None, "-o", "--output"),
):
    """Apply blur to a timestamp range."""
    require_ffmpeg()
    t0, t1 = parse_ts(from_ts), parse_ts(to_ts)
    out = output or input.with_stem(input.stem + "_blur")

    # boxblur luma_radius:luma_power — enable only in [t0, t1]
    blur_filter = (
        f"[0:v]split=2[base][blur_src];"
        f"[blur_src]boxblur={intensity}:{intensity//2 or 1}[blurred];"
        f"[base][blurred]overlay=enable='between(t,{t0},{t1})'"
    )

    rprint(f"[cyan]Blur[/cyan] intensity={intensity} | {fmt_ts(t0)} → {fmt_ts(t1)}")
    ffmpeg("-i", str(input), "-filter_complex", blur_filter, "-c:a", "copy", str(out))
    rprint(f"[green]✓[/green] Saved to {out}")


@app.command()
def spotlight(
    input: Path = typer.Argument(..., help="Input video file"),
    from_ts: str = typer.Option(..., "--from", help="Start timestamp"),
    to_ts: str = typer.Option(..., "--to", help="End timestamp"),
    x: int = typer.Option(..., "--x", help="Center X coordinate"),
    y: int = typer.Option(..., "--y", help="Center Y coordinate"),
    radius: int = typer.Option(200, "--radius", "-r", help="Spotlight radius in pixels"),
    dimness: float = typer.Option(0.5, "--dimness", help="Darkness outside spotlight (0.0–1.0)"),
    output: Path = typer.Option(None, "-o", "--output"),
):
    """Soft spotlight effect — dims everything except a circular region."""
    require_ffmpeg()
    t0, t1 = parse_ts(from_ts), parse_ts(to_ts)
    info = video_info(str(input))
    w, h = info["width"], info["height"]
    out = output or input.with_stem(input.stem + "_spotlight")

    # Build radial gradient mask: bright circle, dark outside
    # Using geq to generate per-pixel brightness based on distance from (x,y)
    mask_expr = (
        f"'if(lte(hypot(X-{x},Y-{y}),{radius}),255,"
        f"255*{1-dimness})'"
    )
    filter_complex = (
        f"[0:v]split=2[orig][copy];"
        f"[copy]geq=lum={mask_expr}:cb=128:cr=128[mask];"
        f"[orig][mask]blend=all_mode=multiply:enable='between(t,{t0},{t1})',"
        f"[0:v]overlay=enable='not(between(t,{t0},{t1}))'"
    )

    # Simpler approach: darken full frame then overlay bright circle
    # Using vignette-style with curves
    geo_filter = (
        f"[0:v]geq="
        f"lum='if(between(t,{t0},{t1}),if(lte(hypot(X-{x},Y-{y}),{radius}),lum(X\\,Y),lum(X\\,Y)*{1-dimness}),lum(X\\,Y))':"
        f"cb='cb(X\\,Y)':cr='cr(X\\,Y)'"
    )

    rprint(f"[cyan]Spotlight[/cyan] center=({x},{y}) radius={radius} | {fmt_ts(t0)} → {fmt_ts(t1)}")
    ffmpeg("-i", str(input), "-vf", geo_filter, "-c:a", "copy", str(out))
    rprint(f"[green]✓[/green] Saved to {out}")
