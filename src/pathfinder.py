from dataclasses import dataclass, field
from graph import Graph
from models import FlyMap, ZoneType


@dataclass
class Path:
    """
    One route from start to end, plus how much traffic it can take.

    Attributes:
        zones: ordered zone names; zones[0] is the start hub,
            zones[-1] the end hub.
        cost: turns for a single drone to walk it alone (sum of entry
            costs of zones[1:]).
        capacity: drones admitted per turn -- the bottleneck slot count
            found while augmenting, halved at any restricted zone on the
            route (its slot ties up for 2 turns per occupant, so it can
            only admit a newcomer every other turn).
    """

    zones: list[str]
    cost: int
    capacity: float = 1.0

    @property
    def hops(self) -> int:
        return len(self.zones) - 1


@dataclass
class Assignment:
    """Which drones ride one path."""

    path: Path
    drone_ids: list[int] = field(default_factory=list)


class PathFinder:
    def __init__(self, fly_map: FlyMap, graph: Graph) -> None:
        self.fly_map = fly_map
        self.graph = graph

    def find_paths(self) -> list[Path]:
        """
        Pull cheapest start->end paths with spare capacity until none remain.
        """
        residual_zone: dict[str, float] = {
            name: zone.max_drones for name, zone in self.fly_map.zones.items()
        }

        residual_link: dict[frozenset[str], float] = {
            frozenset((c.a, c.b)): c.max_link_capacity
            for c in self.fly_map.connections
        }
        paths: list[Path] = []

        while True:
            path = self.graph.shortest_path(
                self.fly_map.start,
                self.fly_map.end,
                usable_zone=lambda z: residual_zone[z] > 0,
                usable_link=lambda a, b: residual_link[frozenset((a, b))] > 0
            )
            if path is None:
                break

            zones, cost = path
            interior = zones[1:-1]
            links = list(zip(zones, zones[1:]))

            # per-turn throughput this route can sustain: a restricted
            # zone's slot is held for 2 turns per occupant, so it only
            # admits a newcomer every other turn -- half the raw count
            throughput_bottleneck = min(
                [
                    residual_zone[z] / 2
                    if self.fly_map.zones[z].zone_type is ZoneType.RESTRICTED
                    else residual_zone[z]
                    for z in interior
                ]
                + [residual_link[frozenset((a, b))] for a, b in links]
            )

            # A restricted zone is a genuine chokepoint: once any path
            # claims it, fully close it (residual -> 0) so a later search
            # is forced onto a *different* restricted chain rather than
            # fractionally re-sharing this exact one (that would require
            # re-halving an already-halved residual, which double-counts).
            # Everything else only loses the throughput THIS path actually
            # uses, so shared prefixes/suffixes keep spare room for a
            # second path to reuse them.
            for z in interior:
                if self.fly_map.zones[z].zone_type is ZoneType.RESTRICTED:
                    residual_zone[z] = 0
                else:
                    residual_zone[z] -= throughput_bottleneck
            for a, b in links:
                residual_link[frozenset((a, b))] -= throughput_bottleneck

            paths.append(Path(zones, cost, throughput_bottleneck))

        return paths

    def distribute(
        self, paths: list[Path], nb_drones: int
    ) -> list[Assignment]:
        """
        Gives each drone the path on which it finishes earliest.

        The k-th (0-indexed) drone to take a path of cost L and
        capacity c lands on turn L + k // c (drones stream in
        c at a time, one wave per turn).

        TODO:
          * assignments = [Assignment(p) for p in paths]
          * for drone_id in range(1, nb_drones + 1):
                choose the assignment minimising
                    a.path.cost + len(a.drone_ids) // a.path.capacity
                and append drone_id to it
          * return only the assignments that received at least one drone
          * if paths is empty, raise -- the map should have been
            rejected earlier
        """
        if not paths:
            raise ValueError("no paths to distribute drones over")

        assignments = [Assignment(p) for p in paths]
        for drone_id in range(1, nb_drones + 1):
            best = min(
                assignments,
                key=lambda a: a.path.cost + len(a.drone_ids) // a.path.capacity
            )
            best.drone_ids.append(drone_id)

        return [a for a in assignments if len(a.drone_ids) > 0]
