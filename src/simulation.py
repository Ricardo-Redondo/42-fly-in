from dataclasses import dataclass, field
from models import FlyMap, Connection, ZoneType
from pathfinder import Assignment


@dataclass
class Move:
    """One drone changing position during a turn."""

    drone_id: int
    # destination zone, or "from-to" while crossing toward a restricted zone
    label: str

    def render(self) -> str:
        return f"D{self.drone_id}-{self.label}"


@dataclass
class Turn:
    """Everything that happened on a single simulation turn."""

    index: int
    moves: list[Move] = field(default_factory=list)
    # zone name -> slots used at end of turn
    zone_occ: dict[str, int] = field(default_factory=dict)
    # "a-b" -> slots used during this turn
    link_load: dict[str, int] = field(default_factory=dict)

    def render_line(self) -> str:
        """Space-separated moves for this turn ('' if nobody moved)."""
        return " ".join(m.render() for m in self.moves)


class Drone:
    """
    Mutable state for one drone as the simulation advances.
    """

    def __init__(self, drone_id: int, path_zones: list[str]) -> None:
        self.id: int = drone_id
        self.zones: list[str] = path_zones
        self.pos: int = 0
        self.in_transit: bool = False

    @property
    def current_zone(self) -> str:
        return self.zones[self.pos]

    @property
    def next_zone(self) -> str | None:
        if self.pos + 1 < len(self.zones):
            return self.zones[self.pos + 1]
        return None

    @property
    def at_end(self) -> bool:
        return self.pos == len(self.zones) - 1

    @property
    def dist_to_end(self) -> int:
        return len(self.zones) - 1 - self.pos

    @property
    def transit_label(self) -> str:
        return f"{self.zones[self.pos]}-{self.zones[self.pos - 1]}"


class Simulator:
    def __init__(
        self, fly_map: FlyMap, assignments: list[Assignment]
    ) -> None:
        self.fly_map = fly_map
        self.assignments = assignments
        self._conn: dict[frozenset[str], Connection] = {
            frozenset((c.a, c.b)): c for c in fly_map.connections
        }

    def run(self) -> list[Turn]:
        drones: list[Drone] = [
            Drone(d_id, a.path.zones)
            for a in self.assignments
            for d_id in a.drone_ids
        ]
        turns: list[Turn] = []
        turn_index = 1
        start_hub, end_hub = self.fly_map.start, self.fly_map.end

        while not all(d.at_end for d in drones):
            turn = Turn(index=turn_index)

            # occ[zone] = drones that "belong" to it this turn.
            # normal drone -> its current_zone;
            # mid-crossing drone -> the restricted zone it will land in.
            occ: dict[str, int] = {}
            for d in drones:
                if d.at_end:
                    continue
                if d.in_transit:
                    target = d.next_zone
                    assert target is not None
                    occ[target] = occ.get(target, 0) + 1
                    continue
                z = d.current_zone
                if z not in (start_hub, end_hub):
                    occ[z] = occ.get(z, 0) + 1

            link_used: dict[frozenset[str], int] = {}
            # tie-break on drone id: without it, ties on dist_to_end fall
            # back to list order, which groups every drone by *assignment*
            # (all of path A, then all of path B) -- so path A would
            # always win a shared bottleneck's one admission per turn and
            # path B would starve until path A fully drained. Breaking
            # ties by id interleaves them the way distribute() intended.
            movers = sorted(
                (d for d in drones if not d.at_end),
                key=lambda d: (d.dist_to_end, d.id),
            )

            for drone in movers:
                # CASE 1: already crossing -> must land now
                if drone.in_transit:
                    r = drone.next_zone
                    assert r is not None
                    drone.pos += 1
                    drone.in_transit = False
                    turn.moves.append(Move(drone.id, r))
                    continue

                cur = drone.current_zone
                nxt = drone.next_zone
                if nxt is None:
                    continue  # unreachable (not at_end); keeps mypy happy

                key = frozenset((cur, nxt))
                conn = self._conn[key]
                if link_used.get(key, 0) + 1 > conn.max_link_capacity:
                    continue  # link full this turn -> wait

                dest = self.fly_map.zones[nxt]
                if nxt != end_hub and occ.get(nxt, 0) + 1 > dest.max_drones:
                    continue  # destination zone full -> wait

                # commit: leave cur, claim nxt, use the link
                link_used[key] = link_used.get(key, 0) + 1
                if cur not in (start_hub, end_hub):
                    occ[cur] -= 1
                if nxt != end_hub:
                    occ[nxt] = occ.get(nxt, 0) + 1

                if dest.zone_type is ZoneType.RESTRICTED:
                    # CASE 2: start the 2-turn crossing; land next turn
                    drone.in_transit = True
                    turn.moves.append(Move(drone.id, f"{cur}-{nxt}"))
                else:
                    # CASE 3: ordinary one-turn hop
                    drone.pos += 1
                    turn.moves.append(Move(drone.id, nxt))

            if not turn.moves and not all(d.at_end for d in drones):
                raise RuntimeError(
                    f"stuck on turn {turn_index}: no drone could move"
                )

            turn.zone_occ = {z: n for z, n in occ.items() if n > 0}
            for pair, n in link_used.items():
                a, b = sorted(pair)
                turn.link_load[f"{a}-{b}"] = n

            turns.append(turn)
            turn_index += 1

        return turns
