import AttackMatrix from "./AttackMatrix";
import type { Catalog, LayerState, TechniqueSort } from "../types/attack";

/** Fit-to-width render of the full ATT&CK matrix. Columns share the full
 * available width equally (see .attack-matrix--overview), so all 15 tactics
 * fit without side-scrolling — only the vertical axis scrolls, for tactics
 * with more techniques than fit in the view's height. Used by the dashboard
 * in both run phases: read-only while the pipeline fills the matrix in
 * (`computing` pulses the frame so it reads as live rather than finished;
 * mapped cells open the evidence popover), and editable once the run is done
 * (pass `onLayerChange` — cells then open the score/comment editor). */
export default function MatrixOverview({
  catalog,
  layer,
  computing = false,
  onLayerChange,
  sortBy,
}: {
  catalog: Catalog;
  layer: LayerState;
  computing?: boolean;
  onLayerChange?: (next: LayerState) => void;
  sortBy?: TechniqueSort;
}) {
  return (
    <div className={`matrix-overview${computing ? " matrix-overview--computing" : ""}`}>
      <div className="matrix-overview__scroll">
        <AttackMatrix catalog={catalog} layer={layer} overview onLayerChange={onLayerChange} sortBy={sortBy} />
      </div>
    </div>
  );
}
