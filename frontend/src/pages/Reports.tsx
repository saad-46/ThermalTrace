import { Link } from "react-router-dom";
import { Async, Empty, errText, useToast } from "../components/ui";
import { downloadFile } from "../lib/api";
import { fmtBytes, fmtDateTime } from "../lib/format";
import { useReports } from "../lib/hooks";

export default function Reports() {
  const reports = useReports();
  const toast = useToast();
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Reports</h1><div className="sub">PDF investigation reports: evidence, confidence, model evidence, timeline, schematic map and source attribution. Generate them from an event.</div></div>
      </div>
      <section className="panel">
        <Async q={reports} empty={(d) => (d.items.length ? null : <Empty title="No reports yet">Open an event and choose "Generate report".</Empty>)}>{(d) => (
          <div className="table-wrap"><table className="table">
            <thead><tr><th scope="col">Report</th><th scope="col">Status</th><th scope="col">Created</th><th scope="col" className="right">Size</th><th scope="col">SHA-256</th><th scope="col" /></tr></thead>
            <tbody>{d.items.map((r) => (
              <tr key={r.id}>
                <td>{r.title}</td>
                <td>{r.status === "pending" ? <span className="row"><span className="spinner" /> Generating</span> : r.status === "failed" ? <span className="pill rejected" title={r.error ?? ""}>Failed</span> : <span className="pill live">Ready</span>}</td>
                <td className="num">{fmtDateTime(r.created_at)}</td>
                <td className="right num">{fmtBytes(r.size_bytes)}</td>
                <td className="mono faint" style={{ fontSize: 11 }}>{r.sha256?.slice(0, 16) ?? "—"}</td>
                <td className="right">
                  <Link className="btn ghost sm" to={`/events/${r.event_id}`}>Event</Link>
                  {r.status === "ready" && <button className="btn sm" onClick={() => downloadFile(`/reports/${r.id}/download`, `${r.title.replace(/\s+/g, "_")}.pdf`).catch((e) => toast(errText(e), "error"))}>Download</button>}
                </td>
              </tr>
            ))}</tbody>
          </table></div>
        )}</Async>
      </section>
    </div>
  );
}
