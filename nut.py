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
# so the first thread is not a knife edge and a screw starts squarely. Where the
# face around the bore is narrower than that, the chamfer is clamped to this
# fraction of the metal actually available, so it can never eat the whole face.
ENTRY_CHAMFER_FACTOR = 1.0
ENTRY_CHAMFER_MARGIN = 0.5

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
             "crown": 0.0, "dome": 0.45, "seat": 0.45},
}

# Wing proportions, as multiples of the nominal diameter. Each wing is a plate
# in the XZ plane, rounded off at the outer top by intersecting it with a
# cylinder lying along Y - one boolean, and no edge picking to go stale.
WING_SPAN = 1.60          # how far a wing reaches from the axis
WING_THICKNESS = 0.25
WING_HEIGHT = 1.45
# 1.30 would clear the plate's outer bottom corner by 0.015 mm - a
# near-tangent boolean, and the one shape of cut OCC is worst at. 1.35 clears
# it by 0.4 mm and still takes the outer top corner off.
WING_ROUND_RADIUS = 1.35
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


def seat_radius(kind, diameter):
    """Radius where a lug nut's conical seat meets its bottom face.

    This is the whole of the metal around the bore down there, and it is narrow:
    a 60 degree seat pulls the body in fast.
    """
    return (corner_radius(kind, diameter)
            - NUT_METRICS[kind]["seat"] * diameter * math.tan(math.radians(30.0)))


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


def entry_chamfer(diameter, pitch, z, opening_down, limit=None):
    """Cone to subtract at a bore mouth, so the first thread is not a knife edge.

    opening_down is True for the mouth in the bottom face, where the bore has to
    flare downwards; False for the mouth in a top face.

    limit is the outer radius of the face being chamfered, for the case where
    that face is narrower than the chamfer wants to be. A lug nut's conical seat
    leaves a rim of only a fifth of a millimetre around the bore, and an
    unclamped chamfer ate the whole bottom face and bit into the cone behind it -
    the nut came out 0.3 mm short with no seat to sit on. Returns None when no
    chamfer fits at all.
    """
    depth = ENTRY_CHAMFER_FACTOR * thread_depth(pitch)
    r = diameter / 2.0 + CLEARANCE
    if limit is not None:
        depth = min(depth, max(0.0, (limit - r) * ENTRY_CHAMFER_MARGIN))
    if depth <= 0.0:
        return None
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


def _wing(diameter):
    """One wing: a plate in the XZ plane, rounded off at the outer top.

    The rounding is a single intersection with a cylinder lying along Y rather
    than a fillet on picked edges, so it cannot go stale when the plate changes.
    The plate starts at the axis so it overlaps the body by a solid volume and
    the fuse has something to bite on.
    """
    span = WING_SPAN * diameter
    half_t = WING_THICKNESS * diameter / 2.0
    height = WING_HEIGHT * diameter

    plate = Part.makeBox(span, 2 * half_t, height, Base.Vector(0, -half_t, 0))
    rounder = Part.makeCylinder(
        WING_ROUND_RADIUS * diameter, 4 * half_t,
        Base.Vector(WING_ROUND_X * diameter, -2 * half_t, WING_ROUND_Z * diameter),
        Base.Vector(0, 1, 0))
    return plate.common(rounder)


