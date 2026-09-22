import os
import select
import sys
import termios
import tty
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from catalog import MAPS_ROOT
from models import COLORS, DEFAULT_COLOR, FlyMap, ZoneType
from simulation import Turn

if TYPE_CHECKING:
    # only for type hints -- importing this module never requires
    # pygame to actually be installed unless PygameRenderer is used
    import pygame

RESET = "\033[0m"
CLEAR = "\033[2J\033[H"
DRONE_ICON = Path(__file__).resolve().parent.parent / "drone.png"


def _getch() -> str:
    """Read a single keypress.

    Arrow keys arrive as a 3-byte escape sequence and come back as the
    strings 'UP' / 'DOWN' / 'LEFT' / 'RIGHT'; a lone Escape returns 'ESC';
    anything else returns the character itself.
    """
    fd = sys.stdin.fileno()  # stdin fileno = 0
    old = termios.tcgetattr(fd)  # returns list of current terminal settings
    try:
        # sets terminal to cbreak mode
        # ICANON = off -> instant read, imediate character delivery
        # ECHO = off -> no key presses sent to stdout
        # ISIG = on -> leaves killing commands available (ex. ctrl + c)
        tty.setcbreak(fd)
        # os.read(fd, ...) talks to the kernel directly, same level as
        # select() below -- sys.stdin.read() is buffered and can silently
        # drain bytes out of the kernel that select() would then never
        # see as "pending", causing false ESC-timeouts on real arrow keys
        ch = os.read(fd, 1).decode()

        # normal letter is returned instantly
        if ch != "\033":
            return ch

        # sequence starting in \033 (ESC) like arrow keys or plain ESC
        # select.select(read_list, write_list, error_list, timeout)
        # if stdin is ready after 0.05 sec no more bytes are incoming
        # so its a bare ESC
        if not select.select([fd], [], [], 0.05)[0]:
            return "ESC"

        # read next 2 chars: "[" (CSI) or "O" (SS3, some terminals use this
        # for arrows) + the direction letter, e.g. right arrow = \033[C
        seq = os.read(fd, 2).decode()
        return {
            "[A": "UP", "OA": "UP",
            "[B": "DOWN", "OB": "DOWN",
            "[C": "RIGHT", "OC": "RIGHT",
            "[D": "LEFT", "OD": "LEFT",
        }.get(seq, "ESC")
    finally:
        # restore defaults
        # TCSADRAIN = wait for all the buffered output to be writen first
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _tint(text: str, color_name: str | None) -> str:
    """Wrap text in a 24-bit ANSI colour from a zone's color=value."""
    r, g, b = COLORS.get(color_name or "", DEFAULT_COLOR)
    return f"\033[38;2;{r};{g};{b}m{text}{RESET}"


def _replay(fly_map: FlyMap, turns: list[Turn]) -> list[dict[str, list[int]]]:
    """One frame per turn: {location: sorted drone ids} after that turn.

    location is a zone name, or an "a-b" connection label while a drone
    is mid-crossing toward a restricted zone (zone names never contain a
    dash, so a dash in the key means "on a connection").
    """
    where: dict[int, str] = {
        drone_id: fly_map.start for drone_id in range(1, fly_map.nb_drones + 1)
    }
    frames: list[dict[str, list[int]]] = []
    for turn in turns:
        for mv in turn.moves:
            where[mv.drone_id] = mv.label
        frame: dict[str, list[int]] = {}
        for drone_id, loc in where.items():
            # if loc in the dict append id to its list, else create empty list
            frame.setdefault(loc, []).append(drone_id)
        for ids in frame.values():
            ids.sort()
        frames.append(frame)
    return frames


class Renderer(ABC):
    """Hand it the map and the list of turns; it shows the run."""

    def pick_map(self, maps: list[Path]) -> Path | None:
        """Default picker: numbered terminal prompt.

        Backends with a graphical picker (PygameRenderer) override this.
        """
        print("Available maps:\n")
        for i, path in enumerate(maps, start=1):
            print(f"  {i:>2}. {path.relative_to(MAPS_ROOT)}")
        print()
        choice = input("Pick a number (blank to cancel): ").strip()
        if not choice.isdigit():
            return None
        idx = int(choice)
        if 1 <= idx <= len(maps):
            return maps[idx - 1]
        return None

    @abstractmethod
    def play(self, fly_map: FlyMap, turns: list[Turn]) -> None:
        ...


