import type {CSSProperties} from "react";

export interface TimelineEvent {
  id?: string;
  timestamp?: string;
  label?: string;
  type?: string;
  entity_id?: string;
  evidence_id?: string;
}

interface TimelineViewProps {
  events: TimelineEvent[];
}

function formatStamp(value?: string) {
  if (!value) return "Unknown time";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function TimelineView({events}: TimelineViewProps) {
  if (events.length === 0) {
    return <p className="panel-empty">No temporal events yet.</p>;
  }

  return (
    <ol className="timeline">
      {events.map((event, index) => {
        const style = {"--i": index} as CSSProperties;
        return (
          <li className="timeline-item" key={event.id || `${event.timestamp}-${index}`} style={style}>
            <time>{formatStamp(event.timestamp)}</time>
            <div>
              <strong>{event.label || event.type || "Event"}</strong>
              <small>{(event.type || "EVENT").replaceAll("_", " ")}</small>
              {event.evidence_id && <code>{event.evidence_id}</code>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
