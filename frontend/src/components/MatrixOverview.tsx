import { useLayoutEffect, useRef, useState } from "react";
import AttackMatrix from "./AttackMatrix";
import type { Catalog, LayerState } from "../types/attack";

/** Renders the full ATT&CK matrix scaled down to fit its container, so the
 * entire matrix is visible at a glance (like Navigator's "fit to screen").
 * The matrix lays out at natural size; we measure it and apply a CSS transform. */
export default function MatrixOverview({ catalog, layer }: { catalog: Catalog; layer: LayerState }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [transform, setTransform] = useState("scale(1)");

  useLayoutEffect(() => {
    const container = containerRef.current;
    const content = contentRef.current;
    if (!container || !content) return;

    const compute = () => {
      const cw = container.clientWidth;
      const ch = container.clientHeight;
      // scrollWidth/Height are the pre-transform layout size, so measuring the
      // already-scaled node still yields its natural dimensions (no feedback loop).
      const nw = content.scrollWidth;
      const nh = content.scrollHeight;
      if (!cw || !ch || !nw || !nh) return;
      const scale = Math.min(cw / nw, ch / nh, 1);
      const offsetX = Math.max(0, (cw - nw * scale) / 2);
      setTransform(`translateX(${offsetX}px) scale(${scale})`);
    };

    compute();
    const ro = new ResizeObserver(compute);
    ro.observe(container);
    ro.observe(content);
    return () => ro.disconnect();
  }, [catalog, layer]);

  return (
    <div className="matrix-overview" ref={containerRef}>
      <div className="matrix-overview__content" ref={contentRef} style={{ transform }}>
        <AttackMatrix catalog={catalog} layer={layer} overview />
      </div>
    </div>
  );
}
