from models import FlyMap, Zone, ZoneType, Connection
from pathlib import Path
from typing import Any
from pydantic import ValidationError


class ParserError(Exception):
    def __init__(self, line_no: int, msg: str) -> None:
        self.line_no = line_no
        self.msg = msg
        super().__init__(f"line {line_no}: {msg}")


class MapError(Exception):
    """Whole-map problem with no single line to blame."""


def _has_route(
    zones: dict[str, Zone],
    connections: list[Connection],
    start: str,
    end: str,
) -> bool:
    """Whether `end` is reachable from `start` without crossing a blocked zone."""
    adjacency: dict[str, list[str]] = {name: [] for name in zones}
    for link in connections:
        adjacency[link.a].append(link.b)
        adjacency[link.b].append(link.a)

    seen = {start}
    stack = [start]
    while stack:
        current = stack.pop()
        if current == end:
            return True
        for neighbour in adjacency[current]:
            if neighbour not in seen and zones[neighbour].is_passable:
                seen.add(neighbour)
                stack.append(neighbour)
    return False


class MapParser:
    def parse_file(self, path: Path) -> FlyMap:
        with open(path, encoding="utf-8") as f:
            return self.parse_text(f.read())

    def parse_text(self, text: str) -> FlyMap:
        nb_drones: int | None = None
        zones: dict[str, Zone] = {}
        connections: list[Connection] = []
        seen_links: set[frozenset[str]] = set()
        start: str | None = None
        end: str | None = None

        for line_no, raw in enumerate(text.splitlines(), start=1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue

            prefix, _, rest = line.partition(":")
            prefix = prefix.strip()
            rest = rest.strip()

            if nb_drones is None and prefix != "nb_drones":
                raise ParserError(line_no, "file must begin with "
                                  "'nb_drones: <n>'")

            if prefix == "nb_drones":
                if nb_drones is not None:
                    raise ParserError(line_no, "file cannot contain "
                                      "2 'nb_drones'")
                try:
                    nb_drones = int(rest)
                    if nb_drones <= 0:
                        raise ValueError
                except ValueError:
                    raise ParserError(line_no, "nb_drones must be a "
                                      f"positive integer, got {rest!r}")
            elif prefix in ("hub", "start_hub", "end_hub"):
                if "[" in rest:
                    rest, _, metadata = rest.partition("[")
                    rest = rest.strip()
                    metadata = metadata.strip()
                    if not metadata.endswith("]"):
                        raise ParserError(line_no, "metadata needs to be "
                                          "enclosed in []")
                    metadata = metadata[:-1].strip()
                else:
                    metadata = ""

                parts = rest.split()
                if len(parts) != 3:
                    raise ParserError(line_no, "hub needs name, "
                                      "x and y coords")
                name, part_x, part_y = parts
                try:
                    x = int(part_x)
                    y = int(part_y)
                except ValueError:
                    raise ParserError(line_no, "x and/or y needs to be "
                                      "an integer")

                if "-" in name:
                    raise ParserError(line_no, "hub name cannot have '-'")
                if name in zones:
                    raise ParserError(line_no, "map cannot have 2 "
                                      f"{name} hubs")

                if prefix == "start_hub":
                    if start is not None:
                        raise ParserError(line_no, "map cannot have 2 "
                                          "start hubs")
                    start = name
                elif prefix == "end_hub":
                    if end is not None:
                        raise ParserError(line_no, "map cannot have 2 "
                                          "end hubs")
                    end = name

                parsed_tags: dict[str, Any] = {}
                if metadata:
                    tags: dict[str, str] = {}
                    for pair in metadata.split():
                        key, sep, value = pair.partition("=")
                        if not sep:
                            raise ParserError(line_no,
                                              f"metadata tag {pair!r} "
                                              "must be key=value")
                        tags[key] = value

                    for i, v in tags.items():
                        if i not in ("zone", "color", "max_drones"):
                            raise ParserError(line_no, f"metadata tag {i!r} "
                                              "is invalid")
                        if i == "max_drones":
                            try:
                                max_drones = int(v)
                                if max_drones <= 0:
                                    raise ValueError
                                parsed_tags["max_drones"] = max_drones
                            except ValueError:
                                raise ParserError(line_no,
                                                  "max_drones must be a "
                                                  "positive integer")
                        elif i == "color":
                            parsed_tags["color"] = v

                        elif i == "zone":
                            try:
                                zone_type = ZoneType(v)
                                parsed_tags["zone_type"] = zone_type
                            except ValueError:
                                raise ParserError(line_no, "unknown zone "
                                                  f"type {v!r}")
                try:
                    zones[name] = Zone(name=name, x=x, y=y, **parsed_tags)
                except ValidationError as e:
                    raise ParserError(line_no, str(e))

            elif prefix == "connection":
                if "[" in rest:
                    rest, _, metadata = rest.partition("[")
                    rest = rest.strip()
                    metadata = metadata.strip()
                    if not metadata.endswith("]"):
                        raise ParserError(line_no, "metadata needs to be "
                                          "enclosed in []")
                    metadata = metadata[:-1].strip()
                else:
                    metadata = ""

                zone1, sep, zone2 = rest.partition("-")
                zone1 = zone1.strip()
                zone2 = zone2.strip()

                if not sep:
                    raise ParserError(line_no,
                                      "connection must be 'zone1-zone2'")

                if zone1 not in zones.keys() or zone2 not in zones.keys():
                    raise ParserError(line_no,
                                      "cannot connect non existing zones")

                if zone1 == zone2:
                    raise ParserError(line_no,
                                      f"zone {zone1!r} cannot connect "
                                      "to itself")

                link = frozenset((zone1, zone2))
                if link in seen_links:
                    raise ParserError(line_no,
                                      f"connection '{zone1}-{zone2}' "
                                      "already exists")
                seen_links.add(link)

                max_link_capacity = 1
                if metadata:
                    key, sep, value = metadata.partition("=")
                    if not sep:
                        raise ParserError(line_no,
                                          f"metadata tag {metadata!r} "
                                          "must be key=value")

                    if key != "max_link_capacity":
                        raise ParserError(line_no, f"metadata tag {key!r} "
                                          "is invalid")

                    try:
                        max_link_capacity = int(value)
                        if max_link_capacity <= 0:
                            raise ValueError
                    except ValueError:
                        raise ParserError(line_no,
                                          "max_link_capacity must be a "
                                          "positive integer")

                connection = Connection(
                    a=zone1,
                    b=zone2,
                    max_link_capacity=max_link_capacity,
                )

                connections.append(connection)

            else:
                raise ParserError(line_no, f"unknown prefix {prefix!r}")

        if nb_drones is None:
            raise MapError("map has no 'nb_drones'")
        if start is None:
            raise MapError("map has no start_hub")
        if end is None:
            raise MapError("map has no end_hub")

        if not _has_route(zones, connections, start, end):
            raise MapError(f"no route from {start!r} to {end!r}")

        return FlyMap(
            nb_drones=nb_drones,
            zones=zones,
            connections=connections,
            start=start,
            end=end,
        )
