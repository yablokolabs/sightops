"""Equipment profiles.

A profile describes the equipment SightOps expects to see: which regions of
interest exist, what they are, and — for gauges — how the printed scale maps to
values. This is the *calibrated region* path the build specification allows for
the initial demonstrator: regions come from the profile rather than being
discovered from scratch, and every :class:`RegionSpec` records
``source="configured"`` so the UI never implies otherwise.

Automatic panel/ROI *detection* is implemented separately in
:mod:`app.vision.regions` (``detect_panel``), which the agent can invoke as a
tool to find a panel before falling back to profile geometry.
"""

from __future__ import annotations

from app.models.schemas import InspectionMode, RegionSpec


class EquipmentProfile:
    """A named set of regions plus the vocabulary used to talk about them."""

    def __init__(
        self,
        profile_id: str,
        label: str,
        mode: InspectionMode,
        regions: list[RegionSpec],
        *,
        description: str = "",
        guidance: dict[str, str] | None = None,
    ) -> None:
        self.profile_id = profile_id
        self.label = label
        self.mode = mode
        self.regions = regions
        self.description = description
        #: component_id -> plain-language note surfaced to the user.
        self.guidance = guidance or {}

    def region(self, region_id: str) -> RegionSpec | None:
        for spec in self.regions:
            if spec.region_id == region_id:
                return spec
        return None

    def regions_of(self, kind: str) -> list[RegionSpec]:
        return [r for r in self.regions if r.kind == kind]

    @property
    def gauge(self) -> RegionSpec | None:
        gauges = self.regions_of("gauge")
        return gauges[0] if gauges else None


# --------------------------------------------------------------------------
# Industrial demonstrator panel
# --------------------------------------------------------------------------
# Layout matches the synthetic panel produced by
# ``backend/app/fixtures/generate_panels.py``, which is also what the evaluation
# fixtures and the demo video use, so ground truth and configuration agree.

INDUSTRIAL_PANEL = EquipmentProfile(
    profile_id="industrial_panel_v1",
    label="Industrial control panel (mock)",
    mode=InspectionMode.INDUSTRIAL,
    description=(
        "Mock pump-station control panel: analog pressure gauge, red warning "
        "indicator, green status indicator and a two-position selector switch."
    ),
    regions=[
        RegionSpec(
            region_id="pressure_gauge_01",
            kind="gauge",
            label="Pressure gauge",
            x=0.075,
            y=0.115,
            w=0.375,
            h=0.520,
            scale_min=0.0,
            scale_max=100.0,
            unit="PSI",
            # 225 deg sweep: 0 PSI at 7:30, 100 PSI at 4:30.
            start_angle_deg=-135.0,
            end_angle_deg=135.0,
            warn_above=75.0,
        ),
        RegionSpec(
            region_id="warning_led_01",
            kind="indicator",
            label="Warning indicator",
            x=0.578,
            y=0.150,
            w=0.108,
            h=0.115,
        ),
        RegionSpec(
            region_id="status_led_01",
            kind="indicator",
            label="Run status indicator",
            x=0.578,
            y=0.360,
            w=0.108,
            h=0.115,
        ),
        RegionSpec(
            region_id="selector_switch_01",
            kind="switch",
            label="Pump selector switch",
            x=0.560,
            y=0.610,
            w=0.150,
            h=0.230,
        ),
    ],
    guidance={
        "pressure_gauge_01": (
            "The gauge shows the pump discharge pressure. The panel is marked "
            "NORMAL below 75 PSI."
        ),
        "warning_led_01": "A steady red warning light means the panel is reporting a fault.",
        "status_led_01": "The green lamp is lit while the pump is running normally.",
        "selector_switch_01": (
            "The selector is a two-position switch; read the position from the panel, "
            "not from this image alone."
        ),
    },
)

# --------------------------------------------------------------------------
# Household appliance demonstrator
# --------------------------------------------------------------------------

DISHWASHER_PANEL = EquipmentProfile(
    profile_id="dishwasher_panel_v1",
    label="Dishwasher control panel (mock)",
    mode=InspectionMode.HOME,
    description=(
        "Mock dishwasher fascia: a seven-segment style status display, a power "
        "indicator, and a start/pause indicator."
    ),
    regions=[
        RegionSpec(
            region_id="display_01",
            kind="display",
            label="Status display",
            x=0.170,
            y=0.300,
            w=0.430,
            h=0.190,
        ),
        RegionSpec(
            region_id="power_led_01",
            kind="indicator",
            label="Power indicator",
            x=0.690,
            y=0.315,
            w=0.075,
            h=0.115,
        ),
        RegionSpec(
            region_id="start_led_01",
            kind="indicator",
            label="Start / pause indicator",
            x=0.690,
            y=0.540,
            w=0.075,
            h=0.115,
        ),
    ],
    guidance={
        "display_01": (
            "The display normally shows the remaining time. If it is blank while the "
            "machine is switched on, the machine is not receiving power."
        ),
        "power_led_01": "This lamp is lit whenever the machine has power.",
        "start_led_01": (
            "This lamp flashes when a cycle is waiting to be started, and stays on "
            "during a cycle."
        ),
    },
)

_PROFILES: dict[str, EquipmentProfile] = {
    INDUSTRIAL_PANEL.profile_id: INDUSTRIAL_PANEL,
    DISHWASHER_PANEL.profile_id: DISHWASHER_PANEL,
}

DEFAULT_PROFILE_BY_MODE: dict[InspectionMode, str] = {
    InspectionMode.INDUSTRIAL: INDUSTRIAL_PANEL.profile_id,
    InspectionMode.HOME: DISHWASHER_PANEL.profile_id,
}


def get_profile(profile_id: str) -> EquipmentProfile:
    try:
        return _PROFILES[profile_id]
    except KeyError as exc:  # pragma: no cover - guarded by API validation
        raise KeyError(f"unknown equipment profile: {profile_id}") from exc


def resolve_profile(mode: InspectionMode, profile_id: str | None) -> EquipmentProfile:
    if profile_id:
        return get_profile(profile_id)
    return get_profile(DEFAULT_PROFILE_BY_MODE[mode])


def list_profiles() -> list[str]:
    return sorted(_PROFILES)
