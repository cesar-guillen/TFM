import AttackMatrix from "./AttackMatrix";
import type { Catalog, LayerState } from "../types/attack";

/** Dashboard preview of the full ATT&CK matrix. Columns share the full
 * available width equally (see .attack-matrix--overview), so all 15 tactics
 * fit without side-scrolling — only the vertical axis scrolls, for tactics
 * with more techniques than fit in the preview's height. */
export default function MatrixOverview({ catalog, layer }: { catalog: Catalog; layer: LayerState }) {
  return (
    <div className="matrix-overview">
      <div className="matrix-overview__scroll">
        <AttackMatrix catalog={catalog} layer={layer} overview />
      </div>
    </div>
  );
}
