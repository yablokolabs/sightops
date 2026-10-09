import { checkIcon, defineScene, fact, shot } from "../../components/scene.js";
import measurementsUrl from "../../videos/sightops-demo/assets/measurements-1.png";

const preprocessing = [
	"Detect the panel quad",
	"Warp it to a square view",
	"Rectify each region of interest",
]
	.map((step) => `<li>${checkIcon}<span>${step}</span></li>`)
	.join("");

export default defineScene({
	id: "vision",
	advances: [5.3833, 15.0167, 37.6833],
	voiceover:
		"Every measurement is real computer vision, not a language model's impression. Perspective is detected and corrected, the panel is located, blur and exposure are scored, and each region of interest is rectified. A gauge reading comes from a radial scan across the dial, with needle shape validation. A lamp is classified by hue segmentation and peak brightness, a switch from the angle of its lever, and a display from its stroke level. When the vision model does speak, its answer is labelled as inferred and never overwrites a measured value.",
	html: `
		<div class="so-scene tight">
			<div>
				<div class="kicker">OpenCV 5, not a VLM guess</div>
				<div class="headline small wrap">Measure the pixels. Then reason.</div>
			</div>
			<div class="stage split">
				${shot(
					measurementsUrl,
					"The real SightOps Measurement detail panel from the industrial demonstration: every measured value with its confidence, its provenance and the OpenCV version that produced it.",
					0,
					"panel-shot fit",
				)}
				<div class="column">
					<div class="panel">
						<div class="panel-title">Measured, in the pipeline</div>
						<div class="facts">
							${fact("Gauge", "radial scan")}
							${fact("Lamp", "HSV segmentation")}
							${fact("Switch", "PCA lever angle")}
							${fact("Display", "stroke level")}
						</div>
					</div>
					<div class="panel accent" data-beat="1">
						<div class="panel-title">Perspective correction</div>
						<ul class="list">${preprocessing}</ul>
					</div>
					<div class="alert good" data-beat="2">
						${checkIcon}
						<span>A VLM answer is labelled inferred. It never overwrites a measured value.</span>
					</div>
				</div>
			</div>
		</div>
	`,
});
