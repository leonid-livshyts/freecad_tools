# -*- coding: utf-8 -*-
"""Parametric nut generator with a parameter dialog.

Builds a nut with a real modelled ISO metric internal thread in four body
styles. Run it as a FreeCAD macro (Macro -> Macros... -> Execute) and a dialog
appears. Without the GUI (FreeCADCmd) the module still works:

    import nut
    nut.build_nut(nut.DEFAULTS)

The nut is built base down at the origin: the body runs up the +Z axis from
z=0. Thread rings are anchored at exact multiples of the pitch, so a nut and a
screw.py screw of the same diameter and pitch are in phase and mate without
any hand alignment.

This file deliberately restates the thread formulas rather than importing
screw.py: each tool here is a single-file macro you copy into your FreeCAD
macro directory, and the internal form is a different thread anyway.
"""

__Title__ = "Nut"
__Author__ = "leonid"
__Version__ = "1.0.0"
__Comment__ = "Parametric nut with a modelled internal thread in four body styles"

# needed for inserting primitives and for the sweep that builds the thread
import Part
# needed for the thread helix maths
import math
import FreeCAD as App
from FreeCAD import Base


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

DEFAULTS = {
    "diameter": 8.0,        # nominal thread diameter, the "M" size
    "pitch": 1.25,          # crest to crest along the axis
    "kind": "hex",
    "new_document": True,
}

# Order and labels used to build the dialog.
FIELDS = [
    ("diameter", "Nut diameter",
     "Nominal diameter of the thread, the 'M' size - the screw this nut takes"),
    ("pitch", "Thread pitch", "Distance from one thread crest to the next"),
]

NUT_TYPES = [
    ("hex", "Hex nut"),
    ("wing", "Wing nut"),
    ("lock", "Lock nut (nylon insert)"),
    ("lug", "Lug nut (closed end, cone seat)"),
]

# ISO 68-1 metric thread, internal form. It is the complement of the external
# form screw.py builds. Of the fundamental triangle of height H = 0.866 * pitch,
# the nut keeps 5H/8 of depth: H/4 is truncated at the minor diameter, leaving a
# crest land of pitch/4, and H/8 at the major diameter, leaving a root flat of
# pitch/8. Those three add up across one pitch exactly:
#     pitch/4 + 2 * h * tan(30) + pitch/8 == pitch
# The nut's crest land is twice the screw's, which is why an internal thread
# looks blunter than an external one. That is correct, not a bug.
THREAD_HALF_ANGLE = 30.0
FUNDAMENTAL_HEIGHT_FACTOR = 0.866025      # H, the untruncated 60 degree triangle
# ISO publishes these as 0.5413 and 1.0825, but those are two independent
# roundings of the same quantity and they disagree in the fifth decimal. Derive
# both from H instead, so the thread form and the bore can never drift apart.
INTERNAL_DEPTH_FACTOR = 5.0 * FUNDAMENTAL_HEIGHT_FACTOR / 8.0   # 5H/8, the depth
MINOR_FACTOR = 2.0 * INTERNAL_DEPTH_FACTOR                      # D1 = d - this * P
CREST_FLAT_FACTOR = 1.0 / 4.0             # of the pitch, at the minor diameter
ROOT_FLAT_FACTOR = 1.0 / 8.0              # of the pitch, at the major diameter

# Radial clearance added to every cut surface, in mm, so a nut turns onto a
# screw instead of sharing surfaces with it. The realised gap is HALF this,
# because the flanks sit 30 degrees off radial and a radial offset only moves
# them by its own sine: 0.2 here measures 0.1 mm between a nut and a screw.py
# screw. Offset radially and nothing else - fudging the flank width to chase a
# uniform gap was measured and is neither predictable nor worth the distortion
# it puts into the crest and root flats.
CLEARANCE = 0.2

# How far the thread ridge is buried in the tool's core, as a fraction of the
# pitch. A ridge that only touches the core is tangent to it and the fuse fails.
# Only the ridge moves: the core cylinder stays at the crest radius, or the
# finished bore comes out undersized with no crest land at all.
SINK_FACTOR = 0.02

