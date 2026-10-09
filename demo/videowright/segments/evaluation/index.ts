import { defineScene } from "../../components/scene.js";

export default defineScene({
	id: "evaluation",
	advances: [10.6333, 30.75, 35.2667],
	voiceover:
		"The vision pipeline is measured on a reproducible fixture set with exact ground truth, across perspective, glare, blur, noise and resolution. On the gauge, the mean absolute error is under half a PSI, and fewer than one in a hundred published readings is wrong by more than a few PSI. Indicators are classified at better than 98 percent precision and recall. A frame is analysed in about 22 milliseconds on a CPU, and the agent completes every scripted task inside its bounds.",
	html: `
		<div class="so-scene">
			<div>
				<div class="kicker">Measured, not claimed</div>
				<div class="headline small wrap">Reproducible evaluation, with the numbers published.</div>
			</div>

			<div class="stage">
				<div class="metrics" data-beat="0">
					<div class="value accent">0.47</div>
					<div class="label">PSI mean absolute error reading the gauge</div>
					<div class="value">112</div>
					<div class="label">readings published, 24 more refused rather than guessed</div>
					<div class="value ok">98.6%</div>
					<div class="label">indicator macro precision, at 98.5% recall</div>
					<div class="value">22 ms</div>
					<div class="label">per 1280x720 frame on one CPU, measured in the running app</div>
				</div>

				<div class="panel" data-beat="1">
					<div class="panel-title">Honest failure modes</div>
					<ul class="list">
						<li><span>A blurred frame is refused, not guessed at</span></li>
						<li><span>One wrong-value escape in 112 readings is 0.9%, and it is reported</span></li>
						<li><span>Display lit or blank is the weakest class, and it is stated as such</span></li>
					</ul>
					<div class="caption">
						The error, refusal and classification figures come from backend/scripts/evaluate.py
						(the full table is in docs/evaluation/results.md); the frame latency is what the
						running application reports per observation.
					</div>
				</div>

				<div data-beat="2">
					<div class="states">
						<span class="state">WAITING_FOR_USER</span>
						<span class="arrow">-</span>
						<span class="state on">AWAITING_APPROVAL</span>
						<span class="arrow">-</span>
						<span class="state">COMPLETED</span>
					</div>
					<div class="caption">Every scripted task finishes inside the step, tool-call and reinspection bounds.</div>
				</div>
			</div>
		</div>
	`,
});
