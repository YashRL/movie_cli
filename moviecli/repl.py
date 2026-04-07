"""Interactive REPL — the main mc experience."""

import shlex
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML, to_formatted_text, StyleAndTextTuples
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from .core.ffmpeg_wrapper import video_info, require_ffmpeg
from .core.timeline import parse_ts, fmt_ts

console = Console()

# ── help text per command ────────────────────────────────────────────────────

COMMANDS = {
    "/load":       ("<file>",                          "Load a video file to work on"),
    "/info":       ("",                                "Show current video metadata"),
    "/trim":       ("<start> <end> [as <name>]",       "Cut between timestamps"),
    "/blur":       ("<start> <end> [intensity <n>]",   "Blur a time range (default intensity 10)"),
    "/spotlight":  ("<start> <end> x<n> y<n> [r<n>]", "Soft spotlight at x,y with radius"),
    "/text":       ('<start> <end> "text" x<n> y<n>',  "Overlay text at coordinates"),
    "/insert":     ("<file> at <timestamp>",           "Insert a clip at a timestamp"),
    "/concat":     ("<file1> <file2> ...",              "Concatenate clips in order"),
    "/export":     ("[as <name>] [quality <preset>]",  "Export final video (presets: lossless/high/medium/web)"),
    "/saves":      ("",                                "List files in the saves folder"),
    "/undo":       ("",                                "Delete the last output file"),
    "/help":       ("",                                "Show this help"),
    "/clear":      ("",                                "Clear the screen"),
    "/exit":       ("",                                "Exit MovieCLI"),
}

QUALITY_PRESETS = ["lossless", "high", "medium", "web"]

# Each command's arguments as a list of (name, optional) tuples for toolbar hints
CMD_ARGS = {
    "/load":      [("file", False)],
    "/trim":      [("start", False), ("end", False), ("as name", True)],
    "/blur":      [("start", False), ("end", False), ("intensity n", True)],
    "/spotlight": [("start", False), ("end", False), ("x…", False), ("y…", False), ("r…", True), ("dim 0.0-1.0", True)],
    "/text":      [("start", False), ("end", False), ('"text"', False), ("x…", False), ("y…", False), ("size n", True), ("color name", True)],
    "/insert":    [("clip", False), ("at", False), ("timestamp", False)],
    "/concat":    [("file1", False), ("file2", False), ("…", True), ("as name", True)],
    "/export":    [("as name", True), ("quality preset", True)],
}

PROMPT_STYLE = Style.from_dict({
    "prompt":       "#00afff bold",
    "file":         "#afd700",
    "dim":          "#626262",
    "tb.cmd":       "#00afff bold",
    "tb.arg":       "#ffffff",
    "tb.arg.cur":   "#ffaf00 bold",   # currently expected argument — highlighted
    "tb.arg.opt":   "#626262",        # optional args
    "tb.sep":       "#444444",
})

# ── live toolbar ─────────────────────────────────────────────────────────────

def make_toolbar(get_text):
    """Return a callable prompt_toolkit uses to render the bottom toolbar."""
    def toolbar() -> StyleAndTextTuples:
        text = get_text()
        try:
            parts = shlex.split(text) if text.strip() else []
        except ValueError:
            parts = text.split()

        if not parts:
            return [("class:tb.sep", " /help  /load  /trim  /blur  /spotlight  /text  /insert  /concat  /export  /saves  /undo ")]

        cmd = parts[0]
        arg_defs = CMD_ARGS.get(cmd)
        if not arg_defs:
            return [("class:tb.sep", f" {cmd} ")]

        # How many positional args already filled (words after command)
        filled = len(parts) - 1  # words typed after command
        # adjust for trailing space — if ends with space, user started next arg
        if text.endswith(" "):
            current_idx = filled
        else:
            current_idx = max(filled - 1, 0)

        result: StyleAndTextTuples = [("class:tb.cmd", f" {cmd} ")]
        for i, (name, optional) in enumerate(arg_defs):
            is_current = (i == current_idx)
            is_done = (i < filled and not text.endswith(" ")) or (i < current_idx)

            if is_done:
                style = "class:tb.sep"
            elif is_current:
                style = "class:tb.arg.cur"
            elif optional:
                style = "class:tb.arg.opt"
            else:
                style = "class:tb.arg"

            bracket = ("class:tb.sep", "[") if optional else ("class:tb.sep", "<")
            end_bracket = ("class:tb.sep", "] ") if optional else ("class:tb.sep", "> ")
            result += [bracket, (style, name), end_bracket]

        return result

    return toolbar


