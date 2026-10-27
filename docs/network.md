# Network: the machines on your network

*Settings → Network* lists every machine Bento knows on your network, whether it runs Bento or
not. From each row you can install Bento on it, secure it, and remove what ties it to this
machine. A machine waiting to be set up shows under *New machines* in the same tab, and the
other ways to add one (Make a Zero, the SD card, keys, the standard setup) are folded under
*Add a machine*.

![Settings → Network: the machines, each with one button and ⋯, then Hidden and Add a machine](screenshots/network-list.png)

It's admin only, because it reaches other machines. Bento looks only at this machine's own
private network, and anything it runs on another machine is shown to you before it runs.

## The list

One row per machine. A Pi that was heard without Bento, then installed, set up and linked is
still one row, matched by its network card's address, its IP and its certificate. Each row says:

- what it is (board or maker), its address, and when it was last heard;
- whether Bento runs there (*No Bento*, *Bento, waiting*, *Bento*, *Bento, linked*), and once
  it has been checked, how secure it is (*2 of 4 in place* or *secured*). That is always what
  Bento measured on the machine the last time it logged in, never a note that a run finished;
- whose it is, for a Zero that belongs to an account.

Each row has one button for the thing it most needs: *Install Bento*, *Secure it* (or
*Security* once checked), or *Set it up* for a Bento machine waiting under New machines. The
rest (Secure it when Install is the button, Disconnect, Rename, Hide) is behind **⋯**.

**Look at the network** knocks on SSH and Bento's port across this machine's own private
networks. A Raspberry Pi that joins the network says its name and you get a toast.

A machine doesn't need SSH open to be found. One that refuses the knock is there, and knocking
makes this machine ask the whole network who is at each address, so even a Pi with a firewall
that drops everything shows up. Its row says SSH is off, and how to turn it on. Raspberry Pi
Imager leaves SSH off unless you tick *Enable SSH*. After a scan, Bento also asks the network
over mDNS what each machine calls itself, so a Pi shows its own name.

![A Pi with SSH off and a firewalled one, found and explained](screenshots/network-ssh-off.png)

Bento listens for new Pis whatever its brain. Before, only a machine that could lead a community
listened, which a hub on Claude Code can't, so it heard no Pi at all. A Pi that was already on
when Bento started has nothing new to say, so press **Look at the network** to find it.

## Network & Teams

Settings → **Network & Teams** is Network and the old Team & Communications in one tab, in three
parts:

- **Discovery and linkage**: the machines on your network and the teams you link with. Finding
  and installing Bento on a machine, new machines and Make a Zero, linked teams, the community,
  and messages with the people on linked teams. Your agents working together (models, who may ask
  whom, huddles) moved to Settings → Agents.
- **Team to agent mapping**: who each Zero and team talks to here, below.
- **Maps**: the logical map and the physical one, below.

### Team to agent mapping

Every Zero and linked team has **Talks to**: your lead agent, or one department of one of your
companies.

- **Your lead agent** can hand the work to every company, department and agent you have. The
  row says so in amber, with how many agents that is and through which tools. Links made before
  this keep talking to the lead, so nothing changes on an update until you choose.
- **A department** keeps the team to that department. Its desk does the work, with its own people
  and their permissions, the company's persona and its sign-offs, and the question is marked as
  coming from outside. Nothing else here is reachable through it. A department of a company that
  isn't open works too.

**What it can reach** lists everything the choice gives it: who answers, the people they can
reach with each one's tools, executor and permissions, which of your agents it may also ask
directly, and every permission row written for it.

![Team to agent mapping: a Zero talking to Sales, and a team talking to the lead with the caution](screenshots/net-mapping.png)

![What a team talking to the lead can reach: every agent, with its tools and permissions](screenshots/net-mapping-access.png)

From a terminal: `bento network talks` lists them, `bento network talks studio Sales` points one at a
department (`--company ID` for another company, `lead` for the lead), and it prints what that gives.

### Maps

Every map in Bento is one view you move through, the way a map app works:

- **One place at a time.** The thing you're looking at sits in the middle, with what's inside it on
  a ring around it, and small dots beyond them where there is more.
- **Tap to go in.** A company opens its departments, a department its people, a group of devices its
  machines. The panel says everything about what you tapped: permissions, tools, executor, address,
  with the buttons that act on it. **↑** in the toolbar, or the trail in the panel, goes back out.
- **Find** goes straight to any agent, department or machine.
- Drag to move, scroll or pinch to zoom, **Fit** to see it all. Keys: + − 0, the arrows, Escape to go up.

The **logical** map starts at your lead: your companies, the Zeros and teams that talk to it, then
departments, people and their permissions. The **physical** map starts at this computer: Zeros,
linked teams, Bento machines and the other devices. Both are in Network & Teams → Maps and in the
Devices app; Settings → Agents has the logical one. `bento network map` prints the logical one.

![The logical map zoomed out: Aria, the companies, and a team talking to her](screenshots/map-overview.png)

![A company opened: its departments around it, with its panel](screenshots/map-company.png)

![On a phone: the Sales department, with a Zero that talks to it and its three people](screenshots/map-department-phone.png)

![The physical map: this computer, its Zeros, linked teams and the devices on the network](screenshots/map-devices.png)

