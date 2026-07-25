"""The capability vocabulary.

Every control in the UI is keyed to one of these ids. The UI asks "can I join a
wifi network?" — never "am I on Linux?" — so one UI codebase serves macOS,
Windows, AgentOS-on-someone-else's-desktop, and AgentOS-as-the-desktop, and a
control that isn't available renders greyed with a reason instead of vanishing
or throwing.

Adding a capability here without implementing it anywhere is fine and expected:
it reports `supported=False` on every platform until a backend claims it.
"""

# --- native applications ---------------------------------------------------
APPS_LIST = "apps.list"
APPS_LAUNCH = "apps.launch"

# --- windows & displays ----------------------------------------------------
WINDOWS_LIST = "windows.list"
WINDOWS_MANAGE = "windows.manage"          # focus / close
WINDOWS_ARRANGE = "windows.arrange"        # move between workspaces, float
WORKSPACES = "workspaces"                  # real, host-wide virtual desktops
DISPLAY_LIST = "display.list"
DISPLAY_CONFIGURE = "display.configure"    # resolution, scale, rotation, layout

# --- audio -----------------------------------------------------------------
AUDIO_VOLUME = "audio.volume"
AUDIO_DEVICES = "audio.devices"            # enumerate + switch default sink
AUDIO_PER_APP = "audio.per_app"

# --- power & session -------------------------------------------------------
POWER_BATTERY = "power.battery"
POWER_PROFILE = "power.profile"
POWER_SESSION = "power.session"            # suspend / restart / power off
SESSION_LOCK = "session.lock"
SESSION_LOGOUT = "session.logout"

# --- network ---------------------------------------------------------------
NET_STATUS = "net.status"
NET_WIFI_SCAN = "net.wifi.scan"
NET_WIFI_JOIN = "net.wifi.join"
NET_AIRPLANE = "net.airplane"

# --- bluetooth -------------------------------------------------------------
BT_STATUS = "bt.status"
BT_MANAGE = "bt.manage"                    # discover / pair / connect / remove

# --- display hardware ------------------------------------------------------
BRIGHTNESS_GET = "brightness.get"
BRIGHTNESS_SET = "brightness.set"

# --- desktop services ------------------------------------------------------
NOTIFY_SEND = "notify.send"                # we can raise a notification
NOTIFY_DAEMON = "notify.daemon"            # we ARE the notification daemon
SCREEN_CAPTURE = "screen.capture"
WALLPAPER_GET = "wallpaper.get"
WALLPAPER_SET = "wallpaper.set"

# --- settings --------------------------------------------------------------
SETTINGS_OPEN = "settings.open"            # hand off to the host's settings app
SETTINGS_NATIVE = "settings.native"        # AgentOS owns the settings panels

# id -> (short title, what it means when unavailable)
CAPS: dict[str, tuple[str, str]] = {
    APPS_LIST:         ("List installed apps", "The app launcher will be empty."),
    APPS_LAUNCH:       ("Launch native apps", "Apps can be listed but not started."),
    WINDOWS_LIST:      ("See open windows", "The taskbar won't show native windows."),
    WINDOWS_MANAGE:    ("Focus & close windows", "Native windows can't be controlled."),
    WINDOWS_ARRANGE:   ("Move & float windows", "Windows can't be rearranged."),
    WORKSPACES:        ("Virtual desktops", "Workspaces stay local to AgentOS windows."),
    DISPLAY_LIST:      ("See connected displays", "Display settings are unavailable."),
    DISPLAY_CONFIGURE: ("Configure displays", "Resolution and layout can't be changed."),
    AUDIO_VOLUME:      ("Volume control", "Volume can't be read or set."),
    AUDIO_DEVICES:     ("Choose audio device", "The output device can't be switched."),
    AUDIO_PER_APP:     ("Per-app volume", "Individual app volumes can't be set."),
    POWER_BATTERY:     ("Battery status", "No battery information."),
    POWER_PROFILE:     ("Power profiles", "Performance mode can't be changed."),
    POWER_SESSION:     ("Suspend & power off", "Power actions are unavailable."),
    SESSION_LOCK:      ("Lock the screen", "The screen can't be locked from AgentOS."),
    SESSION_LOGOUT:    ("Log out", "Logging out is unavailable."),
    NET_STATUS:        ("Network status", "Connection status is unknown."),
    NET_WIFI_SCAN:     ("Scan for wifi", "Nearby networks can't be listed."),
    NET_WIFI_JOIN:     ("Join wifi networks", "Wifi must be joined from system settings."),
    NET_AIRPLANE:      ("Airplane mode", "Radios can't be toggled."),
    BT_STATUS:         ("Bluetooth status", "Bluetooth state is unknown."),
    BT_MANAGE:         ("Pair Bluetooth devices", "Pairing must be done in system settings."),
    BRIGHTNESS_GET:    ("Read brightness", "Screen brightness is unknown."),
    BRIGHTNESS_SET:    ("Set brightness", "Brightness can't be changed from AgentOS."),
    NOTIFY_SEND:       ("Send notifications", "Notifications won't reach the desktop."),
    NOTIFY_DAEMON:     ("Receive app notifications", "Other apps' notifications won't appear here."),
    SCREEN_CAPTURE:    ("Screenshots", "Screen capture is unavailable."),
    WALLPAPER_GET:     ("Read the wallpaper", "The system wallpaper can't be reused."),
    WALLPAPER_SET:     ("Set the wallpaper", "The desktop background can't be changed."),
    SETTINGS_OPEN:     ("Open system settings", "There's no system settings app to hand off to."),
    SETTINGS_NATIVE:   ("Built-in settings panels", "Settings are handled by the host desktop."),
}

ALL = tuple(CAPS)