def build_body(kind, diameter):
    """The nut's outside shape, before the thread is cut. Base at z=0."""
    width = across_flats(kind, diameter)
    height = body_height(kind, diameter)

    if kind == "hex":
        body = _hex_prism(width, height)
        body = body.cut(_face_chamfer(width, 0.0, True))
        body = body.cut(_face_chamfer(width, height, False))
        return _unwrap(body)

    if kind == "wing":
        # A round body, not a hex one: a wing nut is turned by its wings.
        body = Part.makeCylinder(width / 2.0, height)
        wing = _wing(diameter)
        other = wing.copy()
        other.rotate(Base.Vector(0, 0, 0), Base.Vector(0, 0, 1), 180.0)
        return _unwrap(body.fuse(wing).fuse(other))

    if kind == "lock":
        # DIN 985: a hex body with a reduced-diameter crown on top holding the
        # nylon collar. Only the bottom face is chamfered; the crown occupies
        # the top. The crown radius is the hex's chamfer circle, so the two meet
        # on a shared edge with no ledge.
        crown_r = CHAMFER_CIRCLE * width / 2.0
        crown_h = NUT_METRICS[kind]["crown"] * diameter
        body = _hex_prism(width, height)
        body = body.cut(_face_chamfer(width, 0.0, True))
        crown = Part.makeCylinder(crown_r, crown_h, Base.Vector(0, 0, height))
        # Break the crown's top edge, so it is not a raw square corner.
        lip = ENTRY_CHAMFER_FACTOR * crown_h / 4.0
        crown = crown.cut(
            Part.makeCylinder(crown_r + 1.0, lip,
                              Base.Vector(0, 0, height + crown_h - lip)).cut(
                Part.makeCone(crown_r, crown_r - lip, lip,
                              Base.Vector(0, 0, height + crown_h - lip))))
        return _unwrap(body.fuse(crown))

    if kind == "lug":
        # A wheel nut: 60 degree conical seat at the bottom, hex flats above it,
        # closed dome on top. The seat is made by intersecting the prism with a
        # cone-plus-cylinder solid of revolution, which trims the hex corners
        # away over the seat's height and leaves them alone above it.
        r_corner = width / math.sqrt(3.0)
        seat_h = NUT_METRICS[kind]["seat"] * diameter
        # 60 degrees included means the radius grows by rise * tan(30).
        r_seat = seat_radius(kind, diameter)
        envelope = Part.makeCone(r_seat, r_corner, seat_h).fuse(
            Part.makeCylinder(r_corner, height - seat_h,
                              Base.Vector(0, 0, seat_h)))
        body = _hex_prism(width, height).common(envelope)
        # Chamfer the top face only: the bottom is the seat.
        body = body.cut(_face_chamfer(width, height, False))
        # The dome springs from the chamfer circle, so the two meet with no
        # ledge - the same trick the lock nut's crown uses.
        dome = _spherical_cap(CHAMFER_CIRCLE * width / 2.0,
                              NUT_METRICS[kind]["dome"] * diameter, height)
        return _unwrap(body.fuse(dome))

    raise ValueError("Unknown nut type %r." % kind)


# ---------------------------------------------------------------------------
# Geometry: the whole nut
# ---------------------------------------------------------------------------

def nut_label(p):
    """Human readable name for the finished nut.

    The trailing word matters: FreeCAD makes duplicate labels unique by
    rewriting a trailing number, so a label ending in the pitch would come back
    as "Nut M8x001" on the second nut in a document.
    """
    return "Nut M%gx%g, %s" % (p["diameter"], p["pitch"],
                              dict(NUT_TYPES)[p["kind"]].lower())


def build_nut(p, doc=None):
    """Build the nut and add it to a document.

    p is a dict shaped like DEFAULTS. If doc is None a document is created or
    the active one is reused, following p["new_document"].
    Returns the App::Part container holding the nut.
    """
    errors, _ = validate(p)
    if errors:
        raise ValueError("Invalid nut parameters:\n- " + "\n- ".join(errors))

    d, pitch, kind = p["diameter"], p["pitch"], p["kind"]
    threaded = thread_height(kind, d)
    through = threaded >= body_height(kind, d) - 1e-9

    solid = build_body(kind, d)

    # Run the tool past the bottom face so the thread is cut right through it,
    # and past the top of the BODY when the bore is open. Not past the overall
    # height: a wing nut's wings stand well above its body and cross the axis,
    # and threading to the overall height drills a channel up through them.
    # A blind bore stops dead at the thread height, which leaves the flat bottom
    # a real drilled hole has.
    z1 = body_height(kind, d) + pitch if through else threaded
    tool = build_thread_tool(d, pitch, -pitch, z1)
    solid = solid.cut(tool, BOOLEAN_FUZZ)

    # Nothing standing above the body may close over the bore: the space
    # between a wing nut's two wings is open on a real one. A no-op for every
    # other style, whose overall height is its body height or is blind anyway.
    open_above = overall_height(kind, d) - body_height(kind, d)
    if through and open_above > 0:
        solid = solid.cut(Part.makeCylinder(
            d / 2.0 + CLEARANCE, open_above + pitch,
            Base.Vector(0, 0, body_height(kind, d))))

    # A lock nut's nylon collar: an unthreaded bore under the thread's crest,
    # running from the top of the thread out through the crown, so a screw has
    # to cut its own way through it. This is what makes the nut lock.
    if kind == "lock":
        solid = solid.cut(Part.makeCylinder(
            collar_radius(d, pitch), overall_height(kind, d) - threaded + pitch,
            Base.Vector(0, 0, threaded)))

    # Break the mouth of the bore so the first thread is not a knife edge.
    # The bottom face of a lug nut is just the rim of its conical seat, so the
    # chamfer there has to be told how little metal it has to work with.
    limit = seat_radius(kind, d) if NUT_METRICS[kind]["seat"] else None
    mouth = entry_chamfer(d, pitch, 0.0, True, limit)
    if mouth is not None:
        solid = solid.cut(mouth)
    if through:
        mouth = entry_chamfer(d, pitch, body_height(kind, d), False)
        if mouth is not None:
            solid = solid.cut(mouth)

    solid = _unwrap(solid)

    if doc is None:
        if p.get("new_document", True) or App.ActiveDocument is None:
            doc = App.newDocument("Nut")
        else:
            doc = App.ActiveDocument
    App.setActiveDocument(doc.Name)

    obj = Part.show(solid, "Nut")

    # An App::Part carries its own origin and Placement, unlike a plain group,
    # so the finished nut can be moved and reused as one component.
    part = doc.addObject("App::Part", "Nut")
    part.Label = nut_label(p)
    part.addObject(obj)

    doc.recompute()
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewAxometric()
        Gui.SendMsgToActiveView("ViewFit")

    return part