# Explicit fuzzy tolerance for the thread booleans, in mm. Same reasoning as
# screw.py: the ISO form leaves only pitch/8 between adjacent features and at
# that spacing OCC's default tolerance intermittently collapses the result.
BOOLEAN_FUZZ = 1e-5

# 45 degree lead-in at the mouth of the bore, as a multiple of the thread depth,
# so the first thread is not a knife edge and a screw starts squarely.
ENTRY_CHAMFER_FACTOR = 1.0

# Hex corners are cut back to this fraction of the across-flats size on the
# bearing faces, at 30 degrees - the chamfer every real hex nut carries.
CHAMFER_CIRCLE = 0.95

# Body proportions, as multiples of the nominal diameter. These are rounded
# ISO/DIN ratios rather than table lookups, so any diameter gives a plausible
# nut: an M8 hex nut comes out 12.8 mm across flats and 6.4 mm tall against
# ISO 4032's 13.0 x 6.8.
#   across_flats  wrench size; for the wing nut, the round body diameter
#   body          height of the main body, measured from z=0
#   thread        height of threaded bore; less than body where the top is shut
#   crown         lock nut only: insert collar above the body
#   dome          lug nut only: closed spherical cap above the body
#   seat          lug nut only: height of the 60 degree conical seat
NUT_METRICS = {
    "hex":  {"across_flats": 1.60, "body": 0.80, "thread": 0.80,
             "crown": 0.0, "dome": 0.0, "seat": 0.0},
    "wing": {"across_flats": 1.40, "body": 0.90, "thread": 0.90,
             "crown": 0.0, "dome": 0.0, "seat": 0.0},
    "lock": {"across_flats": 1.60, "body": 0.90, "thread": 0.65,
             "crown": 0.30, "dome": 0.0, "seat": 0.0},
    "lug":  {"across_flats": 1.60, "body": 1.00, "thread": 0.85,
             "crown": 0.0, "dome": 0.45, "seat": 0.647},
}

# Wing proportions, as multiples of the nominal diameter. Each wing is a plate
# in the XZ plane, rounded off at the outer top by intersecting it with a
# cylinder lying along Y - one boolean, and no edge picking to go stale.
WING_SPAN = 1.60          # how far a wing reaches from the axis
WING_THICKNESS = 0.25
WING_HEIGHT = 1.45
WING_ROUND_RADIUS = 1.30
WING_ROUND_X = 0.35       # centre of the rounding cylinder
WING_ROUND_Z = 0.35

# The nylon collar of a lock nut is bored under the thread's minor diameter, so
# a screw cuts its own path through it. As a fraction of the pitch.
COLLAR_BITE = 0.15

# The ISO coarse pitch for a given diameter, near enough to spot a pitch that
# was never going to fit anything.
COARSE_PITCH_FACTOR = 0.15

# Each thread turn is a separate sweep and boolean. Nuts are short - an M8 hex
# nut is about 7 turns and under a second - but a fine pitch on a tall lug nut
# still adds up. Measured on FreeCAD 1.1.3, as in screw.py.
SECONDS_PER_TURN = 0.25


# ---------------------------------------------------------------------------
# Derived dimensions
# ---------------------------------------------------------------------------

def thread_depth(pitch):
    """Radial depth of the internal thread, 5H/8."""
    return INTERNAL_DEPTH_FACTOR * pitch


def minor_radius(diameter, pitch):
    """Radius of the nut's thread crest, D1/2 - the narrowest part of the bore."""
    return diameter / 2.0 - thread_depth(pitch)


def crest_truncation(pitch):
    """Radial height cut off the tool's apex: H/8.

    The sweep builds a sharp V whose apex overshoots the nut's root radius by
    this much, and the tool is then trimmed back to it. Truncating with a
    cylinder rather than sweeping an already-flat trapezoid is not cosmetic:
    a trapezoid profile makes consecutive one-turn sweeps meet on coincident
    quadrilateral end faces, and fusing those returns an invalid solid.
    """
    return FUNDAMENTAL_HEIGHT_FACTOR * pitch / 8.0