The map used to draw every agent, brain, executor, skill and mission at once. On a hub with 47
agents that was 2,448 curves on a sheet nearly three thousand pixels tall, and redrawing it made
the whole desktop flicker. The map now has a fixed size and draws one place at a time.

## Teams and Zeros

Under the machines, **Teams and Zeros** lists every tie this computer has with another Bento: the
Zeros it set up and the teams it linked with, wherever they are. A team reached over Tailscale is
here too, even though it isn't on this network. Each one says whether it's answering, checked when
the tab opens and again with **Check them now**.

![Teams and Zeros: a linked team, and a Zero opened with its brain, who it may ask and its sessions](screenshots/network-ties-zero.png)

**Manage** opens one:

- **Its work here runs on.** Which of this computer's brains answers for it: the machine's own,
  one model from a provider, or an agent like Claude Code. A Pi's chats can run on a local model
  while your own chats stay on Claude Code.
- **It may ask.** Which of your agents its agents may ask directly, beside who it talks to. These
  are the same permissions as in Settings → Agents.
- **Sessions, Memory, Knowledge, Logs.** That tie's own rows and nothing else. A Zero's are its
  section here, exactly: nothing of yours and nothing of another Zero's. A team keeps its memory on
  its own machine, so it has sessions and log lines only.
- **Make it mine.** A Pi installed from a terminal belongs to the machine, so its chats and memory
  here sit where your Chat and Profile don't show them. This moves it to your account. New installs
  belong to whoever installs them, and `bento network install --for NAME` names one from a terminal.
- **Remove this link.** Tap it twice. A link a reinstall left behind is marked **Old link**: the
  machine at that address no longer has the certificate it was made with.