class TerminalRenderer(Renderer):
    """Per-turn coloured board: every zone with its [occ/cap] and drones."""

    def _render_list(
        self,
        fly_map: FlyMap,
        turn: Turn,
        frame: dict[str, list[int]],
    ) -> str:
        tag_of = {
            ZoneType.RESTRICTED: " (restricted)",
            ZoneType.BLOCKED: " (blocked)",
            ZoneType.PRIORITY: " (priority)",
        }

        lines: list[str] = [
            f"Turn {turn.index}: {turn.render_line() or '--'}",
            "",
        ]

        zones = sorted(fly_map.zones.values(), key=lambda z: (z.x, z.y))
        for z in zones:
            ids = frame.get(z.name, [])
            cap = (
                float("inf") if z.name in (fly_map.start, fly_map.end)
                else z.max_drones
            )
            body = " ".join(f"D{n}" for n in ids) or "."
            text = f"  {z.name:<14}[{len(ids)}/{cap}] {body}"
            text += tag_of.get(z.zone_type, "")
            lines.append(_tint(text, z.color))
        for loc, ids in frame.items():
            if "-" in loc:
                who = " ".join(f"D{n}" for n in ids)
                lines.append(f"  ~ {loc}: {who}")
        return "\n".join(lines)

    def play(self, fly_map: FlyMap, turns: list[Turn]) -> None:
        # turn 0: every drone still at the start hub, before anyone moves
        start_frame = {fly_map.start: list(range(1, fly_map.nb_drones + 1))}
        all_turns = [Turn(index=0)] + list(turns)
        all_frames = [start_frame] + _replay(fly_map, turns)

        # not a real terminal (piped/redirected) -> just dump every frame once
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            for turn, frame in zip(all_turns, all_frames):
                print(self._render_list(fly_map, turn, frame))
            return

        idx = 0
        while True:
            text = self._render_list(fly_map, all_turns[idx], all_frames[idx])
            sys.stdout.write(CLEAR)  # clear the screen
            sys.stdout.write(text)
            sys.stdout.write(
                f"\n[{idx}/{len(turns)}]  <-/-> step   q quit\n"
            )
            sys.stdout.flush()

            key = _getch()  # read one keypress
            if key in ["q", "ESC"]:  # quit keys
                break
            elif key == "RIGHT":
                idx += 1 if idx < len(all_turns) - 1 else 0
            elif key == "LEFT":
                idx -= 1 if idx > 0 else 0

        sys.stdout.write(CLEAR)  # clear the screen
        sys.stdout.flush()


def _group_by_folder(maps: list[Path]) -> dict[str, list[Path]]:
    """Bucket maps by their immediate parent folder name (relative to
    MAPS_ROOT), e.g. {"easy": [...], "medium": [...], "custom": [...]}.
    """
    groups: dict[str, list[Path]] = {}
    for path in maps:
        folder = path.relative_to(MAPS_ROOT).parts[0]
        groups.setdefault(folder, []).append(path)
    return groups


def _short_label(name: str, max_len: int) -> str:
    """Truncate to max_len chars, keeping the tail so numbered/lettered
    suffixes (waiting_area1/2/3, maze_dead_a/b, ...) stay distinguishable
    -- plain front-truncation collapses all of those to one identical
    string.
    """
    if len(name) <= max_len:
        return name
    tail = min(2, max_len - 1)
    head = max_len - tail
    return name[:head] + name[-tail:]


def _positions(
    fly_map: FlyMap, width: int, height: int, margin: int = 60
) -> dict[str, tuple[int, int]]:
    """Scale every zone's (x, y) into pixel coordinates inside a
    width x height window, y flipped so pygame's top-left/y-grows-down
    screen still reads as "up is up" -- the same normalize-and-flip you
    already did for the terminal grid, just producing pixels instead of
    character cells.
    """
    xs = [v.x for v in fly_map.zones.values()]
    ys = [v.y for v in fly_map.zones.values()]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)

    span_x = max(1, max_x - min_x)
    span_y = max(1, max_y - min_y)
    res = {}
    for name, z in fly_map.zones.items():
        px = margin + (z.x - min_x) / span_x * (width - 2 * margin)
        py = margin + (max_y - z.y) / span_y * (height - 2 * margin)
        res[name] = (int(px), int(py))
    return res


def _drone_points(
    frame: dict[str, list[int]], positions: dict[str, tuple[int, int]]
) -> dict[int, tuple[float, float]]:
    """Where each drone sits on screen for one frame.

    A zone location maps straight to that zone's point; a drone mid
    restricted-crossing ("a-b" location) is placed at the midpoint of
    that connection, so it visibly sits "on the line" while in transit.
    """
    pts: dict[int, tuple[float, float]] = {}
    for loc, ids in frame.items():
        if "-" in loc:
            a, b = loc.split("-")
            ax, ay = positions[a]
            bx, by = positions[b]
            point = ((ax + bx) / 2, (ay + by) / 2)
        else:
            x, y = positions[loc]
            point = (float(x), float(y))
        for drone_id in ids:
            pts[drone_id] = point
    return pts


