/* ================= icons =================
   One small stroke icon set, drawn here (24×24, 1.75px stroke, round caps) so
   every glyph in the chrome comes from one hand: the same weight, the same
   corner radius, the same optical size. Nothing here is copied from a library.

   Why: the shell used unicode characters as icons — ⚙ ✦ ⏻ ▲ ◧ ⇥ ◉ — and they
   render in whatever font the platform has, at whatever weight it has, which is
   the single loudest "this is an old UI" tell on every screen. An SVG is the
   same on a Pi, a Mac and a phone.

   `uiIcon(name, px)` returns inline SVG. The standard desktop keeps its glyphs;
   the immersive look swaps them through `data-ic` (01b-immersive.js), so this
   is opt-in like the rest of that look. Numbered 00d so every file can call it. */
var UI_ICONS={
  sparkles:'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM5 3v3M3.5 4.5h3M19 17v3M17.5 18.5h3',
  agent:'M12 3l7.8 4.5v9L12 21l-7.8-4.5v-9zM12 8.5v7M8.2 10.5l3.8 2.2 3.8-2.2',
  executors:'M4 12h11M11 7l5 5-5 5M20 5v14',
  channels:'M5 6.5h14a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-7.5L8 20v-3.5H5a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1zM8.5 10.5h7M8.5 13.5h4',
  locale:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.6 2.6 3.9 5.6 3.9 9s-1.3 6.4-3.9 9c-2.6-2.6-3.9-5.6-3.9-9S9.4 5.6 12 3z',
  keys:'M9 6a3 3 0 1 0-3 3h3zM15 6a3 3 0 1 1 3 3h-3zM9 18a3 3 0 1 1-3-3h3zM15 18a3 3 0 1 0 3-3h-3zM9 9h6v6H9z',
  voice:'M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM6.5 11.5a5.5 5.5 0 0 0 11 0M12 17v4M9 21h6',
  look:'M12 3a9 9 0 0 0 0 18c1.1 0 2-.9 2-2 0-.5-.2-1-.5-1.3-.3-.4-.5-.8-.5-1.2 0-1.1.9-2 2-2h1.6A4.4 4.4 0 0 0 21 10.1C21 6.2 17 3 12 3zM7.5 12.5a1.2 1.2 0 1 0 0-.1M9.5 8.5a1.2 1.2 0 1 0 0-.1M14.5 8a1.2 1.2 0 1 0 0-.1',
  system:'M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM19.4 13.5l1.4.8-1.6 2.8-1.6-.5a6.7 6.7 0 0 1-1.6.9L15.6 19h-3.2l-.4-1.5a6.7 6.7 0 0 1-1.6-.9l-1.6.5-1.6-2.8 1.4-.8a6.9 6.9 0 0 1 0-1.8L3.2 10.5l1.6-2.8 1.6.5a6.7 6.7 0 0 1 1.6-.9L8.4 5h3.2l.4 1.5c.6.2 1.1.5 1.6.9l1.6-.5 1.6 2.8-1.4.8a6.9 6.9 0 0 1 0 1.8z',
  power:'M12 3v8M17.7 6.3a8 8 0 1 1-11.4 0',
  bell:'M6 9.5a6 6 0 0 1 12 0c0 5 1.7 6 1.7 6H4.3S6 14.5 6 9.5M10.3 19.5a2 2 0 0 0 3.4 0',
  sliders:'M4 7h9M17 7h3M4 17h3M11 17h9M13 4.5v5M7 14.5v5',
  search:'M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM15.5 15.5L20 20',
  plus:'M12 5v14M5 12h14',
  x:'M6 6l12 12M18 6L6 18',
  check:'M5 12.5l4.5 4.5L19 7.5',
  chevronDown:'M6 9l6 6 6-6',
  chevronLeft:'M15 6l-6 6 6 6',
  chevronRight:'M9 6l6 6-6 6',
  more:'M5 12h.01M12 12h.01M19 12h.01',
  image:'M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM4 16l5-5 4 4 2-2 5 5M15.5 9a1 1 0 1 0 0-.1',
  send:'M12 19V5M5.5 11.5L12 5l6.5 6.5',
  expand:'M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7',
  camera:'M4 8h3l1.5-2.5h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1zM12 10.5a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  grid:'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
  home:'M4 11l8-7 8 7v9a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z',
  message:'M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-8l-5 4v-4H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z',
  clock:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2',
  zap:'M13 3L5 13h6l-1 8 9-11h-6z',
  shield:'M12 3l8 3v6c0 4.5-3.4 7.7-8 9-4.6-1.3-8-4.5-8-9V6zM9 12l2 2 4-4',
  folder:'M3 7a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z',
  terminal:'M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM7 9l3 3-3 3M12 15h5',
  globe:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.6 2.6 3.9 5.6 3.9 9s-1.3 6.4-3.9 9c-2.6-2.6-3.9-5.6-3.9-9S9.4 5.6 12 3z',
  wifi:'M2.5 9.5a14 14 0 0 1 19 0M6 13a9 9 0 0 1 12 0M9.5 16.5a4 4 0 0 1 5 0M12 20h.01',
  battery:'M3 8h14a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1zM21 11v2M5 10.5h6v3H5z',
  volume:'M4 10v4h3l4 3.5v-11L7 10zM15 9.5a3.5 3.5 0 0 1 0 5M17.5 7a7 7 0 0 1 0 10',
  sun:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4',
  moon:'M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z',
  lock:'M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1zM8 11V8a4 4 0 0 1 8 0v3',
  user:'M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4.5 20a7.5 7.5 0 0 1 15 0',
  refresh:'M20 11a8 8 0 0 0-14.5-3.5M4 13a8 8 0 0 0 14.5 3.5M4 4v5h5M20 20v-5h-5',
  pin:'M9 4h6l-1 6 3 3v1H7v-1l3-3zM12 14v6',
  bag:'M5 8h14l-1 12H6zM9 8V6a3 3 0 0 1 6 0v2',
  layers:'M12 4l8 4-8 4-8-4zM4 12l8 4 8-4M4 16l8 4 8-4',
  arrowLeft:'M19 12H5M11 6l-6 6 6 6',
  mic:'M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM6.5 11.5a5.5 5.5 0 0 0 11 0M12 17v4',
  triangle:'M12 4l8.5 15h-17z',
};
function uiIcon(name,px,cls){
  const d=UI_ICONS[name];if(!d)return '';
  px=px||16;
  return `<svg class="ic${cls?' '+cls:''}" width="${px}" height="${px}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d}"/></svg>`;
}