# ── smart completer ──────────────────────────────────────────────────────────

class MCCompleter(Completer):
    def __init__(self, state: dict):
        self.state = state  # shared mutable state

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()
        word = document.get_word_before_cursor(WORD=True)

        # First word: complete slash commands
        if not words or (len(words) == 1 and not text.endswith(" ")):
            for cmd, (args, desc) in COMMANDS.items():
                if cmd.startswith(word):
                    yield Completion(
                        cmd, start_position=-len(word),
                        display=cmd,
                        display_meta=desc,
                    )
            return

        cmd = words[0]

        # /load + /insert: complete file paths
        if cmd in ("/load", "/insert") or (cmd == "/concat"):
            yield from self._path_completions(word)
            return

        # quality completions for /export
        if cmd == "/export" and words[-1] in ("quality",):
            for q in QUALITY_PRESETS:
                yield Completion(q, start_position=0, display_meta="quality preset")
            return

        # Suggest common timestamp shortcuts after a command
        if cmd in ("/trim", "/blur", "/spotlight", "/text"):
            if len(words) == 1 or (len(words) == 2 and not text.endswith(" ")):
                return
            # suggest "as" keyword after two timestamps
            if len(words) == 3 and text.endswith(" ") and cmd == "/trim":
                yield Completion("as", start_position=0, display_meta="save as name")

        # /export: suggest "as" and "quality"
        if cmd == "/export":
            if "as" not in words:
                yield Completion("as", start_position=-len(word), display_meta="output filename")
            if "quality" not in words:
                yield Completion("quality", start_position=-len(word), display_meta="quality preset")

    def _path_completions(self, word: str):
        try:
            VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".ts"}
            base = Path(word) if word else Path(".")
            # If word ends with "/" or is an existing dir, list its contents
            directory = base if base.is_dir() else base.parent
            prefix = "" if base.is_dir() else base.name

            matches = [
                p for p in sorted(directory.iterdir())
                if p.name.startswith(prefix) and (p.is_dir() or p.suffix.lower() in VIDEO_EXTS)
            ]

            for p in matches[:5]:
                full = str(p) + ("/" if p.is_dir() else "")
                yield Completion(
                    full,
                    start_position=-len(word),
                    display=p.name + ("/" if p.is_dir() else ""),
                    display_meta="dir" if p.is_dir() else p.suffix,
                )
        except Exception:
            pass


# ── command handlers ─────────────────────────────────────────────────────────

def saves_dir() -> Path:
    d = Path("saves")
    d.mkdir(exist_ok=True)
    return d


def handle_load(args: list, state: dict) -> bool:
    if not args:
        rprint("[red]Usage:[/red] /load <file>")
        return False
    p = Path(args[0])
    if not p.exists():
        rprint(f"[red]File not found:[/red] {p}")
        return False
    if p.is_dir():
        VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".ts"}
        videos = sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXTS)
        if not videos:
            rprint(f"[yellow]No video files in[/yellow] {p}")
        else:
            rprint(f"[dim]Videos in {p}/[/dim]")
            for v in videos:
                rprint(f"  [cyan]{v.name}[/cyan]")
            rprint(f"[dim]Use:[/dim] /load {p}/<filename>")
        return False
    try:
        info = video_info(str(p))
        state["file"] = p
        state["history"].append(p)
        rprint(f"\n[bold green]Loaded[/bold green] [bold]{p.name}[/bold]")
        _print_info(info, p)
        return True
    except Exception as e:
        rprint(f"[red]Error:[/red] {e}")
        return False


def _print_info(info: dict, path: Path):
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_row("[dim]Resolution[/dim]", f"{info['width']}x{info['height']}")
    t.add_row("[dim]FPS[/dim]",        f"{info['fps']:.2f}")
    t.add_row("[dim]Duration[/dim]",   fmt_ts(info["duration"]))
    console.print(t)