def crest_flat(pitch):
    """Axial width of the land at the nut's minor diameter."""
    return CREST_FLAT_FACTOR * pitch


def root_flat(pitch):
    """Axial width of the flat at the nut's major diameter."""
    return ROOT_FLAT_FACTOR * pitch


def across_flats(kind, diameter):
    """Wrench size, or for a wing nut the round body diameter."""
    return NUT_METRICS[kind]["across_flats"] * diameter


def corner_radius(kind, diameter):
    """Across-corners radius of a hex body."""
    return across_flats(kind, diameter) / math.sqrt(3.0)


def body_height(kind, diameter):
    return NUT_METRICS[kind]["body"] * diameter


def thread_height(kind, diameter):
    """Height of threaded bore, measured from z=0."""
    return NUT_METRICS[kind]["thread"] * diameter


def overall_height(kind, diameter):
    """Z of the highest point of the finished nut."""
    metrics = NUT_METRICS[kind]
    top = body_height(kind, diameter) + (metrics["crown"] + metrics["dome"]) * diameter
    if kind == "wing":
        # The wings stand proud of the body; they are the tallest thing on it.
        return max(top, WING_HEIGHT * diameter)
    return top


def wall_thickness(kind, diameter):
    """Thinnest metal between the thread's root and the outside of the body.

    Measured to the flats, which are nearer the axis than the corners.
    """
    return across_flats(kind, diameter) / 2.0 - (diameter / 2.0 + CLEARANCE)


def collar_radius(diameter, pitch):
    """Bore of a lock nut's nylon collar, deliberately under the thread crest."""
    return minor_radius(diameter, pitch) - COLLAR_BITE * pitch


def ring_count(z0, z1, pitch):
    """How many one-turn sweeps cover the span z0..z1.

    Rings are anchored at exact multiples of the pitch so that every nut and
    every screw share one thread phase, with a spare turn beyond each end so
    the helix runs off past the trim.
    """
    return int(math.ceil(z1 / pitch)) - int(math.floor(z0 / pitch)) + 3


def thread_turns(kind, diameter, pitch):
    return ring_count(0.0, thread_height(kind, diameter), pitch)


def estimated_seconds(kind, diameter, pitch):
    return SECONDS_PER_TURN * thread_turns(kind, diameter, pitch)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(p):
    """Check a parameter set.

    Returns (errors, warnings). Errors describe geometry that cannot be built at
    all; warnings describe geometry that builds but is not a sensible nut.
    Catching these here gives a readable message instead of an OCC exception.
    """
    errors = []
    warnings = []

    kind = p["kind"]
    if kind not in NUT_METRICS:
        errors.append("Unknown nut type %r." % kind)

    d, pitch = p["diameter"], p["pitch"]
    if d <= 0:
        errors.append("Nut diameter must be greater than 0.")
    if pitch <= 0:
        errors.append("Thread pitch must be greater than 0.")

    if errors:
        # Everything below divides by these or indexes the metrics table.
        return errors, warnings

    rmin = minor_radius(d, pitch)
    if rmin <= 0:
        errors.append("Thread pitch %g mm is too coarse for an M%g nut: a thread "
                      "%.3f mm deep would swallow the whole %.3f mm bore radius. "
                      "Keep the pitch below %.3f mm."
                      % (pitch, d, thread_depth(pitch), d / 2.0,
                         d / 2.0 / INTERNAL_DEPTH_FACTOR))

    wall = wall_thickness(kind, d)
    if wall <= 0:
        errors.append("An M%g thread breaks out through the flats of a %s only "
                      "%.3f mm across. The body needs to be wider than %.3f mm."
                      % (d, dict(NUT_TYPES)[kind], across_flats(kind, d),
                         d + 2 * CLEARANCE))

    if errors:
        return errors, warnings

    # Buildable, but worth a word.
    if wall < 0.15 * d:
        warnings.append("Only %.3f mm of metal is left between the thread and the "
                        "flats of this %s, so it will split under a wrench."
                        % (wall, dict(NUT_TYPES)[kind]))
    if rmin < 0.25 * d:
        warnings.append("The thread leaves a bore only %.3f mm across on an M%g nut, "
                        "so it is mostly thread. A pitch near %.2f mm suits this "
                        "diameter." % (2 * rmin, d, 0.15 * d))

    coarse = COARSE_PITCH_FACTOR * d
    if pitch > 2.0 * coarse or pitch < 0.4 * coarse:
        warnings.append("A %g mm pitch is unusual on an M%g: the standard coarse "
                        "pitch for this diameter is near %.2f mm. A nut only fits a "
                        "screw of the same pitch." % (pitch, d, coarse))

    threaded = thread_height(kind, d)
    if threaded < 2 * pitch:
        warnings.append("The threaded part of this %s is %.3f mm, too short for two "
                        "full turns of a %g mm pitch thread."
                        % (dict(NUT_TYPES)[kind], threaded, pitch))

    if kind == "lock" and collar_radius(d, pitch) <= 0:
        warnings.append("A %g mm pitch leaves the nylon collar no bore at all on an "
                        "M%g lock nut." % (pitch, d))

    return errors, warnings