# ---------------------------------------------------------------------------
# Preview text
# ---------------------------------------------------------------------------

def preview_lines(p):
    """Derived dimensions plus any problem with the current values.

    Kept out of the dialog class so it can be tested without a GUI.
    """
    errors, warnings = validate(p)
    d, pitch, kind = p["diameter"], p["pitch"], p["kind"]

    lines = ["Thread M%g x %g mm" % (d, pitch)]
    if not errors:
        label = dict(NUT_TYPES)[kind]
        lines.append("%s, %.3f mm across flats, %.3f mm tall"
                     % (label, across_flats(kind, d), overall_height(kind, d)))
        blind = thread_height(kind, d) < body_height(kind, d) - 1e-9
        lines.append("Bore %.3f mm at the thread crest, %s %.3f mm deep"
                     % (2 * (minor_radius(d, pitch) + CLEARANCE),
                        "blind thread" if blind else "threaded right through,",
                        thread_height(kind, d)))
        # The number people actually need when they print one of these.
        lines.append("Wall %.3f mm  -  %.2f mm clearance on the thread, so about "
                     "%.2f mm of play on a screw"
                     % (wall_thickness(kind, d), CLEARANCE, CLEARANCE / 2.0))
        lines.append("%d thread turns  -  about %.0f s to build"
                     % (thread_turns(kind, d, pitch),
                        estimated_seconds(kind, d, pitch)))
    for message in errors:
        lines.append("Error: " + message)
    for message in warnings:
        lines.append("Warning: " + message)
    return lines


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

