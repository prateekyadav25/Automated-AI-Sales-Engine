import { Line } from "@/components/ds";
import type { VoiceHandoff } from "@/lib/types";

export function VoiceHandoffPanel({ voice }: { voice: VoiceHandoff }) {
  if (!voice.session_id) {
    return <p>No permissioned call is stored.</p>;
  }
  const windowText = voice.window_start && voice.window_end
    ? `${voice.window_start} to ${voice.window_end}`
    : "No requested window is stored";
  return (
    <div>
      <p>Fixture call. This is not a live Twilio call.</p>
      <Line label="Product" value={voice.product_name || "No frozen product"} />
      <Line label="Purpose" value={voice.purpose || "Not recorded"} />
      <Line label="Permission" value={voice.permission_source ? `${voice.permission_source} · ${voice.permission_channel} · ${voice.permission_scope}` : "Not recorded"} />
      <Line label="Permission time" value={voice.permission_at || "Not recorded"} />
      <Line label="Execution authorization" value={voice.execution_authorized ? "Authorized" : "Not authorized"} />
      <Line label="Owner" value={voice.owner_name || "Unassigned"} />
      <Line label="Recipient" value={voice.recipient || "Not validated"} />
      <Line label="Caller" value={voice.caller_identity || "Not selected"} />
      <Line label="Calling window" value={windowText} />
      <Line label="Attempt" value={`${voice.status || "Not started"} · ${voice.attempt_count}`} />
      <Line label="Fixture provider call id" value={voice.provider_call_id || "Not returned"} />
      <Line label="Outcome" value={voice.outcome || "Not recorded"} />
      <Line label="Last event" value={voice.last_event || "None"} />
      <Line label="Recording" value={voice.recording || "Not authorized"} />
      <Line label="Transcript" value={voice.transcript || "No transcript is stored."} />
      <Line label="Handoff" value={voice.handoff_task_id ? `${voice.transfer} Task ${voice.handoff_task_id}` : voice.transfer} />
      <Line label="Meeting request" value={voice.meeting_id || "None"} />
      <Line label="Live execution" value={voice.live_execution_ready ? "Ready" : "Not ready"} />
      <Line label="Blocker" value={voice.blocker || "None"} />
      <Line label="Next action" value={voice.next_action || "Review the callback."} />
    </div>
  );
}
