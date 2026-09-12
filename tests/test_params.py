# -*- coding: utf-8 -*-
"""Metrics table, derived dimensions and validation."""

from harness import Checks
import screw

c = Checks("params")

# Every head type offered in the dialog must have metrics, and vice versa.
head_keys = [k for k, _ in screw.HEAD_TYPES]
c.ok("seven head types", len(head_keys) == 7, "got %d" % len(head_keys))
c.ok("head keys match metrics", sorted(head_keys) == sorted(screw.HEAD_METRICS.keys()),
     "%s vs %s" % (sorted(head_keys), sorted(screw.HEAD_METRICS.keys())))
for name in ("flat", "oval", "pan", "round", "mushroom", "truss", "hex"):
    c.ok("head %s present" % name, name in screw.HEAD_METRICS)

drive_keys = [k for k, _ in screw.DRIVE_TYPES]
c.ok("four drive types", sorted(drive_keys) == ["hex_socket", "none", "phillips", "slot"],
     str(sorted(drive_keys)))
c.ok("drive metrics cover the cutting drives",
     sorted(screw.DRIVE_METRICS.keys()) == ["hex_socket", "phillips", "slot"],
     str(sorted(screw.DRIVE_METRICS.keys())))

# DEFAULTS must be a valid, complete parameter set.
for key in ("diameter", "length", "pitch", "head", "drive", "new_document"):
    c.ok("DEFAULTS has %s" % key, key in screw.DEFAULTS)
c.ok("DEFAULTS validate clean", screw.validate(screw.DEFAULTS) == ([], []),
     str(screw.validate(screw.DEFAULTS)))
c.ok("FIELDS only names numeric keys",
     [k for k, _, _ in screw.FIELDS] == ["diameter", "length", "pitch"],
     str([k for k, _, _ in screw.FIELDS]))

# ISO metric thread maths.
c.close("thread depth of 1.25 pitch", screw.thread_depth(1.25), 0.766750)
c.close("M8x1.25 minor radius", screw.minor_radius(8.0, 1.25), 3.233250)

# Head metrics at d = 8.
c.close("pan head height", screw.head_height("pan", 8.0), 4.8)
c.close("pan head radius", screw.head_radius("pan", 8.0), 7.2)
c.close("flat head height", screw.head_height("flat", 8.0), 4.0)
c.close("flat head radius", screw.head_radius("flat", 8.0), 8.0)
c.close("truss head radius", screw.head_radius("truss", 8.0), 9.6)
c.close("hex across flats", screw.head_across_flats(8.0), 12.8)
c.close("hex head radius is across corners", screw.head_radius("hex", 8.0), 7.390083, 1e-5)

# A 90 degree countersink is self-consistent only if height == (D - d) / 2.
c.close("flat head is a 90 degree cone",
        screw.head_height("flat", 8.0), (2 * screw.head_radius("flat", 8.0) - 8.0) / 2.0)

# Length convention: countersunk heads eat into the length, the others sit on top.
c.ok("flat is countersunk", screw.is_countersunk("flat"))
c.ok("oval is countersunk", screw.is_countersunk("oval"))
for name in ("pan", "round", "mushroom", "truss", "hex"):
    c.ok("%s is not countersunk" % name, not screw.is_countersunk(name))

c.close("flat shank is length minus head", screw.shank_length("flat", 8.0, 30.0), 26.0)
c.close("flat overall height is the length", screw.head_top_z("flat", 8.0, 30.0), 30.0)
c.close("oval shank is length minus cone", screw.shank_length("oval", 8.0, 30.0), 26.0)
c.close("oval dome sits above the length", screw.head_top_z("oval", 8.0, 30.0), 32.0)
c.close("pan shank is the length", screw.shank_length("pan", 8.0, 30.0), 30.0)
c.close("pan head sits on top", screw.head_top_z("pan", 8.0, 30.0), 34.8)

# Turn count must agree with the ring count the shank builder will loop over.
c.ok("turns match ring count",
     screw.thread_turns("pan", 8.0, 30.0, 1.25) == screw.ring_count(30.0, 1.25))
c.close("M8x1.25 x 30 turns", screw.thread_turns("pan", 8.0, 30.0, 1.25), 26)
c.close("countersunk turns use the shorter shank",
        screw.thread_turns("flat", 8.0, 30.0, 1.25), 22)
c.between("time estimate is in the right ballpark",
          screw.estimated_seconds("pan", 8.0, 30.0, 1.25), 3.0, 12.0)

# Errors: unbuildable geometry.
def errors_for(**kw):
    p = dict(screw.DEFAULTS)
    p.update(kw)
    return screw.validate(p)[0]

def warnings_for(**kw):
    p = dict(screw.DEFAULTS)
    p.update(kw)
    return screw.validate(p)[1]

c.ok("zero diameter is an error", errors_for(diameter=0.0))
c.ok("negative length is an error", errors_for(length=-5.0))
c.ok("zero pitch is an error", errors_for(pitch=0.0))
c.ok("unknown head is an error", errors_for(head="wingnut"))
c.ok("unknown drive is an error", errors_for(drive="torx"))
# 0.6134 * 7 = 4.29 > 4.0, so the thread would eat the whole core of an M8.
c.ok("pitch coarser than the core is an error", errors_for(pitch=7.0))
# A flat head on an M8 is 4 mm tall, so an overall length of 3 mm leaves no shank.
c.ok("countersunk head taller than the length is an error",
     errors_for(head="flat", length=3.0))
c.ok("a sane screw has no errors", errors_for() == [])

# Warnings: builds, but the user should know.
c.ok("a very long fine thread warns about time",
     any("turn" in w for w in warnings_for(diameter=6.0, length=200.0, pitch=0.5)),
     str(warnings_for(diameter=6.0, length=200.0, pitch=0.5)))
c.ok("hex head with a recess warns",
     any("hex" in w.lower() for w in warnings_for(head="hex", drive="slot")),
     str(warnings_for(head="hex", drive="slot")))
c.ok("a nearly hollowed core warns",
     any("core" in w.lower() or "weak" in w.lower() for w in warnings_for(pitch=3.5)),
     str(warnings_for(pitch=3.5)))
c.ok("a shank shorter than two turns warns",
     any("short" in w.lower() for w in warnings_for(length=2.0, pitch=1.25)),
     str(warnings_for(length=2.0, pitch=1.25)))

c.report()
