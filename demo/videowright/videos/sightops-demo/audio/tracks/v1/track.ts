import type { AudioTrack } from "videowright";

// Written by scripts/sync_audio.py. Each array holds segment-relative seconds: one
// entry for each reveal after the first, then the end of the segment.
const track: AudioTrack = {
	audio_file: "./audio/tracks/v1/track.mp3",
	length_s: 280.82,
	timing: {
		perSegment: {
			title: [17.7167, 19.7],
			problem: [13.7, 26.9],
			vision: [5.3833, 15.0167, 37.6833],
			uncertainty: [21.3167, 25.95],
			active: [2.7167, 13.5333, 28.2],
			remeasure: [4.3167, 13.0833, 28.25],
			diagnosis: [15.8333, 25.0667],
			approval: [2.4667, 28.0667, 30.8333],
			evaluation: [10.6333, 30.75, 35.2667],
			outro: [11.0667, 23.5667],
		},
	},
	audio_plan_path: "../../audio_plan.md",
	plan_snapshot_path: "./plan_snapshot.md",
	created_at: "2026-10-09T02:12:57Z",
};

export default track;
