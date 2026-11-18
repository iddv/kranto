/* The appearance chosen under Settings › Appearance (the page keeps it in this browser as
   kranto.theme: auto, light or dark), applied before the first paint on the pages the server draws
   itself (connecting an account, the install page), so they do not fall back to the OS's scheme
   (it once reset when you clicked). Auto leaves it to prefers-color-scheme. */
"use strict";
(function () {
  let t = null;
  try { t = localStorage.getItem("kranto.theme"); } catch (e) { /* storage off: auto */ }
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
})();
