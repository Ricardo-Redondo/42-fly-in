from collections.abc import Callable
from models import Connection, FlyMap, ZoneType
from heapq import heappop, heappush


class Graph:
    """Undirected graph built from class FlyMap.

    - neighbors never yields a blocked zone, so no search can
      route a drone through one.
    - shortest_path is a Dijkstra whose step weight is the entry
      cost of the zone being moved into (1 for normal/priority, 2 for
      restricted), ties broken in favour of priority zones.
    """

    def __init__(self, fly_map: FlyMap) -> None:
        self.fly_map: FlyMap = fly_map
        self._adjacency: dict[str, list[str]] = {}
        self._link_of: dict[frozenset[str], Connection] = {}
        self._build()

    def _build(self) -> None:
        """Fill _adjacency and _link_of from the map."""
        zones = self.fly_map.zones

        for name in zones:
            self._adjacency[name] = []

        for conn in self.fly_map.connections:
            self._link_of[frozenset((conn.a, conn.b))] = conn

            if zones[conn.a].zone_type is ZoneType.BLOCKED:
                continue
            if zones[conn.b].zone_type is ZoneType.BLOCKED:
                continue

            self._adjacency[conn.a].append(conn.b)
            self._adjacency[conn.b].append(conn.a)

    def neighbors(self, zone: str) -> list[str]:
        """Passable zones directly reachable from zone."""
        return self._adjacency[zone]

    def link(self, a: str, b: str) -> Connection:
        """The Connection joining a and b (order-independent)."""
        return self._link_of[frozenset((a, b))]

    def entry_cost(self, zone: str) -> int:
        """Turns to move into zone (2 for restricted, else 1)."""
        return self.fly_map.zones[zone].entry_cost

    @staticmethod
    def _always_zone(zone: str) -> bool:
        return True

    @staticmethod
    def _always_link(a: str, b: str) -> bool:
        return True

    def shortest_path(
        self,
        start: str,
        end: str,
        *,
        usable_zone: Callable[[str], bool] | None = None,
        usable_link: Callable[[str, str], bool] | None = None,
    ) -> tuple[list[str], int] | None:
        """Least-cost route start -> end, or None if unreachable.

        Args:
            usable_zone: optional predicate; when it returns False for
                a zone other than start/end then that zone is skipped
                for this search. PathFinder passes a residual-capacity
                check here.
            usable_link: same idea for a connection, keyed by its two
                endpoint names.

        Returns:
            (zones, cost) with zones[0] == start,
            zones[-1] == end and cost the summed entry cost of
            every step after start -- or None.
        """
        dist: dict[str, int] = {start: 0}
        came_from: dict[str, str] = {}
        heap: list[tuple[int, int, str]] = [(0, 0, start)]
        visited: set[str] = set()

        usable_zone = usable_zone or self._always_zone
        usable_link = usable_link or self._always_link

        while len(heap) > 0:
            cost, _, zone = heappop(heap)
            if zone == end:
                break
            if zone in visited:
                continue
            visited.add(zone)

            for nb in self.neighbors(zone):
                if nb in visited:
                    continue
                if nb not in (start, end) and not usable_zone(nb):
                    continue
                if not usable_link(zone, nb):
                    continue

                new_cost = cost + self.entry_cost(nb)
                if nb not in dist or new_cost < dist[nb]:
                    dist[nb] = new_cost
                    came_from[nb] = zone
                    is_priority = (
                        self.fly_map.zones[nb].zone_type is ZoneType.PRIORITY
                    )
                    tie = 0 if is_priority else 1
                    heappush(heap, (new_cost, tie, nb))

        if end not in came_from:
            return None

        path = [end]
        while path[-1] != start:
            path.append(came_from[path[-1]])
        path.reverse()
        return path, dist[end]
