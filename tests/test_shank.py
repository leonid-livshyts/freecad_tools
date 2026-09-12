# -*- coding: utf-8 -*-
"""Threaded shank geometry."""

import math

from harness import Checks, max_radius, min_radius, z_extent
import Part
import screw

c = Checks("shank")

d, length, pitch = 8.0, 20.0, 1.25
shank = screw.build_shank(d, length, pitch)
r = d / 2.0
rmin = screw.minor_radius(d, pitch)
chamfer = screw.TIP_CHAMFER_FACTOR * screw.thread_depth(pitch)

c.ok("is a solid", shank.ShapeType == "Solid", shank.ShapeType)
c.ok("one solid", len(shank.Solids) == 1, "got %d" % len(shank.Solids))
c.ok("valid", shank.isValid())
# Vertex extents, never BoundBox: the bound box of a shape carrying swept
# thread faces is the control-pole hull and overshoots by a pitch at each end.
c.close("crests reach the major radius", max_radius(shank), r, 1e-4)
low, high = z_extent(shank)
c.close("flat top at the length", high, length, 1e-4)
c.close("tip at the origin", low, 0.0, 1e-4)
# The flat ends are real planar faces, not just trimmed-looking.
end_faces = [f for f in shank.Faces if "Plane" in str(f.Surface)
             and (abs(f.CenterOfMass.z) < 1e-4 or abs(f.CenterOfMass.z - length) < 1e-4)]
c.ok("both ends are planar faces", len(end_faces) == 2, "got %d" % len(end_faces))

# A threaded shank weighs less than a plain rod of the major diameter and more
# than a bare core, and sits nearer the middle than either end.
plain = math.pi * r * r * length
core = math.pi * rmin * rmin * length
c.between("volume between core and plain rod", shank.Volume, core * 1.05, plain * 0.95)

# The thread must actually be cut: a plain cylinder would have exactly 3 faces.
c.ok("thread produced many faces", len(shank.Faces) > 20, "got %d" % len(shank.Faces))

# The tip chamfer pulls the free end in to r - chamfer.
tip = [math.hypot(v.Point.x, v.Point.y) for v in shank.Vertexes if v.Point.z < 1e-6]
c.ok("tip has vertices", len(tip) > 0)
if tip:
    c.close("tip chamfered to r - chamfer", max(tip), r - chamfer, 1e-3)

# The core is never breached.
c.ok("nothing inside the core", min_radius(shank) >= rmin - 0.02 * pitch - 1e-6,
     "min radius %.4f vs core %.4f" % (min_radius(shank), rmin))

# A different size must work too, including a coarse pitch on a big screw.
big = screw.build_shank(20.0, 30.0, 2.5)
c.ok("M20x2.5 one solid", len(big.Solids) == 1)
c.ok("M20x2.5 valid", big.isValid())
c.close("M20x2.5 major radius", max_radius(big), 10.0, 1e-4)
c.close("M20x2.5 length", z_extent(big)[1], 30.0, 1e-4)

# A short fine-pitch shank is the awkward case: few turns, thin ridge.
small = screw.build_shank(3.0, 6.0, 0.5)
c.ok("M3x0.5 one solid", len(small.Solids) == 1)
c.ok("M3x0.5 valid", small.isValid())
c.close("M3x0.5 major radius", max_radius(small), 1.5, 1e-4)
c.close("M3x0.5 length", z_extent(small)[1], 6.0, 1e-4)

c.report()
