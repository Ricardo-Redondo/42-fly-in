from models import FlyMap
import heapq


def build_adjacency(fly_map: FlyMap) -> dict[str, list[str]]:
    adjacency: dict[str, list[str]] = {name: [] for name in fly_map.zones}

    for link in fly_map.connections:
        adjacency[link.a].append(link.b)
        adjacency[link.b].append(link.a)
    return adjacency



def cost_to_end(fly_map: FlyMap) -> dict[str, int]:
    cost_list: dict[str, int] = {fly_map.end: 0}
    heap: list[tuple[str, int]] = [(fly_map.end, 0)]
    adjacency: dict[str, list[str]] = build_adjacency(fly_map)

    while heap:
        dist, v = heapq.heappop(heap)
        for u in adjacency[v]:
            
