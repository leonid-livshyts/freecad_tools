# -*- coding: utf-8 -*-
"""All seven head shapes."""

import math

from harness import Checks, max_radius, z_extent
import screw

c = Checks("heads")

d = 8.0
z0 = 5.0        # deliberately not zero, to catch a builder that ignores z0

for kind, label in screw.HEAD_TYPES:
    head = screw.build_head(kind, d, z0)
    height = screw.head_height(kind, d)
    dome = screw.HEAD_METRICS[kind]["dome"] * d
    low, high = z_extent(head)

    c.ok("%s one solid" % kind, len(head.Solids) == 1, "got %d" % len(head.Solids))
    c.ok("%s valid" % kind, head.isValid())
    c.close("%s sits on z0" % kind, low, z0, 1e-4)
    c.close("%s top" % kind, high, z0 + height + dome, 1e-4)
    c.close("%s outer radius" % kind, max_radius(head), screw.head_radius(kind, d), 1e-4)
    c.ok("%s has volume" % kind, head.Volume > 0, "got %g" % head.Volume)

# A countersunk head must taper to the shank, so its bottom face is the shank
# diameter, not the head diameter.
flat = screw.build_head("flat", d, z0)
bottom = [math.hypot(v.Point.x, v.Point.y) for v in flat.Vertexes
          if abs(v.Point.z - z0) < 1e-6]
c.close("flat head meets the shank at d/2", max(bottom), d / 2.0, 1e-6)

# A hex head is a prism: across flats is the wrench size, across corners is wider.
hexh = screw.build_head("hex", d, z0)
c.close("hex across corners", max_radius(hexh),
        screw.head_across_flats(d) / math.sqrt(3.0), 1e-6)
c.ok("hex has 8 faces (6 flats plus 2 ends)", len(hexh.Faces) == 8,
     "got %d" % len(hexh.Faces))

# Wide shallow heads must really be wider and shallower than the tall ones.
c.ok("truss is the widest", screw.head_radius("truss", d) >
     max(screw.head_radius(k, d) for k, _ in screw.HEAD_TYPES if k != "truss"))
c.ok("truss is the shortest", screw.head_height("truss", d) <
     min(screw.head_height(k, d) for k, _ in screw.HEAD_TYPES if k != "truss"))

# The oval head is a flat head plus a crown, so it is taller overall but its
# cone is the same.
c.close("oval cone matches the flat cone",
        screw.head_height("oval", d), screw.head_height("flat", d))
oval = screw.build_head("oval", d, z0)
c.ok("oval is taller than flat overall", z_extent(oval)[1] > z_extent(flat)[1])
c.ok("oval volume exceeds flat volume", oval.Volume > flat.Volume)

# The spherical cap helper is the load-bearing primitive: a cap of base radius a
# and height h must meet its base plane at exactly a.
cap = screw._spherical_cap(5.0, 2.0, 3.0)
c.close("cap base radius", max_radius(cap), 5.0, 1e-6)
c.close("cap height", z_extent(cap)[1] - z_extent(cap)[0], 2.0, 1e-6)
c.ok("cap is one valid solid", len(cap.Solids) == 1 and cap.isValid())

# An unknown head must fail loudly rather than return something odd.
try:
    screw.build_head("wingnut", d, z0)
    c.ok("unknown head raises", False, "no exception")
except ValueError:
    c.ok("unknown head raises", True)

c.report()
