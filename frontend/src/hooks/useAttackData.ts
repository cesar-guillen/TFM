import { useEffect, useState } from "react";
import { getAttackCatalog } from "../api/client";
import type { Catalog } from "../types/attack";

interface AttackData {
  catalog: Catalog | null;
  loading: boolean;
  error: string | null;
}

export function useAttackData(): AttackData {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getAttackCatalog()
      .then((c) => {
        if (cancelled) return;
        setCatalog(c);
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

  return { catalog, loading, error };
}