def handle_info(state: dict):
    if not state.get("file"):
        rprint("[yellow]No file loaded. Use /load <file>[/yellow]")
        return
    info = video_info(str(state["file"]))
    _print_info(info, state["file"])


def _resolve_output(args: list, state: dict, suffix: str) -> Path:
    """Parse optional 'as <name>' from args, or auto-name in saves/."""
    if "as" in args:
        idx = args.index("as")
        name = args[idx + 1] if idx + 1 < len(args) else None
        if name:
            out = saves_dir() / name
            if not out.suffix:
                out = out.with_suffix(state["file"].suffix)
            return out
    stem = state["file"].stem + suffix
    return saves_dir() / (stem + state["file"].suffix)


def _run_ffmpeg_track(out: Path, state: dict, *cmd_args):
    """Run ffmpeg and track output for undo."""
    from .core.ffmpeg_wrapper import ffmpeg
    ffmpeg(*cmd_args, str(out))
    state["last_output"] = out
    rprint(f"[green]✓[/green] Saved → [bold]{out}[/bold]")


def handle_trim(args: list, state: dict):
    if not state.get("file") or len(args) < 2:
        rprint("[red]Usage:[/red] /trim <start> <end> [as <name>]")
        return
    try:
        t0, t1 = parse_ts(args[0]), parse_ts(args[1])
    except ValueError as e:
        rprint(f"[red]{e}[/red]"); return

    out = _resolve_output(args, state, "_trimmed")
    duration = t1 - t0
    rprint(f"[cyan]Trimming[/cyan] {fmt_ts(t0)} → {fmt_ts(t1)} ({duration:.1f}s)")
    _run_ffmpeg_track(out, state,
        "-ss", str(t0), "-i", str(state["file"]),
        "-t", str(duration), "-c", "copy",
    )


def handle_blur(args: list, state: dict):
    if not state.get("file") or len(args) < 2:
        rprint("[red]Usage:[/red] /blur <start> <end> [intensity <n>]")
        return
    try:
        t0, t1 = parse_ts(args[0]), parse_ts(args[1])
    except ValueError as e:
        rprint(f"[red]{e}[/red]"); return

    intensity = 10
    if "intensity" in args:
        idx = args.index("intensity")
        intensity = int(args[idx + 1]) if idx + 1 < len(args) else 10

    out = _resolve_output(args, state, "_blur")
    blur_filter = (
        f"[0:v]split=2[base][blur_src];"
        f"[blur_src]boxblur={intensity}:{max(1, intensity//2)}[blurred];"
        f"[base][blurred]overlay=enable='between(t,{t0},{t1})'"
    )
    rprint(f"[cyan]Blur[/cyan] intensity={intensity} | {fmt_ts(t0)} → {fmt_ts(t1)}")
    _run_ffmpeg_track(out, state, "-i", str(state["file"]), "-filter_complex", blur_filter, "-c:a", "copy")


def handle_spotlight(args: list, state: dict):
    # /spotlight <start> <end> x<n> y<n> [r<n>] [dim <f>]
    if not state.get("file") or len(args) < 4:
        rprint("[red]Usage:[/red] /spotlight <start> <end> x<n> y<n> [r<n>] [dim <0.0-1.0>]")
        return
    try:
        t0, t1 = parse_ts(args[0]), parse_ts(args[1])
        x = int(next(a[1:] for a in args if a.startswith("x") and a[1:].isdigit()))
        y = int(next(a[1:] for a in args if a.startswith("y") and a[1:].isdigit()))
        radius = int(next((a[1:] for a in args if a.startswith("r") and a[1:].isdigit()), "200"))
        dimness = float(args[args.index("dim") + 1]) if "dim" in args else 0.5
    except (ValueError, StopIteration) as e:
        rprint(f"[red]Parse error:[/red] {e}"); return

    out = _resolve_output(args, state, "_spotlight")
    geo_filter = (
        f"geq="
        f"lum='if(between(t,{t0},{t1}),if(lte(hypot(X-{x},Y-{y}),{radius}),lum(X\\,Y),lum(X\\,Y)*{1-dimness}),lum(X\\,Y))':"
        f"cb='cb(X\\,Y)':cr='cr(X\\,Y)'"
    )
    rprint(f"[cyan]Spotlight[/cyan] ({x},{y}) r={radius} | {fmt_ts(t0)} → {fmt_ts(t1)}")
    _run_ffmpeg_track(out, state, "-i", str(state["file"]), "-vf", geo_filter, "-c:a", "copy")