# ---------------------------------------------------------------------------
# Geometry: the thread
# ---------------------------------------------------------------------------

def build_thread_tool(diameter, pitch, z0, z1):
    """The solid a mating screw occupies between z0 and z1, to be cut away.

    Building the negative and subtracting it once is what works. Sweeping a
    single multi-turn groove and cutting that does not: OCC reports the face
    valid and then quietly drops most of it from the boolean. Three things here
    are deliberate and load bearing:

    One sweep per turn, all joined in a single multiFuse - the same reason.

    The core cylinder sits at the crest radius and only the ridge is buried
    SINK_FACTOR * pitch below it. A ridge merely tangent to the core fails to
    fuse; a core sunk along with it comes out as an undersized bore with no
    crest land.

    The half-width is measured at the radius the profile is drawn at. Measuring
    it at the un-sunk radius instead tilts the flanks to 29.26 degrees, which
    every validity, volume and radius check in the suite still passes.
    """
    r_root = diameter / 2.0 + CLEARANCE
    base = minor_radius(diameter, pitch) + CLEARANCE
    apex = r_root + crest_truncation(pitch)
    core = base - SINK_FACTOR * pitch
    half = (apex - core) * math.tan(math.radians(THREAD_HALF_ANGLE))

    # Anchor the rings on multiples of the pitch, never on z0: that is what
    # keeps every nut and every screw in one thread phase.
    first = int(math.floor(z0 / pitch)) - 1
    last = int(math.ceil(z1 / pitch)) + 1

    rings = []
    for k in range(first, last + 1):
        z = k * pitch
        helix = Part.makeHelix(pitch, pitch, core)
        helix.translate(Base.Vector(0, 0, z))
        # The 60 degree V, apex outwards past the nut's root radius. Frenet mode
        # and the contact/correction flags all get this wrong; the plain
        # makePipeShell(profiles, solid, frenet) form is what works.
        profile = Part.Wire(Part.makePolygon([
            Base.Vector(core, 0, z + half),
            Base.Vector(core, 0, z - half),
            Base.Vector(apex, 0, z),
            Base.Vector(core, 0, z + half),
        ]))
        rings.append(Part.Wire(helix.Edges).makePipeShell([profile], True, True))

    low = first * pitch
    tool = Part.makeCylinder(base, (last + 1) * pitch - low,
                             Base.Vector(0, 0, low)).multiFuse(rings, BOOLEAN_FUZZ)
    # One trim does two jobs: the helix overruns both ends, and the swept apex
    # overshoots the root radius. Cutting to a cylinder of exactly r_root over
    # exactly z0..z1 gives a flat-ended tool whose apexes are pitch/8 flats.
    tool = tool.common(Part.makeCylinder(r_root, z1 - z0, Base.Vector(0, 0, z0)))

    tool = tool.removeSplitter()
    if tool.ShapeType == "Compound" and len(tool.Solids) == 1:
        tool = tool.Solids[0]
    return tool


