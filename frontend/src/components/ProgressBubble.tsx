import { useRef, useState, type ReactNode } from "react";

interface ProgressBubbleProps {
  title: string;
  /** Shown truncated next to the title (the report's filename). */
  subtitle?: string;
  children: ReactNode;
}

const VIEWPORT_MARGIN = 8;

/** Floating, draggable panel for pipeline progress. Sits bottom-right until
 * the user drags it by its header; collapses to just the header bar so it can
 * sit unobtrusively over the matrix during minutes-long runs. */
export default function ProgressBubble({ title, subtitle, children }: ProgressBubbleProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  // null = untouched, keep the CSS default position (bottom-right corner).
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if ((e.target as HTMLElement).closest("button")) return; // collapse button, not a drag
    const root = rootRef.current;
    if (!root) return;
    const rect = root.getBoundingClientRect();
    const offsetX = e.clientX - rect.left;
    const offsetY = e.clientY - rect.top;
    const handle = e.currentTarget;
    handle.setPointerCapture(e.pointerId);

    function onMove(ev: PointerEvent) {
      setPos({
        x: Math.min(Math.max(ev.clientX - offsetX, VIEWPORT_MARGIN), window.innerWidth - rect.width - VIEWPORT_MARGIN),
        y: Math.min(Math.max(ev.clientY - offsetY, VIEWPORT_MARGIN), window.innerHeight - rect.height - VIEWPORT_MARGIN),
      });
    }
    function onUp() {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
    }
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
  }

  return (
    <div
      ref={rootRef}
      className={`progress-bubble${collapsed ? " progress-bubble--collapsed" : ""}`}
      style={pos ? { left: pos.x, top: pos.y, right: "auto", bottom: "auto" } : undefined}
    >
      <div
        className="progress-bubble__handle"
        onPointerDown={onPointerDown}
        onDoubleClick={() => setCollapsed((v) => !v)}
        title="Drag to move · double-click to collapse"
      >
        <span className="progress-bubble__title">{title}</span>
        {subtitle && <span className="progress-bubble__subtitle">{subtitle}</span>}
        <button
          className="progress-bubble__toggle"
          onClick={() => setCollapsed((v) => !v)}
          aria-label={collapsed ? "Expand progress" : "Collapse progress"}
        >
          {collapsed ? "▴" : "▾"}
        </button>
      </div>
      {!collapsed && <div className="progress-bubble__body">{children}</div>}
    </div>
  );
}
