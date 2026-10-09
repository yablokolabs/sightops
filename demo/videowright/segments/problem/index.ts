import { checkIcon, defineScene, shot } from "../../components/scene.js";
import homeObservationUrl from "../../videos/sightops-demo/assets/home-observation-1.png";

const evidence = [
	"Is the lamp lit, and what colour?",
	"Is the display blank, or showing a value?",
	"Where does the needle point, in PSI?",
	"How sharp and how well exposed is the frame?",
]
	.map((item) => `<li>${checkIcon}<span>${item}</span></li>`)
	.join("");

export default defineScene({
	id: "problem",
	advances: [13.7, 26.9],
	voiceover:
		"The project began with a phone call about a broken dishwasher. A photograph of a control panel is easy to take and hard to read from a distance, and the person on the other end of that call could not tell which light was on. SightOps turns that photograph into evidence: what is lit and what is blank, where a needle points, how sharp and how well exposed the frame is, and how much of all of that you should actually trust.",
	html: `
		<div class="so-scene">
			<div>
				<div class="kicker">The problem</div>
				<div class="headline small wrap">A photograph is easy to take. It is hard to read.</div>
			</div>
			<div class="stage split">
				${shot(
					homeObservationUrl,
					"The real SightOps appliance troubleshooting workspace after the dishwasher demonstration's first photograph, showing the control panel, the agent timeline and a waiting state.",
					0,
				)}
				<div class="panel" data-beat="1">
					<div class="panel-title">From one photograph</div>
					<ul class="list">${evidence}</ul>
					<div class="caption">SightOps measures these. It reports how much it trusts each one.</div>
				</div>
			</div>
		</div>
	`,
});
