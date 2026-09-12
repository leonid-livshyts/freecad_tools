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

# ISO metric thread: 60 degree flanks, external thread depth 0.6134 * pitch.
THREAD_DEPTH_FACTOR = 0.6134
THREAD_HALF_ANGLE = 30.0

# How far the thread ridge is buried in the core, as a fraction of the pitch.
# A ridge that only touches the core is tangent to it and the fuse fails.
SINK_FACTOR = 0.02

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
