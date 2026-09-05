import AttackMatrix from "./AttackMatrix";
import type { Catalog, LayerState, TechniqueSort } from "../types/attack";

/** The matrix in its scrollable frame. Used by the dashboard in both run
 * phases: read-only while the pipeline fills it in (`computing` pulses the
 * frame so it reads as live), and editable once the run is done (pass
 * `onLayerChange`). */
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
        <AttackMatrix catalog={catalog} layer={layer} onLayerChange={onLayerChange} sortBy={sortBy} />
      </div>
    </div>
  );
}