def handle_text(args: list, state: dict):
    # /text <start> <end> "text" x<n> y<n> [size <n>] [color <c>]
    if not state.get("file") or len(args) < 4:
        rprint('[red]Usage:[/red] /text <start> <end> "text" x<n> y<n> [size <n>] [color <name>]')
        return
    try:
        t0, t1 = parse_ts(args[0]), parse_ts(args[1])
        content = args[2]
        x_raw = next(a for a in args[3:] if a.startswith("x"))
        y_raw = next(a for a in args[3:] if a.startswith("y"))
        x = "(w-text_w)/2" if x_raw == "xcenter" else x_raw[1:]
        y = "(h-text_h)/2" if y_raw == "ycenter" else ("h-text_h-30" if y_raw == "ybottom" else y_raw[1:])
        size = int(args[args.index("size") + 1]) if "size" in args else 48
        color = args[args.index("color") + 1] if "color" in args else "white"
    except (ValueError, StopIteration) as e:
        rprint(f"[red]Parse error:[/red] {e}"); return

    out = _resolve_output(args, state, "_text")
    drawtext = (
        f"drawtext=text='{content}':fontsize={size}:fontcolor={color}"
        f":x={x}:y={y}:enable='between(t,{t0},{t1})'"
    )
    rprint(f"[cyan]Text[/cyan] '{content}' at ({x_raw},{y_raw}) | {fmt_ts(t0)} → {fmt_ts(t1)}")
    _run_ffmpeg_track(out, state, "-i", str(state["file"]), "-vf", drawtext, "-c:a", "copy")


def handle_export(args: list, state: dict):
    if not state.get("file"):
        rprint("[yellow]No file loaded.[/yellow]"); return
    quality = args[args.index("quality") + 1] if "quality" in args else "high"
    presets = {
        "lossless": ["-c:v", "libx264", "-crf", "0", "-preset", "veryslow", "-c:a", "copy"],
        "high":     ["-c:v", "libx264", "-crf", "18", "-preset", "slow", "-c:a", "aac", "-b:a", "192k"],
        "medium":   ["-c:v", "libx264", "-crf", "23", "-preset", "medium", "-c:a", "aac", "-b:a", "128k"],
        "web":      ["-c:v", "libx264", "-crf", "28", "-preset", "fast", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "128k"],
    }
    if quality not in presets:
        rprint(f"[red]Unknown quality:[/red] {quality}"); return

    out = _resolve_output(args, state, "_final")
    if not str(out).endswith(".mp4"):
        out = out.with_suffix(".mp4")

    rprint(f"[cyan]Exporting[/cyan] [{quality}] → {out}")
    _run_ffmpeg_track(out, state, "-i", str(state["file"]), *presets[quality])


def handle_saves():
    d = saves_dir()
    files = sorted(d.iterdir())
    if not files:
        rprint("[dim]saves/ is empty[/dim]"); return
    t = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    t.add_column("File"); t.add_column("Size", justify="right")
    for f in files:
        size = f"{f.stat().st_size / 1_048_576:.1f} MB"
        t.add_row(f.name, size)
    console.print(t)


def handle_concat(args: list, state: dict):
    if len(args) < 2:
        rprint("[red]Usage:[/red] /concat <file1> <file2> ... [as <name>]"); return
    import tempfile
    files = [Path(a) for a in args if not a == "as" and not (args.index(a) > 0 and args[args.index(a)-1] == "as")]
    out = _resolve_output(args, state or {}, "_concat") if state.get("file") else saves_dir() / "concat.mp4"
    if "as" in args:
        idx = args.index("as")
        out = saves_dir() / args[idx + 1]

    from .core.ffmpeg_wrapper import ffmpeg
    with tempfile.TemporaryDirectory() as tmp:
        lst = Path(tmp) / "list.txt"
        lst.write_text("\n".join(f"file '{p.resolve()}'" for p in files) + "\n")
        rprint(f"[cyan]Concatenating[/cyan] {len(files)} clips")
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out))
    state["last_output"] = out
    rprint(f"[green]✓[/green] Saved → [bold]{out}[/bold]")


