import AttackMatrix from "./AttackMatrix";
import type { Catalog, LayerState } from "../types/attack";

/** Dashboard preview of the full ATT&CK matrix. Columns share the full
 * available width equally (see .attack-matrix--overview), so all 15 tactics
 * fit without side-scrolling — only the vertical axis scrolls, for tactics
 * with more techniques than fit in the preview's height. While the pipeline
 * is still filling the matrix in (`computing`), the frame pulses so the user
 * can tell it's live rather than finished. */
export default function MatrixOverview({
  catalog,
  layer,
  computing = false,
}: {
  catalog: Catalog;
  layer: LayerState;
  computing?: boolean;
}) {
  return (
    <div className={`matrix-overview${computing ? " matrix-overview--computing" : ""}`}>
      <div className="matrix-overview__scroll">
        <AttackMatrix catalog={catalog} layer={layer} overview />
      </div>
    </div>
  );
}
