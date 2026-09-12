# -*- coding: utf-8 -*-
"""Parametric screw generator with a parameter dialog.

Builds a screw with a real modelled ISO metric thread, a choice of head shape
and an optional drive recess. Run it as a FreeCAD macro (Macro -> Macros... ->
Execute) and a dialog appears. Without the GUI (FreeCADCmd) the module still
works:

    import screw
    screw.build_screw(screw.DEFAULTS)

The screw is built tip down at the origin: the shank runs up the +Z axis from
z=0 and the head sits on top of it.
"""

__Title__ = "Screw"
__Author__ = "leonid"
__Version__ = "1.0.0"
__Comment__ = "Parametric screw with modelled thread, head shapes and drive recesses"

# needed for inserting primitives and for the sweep that cuts the thread
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
    "length": 30.0,         # see the length convention in HEAD_METRICS
    "pitch": 1.25,          # crest to crest along the axis
    "head": "pan",
    "drive": "none",
    "new_document": True,
}

# Order and labels used to build the dialog.
FIELDS = [
    ("diameter", "Screw diameter", "Nominal outside diameter of the thread, the 'M' size"),
    ("length", "Length",
     "Flat and oval heads: overall length including the head, because those heads "
     "sit inside the material. Every other head: the shank length under the head."),
    ("pitch", "Thread pitch", "Distance from one thread crest to the next"),
]

HEAD_TYPES = [
    ("flat", "Flat head (countersunk)"),
    ("oval", "Oval head (raised countersunk)"),
    ("pan", "Pan head"),
    ("round", "Round head"),
    ("mushroom", "Mushroom head"),
    ("truss", "Truss head"),
    ("hex", "Hex head"),
]

DRIVE_TYPES = [
    ("none", "No recess"),
    ("slot", "Slot"),
    ("phillips", "Phillips cross"),
    ("hex_socket", "Hex socket"),
]

# Head proportions, as multiples of the nominal diameter. These are rounded
# ISO/DIN ratios rather than table lookups, so any diameter gives a plausible
# head: an M8 pan head comes out 14.4 mm wide and 4.8 mm tall against DIN 7985's
# 14.0 x 4.6, and an M8 hex head 12.8 mm across flats against ISO 4017's 13.0.
#   width       head diameter, except for "hex" where it is across the flats
#   height      head height, excluding any dome
#   countersunk head sinks into the material, so "length" is measured overall
#   dome        extra crown height above the nominal length (oval head only)
HEAD_METRICS = {
    "flat":     {"width": 2.00, "height": 0.50, "countersunk": True,  "dome": 0.00},
    "oval":     {"width": 2.00, "height": 0.50, "countersunk": True,  "dome": 0.25},
    "pan":      {"width": 1.80, "height": 0.60, "countersunk": False, "dome": 0.00},
    "round":    {"width": 1.80, "height": 0.70, "countersunk": False, "dome": 0.00},
    "mushroom": {"width": 2.20, "height": 0.50, "countersunk": False, "dome": 0.00},
    "truss":    {"width": 2.40, "height": 0.35, "countersunk": False, "dome": 0.00},
    "hex":      {"width": 1.60, "height": 0.65, "countersunk": False, "dome": 0.00},
}

# Drive recess proportions. "width"/"flats"/"tip" scale with the diameter,
# "depth" with the head height so a shallow truss head gets a shallow recess.
DRIVE_METRICS = {
    "slot":       {"width": 0.17, "depth": 0.40},
    "phillips":   {"width": 0.22, "tip": 0.10, "depth": 0.50},
    "hex_socket": {"flats": 0.75, "depth": 0.60},
}

# ISO 68-1 metric thread: 60 degree flanks, external thread depth 0.6134 * pitch.
# The form is a truncated V, not a sharp one. Of the fundamental triangle of
# height H = 0.866 * pitch, H/8 is cut off the crest and H/6 off the root, which
# leaves the depth below and lands a flat of pitch/8 on the crest and pitch/6 in
# the root. Those three add up across one pitch exactly:
#     pitch/8 + 2 * h3 * tan(30) + pitch/6 == pitch
# A sharp crest is both unmachinable and visibly wrong, so the crest flat is
# part of the profile rather than an optional refinement.
THREAD_DEPTH_FACTOR = 0.6134
THREAD_HALF_ANGLE = 30.0
FUNDAMENTAL_HEIGHT_FACTOR = 0.866025      # H, the untruncated 60 degree triangle
CREST_FLAT_FACTOR = 1.0 / 8.0             # of the pitch
ROOT_FLAT_FACTOR = 1.0 / 6.0              # of the pitch

