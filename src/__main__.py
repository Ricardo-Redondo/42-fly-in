import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from catalog import MAPS_ROOT, discover_maps
from graph import Graph
from parser import MapError, MapParser, ParserError
from pathfinder import PathFinder
from render import TerminalRenderer, make_renderer
from simulation import Simulator, Turn


def parse_args() -> Namespace:
    parser = ArgumentParser(
        prog="fly-in",
        description=(
            "Route a fleet of drones from the start hub to the end hub."
        ),
    )
    parser.add_argument(
        "map",
        type=Path,
        nargs="?",
        default=None,
        help="path to the map file (omit to pick one interactively)",
    )
    parser.add_argument(
        "--no-visual",
        action="store_true",
        help="print turns only, skip the visual representation",
    )
    parser.add_argument(
        "--renderer",
        choices=("pygame", "terminal"),
        default="pygame",
        help=(
            "visual backend (falls back to terminal if pygame is unavailable)"
        ),
    )
    # parser.add_argument(
    #     "--capacity-info",
    #     action="store_true"
    # )
    return parser.parse_args()


def print_log(turns: list[Turn]) -> None:
    for turn in turns:
        print(turn.render_line())
        # for zone, used in turn.zone_occ.items():
        #     cap = fly_map.zones[zone].max_drones
        #     print(f"Zone {zone}: {used}/{cap} drones")
        # for label, used in turn.link_load.items():
        #     a, b = label.split("-")
        #     cap = 1
        #     for conn in fly_map.connections:
        #         if {conn.a, conn.b} == {a, b}:
        #             cap = c.max_link_capacity
        #     print(f"Connection {label}: {used}/{cap} used")
    print(f"\n{len(turns)} turns", file=sys.stderr)


def main() -> int:
    args = parse_args()
    renderer = None if args.no_visual else make_renderer(args.renderer)

    if args.map is None:
        maps = discover_maps()
        if not maps:
            print(f"error: no maps found under {MAPS_ROOT}", file=sys.stderr)
            return 1
        picker = renderer if renderer is not None else TerminalRenderer()
        chosen = picker.pick_map(maps)
        if chosen is None:
            print("cancelled", file=sys.stderr)
            return 0
        args.map = chosen

    try:
        fly_map = MapParser().parse_file(args.map)
    except (ParserError, MapError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    graph = Graph(fly_map)
    finder = PathFinder(fly_map, graph)
    paths = finder.find_paths()
    assignments = finder.distribute(paths, fly_map.nb_drones)

    turns = Simulator(fly_map, assignments).run()

    print_log(turns)

    if renderer is not None:
        renderer.play(fly_map, turns)
        # TerminalRenderer clears the screen on exit -- reprint so the
        # log is still the last thing visible instead of a blank screen
        print_log(turns)

    return 0


if __name__ == "__main__":
    sys.exit(main())
