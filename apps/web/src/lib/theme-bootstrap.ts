/**
 * The pre-paint half of the theme setting, kept apart from `theme.ts`.
 *
 * The server layout inlines this, and Next refuses to let a server component import a
 * module that imports a React hook, even one it never calls — so the string cannot live
 * beside `useIsDark`. The storage key is shared from here so the two cannot disagree.
 */

export const THEME_KEY = "theme";

/**
 * Runs in `<head>` before first paint, so a pinned theme never flashes the other one.
 * A string so the layout can inline it; it must not depend on anything bundled.
 */
export const THEME_BOOTSTRAP = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;