# How far the thread ridge is buried in the core, as a fraction of the pitch.
# A ridge that only touches the core is tangent to it and the fuse fails.
SINK_FACTOR = 0.02

# Explicit fuzzy tolerance for the thread fuse, in mm. The ISO form leaves only
# pitch/6 between one thread's root corner and the next one's, and at that
# spacing OCC's default tolerance intermittently collapses the whole fuse to a
# sliver - the same model at 5 mm long came out right and at 8 mm came out
# empty. A fuzz well below the gap but above OCC's confusion scale makes it
# deterministic. Do not raise it towards the root flat or adjacent threads will
# merge into each other.
BOOLEAN_FUZZ = 1e-5

# The head is fused to the shank through a plug reaching down inside the thread
# core, so the two solids overlap by volume rather than meeting on a circle.
PLUG_FACTOR = 0.9       # x minor radius
PLUG_DEPTH = 0.1        # x diameter

# 45 degree lead-in on the free end, as a multiple of the thread depth, so the
# first thread is not a knife edge.
TIP_CHAMFER_FACTOR = 1.0

# Each thread turn is a separate sweep and boolean, so build time tracks the
# turn count. Measured on FreeCAD 1.1.3: 22 turns 3.6 s, 102 turns 24.4 s.
SECONDS_PER_TURN = 0.25
TURN_WARNING = 150


# ---------------------------------------------------------------------------
# Derived dimensions
# ---------------------------------------------------------------------------

def thread_depth(pitch):
    """Radial depth of one thread flank."""
    return THREAD_DEPTH_FACTOR * pitch


def minor_radius(diameter, pitch):
    """Radius of the plain core the thread sits on."""
    return diameter / 2.0 - thread_depth(pitch)


def crest_truncation(pitch):
    """Radial height cut off the crest of the fundamental triangle: H/8.

    The sweep builds a sharp V whose apex overshoots the major radius by this
    much, and the shank is then trimmed back to the major radius. Truncating
    with a cylinder rather than sweeping an already-flat trapezoid is not
    cosmetic: a trapezoid profile makes consecutive one-turn sweeps meet on
    coincident quadrilateral end faces, and fusing those returns an invalid
    solid. A sharp apex meets at a degenerate edge, which fuses cleanly.
    """
    return FUNDAMENTAL_HEIGHT_FACTOR * pitch / 8.0


def crest_flat(pitch):
    """Axial width of the flat land on top of a thread.

    Falls out of the geometry: trimming a 30 degree flank at H/8 below the apex
    leaves 2 * (H/8) * tan(30) == pitch/8.
    """
    return CREST_FLAT_FACTOR * pitch


def root_flat(pitch):
    """Axial width of the flat between two adjacent threads."""
    return ROOT_FLAT_FACTOR * pitch


def is_countersunk(kind):
    return HEAD_METRICS[kind]["countersunk"]


def head_height(kind, diameter):
    """Head height excluding any dome."""
    return HEAD_METRICS[kind]["height"] * diameter


def head_across_flats(diameter):
    """Wrench size of a hex head."""
    return HEAD_METRICS["hex"]["width"] * diameter


def head_radius(kind, diameter):
    """Outermost radius of the head.

    For a hex head this is the across-corners radius, which is what matters for
    clearance and for checking the built solid.
    """
    if kind == "hex":
        return head_across_flats(diameter) / math.sqrt(3.0)
    return HEAD_METRICS[kind]["width"] * diameter / 2.0


def shank_length(kind, diameter, length):
    """Length of the threaded shank.

    A countersunk head sits inside the material, so the nominal length is
    measured overall and the head eats into it. Every other head sits on top of
    the shank and the nominal length is the shank itself.
    """
    if is_countersunk(kind):
        return length - head_height(kind, diameter)
    return length


