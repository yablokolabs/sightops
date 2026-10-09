import { defineScene } from "../../components/scene.js";
import logoUrl from "../../videos/sightops-demo/assets/sightops-logo.png";

export default defineScene({
	id: "outro",
	advances: [11.0667, 23.5667],
	voiceover:
		"SightOps runs on a single CPU machine, with a real OpenCV 5 pipeline, a bounded agent loop, an approval gate, and a complete audit trail. It is open source and a working product rather than a prototype. You take a photograph. It measures, it reasons, it asks, and it acts safely. See. Diagnose. Act.",
	html: `
		<div class="so-scene centered">
			<div class="brand" data-beat="0">
				<img class="logo small" src="${logoUrl}" alt="">
				<div>
					<div class="wordmark small">SightOps</div>
					<div class="lede">See. Diagnose. Act.</div>
				</div>
			</div>

			<div class="flow" data-beat="0">
				<div class="flow-step accent">OpenCV 5.0.0</div>
				<div class="flow-step">FastAPI</div>
				<div class="flow-step">React + TypeScript</div>
				<div class="flow-step">Docker</div>
				<div class="flow-step">SQLite</div>
			</div>

			<div class="promise" data-beat="1">
				The agent knows what it can observe, what remains uncertain, and what needs inspecting next.
			</div>
		</div>
	`,
});
