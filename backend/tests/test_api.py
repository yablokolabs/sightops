"""API integration tests.

These drive the real FastAPI application through an ASGI transport. The fixture
forces the agent's model provider to ``None`` so nothing reaches the network:
every inspection here runs the deterministic policy, which is the documented
degraded path rather than a mock.
"""

from __future__ import annotations

from app.fixtures.generate_panels import (
    scenario_dishwasher_closeup,
    scenario_fault_closeup,
    scenario_fault_distant,
)

PNG = "image/png"


async def _create(client, *, mode="industrial", demo_mode=True):
    response = await client.http.post(
        "/api/inspections",
        json={
            "mode": mode,
            "problem_statement": "pump pressure alarm",
            "demo_mode": demo_mode,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _upload(client, inspection_id, data, filename="panel.png", content_type=PNG):
    return await client.http.post(
        f"/api/inspections/{inspection_id}/images",
        files={"file": (filename, data, content_type)},
        data={"run_agent": "true"},
    )


# --------------------------------------------------------------------------
# system
# --------------------------------------------------------------------------


async def test_health_reports_the_running_opencv_version(client):
    response = await client.http.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["opencv_version"].startswith("5.")


async def test_opencv_endpoint_confirms_version_five(client):
    response = await client.http.get("/api/system/opencv")

    assert response.status_code == 200
    body = response.json()
    assert body["opencv_major"] >= 5
    assert body["is_opencv_5"] is True
    assert "OpenCV 5" in body["claim"]


async def test_system_status_marks_aws_as_not_implemented(client):
    response = await client.http.get("/api/system/status")

    assert response.status_code == 200
    body = response.json()
    assert body["aws_integration"] == "NOT IMPLEMENTED"
    assert body["name"] == "SightOps"
    assert body["tagline"] == "An Agentic Visual Reliability Engineer"
    assert sorted(body["profiles"]) == ["dishwasher_panel_v1", "industrial_panel_v1"]
    assert body["opencv_version"].startswith("5.")


async def test_system_status_reports_provider_presence_without_any_secret(client):
    response = await client.http.get("/api/system/status")
    body = response.json()

    providers = body["providers"]
    assert set(providers) == {"NEBIUS_API_KEY", "ELEVENLABS_API_KEY", "TAVILY_API_KEY"}
    assert all(isinstance(value, bool) for value in providers.values())

    # Nothing in the payload may look like a credential.
    raw = response.text
    for marker in ("sk-", "ghp_", "xi-api-key", "Bearer "):
        assert marker not in raw
    for value in body.values():
        if isinstance(value, str):
            assert len(value) < 120, f"a long string in the status payload is suspicious: {value!r}"


async def test_voice_status_explains_itself_without_leaking_the_key(client):
    response = await client.http.get("/api/voice/status")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "elevenlabs"
    assert body["voice_id"] == "zH7TN9vEZAsEway9xWev"
    assert isinstance(body["configured"], bool)
    assert body["message"]


async def test_request_id_header_is_present(client):
    response = await client.http.get("/health")

    assert response.headers.get("X-Request-ID")


# --------------------------------------------------------------------------
# inspections
# --------------------------------------------------------------------------


async def test_invalid_mode_is_rejected(client):
    response = await client.http.post(
        "/api/inspections", json={"mode": "spaceship", "problem_statement": "x"}
    )

    assert response.status_code == 422


async def test_unknown_inspection_is_a_404(client):
    response = await client.http.get("/api/inspections/does-not-exist")

    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


async def test_created_inspection_starts_in_created_state(client):
    body = await _create(client)

    assert body["state"] == "CREATED"
    assert body["demo_mode"] is True
    assert body["profile_id"] == "industrial_panel_v1"
    assert body["observation_count"] == 0

    listing = await client.http.get("/api/inspections")
    assert listing.status_code == 200
    assert body["id"] in [item["id"] for item in listing.json()]


async def test_uploading_a_valid_image_creates_one_observation(client, png_bytes):
    inspection = await _create(client, mode="home")

    response = await _upload(client, inspection["id"], png_bytes(scenario_dishwasher_closeup()))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["observation_count"] == 1
    assert body["state"] in {"COMPLETED", "WAITING_FOR_USER", "AWAITING_APPROVAL", "DIAGNOSING"}

    observations = await client.http.get(f"/api/inspections/{inspection['id']}/observations")
    assert observations.status_code == 200
    rows = observations.json()
    assert len(rows) == 1
    assert rows[0]["analysis"] is not None
    assert rows[0]["analysis"]["opencv_version"].startswith("5.")
    assert rows[0]["analysis"]["measurements"]


async def test_uploading_garbage_is_rejected_and_stores_nothing(client):
    inspection = await _create(client)

    response = await _upload(client, inspection["id"], b"(binary garbage")

    assert response.status_code == 422
    assert "decode" in response.json()["detail"]

    images = await client.context.repo.list_images(inspection["id"])
    assert images == []


async def test_uploading_a_disallowed_content_type_is_rejected(client, png_bytes):
    inspection = await _create(client)

    response = await _upload(
        client, inspection["id"], png_bytes(scenario_fault_closeup()), content_type="application/x-msdownload"
    )

    assert response.status_code == 415


async def test_the_industrial_demo_reaches_the_human_gate(client):
    response = await client.http.post("/api/demo/industrial")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["demo_mode"] is True
    assert body["observation_count"] == 1
    assert body["state"] == "WAITING_FOR_USER"
    assert body["pending_request"]["target_region"] == "pressure_gauge_01"
    assert body["incident_id"] is None

    inspection_id = body["id"]

    response = await client.http.post(f"/api/demo/{inspection_id}/next-observation")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "AWAITING_APPROVAL"
    assert body["incident_id"] is not None
    assert "PSI" in body["assessment"]["summary"]


async def test_approving_the_incident_marks_it_remediation_approved(client):
    started = (await client.http.post("/api/demo/industrial")).json()
    inspection_id = started["id"]
    await client.http.post(f"/api/demo/{inspection_id}/next-observation")

    response = await client.http.post(
        f"/api/inspections/{inspection_id}/approve",
        json={"approved": True, "note": "Operator reviewed the evidence."},
    )

    assert response.status_code == 200, response.text
    incident = response.json()
    assert incident["status"] == "remediation_approved"
    assert incident["resolution_note"] == "Operator reviewed the evidence."

    final = (await client.http.get(f"/api/inspections/{inspection_id}")).json()
    assert final["state"] == "COMPLETED"
    assert final["resolved"] is True


async def test_rejecting_the_incident_is_recorded_as_a_rejection(client):
    started = (await client.http.post("/api/demo/industrial")).json()
    inspection_id = started["id"]
    await client.http.post(f"/api/demo/{inspection_id}/next-observation")

    response = await client.http.post(
        f"/api/inspections/{inspection_id}/reject",
        json={"approved": False, "note": "Not authorised."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "remediation_rejected"
    final = (await client.http.get(f"/api/inspections/{inspection_id}")).json()
    assert final["resolved"] is False


async def test_approving_an_inspection_without_an_incident_is_refused(client):
    inspection = await _create(client)

    response = await client.http.post(
        f"/api/inspections/{inspection['id']}/approve", json={"approved": True, "note": ""}
    )

    assert response.status_code == 409


async def test_annotated_evidence_is_served_as_png(client, png_bytes):
    inspection = await _create(client)
    await _upload(client, inspection["id"], png_bytes(scenario_fault_distant()))

    observations = (
        await client.http.get(f"/api/inspections/{inspection['id']}/observations")
    ).json()
    image_id = observations[-1]["image_id"]

    response = await client.http.get(
        f"/api/inspections/{inspection['id']}/evidence/{image_id}", params={"annotated": "true"}
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 1000


async def test_original_evidence_is_served_unchanged(client, png_bytes):
    inspection = await _create(client)
    original = png_bytes(scenario_fault_closeup())
    await _upload(client, inspection["id"], original, filename="original.png")

    observations = (
        await client.http.get(f"/api/inspections/{inspection['id']}/observations")
    ).json()
    image_id = observations[-1]["image_id"]

    response = await client.http.get(
        f"/api/inspections/{inspection['id']}/evidence/{image_id}"
    )

    assert response.status_code == 200
    # The stored original must be byte-identical: annotations are a derivative.
    assert response.content == original


async def test_evidence_from_another_inspection_is_not_reachable(client, png_bytes):
    first = await _create(client)
    second = await _create(client)
    await _upload(client, first["id"], png_bytes(scenario_fault_closeup()))

    observations = (
        await client.http.get(f"/api/inspections/{first['id']}/observations")
    ).json()
    image_id = observations[-1]["image_id"]

    response = await client.http.get(f"/api/inspections/{second['id']}/evidence/{image_id}")

    assert response.status_code == 404


async def test_timeline_and_tool_calls_are_exposed(client, png_bytes):
    inspection = await _create(client, mode="home")
    await _upload(client, inspection["id"], png_bytes(scenario_dishwasher_closeup()))

    timeline = await client.http.get(f"/api/inspections/{inspection['id']}/timeline")
    assert timeline.status_code == 200
    entries = timeline.json()
    assert entries
    assert all(entry["inspection_id"] == inspection["id"] for entry in entries)
    kinds = {entry["kind"] for entry in entries}
    assert "observation" in kinds

    calls = await client.http.get(f"/api/inspections/{inspection['id']}/tool-calls")
    assert calls.status_code == 200
    rows = calls.json()
    assert rows
    assert all(row["tool"] for row in rows)
    assert all(row["source"] in {"model", "policy"} for row in rows)


async def test_user_message_is_recorded_and_reasoning_resumes(client):
    """A message arrives while the inspection is waiting for the user.

    The message is persisted, and the run resumes from the waiting state through
    REOBSERVING to REASONING rather than being dropped.
    """
    started = (await client.http.post("/api/demo/industrial")).json()
    inspection_id = started["id"]
    assert started["state"] == "WAITING_FOR_USER"

    response = await client.http.post(
        f"/api/inspections/{inspection_id}/messages",
        json={"content": "I checked the door and it is shut.", "run_agent": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["state"] != "FAILED"

    timeline = (
        await client.http.get(f"/api/inspections/{inspection_id}/timeline")
    ).json()
    assert any(
        entry["kind"] == "user_message" and "door" in entry["detail"] for entry in timeline
    )
    # The message reached the agent: it appears in the recorded problem statement.
    assert "door" in response.json()["problem_statement"]


async def test_resolve_records_the_user_outcome(client, png_bytes):
    inspection = await _create(client, mode="home")
    await _upload(client, inspection["id"], png_bytes(scenario_dishwasher_closeup()))

    response = await client.http.post(
        f"/api/inspections/{inspection['id']}/resolve", params={"resolved": "false"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resolved"] is False
    assert body["state"] == "COMPLETED"


async def test_incident_list_and_detail(client):
    started = (await client.http.post("/api/demo/industrial")).json()
    await client.http.post(f"/api/demo/{started['id']}/next-observation")
    incident_id = (
        await client.http.get(f"/api/inspections/{started['id']}")
    ).json()["incident_id"]

    listing = await client.http.get("/api/incidents")
    assert listing.status_code == 200
    assert incident_id in [item["id"] for item in listing.json()]

    detail = await client.http.get(f"/api/incidents/{incident_id}")
    assert detail.status_code == 200
    assert detail.json()["measurements"]


async def test_unknown_incident_is_a_404(client):
    assert (await client.http.get("/api/incidents/nope")).status_code == 404


async def test_unknown_demo_flow_is_a_404(client):
    assert (await client.http.post("/api/demo/spaceship")).status_code == 404


async def test_demo_flow_listing_describes_the_scripted_steps(client):
    response = await client.http.get("/api/demo/flows")

    assert response.status_code == 200
    body = response.json()
    flows = {flow["id"]: flow for flow in body["flows"]}
    assert set(flows) == {"industrial", "home"}
    assert flows["industrial"]["steps"] == 2
    assert "OpenCV" in body["note"]


async def test_openapi_document_is_served(client):
    response = await client.http.get("/api/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "SightOps API"
    assert "/api/inspections/{inspection_id}/images" in schema["paths"]
