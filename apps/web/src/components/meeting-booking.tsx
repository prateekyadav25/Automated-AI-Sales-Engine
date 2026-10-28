import { Line } from "@/components/ds";
import type { Meeting } from "@/lib/types";

export function MeetingBooking({ meeting }: { meeting: Meeting }) {
  const booked = Boolean(meeting.purpose || meeting.conference_status || meeting.slots?.length || meeting.blocker);
  if (!booked) {
    return <p>No Google Meet booking is stored. A scheduled recap is not a Meet conference.</p>;
  }
  return (
    <div>
      <Line label="Purpose" value={meeting.purpose || "Not recorded"} />
      <Line label="Lead" value={meeting.lead_name || "No lead is stored"} />
      <Line label="Enquiry" value={meeting.enquiry_note || "No enquiry is stored"} />
      <Line label="Product" value={meeting.product_name || "No frozen product"} />
      <Line label="Offer" value={meeting.offer_label || "No offer is stored"} />
      <Line label="Owner" value={meeting.owner_name || "Unassigned"} />
      <Line label="Calendar" value={meeting.calendar_id || "No calendar selected"} />
      <Line label="Owner time zone" value={meeting.owner_timezone || "Not recorded"} />
      <Line label="Attendee time zone" value={meeting.attendee_timezone || "Not recorded"} />
      <h3>Proposed slots</h3>
      {(meeting.slots || []).length === 0 ? <p>No slot has been proposed.</p> : (meeting.slots || []).map((slot) => (
        <p key={`${slot.start}-${slot.end}`}>
          {slot.owner_local} {slot.owner_timezone} · {slot.attendee_local} {slot.attendee_timezone}
        </p>
      ))}
      <Line
        label="Selected slot"
        value={meeting.selected_slot?.owner_local ? `${meeting.selected_slot.owner_local} ${meeting.selected_slot.owner_timezone}` : "Not selected"}
      />
      <Line label="Booking authorization" value={meeting.booking_authorized ? "Authorized" : "Not authorized"} />
      <Line label="Invitations" value={meeting.invite_authorized ? "Authorized" : "Not authorized"} />
      <Line label="Booking status" value={meeting.status || "Not started"} />
      <Line label="Conference" value={meeting.conference_status || "Not created"} />
      <Line label="Conference id" value={meeting.conference_id || "Not returned"} />
      {meeting.fixture_join_url ? <p>Fixture join link: {meeting.fixture_join_url}</p> : <p>No fixture join link is stored.</p>}
      {meeting.join_url ? <p>Google Meet link: {meeting.join_url}</p> : <p>No provider join link has been returned.</p>}
      <Line label="Last sync" value={meeting.last_synced_at || "Not synchronized"} />
      <Line label="Live execution" value={meeting.live_execution_ready ? "Ready" : "Not ready"} />
      <Line label="Attendance" value={meeting.attendance || "Attendance is not recorded."} />
      <Line label="Blocker" value={meeting.blocker || "None"} />
      <Line label="Next action" value={meeting.next_action || "No booking is in progress."} />
    </div>
  );
}
