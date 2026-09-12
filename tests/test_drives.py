# -*- coding: utf-8 -*-
"""Drive recess cutters."""

from harness import Checks, z_extent
import Part
import screw

c = Checks("drives")

d = 8.0
kind = "pan"
top_z = 12.0
height = screw.head_height(kind, d)

c.ok("none has no cutter", screw.build_drive("none", kind, d, top_z) is None)

for drive in ("slot", "phillips", "hex_socket"):
    cutter = screw.build_drive(drive, kind, d, top_z)
    depth = screw.DRIVE_METRICS[drive]["depth"] * height
    low, high = z_extent(cutter)

    c.ok("%s is a solid" % drive, len(cutter.Solids) == 1, "got %d" % len(cutter.Solids))
    c.ok("%s valid" % drive, cutter.isValid())
    c.ok("%s has volume" % drive, cutter.Volume > 0)
    # The cutter must break the surface, so it reaches above the head, and it
    # must stop at the intended depth.
    c.ok("%s reaches above the head" % drive, high > top_z,
         "top vertex %.3f vs head top %.3f" % (high, top_z))
    c.close("%s bottoms at the right depth" % drive, low, top_z - depth, 1e-4)

# Cutting a real head must remove material, leave one solid, and not sever it.
head = screw.build_head(kind, d, top_z - height)
for drive in ("slot", "phillips", "hex_socket"):
    cutter = screw.build_drive(drive, kind, d, top_z)
    cut = head.cut(cutter).removeSplitter()
    c.ok("%s removes material" % drive, cut.Volume < head.Volume,
         "%.3f vs %.3f" % (cut.Volume, head.Volume))
    c.ok("%s leaves one solid" % drive, len(cut.Solids) == 1,
         "got %d" % len(cut.Solids))
    c.ok("%s leaves a valid solid" % drive, cut.isValid())
    c.ok("%s does not hollow the head out" % drive, cut.Volume > 0.5 * head.Volume,
         "%.3f vs %.3f" % (cut.Volume, head.Volume))

# A slot crosses the whole head; a Phillips removes more than a single slot
# because it is two crossed slots.
slot_cut = head.cut(screw.build_drive("slot", kind, d, top_z))
phil_cut = head.cut(screw.build_drive("phillips", kind, d, top_z))
c.ok("phillips removes more than a slot", phil_cut.Volume < slot_cut.Volume,
     "%.3f vs %.3f" % (phil_cut.Volume, slot_cut.Volume))

# The slot must run right across the head, not stop inside it.
slot = screw.build_drive("slot", kind, d, top_z)
c.ok("slot spans the head", slot.BoundBox.XLength > 2 * screw.head_radius(kind, d),
     "%.3f vs %.3f" % (slot.BoundBox.XLength, 2 * screw.head_radius(kind, d)))

# A hex socket is a prism of the wrench size across the flats.
socket = screw.build_drive("hex_socket", kind, d, top_z)
c.ok("socket has 8 faces", len(socket.Faces) == 8, "got %d" % len(socket.Faces))

# A shallow head must still get a proportionally shallow recess, not a hole
# through it.
truss = screw.build_head("truss", d, 0.0)
truss_top = screw.head_height("truss", d)
for drive in ("slot", "phillips", "hex_socket"):
    cut = truss.cut(screw.build_drive(drive, "truss", d, truss_top)).removeSplitter()
    c.ok("truss survives %s" % drive, len(cut.Solids) == 1 and cut.isValid(),
         "solids %d" % len(cut.Solids))

try:
    screw.build_drive("torx", kind, d, top_z)
    c.ok("unknown drive raises", False, "no exception")
except ValueError:
    c.ok("unknown drive raises", True)

c.report()