![On a phone: a Zero's memory, read from its section](screenshots/network-ties-memory-phone.png)

### When a machine's address changes

A Pi on a home network gets its address from your router (DHCP), and it can change after a
reboot or a router restart. Bento follows it. A link trusts the machine's certificate, never its
address, so the address is free to move:

- Every machine says hello to the other once a minute. When the Pi's hello comes from a new
  address, the hub's link moves there.
- When the hub can't reach a machine at its old address, it looks where it might be now: the
  address it last came from, its network card in this computer's neighbour table, its name on
  the network (`raspberrypi.local`), and then, at most every 15 minutes, a knock on the link port
  across this computer's own network.

Each place is dialled with the pinned certificate, and an answer with any other certificate is
never used. Only an address is ever changed. A link made to a name keeps its name. Every move is
an event, below, and a `device.moved` ledger row.

### Events

The Devices app has **Events** under the map: what happened to the machines here, newest first.
A machine that moved and how it was found, one that stopped answering (after two missed minutes,
so a Wi-Fi blink isn't news) and came back, one that's on a new version, a Zero whose screen was
refreshed, and every step done to a machine from here: heard, installed, secured, switched,
linked, set up, asked to update. Manage on a team or a Zero has the same list for it alone.

![Devices: the map, and Events under it](screenshots/devices-events.png)

![Events on a phone: the Pi moved twice, stopped answering and came back](screenshots/devices-events-phone.png)

`bento network events` prints them, and `bento network events pi-kitchen` one machine's.

### The map

The Devices app opens on a map. This computer is in the middle with its agent. Zeros sit on the
nearest ring with a solid line, teams on the next with a dashed one, and other machines with Bento
between. A grey line means it isn't answering. The rest of your network is the dots on the edge.
Tap a node to open it in the list.

![The device map while a Zero's question is worked on this computer: the Zero glows and shows what it asked](screenshots/devmap-zero-working.png)

When somebody talks to a Zero, the chat runs here and the Zero's node glows with what it was asked.
The Office shows the question arriving at your agent's desk.

![The map on a phone: the hub, a Zero and a linked team](screenshots/devmap-phone.png)

From a terminal, `bento network ties` lists them, and `bento network ties pi-zero memory` shows
one tie's own rows:

```
$ bento network ties
  studio-mac               team     answering
                           studio-mac at 127.0.0.1 · belongs to the machine · runs on this machine's brain
  pi-zero                  zero     answering
                           pi-zero at 127.0.0.1 · belongs to the machine · runs on custom/fake-1
  pi-zero-old              zero     old link
```

## Install Bento

Open a row and press **Install Bento**. Type the user you set in Raspberry Pi Imager and its
password, and press **Check it**. Bento logs in, says what the machine is, and shows the exact
command it will run there. Press **Install Bento there** to run it. The machine comes up with a
key this one made for it, so it's set up here the moment it's heard.

New Raspberry Pi OS has no `pi` user. Use the name you typed in Imager's settings.

**Its agent's name** is what you call that machine's agent, like *Chef* or *Fridge*. **Open on its
screen** (on by default) makes Bento open full screen on that machine when it starts, so you can
plug a screen in and talk to it. It adds `--screen` to the command shown. See
[One agent on screen, and the kiosk](small-screens.md#open-on-its-screen-at-start).

When the login is refused, the reason stays under **Check it**:

- **The user name or password was refused.** Check both against what you set in Imager.
- **That machine takes SSH keys only.** Imager's *Allow public-key authentication only* turns
  passwords off. Add this machine's key there (*Set machines up → This machine's SSH key*) and
  flash the card again, or flash it with password authentication on.
- **This machine's key is not on that machine.** You left the password blank; type it.

![Check it on a Pi flashed keys-only: the reason, kept in the form](screenshots/network-keys-only.png)

![The same refusal on a phone, under Check it](screenshots/network-keys-only-phone.png)

### While it installs

Once you press **Install Bento there**, the form turns into the install: the step it's on, out
of seven (six without its screen), and how long it's been going. The steps are read from what the
installer prints, so the bar moves when the machine does. **What it printed** shows the raw lines.
A Pi takes 10 to 20 minutes, and you can close Settings while it runs.

![Installing: the step it's on, the steps done, and how long](screenshots/network-installing.png)

![The same install watched from a phone](screenshots/network-installing-phone.png)

If it stops, the card says why in the installer's words, including what git or apt said just
before it gave up (a clone cut off by a weak Wi-Fi reads *clone failed (fatal: early EOF)*). The
form is back underneath to try again.

![An install that stopped, with git's reason and the lines before it](screenshots/network-install-stopped.png)

With **Open on its screen** on, the machine's own screen shows each step too. On a Pi with the
desktop it's a full-screen page that becomes Bento's Office once Bento answers; with no desktop
it's the console. A failed install leaves its reason up for five minutes, then gives the screen back.

![A Raspberry Pi's own screen while Bento installs, photographed on the Pi](screenshots/network-install-pi-screen.png)

`bento network install` prints the same steps as it reaches them.

![bento network install with the steps named as it goes](screenshots/network-install-terminal-steps.png)

A fresh install fetches Bento without the docs' screenshots, about 14 MB instead of 205 MB. The
pictures are for reading the guides on GitHub; nothing on the machine shows them.

### When it's done

Once it's installed, Bento sets the machine up by itself: the install gave it a key that only
works once. Everything is chosen here, in the Install form, so the machine asks nothing on its
own screen. It may be in another room, or another building. Until it's set up, its screen says
which Bento is setting it up and when it last heard from it.

![A Pi's own screen while its hub sets it up: nothing to answer there](screenshots/network-pi-waits-for-hub.png)

![The same waiting screen at phone width](screenshots/network-pi-waits-for-hub-phone.png)

At the Pi's terminal, `bento setup` says the same and how to set it up there instead.

![bento serve, bento setup and bento pool wait on a machine waiting for its hub](screenshots/network-pi-waits-for-hub-terminal.png)

Bento asks the machine directly as well as listening for it, so a firewall on this computer
can't leave it waiting to be heard. If a machine still says *Waiting to be set up*, press
**Look at the network**.

With **Open on its screen** on, Bento opens full screen there and again at every start.

![Bento open full screen on a Raspberry Pi after the install, photographed on the Pi](screenshots/network-pi-opens-bento.png)

Letting the page use the microphone without asking needs root. On a Pi whose `sudo` asks for a
password, Bento still opens on the screen, and the page asks for the microphone the first time.
Run `bento screen on` at a terminal on the Pi to allow it ahead.

![bento screen on, on a Pi whose sudo asks for a password](screenshots/network-pi-screen-on-terminal.png)

## Secure it

Open a row and press **Secure it**. Type the user there (the one set in Imager) and its
password, and press **Check it**. Bento logs in, reads which of the four steps are already in
place, and changes nothing. Each step that isn't shows why it matters and, under *What runs
there*, the exact command it will send.

![Check it: the four steps, each with what runs there](screenshots/network-secure-it.png)

| Step | What it does |
|---|---|
| Log in with this machine's key | Adds this machine's SSH key, so Bento can reach it with no password |
| Turn off password logins | A guessed or default password no longer gets anybody in, and root can't log in over SSH |
| Turn on a firewall | Only SSH and Bento answer, and only from your network and Tailscale |
| Install security updates by itself | Installs `unattended-upgrades` and switches it on |

**Paste your own SSH key first.** Once password logins are off, only keys get in, and that
includes you on your own computer. Put the one line from `~/.ssh/id_ed25519.pub` on your computer
in *Your own SSH key*, and it's let in before anything else runs. Without it, the confirmation
says your own password login is about to stop.

![Secure it with a box for your own SSH key](screenshots/network-secure-yourkey.png)

![The confirmation when no key of yours was given](screenshots/network-secure-warning.png)

Untick any you don't want, press **Secure it**, and confirm. The steps run in that order, and
three things keep it from locking Bento out:

- **Passwords go off only after the key has worked on its own.** Bento logs in again with the
  key alone first, and stops if that fails. After the change it waits until the key gets in
  again, because SSH restarts itself for a moment when it reloads.
- **The firewall undoes itself unless Bento can still log in.** It's loaded with a 90-second
  timer, and only a new login through it stops the timer. It also refuses to go on when the
  login doing it comes from an address the firewall would drop. If you reach the machine over
  SSH from the internet, that stops working; the step says so.
- **The firewall is its own table** (`table inet bento` in nftables, loaded at boot from
  `/etc/bento-firewall.nft`). Your own rules, and Docker's, are left alone.

![The machine after Secure it: its badge reads secured, with Disconnect beside it](screenshots/network-secured.png)

### Locked out after Secure it

If you secured a machine without your own key, your password no longer gets you in, but Bento's
key still does. Open the row, press **Security**, type the user and press **Check it**. Then:

- **Add my key**: paste your own public key first. Bento logs in with its key and adds yours.
- **Turn password logins back on**: Bento removes its own file from `/etc/ssh/sshd_config.d`
  and reloads SSH. The rest of SSH's settings stay as they were.

![Password logins are off: Add my key, or turn them back on](screenshots/network-letin.png)

![Add my key and passwords back on, on a phone](screenshots/network-letin-phone.png)

Installing Bento there still works with the password you always used: when it's refused, Bento
tries its own key before saying no.

On Raspberry Pi OS the first user needs no password for `sudo`. Where it does, the password
you typed is handed to `sudo` on its standard input, and never on a command line.

## Disconnect

**Disconnect** removes what ties that machine to this one. Each tie is its own tick:

- **a link**: your agents and its agents stop asking each other, and the permissions that named
  the link go (the same as *Remove* in Network & Teams);
- **its place in your community**: it stops thinking with this machine's brain;
- **this machine's SSH key on it**: Bento can no longer log in there without a password.

![Disconnect: the ties, each its own tick](screenshots/network-disconnect.png)

Bento stays installed on the other machine, and nothing else there is touched. Taking the key
off is refused when it's the only key there and password logins are off, because nobody could
log in over SSH afterwards and a Pi with no screen would need reflashing. Add your own key or
turn password logins back on first.

## What a Pi has

Every Pi set up from this hub tells it what hardware it has, and Devices lists it down to each
sensor. Open **⋯ → Hardware** on its row, or tap the count of things beside its address.

![Devices: a Pi 3 B+ and everything on it, each under its inventory name](screenshots/devices-hardware.png)

Each thing has an inventory name, the machine's name and an id: `raspberrypi/cpu.temp`,
`raspberrypi/power.throttle`, `raspberrypi/gpio.17`, `raspberrypi/usb.1-1.1.2`. That name is how
everything that comes later refers to it: its readings, who may read or set it, and the
provisioning profile it belongs to (`docs/design/devices.md`).

What is listed:

- the board: model, serial, memory, operating system;
- cameras: what `rpicam-hello` lists, and USB cameras. A Pi has ten `/dev/video` nodes and no
  camera; those are the chip's video codec and image processor, so they aren't listed;
- temperatures, the power state (under-voltage and throttling, now and since boot) and the core
  voltage;
- sensors a driver already exposes: 1-Wire thermometers, IIO sensors, hwmon chips;
- the 28 GPIO pins with their mode and level;
- I2C buses and the devices bound on them, SPI and serial ports;
- USB devices (hubs left out), microphones, speakers and audio outputs, input devices;
- network interfaces with their Wi-Fi signal, Bluetooth, load, free memory, free disk, uptime.

**When it's read.** Once a day, when the hub first sees the Pi, and within a minute of something
being plugged in or out: the Pi's hello every minute carries a short hash of what is plugged in,
and a different hash makes the hub read it all again. **Check now** reads it at once. The values
shown are what that read found; live readings come with the next step.

**What changed is an event.** Something found, something gone, and a Pi going under-voltage or
fine again each get a line in Events. A Pi on a weak power supply shows a warning at the top of
its hardware.

**Discovery only reads.** It lists `/sys`, `/proc` and `/dev`, and asks `rpicam-hello`,
`vcgencmd` and `pinctrl get` what they see. It never scans an I2C bus, opens a camera, sets a pin
or installs anything. A Pi answers only the hub that set it up, and every read is a line in both
machines' diaries and a `device.hardware` row in both ledgers. What the Pi sends is read field
by field on the hub: an unknown kind, a bad id or a value that isn't a number or short text is
dropped and named in the diary.

![The same hardware on a 390px phone: the power warning, then each thing with its inventory name above it](screenshots/devices-hardware-phone.png)

![bento hardware on a Pi, and bento network hardware on its hub](screenshots/devices-hardware-terminal.png)

## A sensor over time

Tap any reading in a Pi's hardware (a temperature, the power state, the Wi-Fi signal, a pin) and it
opens a chart of that reading over **a day, a week, 30 days or 90 days**.

![A Pi's CPU temperature over the last day, opened from its hardware](screenshots/devices-readings.png)

- The line is the mean and the faint band around it is the lowest to the highest in each slice.
  For a pin or the power state the line is a step: high or low, fine or not.
- What happened to the Pi in that range is marked on the line: something plugged in or out, power
  turning bad, stopping or starting to answer, an update. Hover a mark for what it was.
- Move along the line (or use the arrow keys) for the value at each moment. **Show the numbers**
  lists every point the chart draws.
- A break in the line is a time the hub had nothing from the Pi.

**How the readings get to the hub.** The Pi samples every 10 seconds and keeps the samples in
memory, never on its SD card. A pin is noted only when it changes. The hub collects them with the
hello it already sends every minute, so there is no new connection and nothing new to allow: these
are numbers discovery already reads. While the hub is away, the Pi keeps about an hour and a half
of samples and sends them when it's back. Anything older is lost, and Events says how many.
Sampling costs a Pi 3 about 0.4% of one core.

**How long they're kept.** On the hub, in `telemetry.db` beside the inventory: every sample for 7
days, a summary per minute (lowest, highest, mean) for 30 days, and per hour for 90 days. A day's
chart reads the samples, a week or a month the minutes, 90 days the hours. A sample equal to the
last one kept is kept again only after 5 minutes, which is most of a Pi's disk and voltage samples;
the summaries still count it. Times are the hub's: a Pi whose clock is off is moved onto it.

![The same chart on a phone, with the range buttons across the top](screenshots/devices-readings-phone.png)

![bento network readings in a terminal](screenshots/devices-readings-terminal.png)

## Reading and setting a Pi from the hub

Your agents use a Pi's hardware through two tools on the hub, **get** and **set**. Ask "what is the
Pi's temperature?" or "switch on pin 17" in any chat, including a forwarded one on Claude Code (it
sees them as `mcp__bento__device_get` and `device_set`).

Nothing can be used until you allow it. In Devices, open a Pi's **Hardware** and press **What agents
may use**. Each thing Bento can read gets a choice:

- **Off**: no agent, app or mission can touch it, and the Pi refuses it too.
- **Read**: your own agent may read it. A specialist, an app or a mission asks you the first time,
  and your answer can be remembered.
- **Read and set** (pins only): your agent may ask to switch it. You're asked every time it does,
  whatever your autonomy. When the request comes from the Pi's own screen, the question goes to your
  Telegram if it's connected, and to your screens here if not.

**Read now** beside an allowed item reads it on the Pi straight away.

![What agents may use on a Pi: Off, Read, or Read and set for each thing Bento can read](screenshots/devices-permits.png)

![What agents may use on a 390px phone: each item with its choice and Read now](screenshots/devices-permits-phone.png)

![Aria asks before switching pin 17, with her reason in quotes](screenshots/device-set-asked.png)

![After Allow, the pin is read back from the Pi](screenshots/device-set-done.png)

The Pi keeps its own list of what it lends and checks every request against it, so a hub that was
tricked still can't reach past it. Things Bento has no reader for yet (a camera, an I2C chip) are
listed but can't be allowed. A pin that is lent to a bus (I2C, SPI, a serial port) can't be set.

Every read and set travels over the link's encrypted connection with who asked and why, in the
agent's own words, and both machines write it in their diary and ledger. Devices → Events shows it.

From a terminal on the hub:

```
bento network get raspberrypi                 # what it has, and what may be used
bento network permit raspberrypi gpio.17 set  # read, set or off
bento network get raspberrypi cpu.temp        # read it now
bento network set raspberrypi gpio.17 1       # asks you first
```

![bento network get, permit and set on a hub](screenshots/devices-get-set-terminal.png)

## ESP32 nodes on a Pi

A Pi has a few pins. A cold room needs a thermometer, every dock door a contact and every fan a
relay, and those are usually ESP32 boards running [ESPHome](https://esphome.io). A Pi set up from this
hub can look after them: their sensors and switches become part of that Pi, so everything above works
for them too. They're on its hardware list, kept for 90 days, used only once you allow them, and
every set is asked.

In Devices, open a Pi's **Hardware** and press **ESP32 nodes**:

- **Find on its network** asks the Pi to listen for ESPHome nodes on its own network (mDNS). A node is
  heard when its YAML has `api:`. Finding one adds nothing.
- **Add** reads the node first, through its web server, and keeps it only if it answers. Give it a
  user and password if its `web_server:` has them; the password goes into the Pi's vault.
- **Remove** stops the Pi reading it. The node itself isn't touched.

![ESP32 nodes on a zone Pi: the two it looks after, Find on its network and Add node](screenshots/devices-esp32.png)

![The same on a 390px phone](screenshots/devices-esp32-phone.png)

Each sensor or switch is named `<pi>/esp.<node>.<kind>.<name>`, for example
`zone-cold/esp.cold-2.switch.compressor`. Sensors, contacts and text are read. Switches, lights and
fans can also be turned on or off, and a set is read back from the node before it counts as done.

The node needs `web_server:` in its YAML, because that's what the Pi talks to:

```yaml
api:              # how the Pi finds it
web_server:
  port: 80
  auth:           # optional
    username: admin
    password: !secret web_password
```

ESPHome's web server is plain HTTP, and its password is sent with every request, so anybody on that
network can read it and switch things. Keep the nodes on a network of their own: the Pi's own Wi-Fi
or a VLAN.

From a terminal on the hub:

```
bento network esp zone-cold                         # the nodes it looks after
bento network esp zone-cold find                    # who answers on its network
bento network esp zone-cold add cold-2 10.0.4.12    # read it, then keep it
bento network esp zone-cold add dock-1 10.0.4.20 --user admin   # asks the password
bento network permit zone-cold esp.cold-2.switch.compressor set
bento network set zone-cold esp.cold-2.switch.compressor 1
```

![bento network esp, get and set on the hub: a door contact can't be set](screenshots/esp32-terminal.png)

### A warehouse, as it was tested

`packaging/dev/warehouse/run.py` stands a warehouse up on one computer: a hub, three zone Pis set up
from its one line (cold rooms, the loading dock, the aisles) and six ESP32 nodes speaking ESPHome's own
API and mDNS (`esp_sim.py`). Each zone finds only its own nodes. Nothing is readable until the hub
allows it, and the zone refuses until then. Asked to walk through the warehouse, the hub's agent reads
seven things across three zones. When cold room B's compressor trips, the agent reads the room, the
door and the compressor, asks to switch it back on, and the room starts cooling after a person says
yes. A set nobody says yes to isn't made.

![Aria reads cold room B's temperature, door and compressor, then asks to switch the compressor on](screenshots/esp32-set-asked.png)

![After Allow, the compressor is on, read back from the node](screenshots/esp32-set-done.png)

## Hidden machines

**Hide** (behind ⋯, or on a row under New machines) moves a machine to **Hidden** under the
list. Heard again, it stays there and you get no toast. Nothing about it is forgotten: open
Hidden and press **Show again**, and it's back as it was, with its name and security. A Bento
machine hidden from New machines goes back to waiting to be set up.

![Hidden, opened: each machine with Show again](screenshots/network-hidden.png)

![Hidden opened on a phone, each machine with Show again](screenshots/network-hidden-phone.png)

![bento network: the hidden ones named under the list, then hide and show](screenshots/network-hidden-terminal.png)

The count at the top is of the machines listed, not the hidden ones.

## A reformatted machine

Bento remembers each machine's SSH key the first time it logs in, and refuses a machine whose
key has changed, because that is also what a machine pretending to be yours looks like. A Pi you
reformatted or reinstalled has a new key, so *Check it* stops there and shows both keys: the one
Bento remembered and the one the machine shows now. If you did reformat it, press **It was
reformatted: forget the old key**. Bento asks once more, forgets it, and checks again, and the
new key is remembered from then on.

![Check it on a reformatted Pi: refused, with the old and new keys and the button](screenshots/network-rekey.png)

![The same refusal on a phone, the two keys wrapped under Check it](screenshots/network-rekey-phone.png)

In a terminal the refusal names the command, `bento network rekey MACHINE`, which shows both keys
and asks before it forgets.

![bento network check refused, rekey, then check gets in](screenshots/network-rekey-terminal.png)

Only Bento's own list of keys changes (`~/.agentos/pki/known_hosts`, kept as it was in
`known_hosts.old`). Your own `~/.ssh/known_hosts` is left alone.

### Controls, and removing Bento

Every machine with Bento has **Controls**. Type the user there and press **Read its switches**:
Bento logs in (with this computer's key if it's there, or the password you type) and reads
what's on. Nothing changes until you press a switch.

- **Bento running**: its background service. Off stops Bento there and closes it on its screen;
  on starts it again, back on its screen if that switch is on.
- **Open on its screen**: Bento full screen on its display, now and at every start. Off closes it
  now. Its desktop may still open Bento as an ordinary window at login, if it was installed that way.
  Turning it on needs root there once, to let its page use the microphone. When you typed the
  machine's password, it's handed to sudo there for that one command (over SSH, never on the
  command line). With a key login and a sudo that wants a password, it says so.
- **Listening**: the kiosk face, the Office with the microphone on.
- **Big code to the hub**: whether it may hand heavy Python here (below). This one is a
  permission on this computer, so it needs no login.
- **Update Bento there** runs `bento update` on it and reads the version after.

Each switch shows the line it runs under *What runs there*, and after it runs, the state is
read again: the tab says what is true, not what was asked for. What was read is kept in the
list with when, under the machine's name.

**Remove Bento** stops everything of Bento's that runs there (the service, a server started by
hand, its screen, an installer still going) and takes the program off: the service and its
overrides, the launcher, every autostart entry and the code. Its memory and settings in
`~/.agentos` are set aside as `~/.agentos-removed-<date-time>`, never deleted. It then checks and
names anything that's still there. On this computer it ends the link, its place in your
community, and what was heard and set up at that address, so **Install it again** sets it up as a
new machine. This computer's SSH key stays on it; Disconnect takes that off. `bento network remove`
does all of it from a terminal.

![Three moments from removing and adding back a Raspberry Pi 3 from the hub with bento network remove and install: the Pi's desktop with Bento gone, its screen during the install, and the kiosk Office afterwards](screenshots/network-remove-add-pi.png)

**Install it again** stays on the row after an install stops, so you can just try again. A scan
where the machine didn't answer for a moment doesn't take it away, and a machine you've logged
into before keeps it. If the installer finds no internet while the machine is on Wi-Fi, it names
the network and says to try again: a weak signal drops out for a moment. It also checks twice,
a few seconds apart, before it stops.

![A Pi whose install stopped, with Install it again on its row](screenshots/network-install-again-desk.png)

![The same row at phone width, Install it again a full-width button](screenshots/network-install-again-phone.png)

The install form puts the user, password and agent's name in one row, the choices under them,
and what **Check it** found in a card (the board, its memory, its SSH key, and *What runs there*
folded away). **Check again** and **Install Bento there** come last, at the same height.

![The install form after Check it on a Raspberry Pi 3 B+, with Install Bento there](screenshots/network-install-form-desk.png)

![The install form at phone width, both buttons full width](screenshots/network-install-form-phone.png)

While it installs, the card shows what the machine prints, live: the installer's steps and the
lines from git, uv and apt under them, kept at the newest line. The installer runs on its own
there and writes `~/.cache/bento-install/install.log`, and this computer follows that log. If
the connection drops (a busy Pi, a weak Wi-Fi signal), the install carries on there, and the
card says so and picks the log up again from where it was. Installing again stops an earlier
installer that's still running there.

![An install running, its console showing a dropped connection picked up again](screenshots/network-install-console-desk.png)

![The live console at phone width, at its newest line](screenshots/network-install-console-phone.png)

![The Devices app: every machine, and a Pi's switches as read from it](screenshots/devices-controls-desk.png)

![A Pi's controls at phone width, each switch a full-size button](screenshots/devices-controls-phone.png)

![bento network controls and switch on a real Pi, every switch put back afterwards](screenshots/devices-switches-terminal.png)

![The Pi's own screen with Bento running and Open on its screen both off: its plain desktop](screenshots/devices-pi-off.png)

The **Devices** app in the dock is the same list in a window of its own, with a map above it:
this computer in the middle with your agent, each machine with Bento around it with its own
agent, and the rest of the network as small dots. A solid line is a link or your community; a
dashed one is Bento with no tie to this computer yet. A green ring is running. Tap an agent to
open its machine's Controls.

![The device map: your agent in the middle, Mr. Pi on the Raspberry Pi](screenshots/devices-map-desk.png)

![The device map at phone width](screenshots/devices-map-phone.png)

![The Devices app listing the machines on the network](screenshots/devices-list-desk.png)

### Its agent's look

Controls shows its agent with **Change its look**, which opens the same editor as the Agents
tab: skin, hair, style, colour, what it wears, trousers and extras, or describe it in words and
its own designer picks. Your choices show on the figure as you make them and go to that machine
when you press **Save there**. It changes there (its screen and its Office) and on the map here.

![Mr. Pi's card in a Pi's Controls, with Change its look](screenshots/devices-look-desk.png)

![The agent editor open for Mr. Pi, with the bun picked and not saved yet](screenshots/devices-look-editor-desk.png)

![The agent editor for Mr. Pi at phone width, scrolled to Save there](screenshots/devices-look-phone.png)

![The map after Mr. Pi's hair was made pink from here](screenshots/devices-map-new-look.png)

### Passwords

A password you type for a machine can be remembered: tick **Remember it** and, once it has
logged in, it's kept in this computer's vault, encrypted. Leave the box blank next time and it's
used. It changes only when you type a new one and tick **Replace the saved one**, and **Forget
the saved one** removes it. Nothing ever shows it again, here or anywhere else.

![The Devices app at phone width: the same list, one machine per card](screenshots/devices-list-phone.png)

### Code too big for it

A Pi runs small code itself. When an agent's Python on a machine set up from here runs past a
minute or needs more than 512 MB, Bento hands it to this computer and brings the answer back.
An agent can also send heavy work straight here (`where: "hub"`).

Only the code and the one folder it names come over. Here it runs in a sandbox of its own: no
network, nothing of this computer visible but its system files, 2 GB of memory, 15 minutes,
lower priority than everything else, one run at a time. The files it made or changed go back
into that folder on the Pi, and the sandbox's folder is deleted. A computer without bubblewrap
runs none.

Setting a machine up allows it, as a grant in *Permissions* (`team:<machine>/*`, `code.run`).
Revoke it there to stop it; the Pi then gets a sentence saying so. Every run is a ledger row.

![On the Pi itself: small code stays, a 1 GB array and a 90 s loop hit the Pi's limits](screenshots/network-edge-limits-pi-terminal.png)

![A hub and a Pi on real servers: small code here, slow code on the hub, its file back, then revoked](screenshots/network-edge-code-run-terminal.png)

### This computer's firewall

Machines set up from here reach this computer on two ports: 8322 (TCP) to join and hand work
over, and 8620 (UDP) to be heard. When ufw or firewalld is on, the tab says so with **Open
them**, which asks for your password. Bento can't read the rules without root, so if you
opened them yourself, press **I opened them**.

![This computer's firewall is on: the ports machines set up from here need](screenshots/network-firewall.png)

![The firewall row at phone width, with both buttons full size](screenshots/network-firewall-phone.png)

![bento network firewall in a terminal](screenshots/network-firewall-terminal.png)

## From a terminal

```sh
bento network                                   # the list, with each machine's ties
bento network look                              # look at the network, as the tab's button does
bento network install 192.168.1.40 --user ada   # checks it, shows what runs, asks, installs
bento network install pi-kitchen --user ada --authorize   # and lets this machine's key in
bento network install pi-kitchen --user ada --agent-name Chef --kiosk   # named, and opens on its screen
bento network check 192.168.1.40 --user ada     # which steps are in place; changes nothing
bento network secure 192.168.1.40 --user ada    # shows what runs, asks, then runs it
bento network secure pi-kitchen --user ada --your-key ~/.ssh/id_ed25519.pub
bento network letin pi-kitchen --user ada --your-key ~/.ssh/id_ed25519.pub   # locked out: add your key
bento network letin pi-kitchen --user ada --passwords-on                     # or passwords back on
bento network secure pi-kitchen --steps key,passwords
bento network disconnect pi-kitchen --what key  # or community, or link:NAME
bento network label 192.168.1.40 "Kitchen Pi"
bento network hide 192.168.1.40                 # to Hidden (forget does the same)
bento network show 192.168.1.40                 # back on the list
bento network rekey pi-kitchen                  # it was reformatted: forget its old SSH key
bento network events [pi-kitchen]               # what happened to the machines here
bento network hardware [pi-kitchen] [--check]   # what a Pi has, down to each sensor
bento network readings pi-kitchen cpu.temp --range quarter   # one sensor over 90 days (day, week, month)
bento network esp pi-kitchen [find|add NAME ADDRESS|remove NAME]   # the ESP32 nodes it looks after
bento hardware                                  # on the Pi itself: what this machine has
bento network map                               # the logical map: lead, companies, departments, people
bento network talks studio Sales                # who a team or Zero talks to here, and what it gives it
bento network firewall                          # this computer's firewall, and the ports to open
bento network firewall open                     # open them (asks for your password)
bento network controls pi-kitchen --user pi     # read its switches
bento network switch pi-kitchen screen off --user pi    # running, screen, listening or code; on|off
bento network update pi-kitchen --user pi       # bento update there
bento network remove pi-kitchen --user pi       # Bento off it; its data stays
```

![bento network in a terminal: the list, and how secure each machine was measured](screenshots/network-terminal.png)

![bento network look and install: a keys-only Pi refused in a sentence, then an install](screenshots/network-install-terminal.png)

`install` uses the SSH port the scan found, and an address that isn't on the list yet works too.
`secure` and `letin` use the key in `~/.ssh` on the machine you type them on when you don't name one.

![Secured without a key of yours, installed anyway, then let back in, in a terminal](screenshots/network-letin-terminal.png)

A password is read without echo, or from standard input with `--password-stdin`. A link is
ended by the running server, so the terminal points you to the tab or `bento link remove`.

## The three faces

- **Desktop:** *Settings → Network*. On a phone the actions reflow into two columns of full-size
  buttons.
- **Terminal:** `bento network`, as above, and `bento network ties` for teams and Zeros.
- **Session UI:** the same page; nothing here touches the compositor. A Zero has no Network
  tab: its network is its hub's business.

## The ledger

Every step is a row: `device.scan`, `device.check`, `device.secure`, then `device.secured` or
`device.secure_failed`, `device.disconnect`, `device.forget` (hidden), `device.show`, `device.rekey` (an old SSH key
forgotten), `network.firewall`, `provision.code` (a machine may hand code here) and `edge.code`
(one run, with what went in and came back), `device.controls`, `device.switch`, `device.update` and
`device.remove`, `device.moved` (a machine followed to its new address), `device.hardware`
(its hardware read, on both machines) and `device.esp` (an ESP32 node found, added or removed, on
both machines; never with its password).

## What was tested, and what wasn't

- `tests/test_esp_nodes.py` and `packaging/dev/warehouse/run.py`: ESP32 nodes against a stand-in that
  speaks ESPHome 2026.6's web server API and mDNS, as read from ESPHome's source. A node is kept only
  after it answers, its password stays in the vault, a contact can't be set, a set is read back (a
  relay that doesn't move is an error), and found isn't added. No real ESP32 was used: the protocol is
  ESPHome's, the boards are simulated.

- `tests/test_pi_readings.py`: the Zero's buffer (numbered, a pin only when it moves, a restart
  starts over, a long absence sent in pieces with what was lost said), the hub's store (shifted onto
  its clock, a batch sent twice kept once, a bad id or value dropped), a 90-day range at most 360
  points from the hour summaries, retention, and readings riding a real mTLS hello from a Zero to its
  hub. Sampling was timed on the real Pi 3 B+: 45 ms a sample.

- `tests/test_pi_hardware.py`: discovery over a Pi's `/sys`, `/proc` and `/dev` as a real Pi 3 B+
  on trixie laid them out, with its tools' real answers (an under-voltage, 28 pins, no camera
  behind ten video nodes); a USB camera plugged in moves the hello's hash and is listed as a
  camera; a reading never counts as a change; what arrives is read field by field; and a hub and a
  Zero over real mTLS, where the Zero answers only its own hub and the hub keeps the answer on the
  Zero's inventory row. Discovery itself was run on that Pi (1.4 s). A Pi answering its live hub
  over the link needs both on 0.7.0, so that part runs on the owner's machines after the update.

- `tests/test_device_moves.py`, two machines on real mTLS: a Pi heard from a new address is
  followed there, one that stopped answering is found where it is, and a different certificate at
  the new address moves nothing. A name is never rewritten, and a real address never becomes a
  loopback one. The watch says offline only after two misses, and back on a new version a Zero's
  screen is refreshed.
- `packaging/dev/provision-e2e/dhcp_run.py`, two real `bento serve`s: the hub's record of the Pi
  is pointed at an address where nothing answers, and the hub follows the Pi back, both from the
  Pi's hello and by looking; then the Pi is stopped and started, and Events says so. Finding a Pi
  by its network card or its `.local` name needs a real LAN and wasn't run here.

- `tests/test_network.py`, with a stand-in `ssh` playing a Pi whose state changes as each step
  runs: what runs is what was shown; the password never reaches a command line; `sudo` gets it
  only when it needs it; passwords go off only after a key-only login; every later login uses
  the key; a slow SSH reload is waited for; the firewall is kept only by a new login; the key
  can't be taken off when it's the only way in; the list folds every source into one row.
- `packaging/dev/network-e2e/run.py`, against a real machine: a container with a real OpenSSH
  server, `sudo` and nftables, user `pi` with a password, and an SSH configuration with no
  `Include` line, as Buster ships it. Bento found it, checked it and secured it. Then, measured
  from outside: a password login was refused, the key got in, a port nobody allowed (9999)
  stopped answering while SSH still did, and 95 seconds later the firewall was still on.
  Disconnect refused to take the only key off, then took it off once another key was there.
  The run found that SSH briefly refuses logins right after it reloads; Bento now waits for it.

Not tested: a real Raspberry Pi, and Raspberry Pi OS's own `systemctl reload ssh`. The container
has no systemd, so the reload there came from the `ssh` init script.
