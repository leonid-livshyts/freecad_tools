# -*- coding: utf-8 -*-
"""Threaded shank geometry."""

import math

from harness import Checks, max_radius, min_radius, z_extent
import Part
from FreeCAD import Base
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


# ---------------------------------------------------------------------------
# Thread form, measured off an axial section.
#
# Everything above passes on a sharp-crested V too - volume, radii and validity
# cannot tell a knife edge from a proper crest land, which is exactly how the
# first version shipped with no crest flat at all. These are the checks that
# pin the ISO 68-1 form down.
# ---------------------------------------------------------------------------

def flats(zs, pitch):
    """Pair up consecutive section vertices that bound the same flat."""
    out, i = [], 0
    while i < len(zs) - 1:
        width = zs[i + 1] - zs[i]
        if width < pitch * 0.5:      # a flat, not the gap to the next thread
            out.append(width)
            i += 2
        else:
            i += 1
    return out


for (fd, fl, fp) in ((8.0, 8.0, 1.25), (6.0, 8.0, 1.0), (3.0, 6.0, 0.5)):
    form = screw.build_shank(fd, fl, fp)
    fr = fd / 2.0
    fh3 = screw.thread_depth(fp)
    frmin = fr - fh3
    tag = "M%g x %g" % (fd, fp)

    section = sorted(set((round(v.Point.z, 6), round(v.Point.x, 6))
                         for w in form.slice(Base.Vector(0, 1, 0), 0.0)
                         for v in w.Vertexes if v.Point.x > 0))
    c.ok("%s section is not empty" % tag, len(section) > 0)
    if not section:
        continue

    crest_z = sorted(z for z, x in section if abs(x - fr) < 1e-4)
    root_z = sorted(z for z, x in section if abs(x - frmin) < 1e-4)

    # A sharp crest gives one vertex per turn; a proper land gives a pair.
    c.ok("%s crest is a land, not a knife edge" % tag, len(crest_z) >= 4,
         "only %d vertices at the major radius" % len(crest_z))

    # Drop the first flat of each kind: at the chamfered tip the section starts
    # mid-thread, so that one is a partial.
    crest_lands = flats(crest_z, fp)[1:] or flats(crest_z, fp)
    root_flats = flats(root_z, fp)[1:] or flats(root_z, fp)
    c.ok("%s has crest lands to measure" % tag, len(crest_lands) > 0)
    c.ok("%s has root flats to measure" % tag, len(root_flats) > 0)
    for width in crest_lands[:4]:
        c.close("%s crest land is pitch/8" % tag, width, screw.crest_flat(fp), 2e-3)
    for width in root_flats[:4]:
        c.close("%s root flat is pitch/6" % tag, width, screw.root_flat(fp), 2e-3)

    # Flanks must be 30 degrees off radial, i.e. a 60 degree included angle.
    if len(crest_z) >= 2 and root_z:
        above = [z for z in root_z if z > crest_z[1]]
        if above:
            rise = above[0] - crest_z[1]
            c.close("%s flank is 30 degrees off radial" % tag,
                    math.degrees(math.atan2(rise, fh3)), 30.0, 0.2)

    # The three add up to the pitch, which is the ISO form's defining identity.
    if crest_lands and root_flats:
        span = (crest_lands[0] + root_flats[0]
                + 2 * fh3 * math.tan(math.radians(30.0)))
        c.close("%s crest + 2 flanks + root spans one pitch" % tag, span, fp, 3e-3)

c.report()
