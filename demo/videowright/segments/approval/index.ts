import { defineScene, fact, shot } from "../../components/scene.js";
import approvalUrl from "../../videos/sightops-demo/assets/approval.png";

export default defineScene({
	id: "approval",
	advances: [2.4667, 28.0667, 30.8333],
	voiceover:
		"Then SightOps stops. Consequential actions require a person, so the agent requests approval and waits for it. In this demonstration the proposed action is simulated, and the interface says so plainly. Nothing is switched, no valve is turned, and no safety interlock is ever bypassed, because a troubleshooting assistant that can reach out and touch machinery is a hazard, not a product. A human decides what happens next.",
	html: `
		<div class="so-scene tight">
			<div>
				<div class="kicker warn">Human approval</div>
				<div class="headline small">It stops before it acts.</div>
			</div>

			<div class="stage split">
				${shot(
					approvalUrl,
					"The incident and approval panel: the proposed simulated action, an approve button and a reject button",
					0,
					"capped",
				)}
				<div class="panel warn" data-beat="0">
					<div class="panel-title">Proposed action</div>
					<div class="chip warn">SIMULATED ACTION - REQUIRES APPROVAL</div>
					<div class="facts">
						${fact("State", "AWAITING_APPROVAL")}
						${fact("Autonomy", "none", "ok")}
						${fact("Actuators", "not connected", "ok")}
					</div>
				</div>
			</div>

			<div class="panel" data-beat="1">
				<div class="panel-title">What it will not do</div>
				<div class="row">
					<span class="chip">switch a relay</span>
					<span class="chip">turn a valve</span>
					<span class="chip">bypass an interlock</span>
					<span class="chip">start a motor</span>
				</div>
				<div class="caption">No safety-critical actuation path exists in the system.</div>
			</div>

			<div class="row" data-beat="2">
				<div class="alert good">Approve or reject. Nothing executes without a person.</div>
				<div class="chip good">COMPLETED</div>
				<div class="chip">incident resolved</div>
			</div>
		</div>
	`,
});
