import { arrowIcon, defineScene } from "../../components/scene.js";
import logoUrl from "../../videos/sightops-demo/assets/sightops-logo.png";

const flowSteps = ["SEE", "DIAGNOSE", "ACT"]
	.map((step) => `<div class="flow-step">${step}</div>`)
	.join(`<div class="flow-arrow" aria-hidden="true">${arrowIcon}</div>`);

export default defineScene({
	id: "title",
	advances: [17.7167, 19.7],
	voiceover:
		"SightOps is an agentic visual reliability engineer. You give it a photograph of a machine; it measures what the image actually shows with OpenCV, reasons about what it can and cannot see, and decides what still needs to be inspected. And critically, it does not guess.",
	html: `
		<div class="so-scene centered">
			<div class="brand">
				<img class="logo" src="${logoUrl}" alt="The SightOps logo">
				<div>
					<div class="wordmark">SightOps</div>
					<div class="lede">An Agentic Visual Reliability Engineer</div>
				</div>
			</div>
			<div class="flow">${flowSteps}</div>
			<div class="promise" data-beat="1">
				A confident wrong reading is worse than no reading. <em>It does not guess.</em>
			</div>
		</div>
	`,
});
