"""A crew route along roads, for the same stops the straight tour already visits.

The Overture extract stored in this repository has no one-way attribute, so every
segment is driven in both directions. Roads are split where they cross. A short
fragment that does not meet the main network is left out: the stop walks to the
nearest road of the longest connected component.
"""
import heapq
import math
from collections import defaultdict

from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import substring, unary_union

# A vehicle can use these. Footways, steps and cycleways stay out: a crew does not drive them.
# Service roads are left out too. In this extract they are yards and aisles, and routing through
# them made the same stops a longer drive than staying on the public road and walking the last metres.
DRIVABLE = frozenset({
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
    "residential", "living_street", "track",
})


def node_key(x, y):
    """Join endpoints that fall in the same metre. Coordinates are metres."""
    return (math.floor(x + 0.5), math.floor(y + 0.5))


def _lines_of(geom):
    if geom.is_empty:
        return
    if isinstance(geom, LineString):
        yield geom
    elif isinstance(geom, MultiLineString):
        yield from geom.geoms
    else:
        for part in getattr(geom, "geoms", ()):
            yield from _lines_of(part)


def _slice(line, start, end):
    """The piece of a line between two distances, running from start toward end."""
    if abs(end - start) < 1e-6:
        return None
    if start < end:
        return substring(line, start, end)
    piece = substring(line, end, start)
    return LineString(list(piece.coords)[::-1])


def open_tour(distance):
    """Open tour that leaves stop 0 first: nearest neighbour, then 2-opt.

    The same two moves as the Rust route. The first stop stays put, and the free
    end may be reversed.
    """
    n = len(distance)
    if n == 0:
        return []
    order = [0]
    left = set(range(1, n))
    while left:
        last = order[-1]
        nxt = min(left, key=lambda j: distance[last][j])
        order.append(nxt)
        left.remove(nxt)
    improved = True
    while improved:
        improved = False
        for i in range(1, max(n - 1, 1)):
            for k in range(i + 1, n):
                a1, b1, c1 = order[i - 1], order[i], order[k]
                if k + 1 < n:
                    d1 = order[k + 1]
                    gain = distance[a1][b1] + distance[c1][d1] - distance[a1][c1] - distance[b1][d1]
                else:
                    gain = distance[a1][b1] - distance[a1][c1]
                if gain > 1e-6:
                    order[i:k + 1] = list(reversed(order[i:k + 1]))
                    improved = True
    return order


def _noded_pieces(lines):
    """Split roads at crossings and keep the connected component with the most length."""
    lines = [line for line in lines if line.length >= 0.4]
    if not lines:
        raise ValueError("no road lines")
    parent = {}

    def find(node):
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    pieces = []
    for line in _lines_of(unary_union(lines)):
        if line.length < 0.4:
            continue
        start, end = line.coords[0], line.coords[-1]
        a, b = node_key(*start), node_key(*end)
        if a == b:
            continue
        union(a, b)
        pieces.append((a, b, line.length, line))
    length = defaultdict(float)
    for a, _b, metres, _line in pieces:
        length[find(a)] += metres
    main = max(length, key=length.get)
    return [piece for piece in pieces if find(piece[0]) == main]


def route_stops(stops, lines):
    """Drive an open tour of `stops` along `lines`. Stop 0 is the depot and stays first.

    `access_m[i]` is the walk from stop i to the road. `driving_m` is the road
    distance between those points, without the walk. The drawn line reaches every
    stop: it leaves a stop along the same walk it arrived on.
    """
    stops = [Point(stop) for stop in stops]
    n = len(stops)
    if n == 0:
        raise ValueError("no stops")
    pieces = _noded_pieces(lines)
    nearest = []
    for stop in stops:
        best = None
        for index, (_a, _b, _length, line) in enumerate(pieces):
            gap = line.distance(stop)
            if best is None or gap < best[0]:
                best = (gap, index, line.project(stop))
        nearest.append(best)

    cuts = defaultdict(list)
    snap_point = [None] * n
    snap_node = [None] * n
    for index, (_gap, edge, proj) in enumerate(nearest):
        a, b, length, line = pieces[edge]
        proj = min(max(proj, 0.0), length)
        if proj <= 0.05:
            snap_node[index] = a
            snap_point[index] = Point(line.coords[0])
        elif length - proj <= 0.05:
            snap_node[index] = b
            snap_point[index] = Point(line.coords[-1])
        else:
            snap_node[index] = ("s", index)
            snap_point[index] = line.interpolate(proj)
            cuts[edge].append((proj, snap_node[index]))

    adj = defaultdict(list)

    def link(a, b, metres, line):
        if a == b or metres <= 1e-6 or line is None or line.length <= 1e-6:
            return
        adj[a].append((b, metres, line))
        adj[b].append((a, metres, LineString(list(line.coords)[::-1])))

    for edge, (a, b, length, line) in enumerate(pieces):
        marks = sorted(cuts.get(edge, []))
        nodes = [a]
        cursor = 0.0
        for proj, node in marks:
            nodes.append(node)
            link(nodes[-2], node, proj - cursor, _slice(line, cursor, proj))
            cursor = proj
        nodes.append(b)
        link(nodes[-2], b, length - cursor, _slice(line, cursor, length))

    def shortest(src):
        dist = {src: 0.0}
        prev = {}
        counter = 0
        heap = [(0.0, counter, src)]
        while heap:
            so_far, _tick, node = heapq.heappop(heap)
            if so_far != dist.get(node):
                continue
            for nxt, metres, line in adj[node]:
                cand = so_far + metres
                if cand < dist.get(nxt, math.inf):
                    dist[nxt] = cand
                    prev[nxt] = (node, line)
                    counter += 1
                    heapq.heappush(heap, (cand, counter, nxt))
        return dist, prev

    matrix = [[0.0] * n for _ in range(n)]
    coming = [None] * n
    for i, node in enumerate(snap_node):
        dist, prev = shortest(node)
        coming[i] = prev
        for j, other in enumerate(snap_node):
            if other not in dist:
                raise RuntimeError(f"stop {j} is not on the same road network as stop {i}")
            matrix[i][j] = dist[other]

    order = open_tour(matrix)
    driving = sum(matrix[order[i]][order[i + 1]] for i in range(n - 1))

    def hops(src_i, dst_i):
        src, dst = snap_node[src_i], snap_node[dst_i]
        if src == dst:
            return []
        lines_back = []
        node = dst
        prev = coming[src_i]
        while node != src:
            node, line = prev[node]
            lines_back.append(line)
        return list(reversed(lines_back))

    drawn = []

    def add(point):
        xy = (point[0], point[1]) if not hasattr(point, "x") else (point.x, point.y)
        if not drawn or math.hypot(drawn[-1][0] - xy[0], drawn[-1][1] - xy[1]) > 0.05:
            drawn.append(xy)

    for leg, (src_i, dst_i) in enumerate(zip(order, order[1:])):
        if leg == 0:
            add(stops[src_i])
        add(snap_point[src_i])
        for line in hops(src_i, dst_i):
            for coord in line.coords:
                add(coord)
        add(snap_point[dst_i])
        add(stops[dst_i])

    access = [stops[i].distance(snap_point[i]) for i in range(n)]
    return {
        "order": order,
        "driving_m": driving,
        "access_m": access,
        "line": LineString(drawn),
        "straight_m": sum(stops[i].distance(stops[i + 1]) for i in range(n - 1)),
    }
