import { defineScene, fact, shot } from "../../components/scene.js";
import observation1Url from "../../videos/sightops-demo/assets/observation-1.png";

export default defineScene({
	id: "uncertainty",
	advances: [21.3167, 25.95],
	voiceover:
		"Every measurement carries a confidence, and the agent is allowed to distrust one. On the first photograph the gauge came back at 83.7 PSI with only 57 percent confidence, and two of the four components sat below the floor. So SightOps marked the frame as needing a better view, and wrote down why. A confident wrong pressure reading is far worse than no reading at all.",
	html: `
		<div class="so-scene">
			<div>
				<div class="kicker warn">Uncertainty is a result</div>
				<div class="headline small wrap">It reports a number it does not trust.</div>
			</div>

			<div class="stage split">
				${shot(
					observation1Url,
					"The SightOps workspace showing the first industrial observation: the pump-station panel photographed at an angle with a reflection across the gauge, and a gauge reading of 83.7 PSI at 0.57 confidence.",
					0,
					"capped",
				)}
				<div class="panel warn" data-beat="0">
					<div class="panel-title">Gauge</div>
					<div class="stat-value">83.7</div>
					<div class="stat-label">PSI — published at low confidence</div>
					<div class="facts">
						${fact("Confidence", "0.57", "warn")}
						${fact("Gauge gate", "below the floor", "warn")}
						${fact("Decision", "needs a better view", "warn")}
					</div>
				</div>
			</div>

			<div data-beat="1">
				<div class="alert">
					${"2 of 4 components need a better view: pressure_gauge_01 (57%); status_led_01 (52%)"}
				</div>
				<div class="caption">
					Below 0.50 confidence a reading is withheld entirely and no number is published. Here the
					value cleared that floor, so it was reported — and the agent still refused to conclude from it.
				</div>
			</div>
		</div>
	`,
});
