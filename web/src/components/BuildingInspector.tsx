import { api, Assessment, CLASS_COLOUR, CLASS_LABEL, CLASSES, Feature, NOT_DETECTED_COLOUR } from "../api";

interface Props { assessment: Assessment; feature: Feature; onBack: () => void }

export default function BuildingInspector({ assessment: a, feature: f, onBack }: Props) {
  const p = f.properties;
  const best = p.predicted_class;
  const review = p.review_status === "needs_review";
  return (
    <>
      <section>
        <button className="link" onClick={onBack}>← {a.kind === "area" ? "Alerts" : "Tile summary"}</button>
        <h1 style={{ marginTop: 10 }}>{a.kind === "area" ? `Structure ${f.id}` : `Building ${f.id.slice(0, 8)}`}</h1>
        <p className="meta">{p.centroid_lnglat ? `${p.centroid_lnglat[1].toFixed(5)}, ${p.centroid_lnglat[0].toFixed(5)}` : "Location unavailable"}</p>
      </section>

      <section>
        <div className="pair">
          <figure><img src={api.cropUrl(a.id, f.id, "pre")} alt="Building before the disaster" /><figcaption>Before · {a.scene.pre_date}</figcaption></figure>
          <figure><img src={api.cropUrl(a.id, f.id, "post")} alt="Building after the disaster" /><figcaption>After · {a.scene.post_date}</figcaption></figure>
        </div>
      </section>

      <section>
        <div className="verdict">
          <span className="label">
            <i className="swatch" style={{ background: best ? CLASS_COLOUR[best] : NOT_DETECTED_COLOUR, width: 12, height: 12 }} />
            {best ? CLASS_LABEL[best] : "Not detected"}
          </span>
          <span className="conf">{Math.round(p.confidence * 100)}% confidence</span>
        </div>
        {CLASSES.map((c) => {
          const v = p.class_probabilities[c];
          return (
            <div className="prob" key={c}>
              <span>{CLASS_LABEL[c]}</span>
              <span className="track"><span style={{ width: `${v * 100}%`, background: c === best ? CLASS_COLOUR[c] : "var(--line-strong)" }} /></span>
              <span className="v">{v.toFixed(2)}</span>
            </div>
          );
        })}
      </section>

      <section>
        <dl className="facts">
          <dt>Status</dt>
          <dd>{review ? <span className="tag-review">Needs review</span> : "Assessed"}{review && p.reason_codes.length > 0 && <span className="subtle"> · {p.reason_codes.join(", ").replace(/_/g, " ")}</span>}</dd>
          {a.kind === "area" ? (<><dt>Roof area</dt><dd>{p.area_m2 !== undefined ? `${Math.round(p.area_m2)} m²` : "–"}</dd></>) : (<>
            <dt>xBD label</dt>
            <dd>{p.true_class ? CLASS_LABEL[p.true_class] : "Un-classified"}{p.true_class && best && <span className="subtle"> · {p.true_class === best ? "agrees" : "disagrees"}</span>}</dd></>)}
          {p.localized_fraction !== null && (<><dt>Footprint found</dt><dd>{Math.round(p.localized_fraction * 100)}%</dd></>)}
          <dt>Input</dt><dd>{p.inference_mode}</dd>
          <dt>Model</dt><dd>{a.model.label}</dd>
        </dl>
        <p className="meta" style={{ marginTop: 12 }}>Scores are not calibrated probabilities yet.</p>
      </section>
    </>
  );
}
