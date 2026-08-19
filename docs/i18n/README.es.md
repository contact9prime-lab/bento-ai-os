# Bento Box AI — un sistema operativo con agentes, local por diseño

<p align="right"><sub>
<a href="../../README.md">English</a> ·
<a href="README.zh-CN.md">简体中文</a> ·
<a href="README.zh-TW.md">繁體中文</a> ·
<a href="README.ja.md">日本語</a> ·
<a href="README.ko.md">한국어</a> ·
<b>Español</b> ·
<a href="README.pt-BR.md">Português&nbsp;(BR)</a> ·
<a href="README.fr.md">Français</a> ·
<a href="README.de.md">Deutsch</a> ·
<a href="README.ru.md">Русский</a> ·
<a href="README.hi.md">हिन्दी</a> ·
<a href="README.ar.md">العربية</a>
</sub></p>

**Tu máquina, con un cerebro.** Bento Box AI es un **entorno de escritorio con IA** autoalojado: un
escritorio completo — ventanas, apps, archivos, terminal — impulsado por un **agente de IA autónomo**
que realiza **acciones reales** en tu computadora. Usa modelos locales mediante [Ollama](https://ollama.com)
para una privacidad total, o modelos en la nube (Anthropic Claude, OpenAI, OpenRouter, o cualquier
endpoint compatible con OpenAI) — siempre con tu aprobación. El agente puede navegar, construir sus
propias apps, programar trabajos, recordar lo que aprende, extender su propio código fuente y
localizarte en Telegram o WhatsApp.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Plataformas](https://img.shields.io/badge/platform-Linux%20·%20macOS%20·%20Windows-lightgrey)
![Local por diseño](https://img.shields.io/badge/AI-local--first%20·%20Ollama%20·%20cloud%20optional-5eead4)

Se ejecuta en `http://127.0.0.1:8321` — privado por defecto, instalable como servicio al arranque.

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh
```

![Bento Box AI en movimiento — pidiéndole al agente un resumen matutino y obteniendo una respuesta en vivo, apilando ventanas y alternando entre cinco lenguajes de diseño](../screenshots/demo.gif)

<sub>▶ [Ver el clip completo (MP4)](../screenshots/demo.mp4) — un turno real respondido en el dispositivo; la respuesta del chat de arriba es el agente en vivo, no una maqueta.</sub>

![El escritorio de Bento Box AI — chat con el agente de IA, gestor de archivos y ajustes rápidos en un entorno de escritorio basado en navegador](../screenshots/desktop.png)

**La documentación completa está en [`docs/`](../README.md)** — instalación, una guía de usuario del
escritorio y de cada app, el agente y sus herramientas, la creación de apps, integraciones, la
referencia de la API y resolución de problemas.

---

## La configuración son nueve pasos, y cada uno deja algo tras de sí

No es un formulario de ajustes con una barra de progreso. Cada paso **produce algo real** — un modelo
que responde, un agente que existe, un flujo que se ejecuta, una programación que se dispara — y dice
con qué acabarás antes de pedirte nada.

![La pantalla de configuración inicial: un riel de nueve pasos a la izquierda, y a la derecha "Ponle nombre a tu agente" con la línea "Acabarás con: el nombre en la barra de menú y en cada respuesta"](../screenshots/onboarding-1-name.png)

Cada paso se **sondea, nunca se recuerda**: se marca porque la máquina tiene la cosa. Elimina el agente
y el paso vuelve a pendiente. Eso es lo que hace seguro volver a ejecutarlo — y volver a ejecutarlo es
algo normal aquí, porque **la Configuración también es una app**. Ábrela en cualquier momento para ver
qué hace un paso, en una máquina que configuraste hace meses.

![La app de Configuración en una ventana: el riel de nueve pasos a la izquierda, y el paso "Construir un especialista" abierto a la derecha](../screenshots/setup-app.png)

El mismo catálogo, el mismo sondeo, los mismos paneles — incluso en una terminal, donde `bento setup`
por SSH retoma exactamente donde el navegador lo dejó.

---

## Lo primero que te pregunta es qué trabajo hacer

La configuración termina en una pregunta, no en una puerta: **dame un trabajo.** Elige uno de tres,
responde dos preguntas, y esta máquina está haciendo algo por ti antes de que hayas abierto una sola app.

![La pantalla de Trabajos: tres recetas — resúmeme cada mañana, vigila una carpeta, avísame cuando cambie una página — con las preguntas de la elegida y exactamente lo que se le permitirá hacer](../screenshots/jobs.png)

| | |
|---|---|
| **Resúmeme cada mañana** | se informa durante la noche sobre las cosas que sigues y deja una página esperando |
| **Vigila una carpeta por mí** | nota lo que llega a una carpeta *que tú elijas*, averigua qué es y te lo dice |
| **Avísame cuando cambie una página** | revisa una página y habla solo cuando algo real ha cambiado |

Dos cosas que no hará. No se concederá nada que no hayas visto: el panel imprime los permisos exactos
antes de que pulses el botón, calculados por el mismo código que los escribe — "lee `~/Downloads/*`, y
nada más". Y no ofrecerá una forma de localizarte que no funcione: un Telegram sin vincular se muestra
atenuado con la frase que lo arreglaría, nunca oculto y nunca sustituido en silencio.

El último botón es **"Ejecútalo ahora, para que pueda verlo funcionar"** — porque una programación que no
has visto dispararse es una promesa, y un usuario nuevo no tiene motivos para creer una.

Un trabajo es un *flujo*, no un tipo nuevo de cosa: el mismo programador, la misma puerta de permisos, el
mismo registro de auditoría. En una caja sin pantalla: `bento job recipes`, y luego
`bento job add morning-brief --topics "…"`.

---

## Tres caras, un programa

Bento se ejecuta en tres lugares, y **cada función está construida para los tres**. Esta es la primera
pregunta que se le hace a cualquier cambio, no la última.

| | Qué es | Cómo iniciarlo |
|---|---|---|
| **GUI** | una ventana (o pestaña) en macOS, Windows o Linux. Nada extra que instalar | `bento` |
| **TUI** | todo el SO en una terminal — para un servidor, o una Pi sin pantalla por SSH | `bento tui` |
| **SUI** | Bento **es** tu sesión de Linux: es dueño de la máquina | `bento installer` |

> El comando es `bento`. `agentos` sigue funcionando y siempre lo hará — está en el historial de la shell
> de la gente, en unidades systemd y en scripts, y un cambio de nombre que elegimos no debería costarles eso.

---

## Míralo en acción

| | |
|---|---|
| ![Chat con el agente de IA — respuestas en streaming, llamadas a herramientas y aprobaciones](../screenshots/chat.png) **Agent Chat** — habla con tu máquina; respuestas en streaming, tarjetas de herramientas, aprobaciones, voz | ![App de equipo — subagentes, flujos de trabajo y observabilidad](../screenshots/team.png) **Team** — subagentes especialistas y flujos de trabajo visuales, con mezcla de modelos por paso |
| ![App de documentación integrada mostrando el manual completo](../screenshots/docs.png) **Docs** — el manual completo vive dentro del SO | ![Tienda de apps — apps de un clic, skills y canales MCP](../screenshots/store.png) **Store** — apps de un clic, skills y canales de herramientas MCP |

### Varias personas, una máquina

Añade una cuenta y cada persona obtiene **su propio hogar** — su propia base de datos, memoria, agentes,
canales, servidores MCP y credenciales. No una columna `user_id` que una cláusula `WHERE` olvidada filtre:
su propio directorio, porque dos archivos no pueden filtrarse el uno en el otro.

![La app de Usuarios: dos cuentas, Ada Lovelace marcada como admin y "este eres tú", Bob Kahn con un desplegable de rol puesto en Ejecutor](../screenshots/users-two-accounts.png)

Dos roles — **ejecutor** (todo dentro de su propio hogar) y **admin** (eso, más la máquina). Los ajustes
permanecen compartidos, así que hay una clave de proveedor para la máquina en lugar de una por persona.
Los agentes y las apps se cruzan deliberadamente, como copias, a través de una biblioteca compartida.

Y es **un inicio de sesión, aquí y desde cualquier parte**: una máquina con cuentas queda bloqueada por
ellas, así que el teléfono en el bolsillo de alguien usa el mismo usuario y contraseña que el escritorio y
aterriza en su propio hogar. No hay una segunda frase de contraseña compartida que inventar, compartir u
olvidar.

![El panel de Acceso remoto que dice "Bloqueado por las cuentas de esta máquina — todos inician sesión desde su teléfono con el mismo usuario y contraseña que usan aquí"](../screenshots/remote-locked-by-accounts.png)

### Puedes ver lo que está haciendo

![Un turno en marcha: la llamada Read finalizada conservó su duración, la llamada Bash en ejecución envejece en su sitio, y la fila de abajo dice en qué paso está y cuánto ha tardado el turno](../screenshots/agent-working.png)

Un turno es en su mayor parte esperar, y "trabajando…" durante cuatro minutos no te dice nada — un modelo
pensando y una ejecución que ha muerto en silencio se ven idénticos bajo eso. Cada superficie de espera
dice **en qué está y por cuánto tiempo**: la llamada en ejecución envejece en su sitio (`running · 2m 14s`),
las llamadas terminadas conservan su duración, y la fila de abajo lleva el paso y el total del turno. La
misma frase aparece en la burbuja de presencia y en la omnibarra, así que se puede responder desde el
escritorio sin abrir el chat.

### Puede construir su propio equipo — y pregunta antes de hacerlo

![Aprobando una delegación: la tarjeta nombra al agente, el modelo, el presupuesto de pasos y de tiempo, y las herramientas y skills exactas que tendría](../screenshots/agent-approval.png)

Cuando ningún especialista existente encaja, el agente **construye uno** y le delega. Definir un agente no
le concede nada; la primera vez que se usa de verdad obtienes una tarjeta que nombra el modelo en el que se
ejecuta, su presupuesto y las herramientas y skills exactas que le da su definición — porque el
consentimiento a un actor que no puedes imaginar es consentimiento solo de nombre. Aprobar `researcher` no
es aprobar `deploy-bot`, y la concesión es revocable en Permisos como cualquier otra. [Cómo funciona →](../security.md)

### Responde preguntas sobre sí mismo desde su propio manual

![La app Docs respondiendo una pregunta sobre este SO, fundamentada en el manual](../screenshots/docs-ask.png)

El manual está en el índice de recuperación, así que "¿cómo impido que una app llegue a internet pero la
mantengo funcionando?" se responde desde **estas páginas**, no desde la memoria que un modelo tiene de un
proyecto diferente — y la respuesta nombra la página que usó. Es recuperación con agente en vez de una
búsqueda de un solo paso: el agente busca, lee y vuelve a buscar cuando el primer intento no acierta.

### Ventanas que se comportan como ventanas

![Cuatro ventanas de Bento apiladas en el escritorio: la enfocada lleva un anillo de acento y la sombra completa, el resto se retiran](../screenshots/windows.png)

Una ventana se abre **donde la dejaste** — la posición y el tamaño se recuerdan por app — y una ventana que
se abre por primera vez cae en cascada por más de una barra de título, así que la de abajo sigue siendo
legible. La ventana enfocada lleva un anillo de acento y la sombra completa; las demás se retiran. El ✦ de
la barra de título es el agente *dentro de esa app*: pregúntale sobre lo que hay en pantalla sin salir de
ella.

### Cinco lenguajes de diseño, no cinco paletas

![Los cinco temas de lenguaje de diseño integrados: Bento, Liquid Glass, Spatial, Claymorphism, Minimalism](../screenshots/themes.png)

**Bento · Liquid Glass · Spatial · Claymorphism · Minimalism.** Cada uno recorta de nuevo toda la carcasa —
superficies, radios, elevación, desenfoque, tipografía — y trae su propio fondo de pantalla. Los fondos se
distribuyen como SVG: unos pocos KB cada uno, nítidos desde un teléfono hasta un panel 4K. [Más →](../desktop.md#themes)

El cristal es lo más caro que un escritorio puede dibujar, y el coste se acumula con cada ventana que abres.
**Themes → Effects** mide tu máquina y lo reduce solo si tiene que hacerlo — cinco ventanas en Liquid Glass
pasaron de 6.5fps a 27 (reducido) o 60 (apagado).

### Te localiza donde ya estás

![El canal de WhatsApp en Ajustes: los cuatro campos de la Cloud API, la URL de callback para pegar en la consola de Meta, el número vinculado, y si la ventana de 24 horas está abierta](../screenshots/channels-whatsapp.png)

**Telegram y WhatsApp son canales nativos** — la misma conversación, la misma memoria, las mismas
herramientas y los mismos botones de aprobación que en el escritorio. No es un puente de notificaciones: una
respuesta desde tu teléfono continúa el hilo que empezaste esta mañana.

WhatsApp tiene **dos transportes**, y fallan en direcciones opuestas. La Cloud API de Meta es oficial pero
necesita una cuenta de desarrollador y un webhook público, y fuera de las 24 horas desde tu último mensaje no
transportará una respuesta de formato libre en absoluto — la tarjeta dice si esa ventana está abierta, un
envío que no puede completarse lo dice y cómo arreglarlo, y un trabajo programado guarda su informe primero
para que nada se pierda. El enlace de WhatsApp Web necesita solo un escaneo de QR y no tiene ventana de 24
horas, pero es **no oficial** y Bento lo dice en la tarjeta de instalación antes de que se descargue nada.
[Configuración →](../whatsapp.md)

Telegram es también una **consola de administración**: `/agents`, `/run`, `/flows`, `/model`, `/logs`,
`/perms` — solo el propietario, y cada comando que *hace* algo pasa por la misma puerta de permisos y los
mismos botones de aprobación que el escritorio, así que nunca es una vía de entrada más barata. [Comandos →](../integrations.md)

### Un escritorio, cada pantalla

![Bento Box AI en un teléfono: la pantalla de bloqueo, el escritorio dispuesto para un teléfono, y una app como una hoja a sangre completa](../screenshots/mobile.png)

Teléfono, tablet, estación de trabajo — el mismo escritorio, adaptándose. Las ventanas se convierten en
hojas a sangre completa, el dock abarca el borde inferior, los popovers se convierten en hojas. Activa el
**Acceso remoto** y alcánzalo desde tu teléfono por tu red, tras una frase de contraseña; *Añadir a la
pantalla de inicio* lo convierte en una app a pantalla completa. [Acceso remoto →](../remote-access.md) ·
[Diseño adaptable →](../desktop.md#phone-tablet-desktop)

### Puede *ser* el escritorio, no solo vivir en uno

![Una aplicación nativa de Wayland sobre el escritorio de Bento, con la barra de menú reservada arriba y el dock reservado abajo](../screenshots/session-native-window.png)

Inicia sesión y obtén Bento como tu sesión de Linux. El escritorio se dibuja como una **superficie de capa
de Wayland en la capa de fondo**, así que las ventanas de las aplicaciones nativas están por encima de él en
el orden de apilamiento normal — no porque algo se eleve o se baje, sino porque eso es lo que "fondo"
significa. La barra de menú y el dock se asientan en bandas **reservadas con el compositor**, el mismo
mecanismo que usa un panel de GNOME o KDE, así que una app a pantalla completa se detiene en sus bordes en
lugar de tragárselos.

![Dos terminales nativas ajustadas a las mitades izquierda y derecha del escritorio de Bento](../screenshots/session-snapped.png)

Gestión de ventanas completa para apps nativas: ajustar a mitades y cuartos, mosaico, flotante, disposiciones,
redimensionar con teclado, escritorios virtuales, minimizar, y un selector Alt-Tab — con la barra de tareas y
la barra de menú siguiendo a la app que tenga el foco. [La interfaz de sesión →](../session-ui.md)

### Instala aplicaciones, desde dentro de Bento

![La app Aplicaciones buscando en el catálogo de paquetes de la máquina, con botones de instalación por resultado](../screenshots/app-store.png)

Un escritorio en el que no puedes instalar software es una demo. *Aplicaciones → Obtener apps…* busca en el
catálogo propio de la máquina — AppStream, Flatpak o apt — y te muestra el comando exacto antes de
ejecutarlo. Se prefiere Flatpak donde existe porque una instalación por usuario no necesita contraseña en
absoluto. Bento no replica nada ni empaqueta nada; le pregunta al gestor de paquetes que ya tienes.

### Tu pantalla real, en tu teléfono, en el navegador

![El Escritorio Remoto de Bento abierto en el navegador de un teléfono, mostrando la pantalla real de la máquina con una app nativa y una barra de herramientas con teclas que le faltan al teclado de un teléfono](../screenshots/phone-remote-desktop.png)

El **Acceso remoto** te envía la carcasa de Bento, que es HTML y viaja perfectamente — pero una app nativa
son píxeles en la propia pantalla de la máquina y nunca formó parte de la página. El **Escritorio Remoto**
cierra esa brecha: Bento retransmite la pantalla por su *propia* conexión autenticada, así que obtienes el
escritorio real, en el que se puede hacer clic, sin ninguna app de VNC que instalar en el teléfono.

La forma es el punto clave — el servidor VNC permanece en `127.0.0.1` y nunca se acerca a la red; lo que lo
protege es la frase de contraseña que ya usas. [Acceso remoto →](../remote-access.md)

### Automatizaciones y esquinas activas

![La app de Automatizaciones con rutinas guardadas y el mapa de esquinas activas, y el constructor de pasos](../screenshots/automations.png)

Nombra una secuencia una vez — abre estas apps, cambia de tema, ejecuta este Python, llama a esa herramienta
MCP, pon al agente en una tarea — y ejecútala para siempre después desde la barra de comandos, una esquina
activa, una programación, o pidiéndola por su nombre. [Más →](../desktop.md#automations)

---

## Por qué Bento Box AI

- **Un escritorio de verdad, no una caja de chat** — ventanas arrastrables, barra de tareas, escritorios
  virtuales, widgets, temas, una paleta de comandos, y más de 25 apps integradas.
- **Un agente con manos** — comandos de shell, gestión de archivos, investigación web, notificaciones de
  escritorio, trabajos programados, informes HTML y creación de apps, todo desde lenguaje llano.
- **Local por diseño y privado** — todo puede ejecutarse en tu hardware con Ollama; nada sale de tu máquina
  a menos que añadas una clave de nube. Se vincula solo a localhost, hasta que actives deliberadamente el
  [acceso remoto](../remote-access.md) protegido por frase de contraseña.
- **Todo el ciclo de vida bajo un mismo techo** — **Entrenar · Probar · Operar · Construir · Publicar ·
  Gestionar**, en vivo en una sola pantalla (Mission Control): ajusta tus propios modelos en tu GPU,
  somete a prueba cada automodificación, ejecuta trabajos programados, construye apps y publícalas en GitHub.
- **Autoextensible** — el agente construye nuevas apps de interfaz para sí mismo (App Studio), instala skills
  y servidores de herramientas MCP, y puede modificar el propio código fuente de Bento (con auto-instantáneas
  y una suite de pruebas que debe pasar antes de un reinicio).
- **Memoria que se acumula** — memoria de dos niveles, un grafo de conocimiento en vivo, y un "alma"
  persistente, aprendida automáticamente después de cada conversación.
- **Seguro por diseño** — niveles de autonomía, avisos de aprobación, políticas de permitir/denegar, un
  sandbox de carpetas con bubblewrap, comandos destructivos bloqueados de forma dura, y puntos de restauración
  de un clic.

---

## Inicio rápido

**Un comando, en macOS o Linux.** Instala todo — incluido Python, mediante `uv` — inicia Bento, y luego
*prueba que funciona* haciéndole una pregunta al servidor en ejecución antes de decir "listo".

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh
```

Después abre **http://127.0.0.1:8321**, o ejecuta `bento setup` para los mismos nueve pasos en una terminal.

Deja un comando `bento` en tu `PATH` (en `~/.local/bin`, añadido a tu perfil de shell si no estaba ahí —
abre una terminal nueva después).

### Instalarlo en una dirección y puerto elegidos

En un servidor al que llegas por SSH, `127.0.0.1:8321` significa "alcanzable por nada". Dale al instalador una
frase de contraseña y una dirección y arranca listo, con el servicio de arranque ya apuntando al puerto correcto:

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --passphrase='something long and unguessable' --bind=0.0.0.0 --port=8080
```

Esa máquina ahora responde en **todas** las interfaces en el puerto 8080, y pide esa frase de contraseña antes
de hacer nada. El uso local a través de `127.0.0.1:8080` no cambia.

El instalador dice con cuál de las dos te dejó — `AgentOS is running` solo cuando algo está genuinamente
escuchando. En una caja sin gestor de servicios a mano (un contenedor, una distro sin systemd, SSH sin D-Bus
de usuario) lo dice en su lugar, y `bento service start` termina el trabajo.

Una interfaz en lugar de todas — una VLAN privada, una dirección de Tailscale:

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --passphrase='something long and unguessable' --bind=192.168.1.20 --port=8080
```

Solo un puerto diferente, aún solo en loopback:

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --port=8080
```

> **`-s --` no es opcional.** `curl … | sh --port=8080` le pasa el flag a `sh`, que lo rechaza — un script por
> tubería no recibe argumentos propios. `-s --` significa "el resto es para el script". Esta es la forma más
> común, con diferencia, de que estos flags se pierdan, y el error nombra a `sh`, así que se lee como un
> instalador roto.

**Todos los flags:**

| flag | qué hace |
|---|---|
| `--passphrase=SECRET` | exigir esto para iniciar sesión, y permitir la vinculación fuera de loopback |
| `--bind=ADDR` | en qué interfaz escuchar (por defecto `0.0.0.0`); necesita `--passphrase` |
| `--port=N` | qué puerto (por defecto `8321`); se guarda en la config, así que el servicio de arranque lo usa |
| `--yes` | responder sí a cada componente opcional |
| `--no-service` | sin lanzador y sin servicio de arranque (contenedores, CI) |
| `--no-verify` | omitir el paso de "probar que funciona" |

### Cambiarlo después

Todo lo anterior vive en **`~/.agentos/config.json`** (o bajo `$AGENTOS_HOME`), y `bento config` lo lee y lo
escribe sin que tengas que encontrarlo:

```bash
bento config                       # the whole file, secrets masked
bento config port                  # one setting
bento config port 8080             # change it
bento config remote.bind 0.0.0.0   # dotted paths for nested settings
bento config --path                # where the file is
bento config --edit                # open it in $EDITOR — refuses to save invalid JSON
```

`bento remote` son los mismos ajustes con los de alcanzabilidad agrupados:

```bash
bento remote --on --passphrase 'something long' --bind 0.0.0.0   # the address
bento remote --port 8080                                          # the port
bento remote                                                      # what it is now
```

**Un cambio de puerto no llega por sí solo a un servicio de arranque instalado** — la unidad de systemd y el
LaunchAgent lo hornean dentro de `ExecStart`. Ambos comandos te dicen cuándo aplica eso:

```bash
bento service install && bento service restart
```

> **Ser alcanzable desde otras máquinas es una elección deliberada, no un valor por defecto.** Bento escucha
> solo en `127.0.0.1` hasta que le das una frase de contraseña, porque el agente tiene una shell real — un
> puerto abierto aquí es una shell abierta. `--bind` por sí solo se rechaza por esa razón, y también
> `bento serve --host 0.0.0.0` con el acceso remoto desactivado.

**Sobre los puertos por debajo de 1024.** Se rechazan a un proceso no root en Linux, y en macOS el rechazo es
por dirección — concede `0.0.0.0:80` y deniega `127.0.0.1:80`. Así que nada aquí adivina a partir del número:
`--port` intenta la vinculación real y, si el kernel dice que no, imprime la línea de `sysctl`, la regla de
redirección, o la opción de proxy que lo arregla. En Linux, el puerto 80 normalmente significa un comando:

```bash
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/50-agentos.conf
sudo sysctl --system
```

Ejecutar el servidor como root no es aconsejable — el agente tiene una shell real.

<details>
<summary><b>Desde un checkout de git en su lugar</b></summary>

```bash
uv sync                 # install dependencies (or: pip install -e .)
uv run bento            # start the server and open the desktop in your browser
```
</details>

<details>
<summary><b>En Docker</b></summary>

```bash
docker build -t bento .
docker run -d --name bento -p 8321:8321 -v bento-data:/data \
  -e AGENTOS_PASSPHRASE='something long and unguessable' bento
```

Un contenedor tiene que vincularse a `0.0.0.0` para ser alcanzable en absoluto, así que la frase de contraseña
es obligatoria en lugar de opcional — el entrypoint se niega a arrancar inalcanzable *o* inseguro y te dice
cuál. Todo lo que se perdería vive en el volumen `/data`. Construye una rama específica con
`--build-arg SOURCE=git --build-arg REF=my-branch`.
</details>

Si **Ollama** está en ejecución, tus modelos locales se detectan automáticamente. Añade claves de API en la
nube bajo **Settings** si las quieres. Esa es toda la configuración.

> **Consejo:** las construcciones, las llamadas a herramientas y las tareas de varios pasos son mucho más
> fiables con un **modelo capaz de usar herramientas** (cualquier modelo `qwen*`, o un modelo en la nube). Los
> modelos locales más débiles como `gemma` no llamarán a las herramientas de forma fiable.

---

## Ejecútalo como tu escritorio de Linux (SUI)

```bash
uv run bento installer      # detects your distro, installs what's missing, adds it to the login screen
```

Después cierra sesión y elige **Bento Box AI** en la pantalla de inicio de sesión. Tu escritorio existente
queda intacto — volver es cerrar sesión y elegir Ubuntu de nuevo.

El instalador detecta la distribución, nombra cada paquete que quiere y por qué, y pregunta antes de instalar
nada. Dos grupos: el motor del compositor (sway y compañía, MIT), y la superficie de escritorio nativa
(`python3-gi`, `python3-gi-cairo`, gtk-layer-shell, WebKitGTK) que permite que el escritorio sea una superficie
de Wayland real en lugar de una ventana de navegador.

**Bento no distribuye ni redistribuye ninguno de ellos.** gtk-layer-shell es MIT, pero GTK, PyGObject y
WebKitGTK son LGPL, y aquello de lo que este proyecto *depende* permanece permisivo — así que se piden, con las
licencias a la vista. Sin ellos la sesión aún se ejecuta, dibujando el escritorio en una ventana de Chromium.
[Licencias →](../licensing.md) · [La interfaz de sesión →](../session-ui.md)

Si algo del escritorio se comporta mal, un comando te dice por qué:

```bash
uv run bento doctor --session   # probes what can actually draw on THIS machine, and says so
```

Comprueba el intérprete, la pantalla de GTK, el soporte de layer-shell del compositor, y si WebKit puede
renderizar *y seguir renderizando* — en una ventana y en una superficie de capa — y luego da un veredicto. Los
sondeos se ejecutan en subprocesos, porque los fallos que busca son abortos y segfaults, y un sondeo que hace
caer al doctor no puede informar de que se cayó.

---

## Instalar como paquete Debian/Ubuntu (.deb)

Un `.deb` autocontenido (empaqueta la app **y** un venv de Python con todas las dependencias — sin red necesaria
en la instalación):

```bash
./packaging/build-deb.sh                                   # → packaging/dist/agentos_<ver>_<arch>.deb
sudo dpkg -i packaging/dist/agentos_0.1.0_amd64.deb        # installs to /opt/agentos + launcher + service
systemctl --user enable --now agentos                      # start at login (per user)
bento app                                                  # or launch it from your menu
```

`apt`/`dpkg` se encarga de las actualizaciones y la eliminación. **Recomienda** `bubblewrap` (sandbox) y
`xdg-utils`, y **Sugiere** `ollama`, `nodejs` y `git`. El paquete de escritorio además **Sugiere** la pila de la
interfaz de sesión y `wayvnc`/`novnc` — sugeridos en lugar de dependidos, porque apt instala los Recomendados por
defecto y eso sería empaquetar con un nombre más suave.

## Instalar como una app de verdad (auto-arranque al inicio) — desde el código fuente

```bash
uv run bento install      # app launcher + a background service that starts at login/boot
```

Se usa automáticamente el mecanismo nativo correcto: un lanzador `.desktop` más un **servicio de usuario de
systemd** en Linux (con linger, para que arranque al inicio), un paquete de app más **LaunchAgents** en macOS, un
acceso directo del menú de inicio más **entradas de inicio** en Windows.

Un solo conjunto de comandos gobierna los tres — no deberías tener que saber si esta caja usa systemd o launchd
para controlar tu propio agente:

```bash
bento service status       # is it running, will it come back at boot, is the port answering
bento service start        # …stop, restart
bento service logs -f      # journalctl or the log file, whichever this machine uses
bento service uninstall    # remove the background service only — launcher and data stay
bento uninstall            # remove launcher + service (your data stays)
bento app                  # open as a chromeless desktop window any time
```

`bento service status` informa de lo que el supervisor cree **y** de si el puerto responde, por separado: una
unidad que está "activa" mientras nada escucha es un bucle de caídas, y ese es el estado que vale la pena poder ver.

---

## Modos de lanzamiento

| Comando | Qué hace |
|---|---|
| `uv run bento` | inicia el servidor **y** abre el escritorio en tu navegador |
| `uv run bento serve --no-browser --port 8321` | servidor sin pantalla (usado por el servicio de arranque) |
| `uv run bento app` | abre el escritorio como una ventana con sensación nativa |
| `uv run bento tui` | todo el SO en una terminal (**TUI**) |
| `uv run bento installer` | detecta esta distro y configura la sesión de Linux (**SUI**) |
| `uv run bento doctor` / `doctor --session` | comprobación del entorno / qué puede dibujar el escritorio aquí |
| `uv run bento service status \| start \| stop \| restart \| logs \| uninstall` | el servidor en segundo plano, sobre cualquier supervisor que tenga este SO |
| `uv run bento update` / `update --apply` | buscar una versión más reciente / traer, sincronizar, probar y reiniciar |
| `uv run bento config [key] [value]` | leer o cambiar `~/.agentos/config.json` (`--edit`, `--path`) |
| `uv run bento remote --port 8080 --bind 0.0.0.0` | la dirección en la que responde, guardada en la config |
| `uv run bento serve --if-running open\|port\|restart\|fail` | qué hacer cuando ya hay uno en ejecución (por defecto: preguntar) |
| `uv run bento apps search \| install \| remove` | aplicaciones nativas, desde una terminal |
| `uv run bento remote --on --passphrase '…'` | alcanza este escritorio desde tu teléfono |
| `uv run bento remote-desktop --on` | el escritorio remoto por navegador (pantalla real, apps nativas) |
| `uv run bento ask "…"` | ejecución del agente de un solo turno en la terminal (`--full`, `--model …`) |

---

## Requisitos

- **Python ≥ 3.10** y [**uv**](https://docs.astral.sh/uv/) (o pip).
- **Un proveedor de modelos** — o bien [Ollama](https://ollama.com) localmente (recomendado: un modelo capaz de
  usar herramientas como `qwen3.5:9b`), o una clave de API en la nube.

Opcional, desbloquean funciones extra cuando están presentes — `bento installer` ofrece cada una con su licencia:

- **La sesión de Linux (SUI)** — `sway` y compañía, más `python3-gi`, `python3-gi-cairo`,
  `gir1.2-gtklayershell-0.1` y `gir1.2-webkit2-4.1`. [Detalles →](../session-ui.md)
- **wayvnc + novnc** — Escritorio Remoto desde el navegador de un teléfono, retransmitido en loopback.
- **bubblewrap** (`bwrap`) — el **sandbox** de carpetas que encierra al agente y la terminal en una sola carpeta.
- **Node/npx** y/o **uvx** — para ejecutar **servidores MCP** (Playwright, filesystem, git, …).
- **git** — para instalar **skills** desde repositorios.

---

## El escritorio

- **Ventanas** — cada app se abre en una ventana arrastrable y redimensionable con minimizar/maximizar/cerrar y
  ordenación en z. Una **barra de tareas** rastrea las ventanas abiertas; un **menú de inicio** lanza todo.
- **Ventanas que duermen** — una ventana que no puedes ver deja de hacer trabajo periódico y se refresca en el
  momento en que vuelve. Seis apps abiertas y todas minimizadas pasaron de 25 peticiones por cada 10s a 2.
- **Escritorios virtuales** — un paginador en la barra de tareas; `Ctrl+1..6` para cambiar, clic derecho para
  mover una ventana allí. Los widgets son por escritorio, así que cada uno es su propio espacio.
- **Widgets** — fija cualquier app como un mosaico en vivo sin marco; arrástralo, redimensiónalo, y se restaura
  al arrancar.
- **Paleta de comandos** — `Ctrl+Space` (o `Ctrl+K`) para el lanzamiento difuso de cualquier app o acción, o
  "Ask Aria …" para enviar directo al agente. `Ctrl+Alt+T` abre una terminal.
- **Aspecto y sensación** — fondos de pantalla generados por IA con una galería local, una animación de
  pensamiento mientras el agente trabaja, y voz opcional. Pega imágenes directamente en el chat para modelos con
  capacidad de visión.

### Apps integradas

| App | Qué es |
|---|---|
| **Agent Chat** | habla con el agente; streaming, tarjetas de herramientas, aprobaciones, voz, pegar imágenes |
| **Applications** | cada app de escritorio instalada — lánzalas, o instala nuevas |
| **Remote Desktop** | la pantalla real de la máquina, en la que se puede hacer clic, desde aquí o desde un teléfono |
| **Host Screen** | una instantánea que se refresca de la pantalla real, incluidas las ventanas de apps nativas |
| **Web** | abre URLs en tu **navegador real del sistema** (sitios completos, inicios de sesión, extensiones) |
| **Files** | explora el espacio de trabajo; haz clic en un archivo para abrirlo en tu navegador/app del host |
| **Terminal** | una shell real del host (xterm.js sobre un PTY), encerrada en la carpeta del sandbox |
| **App Studio** | describe una app en lenguaje llano y el agente **la construye en vivo** |
| **Task Manager** | CPU/memoria/disco en vivo, procesos, ventanas abiertas (y cuáles están durmiendo) |
| **Knowledge Graph** | lo que el agente sabe, como un grafo dirigido por fuerzas en vivo |
| **Soul** | la identidad/personalidad persistente del agente (inyectada en cada turno) |
| **Memory** | memoria de usuario y de sesión con auto-aprendizaje + recuerdo semántico |
| **Profile** | todo lo que el agente sabe sobre ti, en un solo lugar |
| **Team** | subagentes y flujos de trabajo visuales (mezcla modelos por paso) + observabilidad |
| **Docs** | este manual, dentro del SO |
| **Automations** | rutinas con nombre, esquinas activas, y el constructor de pasos |
| **Skills** | procedimientos reutilizables; instala desde un repo de git o una URL `.md` en bruto |
| **MCP Servers** | conecta servidores de herramientas externos desde un catálogo |
| **Telegram** | controla el agente desde tu teléfono; lista de permitidos por chat |
| **Policies** | reglas de siempre-permitir / siempre-denegar para herramientas y comandos |
| **Logs** | todo lo que hizo el sistema (turnos, herramientas, MCP, telegram, trabajos) |
| **Scheduler** | **trabajos** recurrentes en segundo plano |
| **Snapshots** | puntos de restauración para todo el SO (config, datos y código fuente) |
| **Settings** | proveedores, modelo, autonomía, voz, sandbox, nombre del agente |

---

## Qué puede hacer el agente

El agente (nombre por defecto **Aria**) tiene un gran conjunto de herramientas y puede gobernar todo el SO desde
el chat o Telegram:

- **Actuar sobre la máquina** — ejecutar comandos de shell, leer/escribir archivos, obtener la web, abrir
  apps/archivos en el host, notificaciones de escritorio.
- **Entregar resultados** — `save_report` escribe un informe HTML con estilo que se muestra en Files y se abre en
  tu navegador, y puede enviar un resumen a Telegram. Al agente se le dice que **termine el trabajo** — convierte
  la investigación en un entregable real, no que pare después de una búsqueda.
- **Construir el SO** — `create_app` crea nuevas apps de interfaz con un icono de escritorio; `pin_widget` las pone
  en el escritorio; `add_mcp_server` conecta nuevos canales de herramientas.
- **Crecer** — memoria de dos niveles, un grafo de conocimiento, `update_soul` — más **auto-aprendizaje**: un pase
  en segundo plano después de cada turno extrae memorias y hechos por su cuenta.
- **Automatizar** — `schedule_task` crea **trabajos** sin pantalla que entregan a un informe y/o a Telegram.
- **Extenderse a sí mismo** — `read_source` / `develop_agentos` le permiten modificar el **propio código fuente**
  de Bento; hace auto-instantáneas primero y comprueba la sintaxis antes de escribir.

Pregunta en lenguaje llano: *"añade el canal MCP de github", "constrúyeme un rastreador de hábitos y fíjalo al
escritorio 2", "cada mañana informa las tendencias de redes sociales a mi Telegram", "instala inkscape".*

---

## Modelos y proveedores

- **Ollama** (local) — autodetectado; nada sale de tu máquina.
- **Anthropic**, **OpenAI**, **OpenRouter**, o cualquier endpoint **compatible con OpenAI** (LM Studio, vLLM,
  Groq, …).
- **Generación de imágenes** — modelos de imagen de Google Gemini u OpenAI cuando hay una clave configurada,
  alternativa gratuita en caso contrario.

`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` y `GOOGLE_API_KEY` se detectan automáticamente. Cambia
de modelo sobre la marcha desde el desplegable de la ventana de chat.

---

## Seguridad

- **Niveles de autonomía** — Paranoico / Equilibrado ejecutan automáticamente las acciones de solo lectura y
  preguntan antes de cualquier cosa que modifique el sistema; Completo ejecuta todo. Los comandos destructivos
  están **bloqueados de forma dura** en todos los niveles.
- **Políticas** — reglas de siempre-permitir / siempre-denegar (con comodines `*`) contrastadas con
  `<tool> <command>`.
- **Sandbox de carpetas** — con bubblewrap, las herramientas de shell/archivos del agente y la Terminal quedan
  encerradas en una sola carpeta; el resto del sistema de archivos es de solo lectura.
- **Instantáneas** — puntos de restauración; el agente hace auto-instantáneas antes de editar su propio código.
- **Privado por defecto** — se vincula a `127.0.0.1`. El acceso remoto está desactivado hasta que lo activas con
  una frase de contraseña, y la instalación de software se rechaza desde cualquier parte que no sea la propia
  máquina.

---

## Telegram · MCP · Programable

**Telegram** — envía un mensaje a @BotFather, pega el token en la app de Telegram, y el primer chat privado se
convierte en el propietario. El agente tiene todas sus herramientas allí; las acciones arriesgadas envían botones
en línea de Permitir/Denegar.

**Servidores MCP** — añade servidores de herramientas externos desde el catálogo (Playwright, filesystem, fetch,
git, GitHub, Postgres, Slack, búsqueda, …) o un servidor `stdio`/`http` personalizado. Sus herramientas aparecen
ante el agente como `mcp_<server>_<tool>`, y ante las apps construidas mediante `POST /api/tool`.

**Programable** — `bento ask "…"` para ejecuciones de un solo turno; una API REST (`POST /api/chat`,
`GET /api/system`, `POST /api/tool`, …); WebSockets en `/ws` (chat en streaming + aprobaciones) y `/ws/terminal`
(PTY del host). Las apps que construyes se ejecutan en un iframe del mismo origen y pueden llamar a todo ello.

---

## Arquitectura

```
agentos/                 # the Python package keeps its original name; see "On the name" below
├── __main__.py    # CLI entry: serve · app · installer · doctor · apps · remote-desktop · ask
├── agent.py       # the kernel: plan → act (tools) → observe loop, approval gates, personas
├── providers.py   # unified streaming chat: Ollama / Anthropic / OpenAI / OpenRouter / custom
├── tools.py       # the hands: shell, files, web, apps, reports, memory, KG, soul, skills, MCP
├── shellhost.py   # the SUI: the desktop as a wlr-layer-shell surface (GTK + WebKitGTK)
├── sessiondoctor.py # what can actually draw the desktop on this machine
├── compositor.py  # sway/wlroots IPC: windows, workspaces, outputs, live events
├── appstore.py    # installing native applications via appstream / flatpak / apt
├── remotedesktop.py # the browser remote desktop, relayed over the authenticated connection
├── installer.py   # OS-aware setup: detect the distro, install what is missing, ask first
├── memory.py      # SQLite: conversations, memories, tasks, logs, KG, skills, apps
├── server.py      # FastAPI: desktop UI, REST API, WebSocket streams, file serving
└── ui/
    ├── src/       # the desktop's source — edit here
    └── index.html # generated by `python -m agentos.ui.build` (do not edit)
```

**El estado vive en `~/.agentos/`:** `config.json`, la base de datos SQLite, `soul.md`, `wallpapers/`,
`snapshots/`. El directorio de trabajo del agente es `~/AgentOS/`.

### Sobre el nombre

El producto es **Bento Box AI**. El paquete de Python, el directorio de datos y la unidad de systemd siguen
siendo `agentos` — deliberadamente. Renombrarlos rompe el servicio, la config y los scripts de cada instalación
existente, y no le compra al usuario nada que pueda ver. Se moverán cuando haya una migración que valga la pena
ejecutar, no antes. El nombre y la marca son nuestros de la misma forma que los de Ubuntu son de Canonical:
bifurca el código libremente bajo MIT, distribúyelo bajo tu propio nombre. [Licencias y marcas →](../licensing.md)

---

*Bento Box AI es una alternativa abierta y local por diseño a los asistentes de IA en la nube: un SO con agentes,
un escritorio con IA, y una plataforma de automatización que ejecutas tú mismo — en Linux, macOS o Windows.*