def handle_insert(args: list, state: dict):
    if not state.get("file") or "at" not in args or len(args) < 3:
        rprint("[red]Usage:[/red] /insert <clip> at <timestamp>"); return
    clip_path = Path(args[0])
    at_ts = parse_ts(args[args.index("at") + 1])
    out = _resolve_output(args, state, "_inserted")

    import tempfile
    from .core.ffmpeg_wrapper import ffmpeg, video_info as vi
    info = vi(str(state["file"]))
    with tempfile.TemporaryDirectory() as tmp:
        p1, p2 = Path(tmp) / "p1.mp4", Path(tmp) / "p2.mp4"
        lst = Path(tmp) / "list.txt"
        ffmpeg("-ss", "0", "-i", str(state["file"]), "-t", str(at_ts), "-c", "copy", str(p1))
        ffmpeg("-ss", str(at_ts), "-i", str(state["file"]), "-t", str(info["duration"] - at_ts), "-c", "copy", str(p2))
        lst.write_text(f"file '{p1}'\nfile '{clip_path.resolve()}'\nfile '{p2}'\n")
        rprint(f"[cyan]Inserting[/cyan] {clip_path.name} at {fmt_ts(at_ts)}")
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out))
    state["last_output"] = out
    rprint(f"[green]✓[/green] Saved → [bold]{out}[/bold]")


def show_help():
    t = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
    t.add_column("Command", style="bold")
    t.add_column("Args", style="dim")
    t.add_column("Description")
    for cmd, (args, desc) in COMMANDS.items():
        t.add_row(cmd, args, desc)
    console.print(t)


# ── REPL loop ────────────────────────────────────────────────────────────────

def run_repl(initial_file: Optional[str] = None):
    require_ffmpeg()

    state: dict = {"file": None, "last_output": None, "history": []}

    history_path = Path.home() / ".mc_history"
    session = PromptSession(
        history=FileHistory(str(history_path)),
        completer=MCCompleter(state),
        style=PROMPT_STYLE,
        complete_while_typing=True,
        # toolbar reads live from the session's buffer
        bottom_toolbar=make_toolbar(lambda: session.default_buffer.text),
    )

    console.print("[bold cyan]MovieCLI[/bold cyan] [dim]— type /help to see commands, Tab to autocomplete[/dim]\n")

    if initial_file:
        handle_load([initial_file], state)

    while True:
        file_label = f" [dim]{state['file'].name}[/dim]" if state.get("file") else ""
        try:
            raw = session.prompt(
                HTML(f'<prompt>mc</prompt><file>{file_label}</file> <dim>›</dim> '),
                style=PROMPT_STYLE,
            )
        except (KeyboardInterrupt, EOFError):
            rprint("\n[dim]bye[/dim]")
            break

        raw = raw.strip()
        if not raw:
            continue

        try:
            parts = shlex.split(raw)
        except ValueError:
            parts = raw.split()

        cmd, args = parts[0], parts[1:]

        match cmd:
            case "/load":       handle_load(args, state)
            case "/info":       handle_info(state)
            case "/trim":       handle_trim(args, state)
            case "/blur":       handle_blur(args, state)
            case "/spotlight":  handle_spotlight(args, state)
            case "/text":       handle_text(args, state)
            case "/export":     handle_export(args, state)
            case "/saves":      handle_saves()
            case "/concat":     handle_concat(args, state)
            case "/insert":     handle_insert(args, state)
            case "/undo":
                if state.get("last_output") and state["last_output"].exists():
                    state["last_output"].unlink()
                    rprint(f"[yellow]Deleted[/yellow] {state['last_output']}")
                    state["last_output"] = None
                else:
                    rprint("[dim]Nothing to undo.[/dim]")
            case "/help":       show_help()
            case "/clear":      console.clear()
            case "/exit" | "/quit": rprint("[dim]bye[/dim]"); break
            case _:
                rprint(f"[red]Unknown command:[/red] {cmd}  [dim](try /help)[/dim]")
