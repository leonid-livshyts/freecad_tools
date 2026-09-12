# -*- coding: utf-8 -*-
"""Whole-screw assembly and document integration."""

from harness import Checks, max_radius, z_extent
import FreeCAD as App
import screw

c = Checks("screw")

# A non-countersunk screw: length is the shank, the head sits on top.
p = dict(screw.DEFAULTS)
p.update({"diameter": 8.0, "length": 16.0, "pitch": 1.25,
          "head": "pan", "drive": "none", "new_document": True})
part = screw.build_screw(p)
c.ok("returns an App::Part", part.TypeId == "App::Part", part.TypeId)
c.ok("holds one shape", len(part.Group) == 1, "got %d" % len(part.Group))
solid = part.Group[0].Shape
c.ok("one solid", len(solid.Solids) == 1, "got %d" % len(solid.Solids))
c.ok("valid", solid.isValid())
# Vertex extents throughout: the screw carries swept thread faces, so BoundBox
# reports the control-pole hull and overshoots by a pitch at each end.
low, high = z_extent(solid)
c.close("tip at the origin", low, 0.0, 1e-4)
c.close("head on top of the shank", high, screw.head_top_z("pan", 8.0, 16.0), 1e-4)
c.close("widest point is the head", max_radius(solid),
        screw.head_radius("pan", 8.0), 1e-4)
# Label must not end in a number: FreeCAD rewrites a trailing number to make
# duplicate labels unique, which would silently change a dimension.
c.ok("label does not end in a digit", not part.Label[-1].isdigit(), part.Label)
c.ok("label names the size", "8" in part.Label and "16" in part.Label, part.Label)

# A countersunk screw: length is overall, so the tip-to-head-top height IS the
# nominal length.
q = dict(p)
q.update({"head": "flat", "length": 16.0})
flat = screw.build_screw(q)
fs = flat.Group[0].Shape
flow, fhigh = z_extent(fs)
c.close("flat head screw is exactly the nominal length overall",
        fhigh - flow, 16.0, 1e-4)
c.ok("flat head screw is one valid solid", len(fs.Solids) == 1 and fs.isValid())
c.close("flat head is the widest point", max_radius(fs),
        screw.head_radius("flat", 8.0), 1e-4)

# The oval head's dome stands above the nominal length.
o = dict(p)
o.update({"head": "oval", "length": 16.0})
oval = screw.build_screw(o).Group[0].Shape
c.close("oval overall height includes the dome",
        z_extent(oval)[1], 16.0 + screw.HEAD_METRICS["oval"]["dome"] * 8.0, 1e-4)

# Head and shank must be one fused solid, not two touching lumps.
h = dict(p)
h.update({"head": "hex", "drive": "none"})
hexs = screw.build_screw(h).Group[0].Shape
c.ok("hex screw is one solid", len(hexs.Solids) == 1, "got %d" % len(hexs.Solids))

# A recess must survive the assembly.
r = dict(p)
r.update({"head": "pan", "drive": "hex_socket"})
socket = screw.build_screw(r).Group[0].Shape
c.ok("socketed screw is one valid solid",
     len(socket.Solids) == 1 and socket.isValid())
c.ok("socket removed material", socket.Volume < solid.Volume,
     "%.3f vs %.3f" % (socket.Volume, solid.Volume))

# Document handling, following bearing.py: new_document False reuses the active
# document instead of opening another one.
before = len(App.listDocuments())
reuse = dict(p)
reuse["new_document"] = False
reuse["length"] = 10.0
screw.build_screw(reuse)
c.ok("new_document False reuses the active document",
     len(App.listDocuments()) == before,
     "%d documents before, %d after" % (before, len(App.listDocuments())))

# Invalid parameters must raise before any geometry is attempted.
bad = dict(p)
bad["pitch"] = 9.0
try:
    screw.build_screw(bad)
    c.ok("invalid parameters raise", False, "no exception")
except ValueError as exc:
    c.ok("invalid parameters raise", True)
    c.ok("the message explains why", "pitch" in str(exc).lower(), str(exc))

c.report()