def head_top_z(kind, diameter, length):
    """Z of the highest point of the finished screw, where a recess is cut."""
    if is_countersunk(kind):
        return length + HEAD_METRICS[kind]["dome"] * diameter
    return length + head_height(kind, diameter)


def ring_count(length, pitch):
    """How many one-turn sweeps cover a shank of this length.

    One extra turn at each end, because the helix has to run off past both faces
    before the shank is trimmed back flat.
    """
    return int(length / pitch) + 2


def thread_turns(kind, diameter, length, pitch):
    return ring_count(shank_length(kind, diameter, length), pitch)


def estimated_seconds(kind, diameter, length, pitch):
    return SECONDS_PER_TURN * thread_turns(kind, diameter, length, pitch)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(p):
    """Check a parameter set.

    Returns (errors, warnings). Errors describe geometry that cannot be built at
    all; warnings describe geometry that builds but is not a sensible screw.
    Catching these here gives a readable message instead of an OCC exception.
    """
    errors = []
    warnings = []

    kind = p["head"]
    drive = p["drive"]
    if kind not in HEAD_METRICS:
        errors.append("Unknown head type %r." % kind)
    if drive not in dict(DRIVE_TYPES):
        errors.append("Unknown drive type %r." % drive)

    d, length, pitch = p["diameter"], p["length"], p["pitch"]
    if d <= 0:
        errors.append("Screw diameter must be greater than 0.")
    if length <= 0:
        errors.append("Length must be greater than 0.")
    if pitch <= 0:
        errors.append("Thread pitch must be greater than 0.")

    if errors:
        # Everything below divides by these or indexes the metrics table.
        return errors, warnings

    rmin = minor_radius(d, pitch)
    if rmin <= 0:
        errors.append("Thread pitch %g mm is too coarse for a %g mm screw: a thread "
                      "%.3f mm deep would cut away the whole %.3f mm core. Keep the "
                      "pitch below %.3f mm."
                      % (pitch, d, thread_depth(pitch), d / 2.0,
                         d / 2.0 / THREAD_DEPTH_FACTOR))

    shank = shank_length(kind, d, length)
    if shank <= 0:
        errors.append("A %s head on a %g mm screw is %.3f mm tall, which is the whole "
                      "of the %g mm length (that length is measured overall, because "
                      "this head sinks into the material). Make it longer than %.3f mm."
                      % (dict(HEAD_TYPES)[kind], d, head_height(kind, d), length,
                         head_height(kind, d)))

    if errors:
        return errors, warnings

    # Buildable, but worth a word.
    if rmin < 0.25 * d:
        warnings.append("The thread leaves a core only %.3f mm across on a %g mm screw, "
                        "so it is mostly thread and very weak. A pitch near %.2f mm "
                        "suits this diameter." % (2 * rmin, d, 0.15 * d))
    if shank < 2 * pitch:
        warnings.append("The shank is %.3f mm, too short for two full turns of a %g mm "
                        "pitch thread." % (shank, pitch))

    turns = thread_turns(kind, d, length, pitch)
    if turns > TURN_WARNING:
        warnings.append("This screw has %d thread turns. Each one is a separate sweep, "
                        "so expect roughly %.0f seconds to build."
                        % (turns, estimated_seconds(kind, d, length, pitch)))

    if kind == "hex" and drive != "none":
        warnings.append("A hex head is driven by its flats, so a %s recess in the top "
                        "is unusual." % dict(DRIVE_TYPES)[drive])

    if drive in DRIVE_METRICS:
        depth = DRIVE_METRICS[drive]["depth"] * head_height(kind, d)
        if depth < 0.15 * d:
            warnings.append("A %s head is only %.3f mm tall, so the recess can only be "
                            "%.3f mm deep and a driver will slip."
                            % (dict(HEAD_TYPES)[kind], head_height(kind, d), depth))
    if drive == "hex_socket":
        socket_r = DRIVE_METRICS["hex_socket"]["flats"] * d / math.sqrt(3.0)
        if socket_r > head_radius(kind, d) - 0.1 * d:
            warnings.append("A %.3f mm hex socket leaves almost no wall in a head only "
                            "%.3f mm across." % (DRIVE_METRICS["hex_socket"]["flats"] * d,
                                                 2 * head_radius(kind, d)))

    return errors, warnings


