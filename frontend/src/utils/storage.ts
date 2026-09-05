/** localStorage that never throws. Access is blocked outright in some private
 * browsing modes, and writes fail when the quota is full — neither should be
 * able to break the page, so a failure just means "no saved preference". */

export function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Preference simply won't survive a reload.
  }
}

export function removeStored(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // Nothing stored, or storage unavailable — either way there is nothing to do.
  }
}
