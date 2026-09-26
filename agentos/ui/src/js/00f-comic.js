/* ================= The comic words: one vocabulary for the playground =================
   A tool call is drawn as a burst with a word in it — in the Office, on the play strip in
   Chat and in every app's agent panel, and on an app window the agent's hands touch. The
   word lives here, once, so "FETCH!" means the same thing on every surface; the real
   tool name is always printed beside it, so the joke never hides what actually ran.
   `var` and a function: the bundle is one script and the Office (24d) and the strip
   (24e) read these at run time. */
var COMIC_WORDS={fetch_url:'FETCH!',web_search:'SEARCH!',read_file:'READ',write_file:'SCRIBBLE!',
  run_command:'RUN!',remember:'NOTED!',recall:'HMM…',brief_item:'BRIEF!',mail_search:'MAIL?',
  mail_read:'MAIL!',calendar_events:'DATES!',save_report:'REPORT!',notify:'PING!',delegate:'HERE!',
  ask_agent:'Q?',huddle:'HUDDLE!',finish:'DONE!',search_files:'SEEK!',take_screenshot:'SNAP!',
  create_app:'BUILD!',control_desktop:'ZAP!',set_wallpaper:'SPLASH!',set_office:'REDECORATE!',
  set_avatar:'NEW LOOK!',create_flow:'PLAN!',schedule_task:'TICK-TOCK!'};
function comicWord(tool){
  return COMIC_WORDS[tool]||String(tool||'').replace(/_/g,' ').toUpperCase().slice(0,12)+'!';
}