# ---------------------------------------------------------------------------
# Geometry: shank
# ---------------------------------------------------------------------------

def build_shank(diameter, length, pitch):
    """Threaded shank, tip at z=0 and a flat top face at z=length.

    The thread is built additively, as a helical ridge on a core of the minor
    diameter. Two things about this are deliberate and load bearing:

    One sweep per turn. Sweeping the whole helix in a single MakePipeShell
    builds a face that wraps dozens of times; it reports isValid() but OCC then
    quietly drops it from the boolean, leaving an almost unthreaded rod. Each
    turn is swept separately and all of them go into one multiFuse.

    The ridge is buried SINK_FACTOR * pitch into the core. A ridge whose base
    merely touches the core is tangent to it, and that fuse fails outright.
    """
    r = diameter / 2.0
    h3 = thread_depth(pitch)
    rmin = minor_radius(diameter, pitch)
    sink = SINK_FACTOR * pitch
    base = rmin - sink
    # Half-widths of the two parallel sides of the thread form. The flank runs
    # from one to the other at 30 degrees off radial, so the root half-width is
    # the crest half-width plus the radial travel times tan(30).
    # The apex overshoots the major radius by the ISO crest truncation, and the
    # trim below cuts it back to a flat land of exactly pitch/8.
    apex = r + crest_truncation(pitch)
    half = (apex - base) * math.tan(math.radians(THREAD_HALF_ANGLE))

    rings = []
    for k in range(ring_count(length, pitch)):
        # Start one turn below the tip so the thread runs off the end cleanly.
        z = -pitch + k * pitch
        helix = Part.makeHelix(pitch, pitch, base)
        helix.translate(Base.Vector(0, 0, z))
        # The 60 degree V, apex outwards past the major radius. Frenet mode and
        # the contact/correction flags all get this wrong; the plain
        # makePipeShell(profiles, solid, frenet) form is what works.
        profile = Part.Wire(Part.makePolygon([
            Base.Vector(base, 0, z + half),
            Base.Vector(base, 0, z - half),
            Base.Vector(apex, 0, z),
            Base.Vector(base, 0, z + half),
        ]))
        rings.append(Part.Wire(helix.Edges).makePipeShell([profile], True, True))

    shank = Part.makeCylinder(rmin, length).multiFuse(rings, BOOLEAN_FUZZ)
    # One trim does two jobs: the helix overruns both ends, and the swept apex
    # overshoots the major radius. Cutting to a cylinder of exactly the major
    # radius gives a flat-ended shank whose crests are pitch/8 lands.
    shank = shank.common(Part.makeCylinder(r, length))

    # 45 degree lead-in, so the first thread is not a knife edge.
    chamfer = TIP_CHAMFER_FACTOR * h3
    if chamfer > 0:
        ring = Part.makeCylinder(r + 1.0, chamfer).cut(
            Part.makeCone(r - chamfer, r, chamfer))
        shank = shank.cut(ring)

    shank = shank.removeSplitter()
    # multiFuse and the trim hand back a single-solid compound; unwrap it so
    # callers get a solid they can fuse and Part.show without a nested layer.
    if shank.ShapeType == "Compound" and len(shank.Solids) == 1:
        shank = shank.Solids[0]
    return shank


# ---------------------------------------------------------------------------
# Geometry: heads
# ---------------------------------------------------------------------------

def _spherical_cap(base_radius, height, z0):
    """Spherical cap of the given base radius and height, sitting on z0.

    The sphere radius is chosen so the cap meets the z0 plane at exactly
    base_radius, which keeps the head diameter exact without a trim boolean:
    at z0 the sphere centre is (R - height) away, so the circle there has
    radius sqrt(R^2 - (R - height)^2) = base_radius.
    """
    R = (base_radius ** 2 + height ** 2) / (2.0 * height)
    sphere = Part.makeSphere(R)
    sphere.translate(Base.Vector(0, 0, z0 + height - R))
    return sphere.common(
        Part.makeCylinder(base_radius + 1.0, height, Base.Vector(0, 0, z0)))


