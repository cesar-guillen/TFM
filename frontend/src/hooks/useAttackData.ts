import { useEffect, useState } from "react";
import { getAttackCatalog, getMatrixLayer } from "../api/client";
import type { Catalog, Layer } from "../types/attack";

interface AttackData {
  catalog: Catalog | null;
  layer: Layer | null;
  loading: boolean;
  error: string | null;
}

export function useAttackData(): AttackData {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [layer, setLayer] = useState<Layer | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([getAttackCatalog(), getMatrixLayer()])
      .then(([c, l]) => {
        if (cancelled) return;
        setCatalog(c);
        setLayer(l);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { catalog, layer, loading, error };
}
