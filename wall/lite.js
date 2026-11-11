/* Lighter mode: no blur, no big soft shadows. On by default on the Android wall tablet, off on a desktop.
   Force it with ?lite=1 or ?lite=0. (A file of its own so the page needs no inline script.) */
(function () { var m = /[?&]lite=([01])/.exec(location.search), on = m ? m[1] === "1" : /Android/.test(navigator.userAgent);
  if (on) document.documentElement.classList.add("lighter"); })();