def _hex_prism(across_flats, height, z0):
    """Hexagonal prism of the given wrench size, standing on z0."""
    rc = across_flats / math.sqrt(3.0)
    points = [Base.Vector(rc * math.cos(i * math.pi / 3.0),
                          rc * math.sin(i * math.pi / 3.0), z0) for i in range(6)]
    points.append(points[0])
    return Part.Face(Part.makePolygon(points)).extrude(Base.Vector(0, 0, height))


def build_head(kind, diameter, z0):
    """One head solid with its base plane on z0.

    Curved heads are spherical caps rather than swept or filleted profiles: the
    cap is exact, cheap, and needs no fillet that OCC might refuse. Where a cap
    tops a cylinder or a cone the two meet on a full coincident plane, which
    fuses cleanly - do not offset them into each other, that leaves a visible
    ledge where the cap has already narrowed.
    """
    if kind not in HEAD_METRICS:
        raise ValueError("Unknown head type %r" % kind)

    d = diameter
    height = head_height(kind, d)
    radius = head_radius(kind, d)

    if kind == "flat":
        # 90 degree countersink: the ratios make the flank exactly 45 degrees.
        head = Part.makeCone(d / 2.0, radius, height, Base.Vector(0, 0, z0))
    elif kind == "oval":
        cone = Part.makeCone(d / 2.0, radius, height, Base.Vector(0, 0, z0))
        dome = HEAD_METRICS["oval"]["dome"] * d
        head = cone.fuse(_spherical_cap(radius, dome, z0 + height))
    elif kind == "pan":
        # Straight flank with a domed crown on top.
        stem = 0.55 * height
        head = Part.makeCylinder(radius, stem, Base.Vector(0, 0, z0))
        head = head.fuse(_spherical_cap(radius, height - stem, z0 + stem))
    elif kind in ("round", "mushroom", "truss"):
        # The same cap at three different width-to-height ratios: round is a
        # tall dome, mushroom a wide low one, truss wider and lower still.
        head = _spherical_cap(radius, height, z0)
    elif kind == "hex":
        head = _hex_prism(head_across_flats(d), height, z0)
    else:
        raise ValueError("Unknown head type %r" % kind)

    head = head.removeSplitter()
    if head.ShapeType == "Compound" and len(head.Solids) == 1:
        head = head.Solids[0]
    return head


# ---------------------------------------------------------------------------
# Geometry: drive recesses
# ---------------------------------------------------------------------------

def _phillips_wing(width_top, width_tip, span, depth, top_z):
    """One tapered wing of a Phillips recess, open at the top.

    The taper - wider and longer at the surface than at the bottom - is what
    makes a real Phillips recess self-centring, so it is lofted rather than
    extruded.
    """
    def rectangle(width, length, z):
        points = [Base.Vector(-length / 2.0, -width / 2.0, z),
                  Base.Vector(length / 2.0, -width / 2.0, z),
                  Base.Vector(length / 2.0, width / 2.0, z),
                  Base.Vector(-length / 2.0, width / 2.0, z)]
        points.append(points[0])
        return Part.Wire(Part.makePolygon(points))

    return Part.makeLoft([rectangle(width_top, span, top_z + 0.5),
                          rectangle(width_tip, span * 0.55, top_z - depth)], True)


def build_drive(drive, kind, diameter, top_z):
    """Cutter for the drive recess, or None when there is no recess.

    top_z is the highest point of the finished screw. Every cutter reaches above
    it so the cut breaks the surface cleanly even on a domed head.
    """
    if drive == "none":
        return None
    if drive not in DRIVE_METRICS:
        raise ValueError("Unknown drive type %r" % drive)

    d = diameter
    height = head_height(kind, d)
    # Long enough to cross the whole head whatever its shape.
    span = 2.2 * head_radius(kind, d)
    metrics = DRIVE_METRICS[drive]
    depth = metrics["depth"] * height

    if drive == "slot":
        width = metrics["width"] * d
        return Part.makeBox(span, width, depth + 1.0,
                            Base.Vector(-span / 2.0, -width / 2.0, top_z - depth))

    if drive == "phillips":
        wing = _phillips_wing(metrics["width"] * d, metrics["tip"] * d,
                              span, depth, top_z)
        crossed = wing.copy()
        crossed.rotate(Base.Vector(0, 0, 0), Base.Vector(0, 0, 1), 90.0)
        cross = wing.fuse(crossed).removeSplitter()
        if cross.ShapeType == "Compound" and len(cross.Solids) == 1:
            cross = cross.Solids[0]
        return cross

    # hex_socket
    return _hex_prism(metrics["flats"] * d, depth + 1.0, top_z - depth)


