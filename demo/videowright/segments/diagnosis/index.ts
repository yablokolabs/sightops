import { checkIcon, defineScene, fact, shot } from "../../components/scene.js";
import evidence2Url from "../../videos/sightops-demo/assets/evidence-2.png";

export default defineScene({
	id: "diagnosis",
	advances: [15.8333, 25.0667],
	voiceover:
		"That measurement is recorded as a diagnosis, with its evidence attached: the region ids, the values, the confidences, and the annotated image they came from. An incident is raised and a remediation is proposed. Every claim in the trace is traceable to a number that OpenCV produced, and to an image that a person can open and check for themselves.",
	html: `
		<div class="so-scene">
			<div>
				<div class="kicker">Diagnosis</div>
				<div class="headline small">Every claim carries its evidence.</div>
			</div>

			<div class="stage split">
				${shot(
					evidence2Url,
					"The annotated industrial panel: the detected regions and the measured gauge value drawn over the original photograph",
					0,
				)}
				<div class="panel accent" data-beat="0">
					<div class="panel-title">Recorded findings</div>
					<div class="facts">
						${fact("Region", "pressure_gauge_01")}
						${fact("Value", "87.2 PSI", "bad")}
						${fact("Confidence", "0.96", "ok")}
						${fact("Provenance", "measured", "ok")}
						${fact("Warning lamp", "RED", "bad")}
						${fact("Incident", "raised", "accent")}
					</div>
				</div>
			</div>

			<div class="panel accent" data-beat="1">
				<div class="panel-title">Auditable by construction</div>
				<ul class="list">
					<li>${checkIcon}<span>The value comes from OpenCV, not from the model</span></li>
					<li>${checkIcon}<span>The annotated image is stored with the inspection</span></li>
					<li>${checkIcon}<span>The tool-call trace records every step and its source</span></li>
				</ul>
				<div class="caption">The user can open the annotated frame and check the number themselves.</div>
			</div>
		</div>
	`,
});
