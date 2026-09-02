# Bento Box AI —— 一个本地优先的智能体操作系统

<p align="right"><sub>
<a href="../../README.md">English</a> ·
<b>简体中文</b> ·
<a href="README.zh-TW.md">繁體中文</a> ·
<a href="README.ja.md">日本語</a> ·
<a href="README.ko.md">한국어</a> ·
<a href="README.es.md">Español</a> ·
<a href="README.pt-BR.md">Português&nbsp;(BR)</a> ·
<a href="README.fr.md">Français</a> ·
<a href="README.de.md">Deutsch</a> ·
<a href="README.ru.md">Русский</a> ·
<a href="README.hi.md">हिन्दी</a> ·
<a href="README.ar.md">العربية</a>
</sub></p>

**你的机器，拥有了大脑。** Bento Box AI 是一个自托管的 **AI 桌面环境**：一个完整的桌面——窗口、应用、文件、终端——由一个在你电脑上执行**真实操作**的**自主 AI 智能体**驱动。通过 [Ollama](https://ollama.com) 使用本地模型以获得完全的隐私，或者使用云端模型（Anthropic Claude、OpenAI、OpenRouter，或任何兼容 OpenAI 的端点）——始终需要你的批准。这个智能体可以浏览网页、构建自己的应用、安排定时任务、记住它学到的东西、扩展自己的源代码，并通过 Telegram 或 WhatsApp 联系你。

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![平台](https://img.shields.io/badge/platform-Linux%20·%20macOS%20·%20Windows-lightgrey)
![本地优先](https://img.shields.io/badge/AI-local--first%20·%20Ollama%20·%20cloud%20optional-5eead4)

运行在 `http://127.0.0.1:8321` —— 默认私有，可安装为开机自启服务。

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh
```

![Bento Box AI 桌面 —— 在一个基于浏览器的桌面环境中呈现 AI 智能体聊天、文件管理器和快捷设置](../screenshots/desktop.png)

**完整文档在 [`docs/`](../README.md) 中** —— 涵盖安装、桌面及每个应用的用户指南、智能体及其工具、构建应用、集成、API 参考以及故障排查。

---

## 安装分十一步，每一步都留下真实的东西

这不是一个带进度条的设置表单。每一步都**产出真实的东西**——一个会作答的模型、一个真实存在的智能体、一条会运行的流程、一个会触发的定时任务——并且在向你索要任何东西之前，先说清楚你最终会得到什么。

![首次运行的安装界面：左侧是十一个步骤的导轨，右侧是"为你的智能体命名"，附带一行字"你最终会得到：菜单栏上以及每条回复里的那个名字"](../screenshots/onboarding-1-name.png)

每一步都是**探测得来的，而非记住的**：某一步被打上勾，是因为这台机器确实拥有那个东西。删掉智能体，那一步就回到待办状态。这正是重新运行它之所以安全的原因——而在这里重新运行是很正常的事，因为 **Setup 本身也是一个应用**。你可以随时打开它，看看某一步做了什么，哪怕是在几个月前就已经设置好的机器上。

![窗口中的 Setup 应用：左侧是十一步导轨，右侧打开的是"构建一名专家"步骤](../screenshots/setup-app.png)

同一套目录、同一套探测、同一组面板——包括在终端里也是如此，在那里通过 SSH 运行的 `bento setup` 会精准地从浏览器停下的地方接着往下走。

---

## 它问你的第一件事，是要做什么工作

Setup 以一个问题收尾，而不是一扇门：**给我一份工作。** 从三个选项里挑一个，回答两个问题，这台机器就会在你还没打开任何一个应用之前，为你做起事来。

![Jobs 界面：三份配方——每天早晨给我简报、替我盯着一个文件夹、有页面变化时告诉我——旁边是所选配方要回答的问题以及它将被准许做的确切事项](../screenshots/jobs.png)

| | |
|---|---|
| **每天早晨给我简报** | 在夜里读一读你关注的那些东西，留下一页等你查看 |
| **替我盯着一个文件夹** | 留意*你选定的*文件夹里出现了什么，弄清它是什么，然后告诉你 |
| **有页面变化时告诉我** | 检查某个页面，只在确实有实质变化时才出声 |

有两件事它不会做。它不会给自己授予任何你没看过的东西：面板会在你按下按钮之前打印出确切的权限，而这些权限由写入它们的同一段代码计算得出——"读取 `~/Downloads/*`，除此之外别无其他"。它也不会提供一条根本行不通的联系方式：一个未配对的 Telegram 会以灰显方式呈现，并附上能修复它的那句话，绝不隐藏，也绝不悄悄替换成别的。

最后一个按钮是 **"现在就运行，好让我看到它起作用"**——因为一个你没有亲眼看它触发过的定时任务只是一句承诺，而新用户没有理由去相信一句承诺。

一份工作就是一条*流程（flow）*，不是一种新东西：同一个调度器、同一道权限关卡、同一本审计账本。在无显示器的机器上：`bento job recipes`，然后 `bento job add morning-brief --topics "…"`。

---

## 三张面孔，一个程序

Bento 在三个地方运行，而且**每个功能都是为这三者共同构建的**。这是对任何一次改动首先要问的问题，而不是最后才问。

| | 它是什么 | 用什么启动 |
|---|---|---|
| **GUI** | macOS、Windows 或 Linux 上的一个窗口（或标签页）。无需额外安装任何东西 | `bento` |
| **TUI** | 整个操作系统跑在一个终端里——用于服务器，或通过 SSH 连接的无显示器 Pi | `bento tui` |
| **SUI** | Bento **就是**你的 Linux 会话：它掌管整台机器 | `bento installer` |

> 命令是 `bento`。`agentos` 依然可用，而且永远可用——它存在于人们的 shell 历史记录、systemd 单元和脚本里，我们选择的改名不应让他们为此付出代价。

---

## 亲眼看它运作

| | |
|---|---|
| ![与 AI 智能体聊天 —— 流式回复、工具调用与审批](../screenshots/chat.png) **Agent Chat** —— 与你的机器对话；流式回复、工具卡片、审批、语音 | ![Team 应用 —— 子智能体、工作流与可观测性](../screenshots/team.png) **Team** —— 专职子智能体与可视化工作流，可对每一步混用不同模型 |
| ![内置文档应用呈现完整手册](../screenshots/docs.png) **Docs** —— 完整手册就在操作系统内部 | ![应用商店 —— 一键应用、技能与 MCP 通道](../screenshots/store.png) **Store** —— 一键应用、技能与 MCP 工具通道 |

### 多人共用一台机器

添加一个账户，每个人都会得到**属于自己的家目录**——自己的数据库、记忆、智能体、通道、MCP 服务器和凭据。这不是一个被某条遗漏的 `WHERE` 子句就能泄露的 `user_id` 列：而是各自独立的目录，因为两个文件无法互相泄露。

![Users 应用：两个账户，Ada Lovelace 被标记为管理员并注明"这是你"，Bob Kahn 的角色下拉框设置为 Executor](../screenshots/users-two-accounts.png)

两种角色——**executor（执行者）**（掌管自己家目录内的一切）和 **admin（管理员）**（在此之上，还掌管整台机器）。设置保持共享，因此整台机器只有一份提供商密钥，而非每人一份。智能体和应用会以副本形式，经由一个共享库，被有意地跨账户传递。

而且这是**一次登录，此处及任何地方通用**：一台设有账户的机器会被这些账户锁定，所以某人口袋里的手机使用与桌面相同的用户名和密码，并进入他自己的家目录。无需再另外发明、共享或记住一个共用口令。

![远程访问面板显示"由本机的账户锁定 —— 每个人都用他们在这里使用的同一套用户名和密码从手机登录"](../screenshots/remote-locked-by-accounts.png)

### 你能看到它正在做什么

![一次进行中的对话轮次：已完成的 Read 调用保留了它的耗时，正在运行的 Bash 调用就地累计时长，下方那一行显示当前是哪一步以及这一轮已经花了多久](../screenshots/agent-working.png)

一次对话轮次大部分时间都在等待，而一个连续四分钟的"处理中…"什么也没告诉你——一个正在思考的模型和一个已经悄然死掉的运行，在它下面看起来一模一样。每一个等待中的界面都会说清**它在忙什么、忙了多久**：正在运行的调用就地累计时长（`running · 2m 14s`），已完成的调用保留其耗时，下方那一行则承载着当前步骤和这一轮的总用时。同一句话也出现在在线状态气泡和全能栏（omnibar）上，因此无需打开聊天，也能从桌面得到答案。

### 它能组建自己的团队 —— 而且动手之前会先征询

![批准一次委派：卡片写明了智能体、模型、步数和时间预算，以及它将持有的确切工具和技能](../screenshots/agent-approval.png)

当没有现成的专家合适时，智能体会**构建一个**并把任务委派给它。定义一个智能体并不会授予它任何权限；第一次真正使用它时，你会收到一张卡片，写明它运行所依托的模型、它的预算，以及它的定义赋予它的确切工具和技能——因为对一个你无法想象的行动者表示同意，只是名义上的同意。批准 `researcher` 并不等于批准 `deploy-bot`，而且这项授权和其他任何授权一样，可以在 Permissions 里撤销。[工作原理 →](../security.md)

### 它会依据自己的手册回答关于自身的问题

![Docs 应用基于手册回答一个关于本操作系统的问题](../screenshots/docs-ask.png)

手册就在检索索引里，所以"我如何阻止一个应用访问互联网但又让它继续工作？"这个问题是依据**这些页面**作答的，而不是依据某个模型对另一个项目的记忆——而且回复会点明它所引用的页面。这是智能体式检索，而非一次性查表：智能体会搜索、阅读，并在第一遍没找到时再次搜索。

### 表现得像窗口的窗口

![四个 Bento 窗口堆叠在桌面上：获得焦点的那个带有强调色描边环和完整阴影，其余的则后退隐去](../screenshots/windows.png)

一个窗口会在**你上次离开它的地方**打开——位置和大小按应用分别记住——而一个首次打开的窗口会以超过一个标题栏高度的幅度层叠展开，好让它下面那个的名字仍然可读。获得焦点的窗口带有强调色描边环和完整阴影；其余的则后退隐去。标题栏里的 ✦ 是*位于那个应用之内*的智能体：无需离开该应用，就可以就屏幕上的内容向它提问。

### 五种设计语言，而非五套配色

![五种内置的设计语言主题：Bento、Liquid Glass、Spatial、Claymorphism、Minimalism](../screenshots/themes.png)

**Bento · Liquid Glass · Spatial · Claymorphism · Minimalism。** 每一种都会重新裁剪整个外壳——表面、圆角、层次、模糊、字体——并带来自己的壁纸。这些壁纸以 SVG 形式随附：每张只有几 KB，从手机到 4K 屏幕都清晰锐利。[了解更多 →](../desktop.md#themes)

玻璃质感是桌面能绘制的最昂贵的东西，而且这种代价会随你打开的每一个窗口而叠加。**Themes → Effects** 会测量你的机器，并且只在不得不这么做时才把它调低——在 Liquid Glass 下五个窗口从 6.5fps 提升到了 27（已降低）或 60（关闭）。

### 它在你已经身处的地方联系你

![Settings 里的 WhatsApp 通道：四个 Cloud API 字段、要粘贴到 Meta 控制台的回调 URL、已配对的号码，以及 24 小时窗口是否处于打开状态](../screenshots/channels-whatsapp.png)

**Telegram 和 WhatsApp 是原生通道**——与坐在办公桌前时同样的对话、同样的记忆、同样的工具和同样的审批按钮。这不是一个通知桥接器：来自你手机的一条回复会接续你今天早上开启的那个话题。

WhatsApp 有**两种传输方式**，它们的失败方向恰好相反。Meta 的 Cloud API 是官方的，但需要一个开发者账户和一个公开的 webhook，而且在距你上一条消息超过 24 小时之后，它根本不会传送任何自由格式的回复——卡片会说明那个窗口是否打开，一条无法发出的消息会说明这一点以及如何修复，而一个定时任务会先把它的报告保存下来，这样就什么都不会丢失。WhatsApp Web 链接只需扫一个二维码，且没有 24 小时窗口，但它是**非官方的**，Bento 在任何东西下载之前就会在安装卡片上如实说明这一点。[设置方法 →](../whatsapp.md)

Telegram 同时也是一个**管理控制台**：`/agents`、`/run`、`/flows`、`/model`、`/logs`、`/perms`——仅限所有者，而且每一条*会做点什么*的命令都会经过与桌面相同的权限关卡和相同的审批按钮，因此它绝不会成为一条更省事的入侵路径。[命令列表 →](../integrations.md)

### 一个桌面，适配每一块屏幕

![手机上的 Bento Box AI：锁屏、为手机布局的桌面，以及一个作为满幅面板呈现的应用](../screenshots/mobile.png)

手机、平板、工作站——同一个桌面，随之适配。窗口变成满幅面板，程序坞横跨底部边缘，弹出框变成面板。打开**远程访问**，就能在你的网络上通过一个口令从手机访问它；*添加到主屏幕*会让它成为一个全屏应用。
[远程访问 →](../remote-access.md) · [响应式布局 →](../desktop.md#phone-tablet-desktop)

### 它可以*成为*桌面本身，而不只是活在某个桌面之上

![一个原生 Wayland 应用位于 Bento 桌面之上，其上方为菜单栏所预留，其下方为程序坞所预留](../screenshots/session-native-window.png)

登录后，把 Bento 作为你的 Linux 会话来使用。桌面被绘制成一个**位于背景层的 Wayland 图层表面**，因此原生应用窗口在正常的堆叠顺序中位于它之上——不是因为有什么东西被抬高或压低，而是因为"背景"本就意味着如此。菜单栏和程序坞坐落在**由合成器预留**的条带里，用的正是 GNOME 或 KDE 面板所用的同一套机制，因此一个全屏应用会在它们的边缘处停下，而不是把它们吞没。

![两个原生终端被吸附到 Bento 桌面的左右两半](../screenshots/session-snapped.png)

为原生应用提供完整的窗口管理：吸附到二分之一和四分之一、平铺、浮动、布局、键盘调整大小、工作区、最小化，以及一个 Alt-Tab 切换器——任务栏和菜单栏会跟随当前获得焦点的应用。[会话 UI →](../session-ui.md)

### 在 Bento 内部安装应用程序

![Applications 应用正在搜索机器的软件包目录，每个结果旁边都有一个安装按钮](../screenshots/app-store.png)

一个无法在其上安装软件的桌面只是个演示。*Applications → Get apps…* 会搜索机器自己的目录——AppStream、Flatpak 或 apt——并在运行之前把确切的命令展示给你。凡是有 Flatpak 的地方都会优先选用它，因为一次按用户安装完全不需要密码。Bento 不镜像任何东西，也不捆绑任何东西；它询问你已经拥有的那个包管理器。

### 你真实的屏幕，在你的手机上，在浏览器里

![Bento 的 Remote Desktop 在手机浏览器中打开，显示着机器上运行着一个原生应用的真实屏幕，以及一排手机键盘所缺少的按键工具条](../screenshots/phone-remote-desktop.png)

**远程访问**会把 Bento 外壳发送给你，它是 HTML，能完美地传输——但一个原生应用是机器自己显示器上的像素，从来就不是页面的一部分。**Remote Desktop** 弥合了这一点：Bento 通过它*自己*经过认证的连接来转发屏幕，于是你得到的是真实的、可点击的桌面，而无需在手机上安装任何 VNC 应用。

这个形态正是关键所在——VNC 服务器始终留在 `127.0.0.1` 上，绝不靠近网络；保护它的，是你已经在用的那个口令。[远程访问 →](../remote-access.md)

### 自动化与热角

![Automations 应用，展示已保存的例程、热角映射图以及步骤构建器](../screenshots/automations.png)

只需命名一次一段序列——打开这些应用、切换主题、运行这段 Python、调用那个 MCP 工具、给智能体派一个任务——从此以后就能永久地从提示栏、一个热角、一个定时任务，或者通过报出它的名字来运行它。[了解更多 →](../desktop.md#automations)

---

## 为什么选择 Bento Box AI

- **一个真正的桌面，而非一个聊天框**——可拖动的窗口、任务栏、虚拟桌面、小组件、主题、一个命令面板，以及 25 个以上的内置应用。
- **一个有双手的智能体**——shell 命令、文件管理、网络研究、桌面通知、定时任务、HTML 报告和应用构建，全都用平实的语言来完成。
- **本地优先且私密**——一切都可以在你自己的硬件上通过 Ollama 运行；除非你添加一个云端密钥，否则没有任何东西离开你的机器。它仅绑定到 localhost，直到你有意地开启受口令保护的[远程访问](../remote-access.md)。
- **整个生命周期尽收一处**——**Train · Test · Operate · Build · Ship · Manage**，实时呈现在一块屏幕上（Mission Control）：在你的 GPU 上微调你自己的模型、为每一次自我修改设置测试关卡、运行定时任务、构建应用，并把它们发布到 GitHub。
- **自我扩展**——智能体为自己构建新的 UI 应用（App Studio）、安装技能和 MCP 工具服务器，并且可以修改 Bento 自己的源代码（附带自动快照，以及一套必须在重启前通过的测试）。
- **会累积的记忆**——两级记忆、一张实时的知识图谱，以及一份持久的"灵魂"，在每次对话之后自动习得。
- **设计上就安全**——自主级别、审批提示、允许/拒绝策略、一个 bubblewrap 文件夹沙箱、被硬性拦截的破坏性命令，以及一键还原点。

---

## 快速开始

**一条命令，在 macOS 或 Linux 上。** 它会安装一切——包括通过 `uv` 安装的 Python——启动 Bento，然后在它说"完成"之前，通过向正在运行的服务器提一个问题来*证明它确实能工作*。

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh
```

然后打开 **http://127.0.0.1:8321**，或者运行 `bento setup` 在终端里走一遍同样的十一个步骤。

只要有一个可以发问的终端，安装程序在结束前会问两件事：这台机器是否要能被你的其他设备访问；如果要，你是用**口令**登录还是用**账户**登录。在一台没有屏幕的机器上，第一个问题正是「一次你看得到的安装」和「一次你看不到的安装」之间的分界。`--yes` 有意不回答它——这里的一个开放端口，就是一个开放的 shell。

它会在你的 `PATH` 上留下一个 `bento` 命令（在 `~/.local/bin` 中，如果那里原本没有，就会添加到你的 shell 配置文件里——之后请打开一个新终端）。`bento --help` 会列出一台新机器需要的十个命令；其余的在 `bento help --all` 里。

### 在指定的地址和端口上安装它

在一台你通过 SSH 访问的服务器上，`127.0.0.1:8321` 意味着"任何东西都访问不到"。给安装程序一个口令和一个地址，它就会启动就绪，并且开机自启服务已经指向了正确的端口：

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --passphrase='something long and unguessable' --bind=0.0.0.0 --port=8080
```

那台机器现在会在**每一个**接口的 8080 端口上作答，并且在做任何事之前都会索要那个口令。通过 `127.0.0.1:8080` 的本地使用则一如既往。

安装程序会说明它给你留下的是二者中的哪一种——只有当确实有东西在监听时，才会显示 `AgentOS is running`。在一台手头没有服务管理器的机器上（一个容器、一个非 systemd 发行版、一个没有用户 D-Bus 的 SSH 会话），它会转而如实说明，而 `bento service start` 会把这份活儿收尾。

只监听一个接口，而非全部——一个私有 VLAN、一个 Tailscale 地址：

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --passphrase='something long and unguessable' --bind=192.168.1.20 --port=8080
```

只是换一个端口，仍然仅限回环：

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --port=8080
```

> **`-s --` 不是可有可无的。** `curl … | sh --port=8080` 会把这个参数交给 `sh`，而 `sh` 会拒绝它——一个通过管道传入的脚本本身得不到任何参数。`-s --` 的意思是"其余的都是给脚本用的"。这是这些参数最常见的丢失方式，而且错误信息指名道姓地提到 `sh`，因此读起来就像是安装程序坏了。

**全部参数：**

| 参数 | 它的作用 |
|---|---|
| `--passphrase=SECRET` | 登录时要求提供它，并允许绑定到回环之外 —— 在这里给出，安装程序就不再询问 |
| `--bind=ADDR` | 监听哪个接口（默认 `0.0.0.0`）；需要 `--passphrase` |
| `--port=N` | 用哪个端口（默认 `8321`）；会保存到配置里，因此开机自启服务会使用它 |
| `--yes` | 对每一个可选组件都回答"是" —— 但**不**包括打开端口 |
| `--no-service` | 不设启动器，也不设开机自启服务（容器、CI） |
| `--no-verify` | 跳过"证明它能工作"这一步 |

### 事后更改它

上面这一切都存在于 **`~/.agentos/config.json`**（或在 `$AGENTOS_HOME` 之下），而 `bento config` 无需你去找它就能读写它：

```bash
bento config                       # 整个文件，密钥已遮掩
bento config port                  # 单个设置
bento config port 8080             # 更改它
bento config remote.bind 0.0.0.0   # 用点号路径访问嵌套设置
bento config --path                # 文件在哪里
bento config --edit                # 在 $EDITOR 中打开它 —— 拒绝保存无效的 JSON
```

`bento remote` 是同一套设置，只是把与可达性相关的那些归到了一起：

```bash
bento remote --on --passphrase 'something long' --bind 0.0.0.0   # 一个共享的秘密
bento user add alice && bento remote --on --bind 0.0.0.0          # 或者每人一个账户
bento remote --port 8080                                          # 端口
bento remote                                                      # 现在是什么状态，以及谁来登录
```

**端口的更改不会自己传达到已安装的开机自启服务**——systemd 单元和 LaunchAgent 会把它烘焙进 `ExecStart` 里。这两条命令都会在这种情况适用时告诉你：

```bash
bento service install && bento service restart
```

> **能被其他机器访问是一个有意的选择，不是默认设置。** Bento 仅监听 `127.0.0.1`，直到它有了一把锁：一个口令，或者一个可供某人登录的账户。因为智能体拥有一个真实的 shell——这里的一个开放端口就是一个开放的 shell。单用 `--bind` 会因此被拒绝，`bento serve --host 0.0.0.0` 在远程访问关闭时同样会被拒绝。两把锁是二选一，而不是叠加：一旦存在账户，账户本身就是那把锁，摆在它前面的口令只是没有任何代码会读取的配置。

**关于 1024 以下的端口。** 在 Linux 上，它们对一个非 root 进程是被拒绝的，而在 macOS 上，这种拒绝是按地址来的——它会准许 `0.0.0.0:80` 却拒绝 `127.0.0.1:80`。因此这里没有任何东西是靠数字来猜的：`--port` 会尝试真正的绑定，如果内核说不行，就打印出能修复它的 `sysctl` 那一行、重定向规则，或者代理选项。在 Linux 上，80 端口通常意味着一条命令：

```bash
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/50-agentos.conf
sudo sysctl --system
```

不建议以 root 身份运行服务器——智能体拥有一个真实的 shell。

<details>
<summary><b>改从 git 检出运行</b></summary>

```bash
uv sync                 # 安装依赖（或者：pip install -e .）
uv run bento            # 启动服务器并在浏览器中打开桌面
```
</details>

<details>
<summary><b>在 Docker 中</b></summary>

```bash
docker build -t bento .
docker run -d --name bento -p 8321:8321 -v bento-data:/data \
  -e AGENTOS_PASSPHRASE='something long and unguessable' bento
```

一个容器必须绑定 `0.0.0.0` 才能被访问到，所以口令是必需的而非可选的——入口点会拒绝在既不可达*或*不安全的情况下启动，并告诉你是哪一种。所有会丢失的东西都存放在 `/data` 卷里。用 `--build-arg SOURCE=git --build-arg REF=my-branch` 来构建某个特定分支。
</details>

如果 **Ollama** 正在运行，你的本地模型会被自动识别。如果你想用云端模型，就在 **Settings** 下添加云端 API 密钥。整个设置就是这样。

> **提示：** 使用一个**具备工具调用能力的模型**（任何 `qwen*` 模型，或一个云端模型），构建、工具调用和多步骤任务会可靠得多。像 `gemma` 这样较弱的本地模型无法可靠地调用工具。

---

## 把它作为你的 Linux 桌面来运行（SUI）

```bash
uv run bento installer      # 检测你的发行版，安装缺失的东西，并把它添加到登录界面
```

然后注销并在登录界面选择 **Bento Box AI**。你现有的桌面不受任何影响——切换回去，只需注销并再次选择 Ubuntu。

安装程序会检测发行版，说出它想要的每一个软件包及其原因，并在安装任何东西之前先征询。分两组：合成器引擎（sway 及其相关组件，MIT 许可），以及原生桌面表面层（`python3-gi`、`python3-gi-cairo`、gtk-layer-shell、WebKitGTK），后者让桌面成为一个真正的 Wayland 表面，而不是一个浏览器窗口。

**Bento 不随附也不再分发它们中的任何一个。** gtk-layer-shell 是 MIT 许可的，但 GTK、PyGObject 和 WebKitGTK 是 LGPL 许可的，而本项目所*依赖*的东西必须保持宽松许可——所以它们是被征询获取的，且许可证清晰可见。没有它们，会话依然能运行，会在一个 Chromium 窗口里绘制桌面。
[许可 →](../licensing.md) · [会话 UI →](../session-ui.md)

如果桌面有任何地方表现异常，一条命令就会告诉你原因：

```bash
uv run bento doctor --session   # 探测在这台机器上究竟什么东西能绘制，并如实说明
```

它会检查解释器、GTK 的显示、合成器的 layer-shell 支持，以及 WebKit 是否能渲染*并持续渲染*——在窗口中以及在图层表面上——然后给出一个判定。探测在子进程中运行，因为它所排查的那类故障是中止和段错误，而一个把 doctor 本身也弄崩的探测无法报告自己崩溃了。

---

## 作为 Debian/Ubuntu 软件包（.deb）安装

一个自包含的 `.deb`（捆绑了应用**以及**一个带全部依赖的 Python 虚拟环境——安装时无需网络）：

```bash
./packaging/build-deb.sh                                   # → packaging/dist/agentos_<ver>_<arch>.deb
sudo dpkg -i packaging/dist/agentos_0.1.0_amd64.deb        # 安装到 /opt/agentos + 启动器 + 服务
systemctl --user enable --now agentos                      # 登录时启动（按用户）
bento app                                                  # 或者从你的菜单启动它
```

`apt`/`dpkg` 会处理更新和卸载。它 **Recommends**（推荐）`bubblewrap`（沙箱）和 `xdg-utils`，并 **Suggests**（建议）`ollama`、`nodejs` 和 `git`。桌面软件包还额外 **Suggests** 会话 UI 技术栈以及 `wayvnc`/`novnc`——采用 suggested（建议）而非 depended（依赖），是因为 apt 默认会安装 Recommends，那样就等于换了个更温和的说法来做捆绑。

## 作为一个真正的应用安装（开机自启）—— 从源码

```bash
uv run bento install      # 应用启动器 + 一个登录/开机时启动的后台服务
```

正确的原生机制会被自动采用：在 Linux 上是一个 `.desktop` 启动器加上一个 **systemd 用户服务**（启用 linger，因此开机时启动），在 macOS 上是一个应用包加上 **LaunchAgents**，在 Windows 上是一个开始菜单快捷方式加上**启动项**。

一套命令驱动这三者——你不应该为了控制你自己的智能体，还得知道这台机器用的是 systemd 还是 launchd：

```bash
bento service status       # 它在运行吗、开机时会回来吗、端口有响应吗
bento service start        # …stop、restart
bento service logs -f      # journalctl 或日志文件，取决于这台机器用哪个
bento service uninstall    # 仅移除后台服务 —— 启动器和数据保留
bento uninstall            # 移除启动器 + 服务（你的数据保留）
bento app                  # 随时以一个无边框桌面窗口打开
```

`bento service status` 会分别报告监管进程所认为的状态**以及**端口是否响应：一个明明"活跃"却没有任何东西在监听的单元是一个崩溃循环，而那正是值得能被看见的状态。

---

## 启动模式

| 命令 | 它的作用 |
|---|---|
| `uv run bento` | 启动服务器**并**在你的浏览器中打开桌面 |
| `uv run bento serve --no-browser --port 8321` | 无头服务器（由开机自启服务使用） |
| `uv run bento app` | 以一个原生质感的窗口打开桌面 |
| `uv run bento tui` | 整个操作系统跑在一个终端里（**TUI**） |
| `uv run bento installer` | 检测这个发行版并设置 Linux 会话（**SUI**） |
| `uv run bento doctor` / `doctor --session` | 环境检查 / 这里什么东西能绘制桌面 |
| `uv run bento service status \| start \| stop \| restart \| logs \| uninstall` | 后台服务器，运行在这个操作系统所拥有的任何监管进程之上 |
| `uv run bento update` / `update --apply` | 检查是否有更新版本 / 拉取、同步、测试并重启 |
| `uv run bento config [key] [value]` | 读取或更改 `~/.agentos/config.json`（`--edit`、`--path`） |
| `uv run bento remote --port 8080 --bind 0.0.0.0` | 它作答所用的地址，保存到配置里 |
| `uv run bento serve --if-running open\|port\|restart\|fail` | 当已有一个在运行时该怎么办（默认：询问） |
| `uv run bento apps search \| install \| remove` | 原生应用程序，从终端操作 |
| `uv run bento remote --on --passphrase '…'` | 从你的手机访问这个桌面 |
| `uv run bento remote-desktop --on` | 浏览器远程桌面（真实屏幕、原生应用） |
| `uv run bento ask "…"` | 在终端里一次性运行智能体（`--full`、`--model …`） |
| `uv run bento user add <名字>` | 账户 —— 第一个账户会接管这台机器，并且是管理员 |
| `uv run bento help --all` | 全部命令；`bento --help` 只列出一台新机器需要的那十个 |

---

## 环境要求

- **Python ≥ 3.10** 和 [**uv**](https://docs.astral.sh/uv/)（或 pip）。
- **一个模型提供商**——要么是本地的 [Ollama](https://ollama.com)（推荐：一个具备工具调用能力的模型，例如 `qwen3.5:9b`），要么是一个云端 API 密钥。

以下为可选项，存在时可解锁额外功能——`bento installer` 会连同其许可证一并提供每一项：

- **Linux 会话（SUI）**——`sway` 及其相关组件，外加 `python3-gi`、`python3-gi-cairo`、`gir1.2-gtklayershell-0.1` 和 `gir1.2-webkit2-4.1`。[详情 →](../session-ui.md)
- **wayvnc + novnc**——从手机浏览器使用 Remote Desktop，经回环转发。
- **bubblewrap**（`bwrap`）——把智能体和终端关进单个文件夹的文件夹**沙箱**。
- **Node/npx** 和/或 **uvx**——用于运行 **MCP 服务器**（Playwright、filesystem、git……）。
- **git**——用于从代码仓库安装**技能**。

---

## 桌面

- **窗口**——每个应用都在一个可拖动、可调整大小的窗口中打开，带有最小化/最大化/关闭以及 z 轴层叠。一个**任务栏**跟踪打开的窗口；一个**开始菜单**启动一切。
- **会休眠的窗口**——一个你看不见的窗口会停止做周期性的工作，并在它一回来时立即刷新。六个应用打开且全部最小化，其请求从每 10 秒 25 次降到了 2 次。
- **虚拟桌面**——一个任务栏页面切换器；用 `Ctrl+1..6` 切换，右键点击可把一个窗口移到那里。小组件是按桌面区分的，所以每个桌面都是它自己的一片空间。
- **小组件**——把任何应用固定为一块无边框的实时磁贴；可拖动、可调整大小，并在启动时恢复。
- **命令面板**——用 `Ctrl+Space`（或 `Ctrl+K`）模糊启动任何应用或操作，或者用"Ask Aria …"直接发给智能体。`Ctrl+Alt+T` 打开一个终端。
- **观感**——AI 生成的壁纸配有一个本地图库、智能体工作时的一段思考动画，以及可选的语音。可以把图片直接粘贴到聊天里，供具备视觉能力的模型使用。

### 内置应用

| 应用 | 它是什么 |
|---|---|
| **Agent Chat** | 与智能体对话；流式、工具卡片、审批、语音、图片粘贴 |
| **Applications** | 每一个已安装的桌面应用——启动它们，或安装新的 |
| **Remote Desktop** | 机器的真实屏幕，可点击，从这里或从手机操作 |
| **Host Screen** | 真实显示的一张刷新中的静态截图，包含原生应用窗口 |
| **Web** | 在你**真实的系统浏览器**中打开 URL（完整站点、登录、扩展） |
| **Files** | 浏览工作区；点击一个文件即可在你的宿主浏览器/应用中打开它 |
| **Terminal** | 一个真实的宿主 shell（在 PTY 之上的 xterm.js），被关进沙箱文件夹 |
| **App Studio** | 用平实的语言描述一个应用，智能体就会**当场把它构建出来** |
| **Task Manager** | 实时的 CPU/内存/磁盘、进程、打开的窗口（以及哪些正在休眠） |
| **Knowledge Graph** | 智能体所知道的东西，以一张实时的力导向图呈现 |
| **Soul** | 智能体持久的身份/个性（每一轮都会注入） |
| **Memory** | 用户和会话记忆，带自动学习 + 语义召回 |
| **Profile** | 智能体所了解的关于你的一切，集中在一处 |
| **Team** | 子智能体和可视化工作流（每一步可混用模型）+ 可观测性 |
| **Docs** | 这份手册，就在操作系统内部 |
| **Automations** | 命名例程、热角，以及步骤构建器 |
| **Skills** | 可复用的流程；从一个 git 仓库或一个原始 `.md` URL 安装 |
| **MCP Servers** | 从一个目录连接外部工具服务器 |
| **Telegram** | 从你的手机控制智能体；按聊天设置允许名单 |
| **Policies** | 针对工具和命令的始终允许 / 始终拒绝规则 |
| **Logs** | 系统所做的一切（对话轮次、工具、MCP、telegram、任务） |
| **Scheduler** | 循环的后台**任务** |
| **Snapshots** | 整个操作系统的还原点（配置、数据和源码） |
| **Settings** | 提供商、模型、自主级别、语音、沙箱、智能体名字 |

---

## 智能体能做什么

这个智能体（默认名字为 **Aria**）拥有一套庞大的工具集，能从聊天或 Telegram 驱动整个操作系统：

- **在机器上行动**——运行 shell 命令、读写文件、抓取网页、在宿主上打开应用/文件、桌面通知。
- **交付成果**——`save_report` 会写出一份带样式的 HTML 报告，它会显示在 Files 里并在你的浏览器中打开，还能把一份摘要发送到 Telegram。智能体被告知要**把活干完**——把研究变成一份实实在在的交付物，而不是搜索完就停下。
- **构建操作系统**——`create_app` 制作带桌面图标的新 UI 应用；`pin_widget` 把它们放到桌面上；`add_mcp_server` 连接新的工具通道。
- **成长**——两级记忆、一张知识图谱、`update_soul`——外加**自动学习**：每一轮之后的一次后台处理会自行提取记忆和事实。
- **自动化**——`schedule_task` 创建无头**任务**，交付到一份报告和/或 Telegram。
- **扩展自身**——`read_source` / `develop_agentos` 让它修改 Bento **自己的源代码**；它会先自动快照，并在写入前做语法检查。

用平实的语言提要求即可：*"添加 github MCP 通道"、"给我构建一个习惯追踪器并把它固定到桌面 2"、"每天早晨把社交媒体趋势报告到我的 Telegram"、"安装 inkscape"。*

---

## 模型与提供商

- **Ollama**（本地）——自动发现；没有任何东西离开你的机器。
- **Anthropic**、**OpenAI**、**OpenRouter**，或任何**兼容 OpenAI** 的端点（LM Studio、vLLM、Groq……）。
- **图像生成**——设置了密钥时使用 Google Gemini 或 OpenAI 的图像模型，否则使用免费的后备方案。

`ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`OPENROUTER_API_KEY` 和 `GOOGLE_API_KEY` 会被自动识别。可以从聊天窗口的下拉框里中途切换模型。

---

## 安全

- **自主级别**——Paranoid（多疑）/ Balanced（平衡）会自动运行只读操作，并在做任何会修改系统的事情之前先征询；Full（完全）则运行一切。破坏性命令在每一个级别都被**硬性拦截**。
- **策略**——始终允许 / 始终拒绝规则（带 `*` 通配符），针对 `<tool> <command>` 进行匹配。
- **文件夹沙箱**——借助 bubblewrap，智能体的 shell/文件工具以及终端被关进单个文件夹；文件系统的其余部分为只读。
- **快照**——还原点；智能体在编辑自己的代码之前会自动快照。
- **默认私密**——绑定到 `127.0.0.1`。远程访问处于关闭状态，直到你用一个口令把它打开为止，而且从机器本身之外的任何地方安装软件都会被拒绝。

---

## Telegram · MCP · 可编程

**Telegram**——给 @BotFather 发消息，把 token 粘贴到 Telegram 应用里，第一个私聊会话就会成为所有者。智能体在那里拥有它全部的工具；有风险的操作会发送内联的 Allow/Deny 按钮。

**MCP 服务器**——从目录中添加外部工具服务器（Playwright、filesystem、fetch、git、GitHub、Postgres、Slack、search……），或者一个自定义的 `stdio`/`http` 服务器。它们的工具对智能体表现为 `mcp_<server>_<tool>`，对构建出的应用则通过 `POST /api/tool` 呈现。

**可编程**——`bento ask "…"` 用于一次性运行；一套 REST API（`POST /api/chat`、`GET /api/system`、`POST /api/tool`……）；`/ws` 上的 WebSocket（流式聊天 + 审批）和 `/ws/terminal`（宿主 PTY）。你构建的应用运行在一个同源 iframe 中，并且可以调用所有这些。

---

## 架构

```
agentos/                 # 这个 Python 包保留其最初的名字；见下方"关于名字"
├── __main__.py    # CLI 入口：serve · app · installer · doctor · apps · remote-desktop · ask
├── agent.py       # 内核：plan → act（工具）→ observe 循环、审批关卡、人设
├── providers.py   # 统一的流式聊天：Ollama / Anthropic / OpenAI / OpenRouter / 自定义
├── tools.py       # 双手：shell、文件、网页、应用、报告、记忆、KG、灵魂、技能、MCP
├── shellhost.py   # SUI：作为 wlr-layer-shell 表面的桌面（GTK + WebKitGTK）
├── sessiondoctor.py # 在这台机器上究竟什么东西能绘制桌面
├── compositor.py  # sway/wlroots IPC：窗口、工作区、输出、实时事件
├── appstore.py    # 通过 appstream / flatpak / apt 安装原生应用
├── remotedesktop.py # 浏览器远程桌面，经由已认证的连接转发
├── installer.py   # 感知操作系统的设置：检测发行版、安装缺失的东西、先征询
├── memory.py      # SQLite：对话、记忆、任务、日志、KG、技能、应用
├── server.py      # FastAPI：桌面 UI、REST API、WebSocket 流、文件服务
└── ui/
    ├── src/       # 桌面的源码 —— 在这里编辑
    └── index.html # 由 `python -m agentos.ui.build` 生成（请勿编辑）
```

**状态存放在 `~/.agentos/` 中：** `config.json`、SQLite 数据库、`soul.md`、`wallpapers/`、`snapshots/`。智能体的工作目录是 `~/AgentOS/`。

### 关于名字

产品是 **Bento Box AI**。Python 包、数据目录和 systemd 单元仍然是 `agentos`——这是有意为之。重命名它们会破坏每一个现有安装的服务、配置和脚本，而买给用户的是他们看不见的任何东西。它们会在有一次值得进行的迁移时才移动，而不是提前。这个名字和标识归我们所有，方式与 Ubuntu 的归 Canonical 所有一样：可以在 MIT 许可下自由地 fork 代码，以你自己的名字发布它。[许可与商标 →](../licensing.md)

---

*Bento Box AI 是一个开放的、本地优先的、对云端 AI 助手的替代品：一个由你自己运行的智能体操作系统、AI 桌面和自动化平台——运行在 Linux、macOS 或 Windows 上。*