def entry_chamfer(diameter, pitch, z, opening_down):
    """Cone to subtract at a bore mouth, so the first thread is not a knife edge.

    opening_down is True for the mouth in the bottom face, where the bore has to
    flare downwards; False for the mouth in a top face.
    """
    depth = ENTRY_CHAMFER_FACTOR * thread_depth(pitch)
    r = diameter / 2.0 + CLEARANCE
    if opening_down:
        return Part.makeCone(r + depth, r, depth, Base.Vector(0, 0, z))
    return Part.makeCone(r, r + depth, depth, Base.Vector(0, 0, z - depth))


# ---------------------------------------------------------------------------
# Geometry: bodies
# ---------------------------------------------------------------------------

def _hex_prism(width, height, z0=0.0):
    """Hexagonal prism of the given across-flats size, sitting on z0."""
    r = width / math.sqrt(3.0)
    points = [Base.Vector(r * math.cos(math.radians(60 * i)),
                          r * math.sin(math.radians(60 * i)), z0)
              for i in range(6)]
    face = Part.Face(Part.Wire(Part.makePolygon(points + [points[0]])))
    return face.extrude(Base.Vector(0, 0, height))


def _face_chamfer(width, z, from_below):
    """Ring to subtract that cuts the hex corners back on a bearing face.

    Every real hex nut has one: a 30 degree chamfer taking the corners back to
    CHAMFER_CIRCLE of the across-flats size, so the nut has no fragile points
    and seats flat. Built as cylinder-minus-cone, the same way screw.py builds
    its tip chamfer, because cutting a ring is far cheaper than picking edges.

    from_below is True for the bottom face, where the chamfer opens downwards.
    """
    r_corner = width / math.sqrt(3.0)
    r_flat = CHAMFER_CIRCLE * width / 2.0
    height = (r_corner - r_flat) * math.tan(math.radians(30.0))
    if from_below:
        z0 = z
        cone = Part.makeCone(r_flat, r_corner, height, Base.Vector(0, 0, z0))
    else:
        z0 = z - height
        cone = Part.makeCone(r_corner, r_flat, height, Base.Vector(0, 0, z0))
    return Part.makeCylinder(r_corner + 1.0, height,
                             Base.Vector(0, 0, z0)).cut(cone)


def _spherical_cap(base_radius, height, z0):
    """Spherical cap of the given base radius and height, sitting on z0.

    A sphere of radius R = (a^2 + h^2) / 2h meets the plane z0 at exactly the
    base radius, so the cap springs from its seat with no ledge and no fillet.
    """
    r_sphere = (base_radius * base_radius + height * height) / (2.0 * height)
    sphere = Part.makeSphere(r_sphere, Base.Vector(0, 0, z0 + height - r_sphere))
    return sphere.common(Part.makeCylinder(base_radius, height,
                                           Base.Vector(0, 0, z0)))


def _unwrap(shape):
    """multiFuse, common and cut all hand back a single-solid Compound."""
    shape = shape.removeSplitter()
    if shape.ShapeType == "Compound" and len(shape.Solids) == 1:
        return shape.Solids[0]
    return shape


def build_body(kind, diameter):
    """The nut's outside shape, before the thread is cut. Base at z=0."""
    width = across_flats(kind, diameter)
    height = body_height(kind, diameter)

    if kind == "hex":
        body = _hex_prism(width, height)
        body = body.cut(_face_chamfer(width, 0.0, True))
        body = body.cut(_face_chamfer(width, height, False))
        return _unwrap(body)

    raise ValueError("Unknown nut type %r." % kind)
