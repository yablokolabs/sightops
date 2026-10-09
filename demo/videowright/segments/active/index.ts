import { defineScene, loopBar } from "../../components/scene.js";

export default defineScene({
	id: "active",
	advances: [2.7167, 13.5333, 28.2],
	voiceover:
		"This is the part that matters most. The agent compares image quality and measurements across observations, decides that the gauge cannot be trusted from this angle, and asks for a better photograph. The inspection pauses in a waiting state, with a specific request rather than a vague shrug: re-image the gauge square-on, filling most of the frame, with diffuse light and no specular reflection across the dial.",
	html: `
		<div class="so-scene tight">
			<div>
				<div class="kicker">Active perception</div>
				<div class="headline small">It asks for a better look instead of guessing.</div>
			</div>

			<div class="stage" data-beat="0">
				<div class="loop-stack">
					${loopBar(2, 0)}
					${loopBar(3, 1)}
				</div>

				<div class="panel">
					<div class="panel-title">Seven tool calls, in order. Calls 3 to 7 wait for a better image.</div>
					<ul class="mono-list columns">
						<li>1&nbsp; inspect_panel</li>
						<li>2&nbsp; request_new_view</li>
						<li class="dim">3&nbsp; inspect_panel</li>
						<li class="dim">4&nbsp; compare_observations</li>
						<li class="dim">5&nbsp; record_diagnosis</li>
						<li class="dim">6&nbsp; create_incident</li>
						<li class="dim">7&nbsp; request_human_approval</li>
					</ul>
				</div>
			</div>

			<div class="alert" data-beat="1">
				request_new_view — reason: pressure_gauge_01 was measured with low confidence
			</div>

			<div class="request" data-beat="2">
				<div class="row between">
					<span class="from">Request from the agent</span>
					<span class="chip warn"><span class="dot"></span>WAITING_FOR_USER</span>
				</div>
				Re-image pressure_gauge_01 square-on, filling most of the frame, with diffuse light and no specular reflection across the dial or lamp face.
			</div>
		</div>
	`,
});
