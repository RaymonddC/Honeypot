/**
 * i18n configuration — the single source of truth for supported locales.
 *
 * Setup note: this app does NOT use next-intl's routing/[locale] segment
 * (that would move every route to /en/... , /id/... and touch every Link
 * href in the app — too large a change for how this is being introduced).
 * Instead: a client-side provider (see `components/i18n/locale-provider.tsx`)
 * picks the active locale from localStorage (falling back to the browser),
 * and every component reads strings via `useTranslations()`. Switching
 * locale is instant (no navigation), same URL.
 */

export const locales = ["id", "en"] as const;
export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = "id";

export function isLocale(value: string | null | undefined): value is Locale {
  return !!value && (locales as readonly string[]).includes(value);
}