class PygameRenderer(Renderer):
    """pygame-ce window: a map-selection menu, then a turn-by-turn replay."""

    WIDTH = 1000
    HEIGHT = 700
    ANIM_MS = 400  # how long a drone takes to glide between two points

    # dynamic sizing for the play window: guarantee this many pixels per
    # map-x/y unit so dense maps (many zones close together) still get
    # breathing room, capped so it doesn't outgrow a normal screen
    COL_PX = 150
    ROW_PX = 130
    MAX_WIDTH = 3200
    MAX_HEIGHT = 1200
    LABEL_MAX = 12  # zone names longer than this are truncated on screen

    def __init__(self) -> None:
        import pygame

        self.pygame = pygame
        pygame.init()
        self.screen: pygame.Surface = pygame.display.set_mode(
            (self.WIDTH, self.HEIGHT)
            )
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(None, 22)

        self.drone_icon: pygame.Surface | None = None
        try:
            icon = pygame.image.load(str(DRONE_ICON)).convert_alpha()
            self.drone_icon = pygame.transform.smoothscale(icon, (26, 26))
        except (FileNotFoundError, pygame.error) as exc:
            print(f"drone icon unavailable ({exc}); using dots",
                  file=sys.stderr)

    def pick_map(self, maps: list[Path]) -> Path | None:
        """Two-level menu: folders first, then the maps inside one.

        Controls: UP/DOWN move the selection (auto-scrolling once the
        list is taller than the window), ENTER opens a folder / confirms
        a map, BACKSPACE or LEFT goes back a level, ESC or the window's
        close button quits.
        """
        folders = _group_by_folder(maps)
        folder_names = sorted(folders)

        mode = "folders"  # or "maps"
        folder_idx = 0
        map_idx = 0
        scroll = 0
        row_h = 26
        top_margin = 50
        bottom_margin = 40

        while True:
            for event in self.pygame.event.get():
                if event.type == self.pygame.QUIT:
                    return None
                elif event.type == self.pygame.KEYDOWN:
                    if event.key == self.pygame.K_ESCAPE:
                        return None
                    if event.key in (
                        self.pygame.K_BACKSPACE, self.pygame.K_LEFT
                    ):
                        if mode == "maps":
                            mode = "folders"
                            scroll = 0
                        continue

                    count = (
                        len(folder_names) if mode == "folders"
                        else len(folders[folder_names[folder_idx]])
                    )

                    if event.key == self.pygame.K_UP:
                        if mode == "folders":
                            folder_idx = (folder_idx - 1) % count
                        else:
                            map_idx = (map_idx - 1) % count
                    elif event.key == self.pygame.K_DOWN:
                        if mode == "folders":
                            folder_idx = (folder_idx + 1) % count
                        else:
                            map_idx = (map_idx + 1) % count
                    elif event.key == self.pygame.K_RETURN:
                        if mode == "folders":
                            mode = "maps"
                            map_idx = 0
                            scroll = 0
                        else:
                            return folders[folder_names[folder_idx]][map_idx]

            if mode == "folders":
                selected = folder_idx
                labels = folder_names
                title_text = "Select a folder"
                hint = "UP/DOWN move   ENTER open   ESC quit"
            else:
                current_maps = folders[folder_names[folder_idx]]
                selected = map_idx
                labels = [p.name for p in current_maps]
                title_text = f"{folder_names[folder_idx]}/  --  select a map"
                hint = (
                    "UP/DOWN move   ENTER select   "
                    "BACKSPACE back   ESC quit"
                )

            visible = max(
                1,
                (self.screen.get_height() - top_margin - bottom_margin)
                // row_h,
            )
            if selected < scroll:
                scroll = selected
            elif selected >= scroll + visible:
                scroll = selected - visible + 1

            self.screen.fill((20, 20, 20))
            title = self.font.render(title_text, True, (255, 255, 255))
            self.screen.blit(title, (40, 10))

            for row, i in enumerate(
                range(scroll, min(scroll + visible, len(labels)))
            ):
                color = (255, 220, 0) if i == selected else (180, 180, 180)
                label = self.font.render(labels[i], True, color)
                self.screen.blit(label, (40, top_margin + row * row_h))

            footer = self.font.render(
                f"[{selected + 1}/{len(labels)}]  {hint}",
                True, (200, 200, 200),
            )
            self.screen.blit(footer, (40, self.screen.get_height() - 30))
            self.pygame.display.flip()
            self.clock.tick(30)

    def _desktop_size(self) -> tuple[int, int]:
        """Best-effort monitor resolution, so the window never opens
        bigger than the screen it's on."""
        try:
            return self.pygame.display.get_desktop_sizes()[0]
        except (self.pygame.error, IndexError):
            info = self.pygame.display.Info()
            return info.current_w, info.current_h

    def play(self, fly_map: FlyMap, turns: list[Turn]) -> None:
        """Turn-by-turn replay window.

        Controls: LEFT/RIGHT step a turn, SPACE toggles auto-play,
        R resets to turn 0, WASD / mouse wheel pan when the map is
        bigger than the window, ESC/Q/closing the window quits.
        """
        xs = [z.x for z in fly_map.zones.values()]
        ys = [z.y for z in fly_map.zones.values()]
        cols = max(xs) - min(xs) + 1
        rows = max(ys) - min(ys) + 1
        canvas_w = min(self.MAX_WIDTH, max(self.WIDTH, cols * self.COL_PX))
        canvas_h = min(self.MAX_HEIGHT, max(self.HEIGHT, rows * self.ROW_PX))

        # the actual window: the full canvas, unless that's bigger than
        # the monitor, in which case we open a smaller window and scroll
        screen_w, screen_h = self._desktop_size()
        chrome = 100  # headroom for title bar / taskbar
        viewport_w = min(canvas_w, max(400, screen_w - chrome))
        viewport_h = min(canvas_h, max(300, screen_h - chrome))
        self.screen = self.pygame.display.set_mode((viewport_w, viewport_h))
        canvas = self.pygame.Surface((canvas_w, canvas_h))

        max_scroll_x = canvas_w - viewport_w
        max_scroll_y = canvas_h - viewport_h
        scroll_x, scroll_y = 0, 0
        can_scroll = max_scroll_x > 0 or max_scroll_y > 0
        # one key press covers a fixed fraction of whatever there is to
        # scroll, so a huge map doesn't take forever to cross -- floored
        # so a small map with little to scroll still moves a sane amount
        pan_x = max(40, max_scroll_x // 6)
        pan_y = max(40, max_scroll_y // 6)

        positions = _positions(fly_map, canvas_w, canvas_h)
        all_turns = [Turn(index=0)] + list(turns)
        all_frames = (
            [{fly_map.start: list(range(1, fly_map.nb_drones + 1))}]
            + _replay(fly_map, turns)
        )
        idx = 0
        playing = False
        last_step_ms = 0

        # animation state: every drone glides from anim_from to anim_to
        # over ANIM_MS, timed from anim_start_ms. _goto() re-anchors all
        # three whenever idx actually changes.
        anim_from = _drone_points(all_frames[0], positions)
        anim_to = anim_from
        anim_start_ms = 0

        def _goto(new_idx: int) -> None:
            nonlocal idx, anim_from, anim_to, anim_start_ms
            if new_idx == idx:
                return
            anim_from = _drone_points(all_frames[idx], positions)
            idx = new_idx
            anim_to = _drone_points(all_frames[idx], positions)
            anim_start_ms = self.pygame.time.get_ticks()

        while True:
            for event in self.pygame.event.get():
                if event.type == self.pygame.QUIT:
                    return None
                elif event.type == self.pygame.KEYDOWN:
                    if (
                        event.key == self.pygame.K_ESCAPE
                        or event.key == self.pygame.K_q
                    ):
                        return None
                    if event.key == self.pygame.K_RIGHT:
                        _goto(min(idx + 1, len(all_turns) - 1))
                    if event.key == self.pygame.K_LEFT:
                        _goto(max(idx - 1, 0))
                    if event.key == self.pygame.K_SPACE:
                        playing = not playing
                    if event.key == self.pygame.K_r:
                        _goto(0)
                        playing = False
                    if event.key == self.pygame.K_a:
                        scroll_x = max(0, scroll_x - pan_x)
                    if event.key == self.pygame.K_d:
                        scroll_x = min(max_scroll_x, scroll_x + pan_x)
                    if event.key == self.pygame.K_w:
                        scroll_y = max(0, scroll_y - pan_y)
                    if event.key == self.pygame.K_s:
                        scroll_y = min(max_scroll_y, scroll_y + pan_y)
                elif event.type == self.pygame.MOUSEWHEEL:
                    dx, dy = event.x, event.y
                    if max_scroll_y == 0 and max_scroll_x > 0:
                        # nothing to scroll vertically (the common case:
                        # a wide-but-not-tall map) -- let a plain mouse
                        # wheel (which only ever sends dy) pan sideways
                        # instead of silently doing nothing
                        dx, dy = dx + dy, 0
                    scroll_x = min(max_scroll_x, max(0, scroll_x - dx * pan_x))
                    scroll_y = min(max_scroll_y, max(0, scroll_y - dy * pan_y))

            if playing:
                now = self.pygame.time.get_ticks()
                if now - last_step_ms >= 500:
                    if idx < len(all_turns) - 1:
                        _goto(idx + 1)
                        last_step_ms = now
                    else:
                        playing = False

            # ease-out interpolation: fast start, gentle stop
            now = self.pygame.time.get_ticks()
            t = min(1.0, (now - anim_start_ms) / self.ANIM_MS)
            eased = 1 - (1 - t) ** 2
            drone_points = {
                drone_id: (
                    anim_from[drone_id][0] + (
                        anim_to[drone_id][0] - anim_from[drone_id][0]
                    ) * eased,
                    anim_from[drone_id][1] + (
                        anim_to[drone_id][1] - anim_from[drone_id][1]
                    ) * eased,
                )
                for drone_id in anim_to
            }

            self._draw_frame(
                canvas, fly_map, all_turns[idx], all_frames[idx], positions,
                drone_points,
            )

            # only the visible slice of the canvas reaches the window
            self.screen.blit(
                canvas, (0, 0),
                self.pygame.Rect(scroll_x, scroll_y, viewport_w, viewport_h),
            )

            # UI chrome drawn on the window directly (never scrolls away)
            title = self.font.render(
                f"Turn {all_turns[idx].index}: "
                f"{all_turns[idx].render_line() or '--'}",
                True, (255, 255, 255),
            )
            self.screen.blit(title, (20, 10))

            hint = "   WASD/wheel pan" if can_scroll else ""
            footer = self.font.render(
                f"[{idx}/{len(all_turns) - 1}] "
                f"{'PLAYING' if playing else ''}"
                "   <-/-> step   Space play   R reset   ESC quit" + hint,
                True, (200, 200, 200),
            )
            self.screen.blit(footer, (20, self.screen.get_height() - 30))

            self.pygame.display.flip()
            self.clock.tick(30)

    def _draw_frame(
        self,
        surface: "pygame.Surface",
        fly_map: FlyMap,
        turn: Turn,
        frame: dict[str, list[int]],
        positions: dict[str, tuple[int, int]],
        drone_points: dict[int, tuple[float, float]],
    ) -> None:
        """Draw one turn's map picture onto surface (a Surface -- title
        bar and footer are drawn separately, straight onto the window,
        so they never scroll away with the map content).
        """
        surface.fill((20, 20, 20))

        for c in fly_map.connections:
            self.pygame.draw.line(surface, (90, 90, 90),
                                  positions[c.a], positions[c.b], 2)

        # pass 1: every zone circle
        for z in fly_map.zones.values():
            color = COLORS.get(z.color or "", DEFAULT_COLOR)
            self.pygame.draw.circle(surface, color, positions[z.name], 18)

        # pass 2: every label, drawn AFTER all circles so a neighbour's
        # circle (common on dense maps) can never paint over this text
        for z in fly_map.zones.values():
            ids = frame.get(z.name, [])
            cap = "inf" if z.name in [fly_map.start, fly_map.end] \
                else z.max_drones
            short_name = _short_label(z.name, self.LABEL_MAX)
            label = self.font.render(
                f"{short_name} [{len(ids)}/{cap}]", True, (255, 255, 255)
                )
            surface.blit(
                label,
                (positions[z.name][0] + 20, positions[z.name][1] - 8),
            )

        # drone markers, drawn on top of the zones/lines, at their
        # (possibly mid-glide) interpolated position
        for x, y in drone_points.values():
            pos = (int(x), int(y))
            if self.drone_icon is not None:
                rect = self.drone_icon.get_rect(center=pos)
                surface.blit(self.drone_icon, rect)
            else:
                self.pygame.draw.circle(surface, (255, 255, 0), pos, 5)
                self.pygame.draw.circle(surface, (0, 0, 0), pos, 5, 1)


def make_renderer(kind: str) -> Renderer:
    """
    Requested backend, falling back to terminal when pygame can't start.
    """
    if kind == "terminal":
        return TerminalRenderer()
    try:
        return PygameRenderer()
    except Exception as exc:
        print(f"pygame not setup ({exc}); using terminal", file=sys.stderr)
        return TerminalRenderer()
