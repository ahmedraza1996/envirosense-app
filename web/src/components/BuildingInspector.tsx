import { api, Assessment, CLASS_COLOUR, CLASS_LABEL, CLASSES, Feature } from "../api";

interface Props { assessment: Assessment; feature: Feature; onBack: () => void }

export default function BuildingInspector({ assessment: a, feature: f, onBack }: Props) {
  const p = f.properties;
  const best = p.predicted_class;
  const review = p.review_status === "needs_review";
  return (
    <>
      <div className="ph">
        <div className="between">
          <h2>Building {f.id.slice(0, 8)}</h2>
          <button className="btn" onClick={onBack}>← Summary</button>
        </div>
        <div className="sub">{a.scene.disaster} · {a.pair_id}</div>
      </div>

      <div className="sec">
        <div className="crops">
          <figure><img src={api.cropUrl(a.pair_id, f.id, "pre")} alt="before" /><figcaption>Before · {a.scene.pre_date ?? ""}</figcaption></figure>
          <figure><img src={api.cropUrl(a.pair_id, f.id, "post")} alt="after" /><figcaption>After · {a.scene.post_date ?? ""}</figcaption></figure>
        </div>
        <div className="note" style={{ marginTop: 6 }}>Window is 3× the building size; blue line = xBD footprint.</div>
      </div>

      <div className="sec">
        <div className="between">
          <div>
            <div className="lbl" style={{ marginBottom: 2 }}>Model assessment</div>
            <div style={{ fontSize: 22, fontWeight: 750, color: best ? CLASS_COLOUR[best] : "var(--nv)" }}>
              {best ? CLASS_LABEL[best] : "Not detected"}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="lbl" style={{ marginBottom: 2 }}>Confidence</div>
            <div style={{ fontSize: 22, fontWeight: 750 }}>{p.confidence.toFixed(2)}</div>
          </div>
        </div>
        {CLASSES.map((c) => {
          const v = p.class_probabilities[c];
          return (
            <div className="pb" key={c}>
              <span className={c === best ? "" : "muted"}>{CLASS_LABEL[c]}</span>
              <div className="tr"><span style={{ width: `${(v * 100).toFixed(0)}%`, background: CLASS_COLOUR[c] }} /></div>
              <span className="mono" style={{ textAlign: "right" }}>{v.toFixed(2)}</span>
            </div>
          );
        })}
        <div className="note">Uncalibrated model scores; calibration is a later step.</div>
      </div>

      <div className="sec" style={{ borderBottom: 0 }}>
        <div className="kv">
          <div>Status</div>
          <div><span className={`pill ${review ? "p-review" : "p-auto"}`}>{review ? "Needs review" : "Auto"}</span>
            {p.reason_codes.length > 0 && <span className="dim"> {p.reason_codes.join(", ")}</span>}</div>
          <div>xBD label</div>
          <div style={{ color: p.true_class ? CLASS_COLOUR[p.true_class] : "var(--dim)" }}>
            {p.true_class ? CLASS_LABEL[p.true_class] : "un-classified"}
            {p.true_class && best && <span className="dim"> · {p.true_class === best ? "match" : "differs"}</span>}
          </div>
          <div>Location</div>
          <div className="mono">{p.centroid_lnglat ? `${p.centroid_lnglat[1].toFixed(5)}, ${p.centroid_lnglat[0].toFixed(5)}` : "–"}</div>
          {p.localized_fraction !== null && (<><div>Localized</div><div>{(p.localized_fraction * 100).toFixed(0)}% of footprint found by the U-Net</div></>)}
          <div>Input</div><div>{p.inference_mode}</div>
          <div>Model</div><div className="mono">{a.model.run}</div>
        </div>
      </div>
    </>
  );
}
