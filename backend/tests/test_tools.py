"""Typed agent tools.

Tool arguments arrive from a language model, so validation and error handling
are part of the safety surface, not just convenience.
"""

from __future__ import annotations

import pytest

from app.agent.tools import (
    ALL_TOOLS,
    CompareObservationsArgs,
    CompareObservationsTool,
    CreateIncidentArgs,
    CreateIncidentTool,
    ReadGaugeArgs,
    ReadGaugeTool,
    REGISTRY,
    RequestNewViewArgs,
    RequestNewViewTool,
    ToolContext,
    ToolError,
    get_tool,
    tool_schemas,
)


def _bare_context(profile, engine=None):
    return ToolContext(
        engine=engine,
        profile=profile,
        images={},
        analyses={},
        ordered_image_ids=[],
    )


def test_every_tool_exposes_a_valid_json_schema():
    schemas = tool_schemas()

    assert len(schemas) == len(ALL_TOOLS)
    names = set()
    for schema in schemas:
        assert schema["type"] == "function"
        function = schema["function"]
        assert function["name"]
        assert isinstance(function["description"], str) and function["description"]
        parameters = function["parameters"]
        assert isinstance(parameters, dict)
        assert parameters.get("type") == "object"
        assert isinstance(parameters.get("properties"), dict)
        names.add(function["name"])

    assert names == set(REGISTRY)
    assert {
        "inspect_panel",
        "inspect_region",
        "read_gauge",
        "detect_indicator",
        "check_image_quality",
        "compare_observations",
        "request_new_view",
        "create_incident",
        "request_human_approval",
    } <= names


def test_unknown_tool_name_raises():
    with pytest.raises(ToolError) as excinfo:
        get_tool("nope")

    assert "nope" in str(excinfo.value)
    assert "available" in str(excinfo.value)


def test_wrong_argument_type_is_rejected_before_anything_runs():
    tool = ReadGaugeTool()

    with pytest.raises(ToolError) as excinfo:
        tool.validate({"region_id": 5})

    assert "region_id" in str(excinfo.value)


def test_missing_required_argument_is_rejected():
    with pytest.raises(ToolError):
        RequestNewViewTool().validate({"target_region": "pressure_gauge_01"})


async def test_read_gauge_refuses_a_region_that_is_not_a_gauge(industrial_profile):
    context = _bare_context(industrial_profile)

    with pytest.raises(ToolError) as excinfo:
        await ReadGaugeTool().run(context, ReadGaugeArgs(region_id="warning_led_01"))

    assert "not a gauge" in str(excinfo.value)


async def test_compare_observations_refuses_an_unanalysed_image(industrial_profile):
    context = _bare_context(industrial_profile)

    with pytest.raises(ToolError) as excinfo:
        await CompareObservationsTool().run(
            context,
            CompareObservationsArgs(previous_image_id="missing-a", current_image_id="missing-b"),
        )

    assert "has not been analysed" in str(excinfo.value)


async def test_request_new_view_records_the_request_on_the_context(industrial_profile):
    context = _bare_context(industrial_profile)
    arguments = RequestNewViewArgs(
        target_region="pressure_gauge_01",
        instruction="Re-image square-on.",
        reason="the dial could not be measured",
    )

    result = await RequestNewViewTool().run(context, arguments)

    assert result["recorded"] is True
    assert context.pending_request == {
        "target_region": "pressure_gauge_01",
        "instruction": "Re-image square-on.",
        "reason": "the dial could not be measured",
    }


async def test_create_incident_rejects_an_invalid_severity(industrial_profile):
    context = _bare_context(industrial_profile)
    arguments = CreateIncidentArgs(
        title="x", summary="y", severity="banana", proposed_action="z"
    )

    with pytest.raises(ToolError) as excinfo:
        await CreateIncidentTool().run(context, arguments)

    assert "severity" in str(excinfo.value)
    assert context.incident_request is None


async def test_create_incident_defaults_to_requiring_approval(industrial_profile):
    context = _bare_context(industrial_profile)
    arguments = CreateIncidentArgs(
        title="Pressure high",
        summary="Gauge reads above the limit.",
        severity="high",
        proposed_action="Simulated remediation.",
    )

    await CreateIncidentTool().run(context, arguments)

    assert arguments.requires_approval is True
    assert context.incident_request is not None
    assert context.incident_request["requires_approval"] is True


async def test_tools_refuse_to_run_without_images(industrial_profile):
    context = _bare_context(industrial_profile)

    from app.agent.tools import InspectPanelArgs, InspectPanelTool

    with pytest.raises(ToolError) as excinfo:
        await InspectPanelTool().run(context, InspectPanelArgs())

    assert "no images" in str(excinfo.value)


async def test_tools_refuse_an_unknown_image_id(engine, industrial_profile):
    from app.fixtures.generate_panels import scenario_normal
    from app.agent.tools import InspectPanelArgs, InspectPanelTool

    scene = scenario_normal()
    context = ToolContext(
        engine=engine,
        profile=industrial_profile,
        images={"known": scene.image},
        analyses={},
        ordered_image_ids=["known"],
    )

    with pytest.raises(ToolError) as excinfo:
        await InspectPanelTool().run(context, InspectPanelArgs(image_id="unknown"))

    assert "unknown" in str(excinfo.value)


def test_tool_context_exposes_a_small_surface():
    """The context is the whole authority a tool has, so it must stay tiny.

    A narrow surface is what makes "a tool cannot do anything the agent did not
    authorise" checkable rather than aspirational.
    """
    from app.vision.profiles import INDUSTRIAL_PANEL

    public = {
        name
        for name in set(dir(ToolContext)) | set(dir(_bare_context(INDUSTRIAL_PANEL)))
        if not name.startswith("_")
    }

    assert public == {
        "analysis_of",
        "analyses",
        "approval_request",
        "diagnosis",
        "engine",
        "images",
        "incident_request",
        "ordered_image_ids",
        "pending_request",
        "profile",
        "question",
        "resolve_image",
    }