# ---------------------------------------------------------------------------
# Geometry: the whole screw
# ---------------------------------------------------------------------------

def screw_label(p):
    """Human readable name for the finished screw.

    The trailing word matters: FreeCAD makes duplicate labels unique by
    rewriting a trailing number, so a label ending in the length would come back
    as "Screw M8x1.25 x 001" on the second screw in a document.
    """
    return "Screw M%gx%g x %g mm, %s" % (
        p["diameter"], p["pitch"], p["length"], dict(HEAD_TYPES)[p["head"]].lower())


def build_screw(p, doc=None):
    """Build the screw and add it to a document.

    p is a dict shaped like DEFAULTS. If doc is None a document is created or
    the active one is reused, following p["new_document"].
    Returns the App::Part container holding the screw.
    """
    errors, _ = validate(p)
    if errors:
        raise ValueError("Invalid screw parameters:\n- " + "\n- ".join(errors))

    d, length, pitch = p["diameter"], p["length"], p["pitch"]
    kind, drive = p["head"], p["drive"]

    # The head's base plane is the top of the shank. For a countersunk head that
    # is below the nominal length, because the head sinks into the material.
    base_z = shank_length(kind, d, length)

    shank = build_shank(d, base_z, pitch)
    head = build_head(kind, d, base_z)

    # Fuse through a plug reaching down inside the thread core. Head and shank
    # otherwise meet only on a circle - a countersunk cone's base is exactly the
    # shank diameter - and that fuse is unreliable.
    plug_depth = PLUG_DEPTH * d
    head = head.fuse(Part.makeCylinder(PLUG_FACTOR * minor_radius(d, pitch),
                                       plug_depth,
                                       Base.Vector(0, 0, base_z - plug_depth)))
    solid = shank.fuse(head).removeSplitter()

    cutter = build_drive(drive, kind, d, head_top_z(kind, d, length))
    if cutter is not None:
        solid = solid.cut(cutter).removeSplitter()

    if solid.ShapeType == "Compound" and len(solid.Solids) == 1:
        solid = solid.Solids[0]

    if doc is None:
        if p.get("new_document", True) or App.ActiveDocument is None:
            doc = App.newDocument("Screw")
        else:
            doc = App.ActiveDocument
    App.setActiveDocument(doc.Name)

    obj = Part.show(solid, "Screw")

    # An App::Part carries its own origin and Placement, unlike a plain group,
    # so the finished screw can be moved and reused as one component.
    part = doc.addObject("App::Part", "Screw")
    part.Label = screw_label(p)
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
    d, length, pitch = p["diameter"], p["length"], p["pitch"]
    kind = p["head"]

    lines = ["Thread M%g x %g mm" % (d, pitch)]
    if not errors:
        if is_countersunk(kind):
            lines.append("Length %g mm overall (countersunk head sinks in), "
                         "shank %.3f mm" % (length, shank_length(kind, d, length)))
        else:
            lines.append("Shank %g mm, %.3f mm overall with the head"
                         % (length, head_top_z(kind, d, length)))
        if kind == "hex":
            lines.append("Head %.3f mm across flats, %.3f mm tall"
                         % (head_across_flats(d), head_height(kind, d)))
        else:
            lines.append("Head %.3f mm across, %.3f mm tall"
                         % (2 * head_radius(kind, d), head_height(kind, d)))
        lines.append("Core %.3f mm across  -  %d thread turns  -  about %.0f s to build"
                     % (2 * minor_radius(d, pitch),
                        thread_turns(kind, d, length, pitch),
                        estimated_seconds(kind, d, length, pitch)))
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

    class ScrewDialog(QtWidgets.QDialog):
        """Parameter dialog for the screw."""

        def __init__(self, values=None, parent=None):
            if parent is None:
                parent = Gui.getMainWindow()
            super(ScrewDialog, self).__init__(parent)

            self.setWindowTitle("Screw")
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

            self.head = QtWidgets.QComboBox()
            for key, label in HEAD_TYPES:
                self.head.addItem(label, key)
            self.head.setCurrentIndex(
                max(0, [k for k, _ in HEAD_TYPES].index(values["head"])))
            self.head.setToolTip("Shape of the head. Flat and oval heads sink into "
                                 "the material, so their length is measured overall.")
            self.head.currentIndexChanged.connect(self.head_changed)
            form.addRow("Head shape:", self.head)

            self.drive = QtWidgets.QComboBox()
            for key, label in DRIVE_TYPES:
                self.drive.addItem(label, key)
            self.drive.setCurrentIndex(
                max(0, [k for k, _ in DRIVE_TYPES].index(values["drive"])))
            self.drive.setToolTip("Recess in the top of the head for the driver")
            self.drive.currentIndexChanged.connect(self.update_preview)
            form.addRow("Drive:", self.drive)

            self.new_doc = QtWidgets.QCheckBox("Create a new document")
            self.new_doc.setChecked(bool(values.get("new_document", True)))
            self.new_doc.setToolTip("Unchecked, the screw is added to the active document")
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

            self.head_changed()

        def parameters(self):
            """Read the widgets back into a parameter dict."""
            p = {key: spin.value() for key, spin in self.spins.items()}
            p["head"] = self.head.currentData()
            p["drive"] = self.drive.currentData()
            p["new_document"] = self.new_doc.isChecked()
            return p

        def head_changed(self):
            # A hex head is driven by its flats, so a recess makes no sense.
            hex_head = self.head.currentData() == "hex"
            if hex_head:
                self.drive.setCurrentIndex([k for k, _ in DRIVE_TYPES].index("none"))
            self.drive.setEnabled(not hex_head)
            self.update_preview()

        def restore_defaults(self):
            for key, spin in self.spins.items():
                spin.setValue(float(DEFAULTS[key]))
            self.head.setCurrentIndex([k for k, _ in HEAD_TYPES].index(DEFAULTS["head"]))
            self.drive.setCurrentIndex([k for k, _ in DRIVE_TYPES].index(DEFAULTS["drive"]))
            self.new_doc.setChecked(bool(DEFAULTS["new_document"]))
            self.head_changed()

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
                    self, "Screw", "This screw cannot be built:\n\n- "
                    + "\n- ".join(errors))
                return
            if warnings:
                answer = QtWidgets.QMessageBox.warning(
                    self, "Screw",
                    "This builds, but:\n\n- " + "\n- ".join(warnings)
                    + "\n\nCreate it anyway?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No)
                if answer != QtWidgets.QMessageBox.Yes:
                    return
            super(ScrewDialog, self).accept()

    # Values carry over to the next run within the same FreeCAD session.
    _last_values = dict(DEFAULTS)

    def show_dialog():
        """Ask for the parameters and build the screw if the user confirms."""
        global _last_values
        dialog = ScrewDialog(_last_values)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None
        _last_values = dialog.parameters()
        # A long fine-pitch thread is minutes of sweeps; say so before freezing.
        App.Console.PrintMessage(
            "Screw: building %d thread turns, this may take about %.0f seconds\n"
            % (thread_turns(_last_values["head"], _last_values["diameter"],
                            _last_values["length"], _last_values["pitch"]),
               estimated_seconds(_last_values["head"], _last_values["diameter"],
                                 _last_values["length"], _last_values["pitch"])))
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            return build_screw(_last_values)
        except Exception as exc:  # OCC can still refuse a geometrically odd set
            App.Console.PrintError("Screw: %s\n" % exc)
            QtWidgets.QMessageBox.critical(
                Gui.getMainWindow(), "Screw",
                "FreeCAD could not build this screw:\n\n%s" % exc)
            return None
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()


# FreeCAD executes a macro with __name__ set to "__main__"; the extra names
# cover being pasted into the Python console.
if __name__ in ("__main__", "__builtin__", "builtins"):
    if App.GuiUp:
        show_dialog()
    else:
        build_screw(DEFAULTS)
