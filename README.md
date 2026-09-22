*This project has been created as part of the 42 curriculum by rsao-pay.*

# Fly-in

## Description

Fly-in routes a fleet of drones from a start hub to an end hub across a
network of zones and connections, under capacity constraints, and shows
the result turn by turn.

Given a text file describing a graph of zones (normal, restricted,
priority or blocked) linked by connections, each with its own capacity,
the program:

1. parses the map and validates it,
2. builds a graph and computes one or more routes from the start hub to
   the end hub,
3. distributes every drone across those routes to minimise the total
   number of simulation turns,
4. simulates the run turn by turn, enforcing zone and connection
   capacity at every step,
5. shows the result as a coloured turn log, and optionally as an
   interactive terminal or pygame visualisation.

The project is fully object-oriented, statically typed (passes
`mypy --strict`), and its graph/pathfinding/simulation logic is entirely
hand-written -- no graph library (`networkx`, `graphlib`, ...) is used
anywhere.

## Instructions

**Requirements:** Python 3.10+. The Makefile installs
[`uv`](https://docs.astral.sh/uv/) automatically if it isn't already on
your machine.

```sh
make install       # install dependencies
make run           # run interactively -- pick a map, pygame view
make trun          # run interactively -- pick a map, terminal view
make nvrun         # run interactively -- pick a map, no visual, only log
make lint          # flake8 + mypy (project-required flags)
make lint-strict   # flake8 + mypy --strict
make test          # pytest
make clean         # remove caches
```

You can also run it directly:

```sh
uv run python3 src [map_file] [--renderer pygame|terminal] [--no-visual]
```

- `map_file` -- optional. Omit it to get an interactive picker: a
  folder-then-map menu in the pygame backend, or a numbered list in the
  terminal backend.
- `--renderer {pygame,terminal}` -- which visual backend to use
  (default `pygame`; falls back to `terminal` automatically if pygame
  can't start, e.g. no display available).
- `--no-visual` -- print the turn log only, skip any visual entirely.

The turn log (see *Example* below) always prints to stdout regardless
of which renderer is used, since it's the format the subject requires.

**Controls**

| Backend | Keys |
|---|---|
| pygame picker | `UP`/`DOWN` move, `ENTER` open a folder / select a map, `BACKSPACE`/`LEFT` go back a level, `ESC` quit |
| pygame playback | `LEFT`/`RIGHT` step a turn, `SPACE` toggle autoplay, `R` reset to turn 0, `WASD` / mouse wheel pan (maps wider than the window), `ESC`/`Q` quit |
| terminal playback | `LEFT`/`RIGHT` step a turn, `Q`/`ESC` quit (falls back to a one-shot dump of every turn if stdout isn't an interactive terminal) |

## Algorithm explanation

**Parsing** (`parser.py`) -- a hand-written line-by-line parser: no
regex/grammar library. It validates every rule in the subject (unique
start/end hub, no duplicate zones/connections, dash-free names, valid
zone types, positive capacities, a route must exist from start to end,
...) and reports the offending line number on error.

**Graph** (`graph.py`) -- a plain adjacency list built from the parsed
zones/connections (blocked zones are simply left out of it, so no
search can ever route through one), plus a hand-written Dijkstra
(`heapq`-based). Each step's weight is the *entry cost* of the zone
being moved into: 1 for normal/priority, 2 for restricted. Equal-cost
routes are tie-broken toward `priority` zones via a secondary sort key
in the heap tuple.

**Pathfinding** (`pathfinder.py`) -- `find_paths()` repeatedly pulls the
cheapest remaining start-to-end route on a *capacitated residual
graph*: every zone/connection starts with its full capacity, and each
found route consumes some of it, so the next search is forced onto a
different route once something is exhausted. Two things make this more
than a naive residual subtraction:

- **Restricted-zone throughput.** A restricted zone's slot is held for
  2 turns per occupant (the crossing turn plus the landing turn), so it
  can only admit a newcomer every *other* turn -- half the throughput
  its raw `max_drones` would suggest. `Path.capacity` reflects that
  halved rate, not the raw slot count, so drone distribution (below)
  doesn't overload a restricted-heavy route relative to a faster one.
- **Shared-prefix reuse.** A restricted zone is a genuine chokepoint --
  once any route claims it, it's closed for good, since sharing it
  fractionally would mean re-halving an already-halved number. Every
  *other* zone/connection on the route only loses the throughput that
  route actually uses, not its full capacity, so a second route sharing
  the same single-file entrance (common on maps with one narrow gate)
  can still be found using the entrance's remaining spare capacity.
  This is what lets the algorithm discover genuinely parallel routes
  (e.g. three parallel restricted-zone chains that reconverge later)
  instead of settling for one and brute-forcing every drone through it.

`distribute()` then greedily assigns each drone, one at a time, to
whichever found route currently gives *that* drone the earliest finish
time, using the pipelining formula: the k-th (0-indexed) drone to join
a route of cost `L` and capacity `c` lands on turn `L + k // c` (drones
stream down a route `c` at a time, one wave per turn).

**Simulation** (`simulation.py`) -- `Simulator.run()` advances every
drone turn by turn. Each turn, *active* drones are processed
closest-to-the-goal first (ties broken by drone id, so drones from
different routes sharing a bottleneck actually interleave the way
`distribute()` planned, instead of one route's whole batch starving the
other's) -- so a drone vacating a zone frees its slot for a drone
entering the same zone in the *same* turn, matching the subject's rule.
A restricted-zone crossing is modelled as a genuine two-turn commitment:
the destination's occupancy is reserved the moment the crossing starts,
not only once the drone lands, and the drone cannot idle on the
connection once committed.

**Complexity.** Each Dijkstra call is `O((V + E) log V)`; `find_paths`
calls it repeatedly, bounded by the number of zones/links (each call
strictly exhausts at least one of them, so the loop always terminates).
The simulation is `O(turns * drones)`, since every turn re-sorts and
considers every still-active drone.

## Visual representation

Both backends replay the *exact* same simulated turns
(`_replay()`/`_drone_points()`), so whichever one you look at is
guaranteed to match the printed turn log.

**Terminal** (`TerminalRenderer`) -- a 24-bit ANSI-coloured board, one
line per zone tinted by its `color=` metadata, showing
`name [occupied/capacity]`, the drone ids currently there, and a tag
for restricted/priority/blocked zones; drones mid-restricted-crossing
get their own `~ a-b: Dn` line. Step through turns with the arrow keys;
falls back to printing every turn once, without waiting for input, when
stdout isn't an interactive terminal (e.g. piped output).

**Pygame** (`PygameRenderer`) -- zones are placed at their actual
`(x, y)` map coordinates (scaled to the window and y-flipped, so "up"
in the map file reads as up on screen), tinted by `color=`, with
connections drawn as lines between them. Drones are drawn as a small
icon that *glides* smoothly between zones as turns advance (eased
interpolation over ~400ms, not an instant jump), including sitting
visibly on the connection line for the two turns of a restricted
crossing. The window sizes itself to the map's actual span (capped to
fit the screen); maps too wide for the monitor become scrollable
(`WASD` / mouse wheel), and the map-selection screen groups maps by
folder with the same auto-scrolling list so a folder with many maps
(e.g. `errors/`, 14 files) never overflows the window.

Together, these make it easy to see *why* a given simulation takes the
number of turns it does -- which zones are bottlenecks, which drones
are waiting, and which are mid-crossing -- rather than just reading a
flat list of moves.

## Example input and expected output

`maps/easy/01_linear_path.txt`:

```
# Easy Level 1: Simple linear path
nb_drones: 2

start_hub: start 0 0 [color=green]
hub: waypoint1 1 0 [color=blue]
hub: waypoint2 2 0 [color=blue]
end_hub: goal 3 0 [color=red]

connection: start-waypoint1
connection: waypoint1-waypoint2
connection: waypoint2-goal
```

Running `uv run python3 src maps/easy/01_linear_path.txt --no-visual`
prints:

```
D1-waypoint1
D1-waypoint2 D2-waypoint1
D1-goal D2-waypoint2
D2-goal

4 turns
```

Both drones share the single available path (capacity 1, so one at a
time): D1 enters first, D2 follows one turn behind it, and each is
delivered as soon as it reaches `goal`.

## Resources

- [Dijkstra's algorithm](https://en.wikipedia.org/wiki/Dijkstra%27s_algorithm)
  and the augmenting-path idea behind max-flow algorithms (the
  residual-capacity technique `find_paths` is a simplified version of)
- [Python `heapq` docs](https://docs.python.org/3/library/heapq.html) --
  the priority queue used by the hand-written Dijkstra
- [Python `dataclasses` docs](https://docs.python.org/3/library/dataclasses.html)
- [`termios`](https://docs.python.org/3/library/termios.html) /
  [`tty`](https://docs.python.org/3/library/tty.html) /
  [`select`](https://docs.python.org/3/library/select.html) -- raw
  single-keypress terminal input without blocking on Enter
- [Pydantic docs](https://docs.pydantic.dev/) -- used for the parsed
  data models (`models.py`)
- [pygame-ce docs](https://pyga.me/docs/) -- window, event loop,
  drawing, fonts
- [mypy docs](https://mypy.readthedocs.io/) for the `--strict` typing
  requirement

**Use of AI.**

an AI was used sparingly for the understanding of some concepts, and for the creation and improvement of docstrings, comments and README.
