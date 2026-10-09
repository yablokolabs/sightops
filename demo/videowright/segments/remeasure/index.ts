import { defineScene, fact, shot } from "../../components/scene.js";
import observation2Url from "../../videos/sightops-demo/assets/observation-2.png";

export default defineScene({
	id: "remeasure",
	advances: [4.3167, 13.0833, 28.25],
	voiceover:
		"A new photograph arrives, and this time the view is clean. The gauge reads 87.2 PSI, above the 75 PSI warning threshold, at 96 percent confidence. The agent diffs the two observations, sees the frame stop asking for a better view and the confidence on the gauge climb from 0.57 to 0.96, and replaces its earlier uncertainty with a measurement it can defend.",
	html: `
		<div class="so-scene">
			<div>
				<div class="kicker">A better view</div>
				<div class="headline wrap">The second look is what produces the measurement.</div>
			</div>

			<div class="stage split">
				${shot(
					observation2Url,
					"The SightOps workspace showing the second industrial observation: the same pump-station panel re-imaged square-on with diffuse light, and a measured gauge reading of 87.2 PSI at 0.96 confidence.",
					0,
					"capped",
				)}

				<div class="column">
					<div class="panel good" data-beat="0">
						<div class="panel-title">Gauge</div>
						<div class="stat-value">87.2</div>
						<div class="stat-label">PSI — measured by OpenCV</div>
						<div class="facts">
							${fact("Confidence", "0.96", "ok")}
							${fact("Warning threshold", "75 PSI", "warn")}
							${fact("State", "HIGH", "bad")}
							${fact("Provenance", "measured", "ok")}
						</div>
					</div>

					<div class="panel" data-beat="1">
						<div class="panel-title">compare_observations</div>
						<ul class="list">
							<li>The frame no longer needs a better view</li>
							<li>Gauge confidence rose from 0.57 to 0.96</li>
							<li>Measured pressure 83.7 to 87.2 PSI</li>
						</ul>
						<div class="caption">Read from the two measurement sets, not described by a model.</div>
					</div>
				</div>
			</div>

			<div class="alert good" data-beat="2">
				Observation 1: 83.7 PSI at 0.57 confidence, needing a better view. Observation 2: 87.2 PSI at 0.96.
			</div>
		</div>
	`,
});
