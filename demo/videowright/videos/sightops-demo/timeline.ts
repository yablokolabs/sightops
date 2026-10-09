import "../../styles/sightops/tokens.css";
import type { Timeline } from "videowright";
import defaultAudioTrack from "./audio/tracks/v1/track.js";

const timeline: Timeline = {
	meta: {
		title: "SightOps: an agentic visual reliability engineer",
	},
	segments: [
		{ id: "title" },
		{ id: "problem", transition: "fade" },
		{ id: "vision", transition: "fade" },
		{ id: "uncertainty", transition: "fade" },
		{ id: "active", transition: "fade" },
		{ id: "remeasure", transition: "fade" },
		{ id: "diagnosis", transition: "fade" },
		{ id: "approval", transition: "fade" },
		{ id: "evaluation", transition: "fade" },
		{ id: "outro", transition: "fade" },
	],
	default_audio_track: defaultAudioTrack,
};

export default timeline;