if App.GuiUp:
    import FreeCADGui as Gui
    # FreeCAD ships a PySide shim (Ext/PySide) that forwards to the PySide
    # version this build uses (PySide6 on FreeCAD 1.x), so this import works
    # unchanged across FreeCAD versions.
    from PySide import QtCore, QtWidgets

    class NutDialog(QtWidgets.QDialog):
        """Parameter dialog for the nut."""

        def __init__(self, values=None, parent=None):
            if parent is None:
                parent = Gui.getMainWindow()
            super(NutDialog, self).__init__(parent)

            self.setWindowTitle("Nut")
            self.setModal(True)

            values = dict(values or DEFAULTS)
            self.spins = {}

            form = QtWidgets.QFormLayout()
            form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

            for key, label, tip in FIELDS:
                spin = QtWidgets.QDoubleSpinBox()
                spin.setDecimals(3)
                spin.setRange(0.0, 100000.0)
                spin.setSingleStep(0.5 if key == "pitch" else 1.0)
                spin.setSuffix(" mm")
                spin.setValue(float(values[key]))
                spin.setToolTip(tip)
                spin.valueChanged.connect(self.update_preview)
                self.spins[key] = spin
                form.addRow(label + ":", spin)

            self.kind = QtWidgets.QComboBox()
            for key, label in NUT_TYPES:
                self.kind.addItem(label, key)
            self.kind.setCurrentIndex(
                max(0, [k for k, _ in NUT_TYPES].index(values["kind"])))
            self.kind.setToolTip("Body style. Lock and lug nuts are closed at the "
                                 "top, so their thread is blind.")
            self.kind.currentIndexChanged.connect(self.update_preview)
            form.addRow("Nut type:", self.kind)

            self.new_doc = QtWidgets.QCheckBox("Create a new document")
            self.new_doc.setChecked(bool(values.get("new_document", True)))
            self.new_doc.setToolTip("Unchecked, the nut is added to the active document")
            form.addRow("", self.new_doc)

            # Derived values and problems, refreshed on every edit.
            self.preview = QtWidgets.QLabel()
            self.preview.setWordWrap(True)
            self.preview.setTextFormat(QtCore.Qt.PlainText)
            self.preview.setMinimumWidth(380)

            self.buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok
                | QtWidgets.QDialogButtonBox.Cancel
                | QtWidgets.QDialogButtonBox.RestoreDefaults
            )
            self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Create")
            self.buttons.accepted.connect(self.accept)
            self.buttons.rejected.connect(self.reject)
            self.buttons.button(QtWidgets.QDialogButtonBox.RestoreDefaults).clicked.connect(
                self.restore_defaults
            )

            layout = QtWidgets.QVBoxLayout(self)
            layout.addLayout(form)
            layout.addWidget(self.preview)
            layout.addWidget(self.buttons)

            self.update_preview()

        def parameters(self):
            """Read the widgets back into a parameter dict."""
            p = {key: spin.value() for key, spin in self.spins.items()}
            p["kind"] = self.kind.currentData()
            p["new_document"] = self.new_doc.isChecked()
            return p

        def restore_defaults(self):
            for key, spin in self.spins.items():
                spin.setValue(float(DEFAULTS[key]))
            self.kind.setCurrentIndex([k for k, _ in NUT_TYPES].index(DEFAULTS["kind"]))
            self.new_doc.setChecked(bool(DEFAULTS["new_document"]))
            self.update_preview()

        def update_preview(self):
            p = self.parameters()
            errors, _ = validate(p)
            self.preview.setText("\n".join(preview_lines(p)))
            self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(not errors)

        def accept(self):
            p = self.parameters()
            errors, warnings = validate(p)
            if errors:
                QtWidgets.QMessageBox.critical(
                    self, "Nut", "This nut cannot be built:\n\n- "
                    + "\n- ".join(errors))
                return
            if warnings:
                answer = QtWidgets.QMessageBox.warning(
                    self, "Nut",
                    "This builds, but:\n\n- " + "\n- ".join(warnings)
                    + "\n\nCreate it anyway?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No)
                if answer != QtWidgets.QMessageBox.Yes:
                    return
            super(NutDialog, self).accept()

    # Values carry over to the next run within the same FreeCAD session.
    _last_values = dict(DEFAULTS)

    def show_dialog():
        """Ask for the parameters and build the nut if the user confirms."""
        global _last_values
        dialog = NutDialog(_last_values)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None
        _last_values = dialog.parameters()
        App.Console.PrintMessage(
            "Nut: building %d thread turns, this may take about %.0f seconds\n"
            % (thread_turns(_last_values["kind"], _last_values["diameter"],
                            _last_values["pitch"]),
               estimated_seconds(_last_values["kind"], _last_values["diameter"],
                                 _last_values["pitch"])))
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            return build_nut(_last_values)
        except Exception as exc:  # OCC can still refuse a geometrically odd set
            App.Console.PrintError("Nut: %s\n" % exc)
            QtWidgets.QMessageBox.critical(
                Gui.getMainWindow(), "Nut",
                "FreeCAD could not build this nut:\n\n%s" % exc)
            return None
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()


# FreeCAD executes a macro with __name__ set to "__main__"; the extra names
# cover being pasted into the Python console.
if __name__ in ("__main__", "__builtin__", "builtins"):
    if App.GuiUp:
        show_dialog()
    else:
        build_nut(DEFAULTS)
