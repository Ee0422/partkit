"""Standard parameter names, categories and display-name rules.

Every part PartKit writes uses exactly these BOM field names, in every
category and every stage, so Altium's BOM never splits a column because two
parts spell a field differently.
"""

from __future__ import annotations

# Fields every part carries. Order is the column order of the BOM template.
BOM_FIELDS: tuple[str, ...] = (
    "Manufacturer",
    "Manufacturer Part Number",
    "Description",
    "Value",
    "Package",
    "Supplier 1",
    "Supplier Part Number 1",
    "Supplier 2",
    "Supplier Part Number 2",
    "Datasheet",
)

# Fields PartKit uses to track a part; also written onto the symbol.
TRACKING_FIELDS: tuple[str, ...] = ("Category", "PartKit Status", "3D Model")

# Fields the health check requires before a part may reach a BOM.
REQUIRED_FOR_BOM: tuple[str, ...] = (
    "Manufacturer",
    "Manufacturer Part Number",
    "Description",
    "Supplier 1",
    "Supplier Part Number 1",
)

# Common misspellings found in vendor libraries, mapped to the standard name.
# Vendor parameters that are only links back to the vendor's site; kept out of the BOM.
VENDOR_LINK_FIELDS = {"snapeda_link", "check_prices", "snapmagic_link", "ul_link"}

FIELD_ALIASES: dict[str, str] = {
    "mpn": "Manufacturer Part Number",
    "manufacturer_part_number": "Manufacturer Part Number",
    "manufacturer part number 1": "Manufacturer Part Number",
    "mfr part number": "Manufacturer Part Number",
    "mfr. part #": "Manufacturer Part Number",
    "part number": "Manufacturer Part Number",
    "mp": "Manufacturer Part Number",
    "mf": "Manufacturer",
    "mfr": "Manufacturer",
    "manufacturer 1": "Manufacturer",
    "manufacturer_name": "Manufacturer",
    "description": "Description",
    "value": "Value",
    "package": "Package",
    "case/package": "Package",
    "datasheet": "Datasheet",
    "datasheet link": "Datasheet",
    "componentlink1url": "Datasheet",
    "supplier": "Supplier 1",
    "supplier part number": "Supplier Part Number 1",
}

# Category -> the parameters that tell variants of that category apart.
CATEGORIES: dict[str, tuple[str, ...]] = {
    "Capacitors": ("Capacitance", "Voltage Rating", "Dielectric", "Tolerance", "Size", "Height", "AEC-Q200"),
    "Capacitors Polarized": ("Capacitance", "Voltage Rating", "ESR", "Ripple Current", "Size", "Height", "Lifetime"),
    "Resistors": ("Resistance", "Tolerance", "Power", "TCR", "Voltage Rating", "Size", "Technology", "AEC-Q200"),
    "Inductors": ("Inductance", "Rated Current", "Saturation Current", "DCR", "Shielding", "Size"),
    "Ferrite Beads": ("Impedance at 100MHz", "Rated Current", "DCR", "Size"),
    "Diodes": ("Type", "Reverse Voltage", "Forward Current", "Forward Voltage"),
    "LEDs": ("Colour", "Wavelength", "Forward Current", "Forward Voltage"),
    "Transistors": ("Type", "Vds/Vce", "Id/Ic", "Rds(on)", "Gate Charge"),
    "ICs": ("Function", "Supply Voltage", "Channels", "Temperature Grade"),
    "Power": ("Function", "Input Voltage", "Output Voltage", "Output Current", "Temperature Grade"),
    "Connectors": ("Series", "Pitch", "Pins", "Rows", "Mounting", "Orientation", "Gender"),
    "Crystals": ("Frequency", "Load Capacitance", "Stability", "Size"),
    "Misc": (),
}

DEFAULT_CATEGORY = "Misc"

# Reference designator prefix Altium shows on a new symbol, e.g. R? or U?.
DESIGNATOR_PREFIX: dict[str, str] = {
    "Capacitors": "C", "Capacitors Polarized": "C", "Resistors": "R", "Inductors": "L",
    "Ferrite Beads": "FB", "Diodes": "D", "LEDs": "D", "Transistors": "Q", "ICs": "U",
    "Power": "U", "Connectors": "J", "Crystals": "Y", "Misc": "U",
}

# Plain words for first-time users. Older libraries said Review/Released.
TO_CHECK, READY, OBSOLETE = "To check", "Ready", "Obsolete"
STAGES: tuple[str, ...] = (TO_CHECK, READY, OBSOLETE)
OLD_STAGE_NAMES = {"Review": TO_CHECK, "Released": READY, "Downloaded": TO_CHECK}

MODEL_3D_STATES: tuple[str, ...] = ("Full", "Simple", "None")


def normalise_field(name: str) -> str:
    """Map a vendor's field name onto PartKit's standard name."""
    key = name.strip().lower()
    if key in FIELD_ALIASES:
        return FIELD_ALIASES[key]
    for std in BOM_FIELDS + TRACKING_FIELDS:
        if std.lower() == key:
            return std
    return name.strip()


def category_fields(category: str) -> tuple[str, ...]:
    return CATEGORIES.get(category, ())


def display_name(params: dict[str, str], category: str) -> str:
    """A readable component name, e.g. 'C 100nF 50V X7R 10% 0603'."""
    if category == "Capacitors":
        bits = ["C", params.get("Capacitance"), params.get("Voltage Rating"),
                params.get("Dielectric"), params.get("Tolerance"), params.get("Size")]
    elif category == "Resistors":
        bits = ["R", params.get("Resistance"), params.get("Tolerance"),
                params.get("Power"), params.get("Size")]
    else:
        bits = [params.get("Manufacturer Part Number")]
    if len([b for b in bits if b]) < 2 and category in ("Capacitors", "Resistors"):
        return ""  # no spec known yet: a bare "R" or "C" would clash, so the MPN is used instead
    return " ".join(b for b in bits if b)
