# Bento Box AI — um sistema operacional agêntico local-first

<p align="right"><sub>
<a href="../../README.md">English</a> ·
<a href="README.zh-CN.md">简体中文</a> ·
<a href="README.zh-TW.md">繁體中文</a> ·
<a href="README.ja.md">日本語</a> ·
<a href="README.ko.md">한국어</a> ·
<a href="README.es.md">Español</a> ·
<b>Português&nbsp;(BR)</b> ·
<a href="README.fr.md">Français</a> ·
<a href="README.de.md">Deutsch</a> ·
<a href="README.ru.md">Русский</a> ·
<a href="README.hi.md">हिन्दी</a> ·
<a href="README.ar.md">العربية</a>
</sub></p>

**Sua máquina, com um cérebro.** O Bento Box AI é um **ambiente de desktop com IA** auto-hospedado: um
desktop completo — janelas, apps, arquivos, terminal — conduzido por um **agente de IA autônomo** que executa
**ações reais** no seu computador. Use modelos locais via [Ollama](https://ollama.com) para privacidade total, ou
modelos na nuvem (Anthropic Claude, OpenAI, OpenRouter ou qualquer endpoint compatível com OpenAI) — sempre com
a sua aprovação. O agente pode navegar, criar seus próprios apps, agendar tarefas, lembrar o que aprende,
estender o próprio código-fonte e falar com você no Telegram ou WhatsApp.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Platforms](https://img.shields.io/badge/platform-Linux%20·%20macOS%20·%20Windows-lightgrey)
![Local-first](https://img.shields.io/badge/AI-local--first%20·%20Ollama%20·%20cloud%20optional-5eead4)

Roda em `http://127.0.0.1:8321` — privado por padrão, instalável como serviço de inicialização.

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh
```

![O desktop do Bento Box AI — chat do agente de IA, gerenciador de arquivos e configurações rápidas em um ambiente de desktop no navegador](../screenshots/desktop.png)

**A documentação completa está em [`docs/`](../README.md)** — instalação, um guia do usuário para o desktop
e cada app, o agente e suas ferramentas, criação de apps, integrações, a referência da API e
solução de problemas.

---

## A configuração tem onze passos, e cada um deixa algo para trás

Não é um formulário de configurações com uma barra de progresso. Cada passo **produz algo real** — um modelo
que responde, um agente que existe, um fluxo que roda, um agendamento que dispara — e diz o que
você vai obter antes de pedir qualquer coisa.

![A tela de configuração de primeira execução: uma trilha de onze passos à esquerda e, à direita, "Dê um nome ao seu agente" com a frase "Você vai terminar com: o nome na barra de menus e em cada resposta"](../screenshots/onboarding-1-name.png)

Cada passo é **verificado, nunca lembrado**: ele é marcado porque a máquina tem aquilo.
Exclua o agente e o passo volta a pendente. É isso que torna seguro repetir — e
repetir é algo normal de se fazer aqui, porque **a configuração também é um app**. Abra a qualquer momento para
ver o que um passo faz, em uma máquina que você configurou meses atrás.

![O app de configuração em uma janela: a trilha de onze passos à esquerda e o passo "Crie um especialista" aberto à direita](../screenshots/setup-app.png)

Mesmo catálogo, mesma verificação, mesmos painéis — inclusive em um terminal, onde `bento setup` por
SSH continua exatamente de onde o navegador parou.

---

## A primeira coisa que ele pergunta é qual tarefa fazer

A configuração termina com uma pergunta, não com uma porta: **me dê uma tarefa.** Escolha uma entre três, responda duas perguntas,
e esta máquina está fazendo algo por você antes mesmo de você abrir um único app.

![A tela de Tarefas: três receitas — me faça um resumo toda manhã, monitore uma pasta, me avise quando uma página mudar — com as perguntas da escolhida e exatamente o que ela terá permissão de fazer](../screenshots/jobs.png)

| | |
|---|---|
| **Me faça um resumo toda manhã** | lê sobre as coisas que você acompanha durante a noite e deixa uma página esperando |
| **Monitore uma pasta para mim** | percebe o que chega numa pasta *que você escolhe*, descobre o que é e te avisa |
| **Me avise quando uma página mudar** | verifica uma página e só fala quando algo real mudou |

Duas coisas que ele não fará. Ele não vai conceder a si mesmo nada que você não tenha visto: o painel imprime
as permissões exatas antes de você apertar o botão, computadas pelo mesmo código que as escreve —
"lê `~/Downloads/*`, e nada mais". E ele não vai oferecer uma forma de alcançar você que não
funcione: um Telegram não pareado é mostrado esmaecido com a frase que resolveria, nunca escondido e
nunca substituído silenciosamente.

O último botão é **"Rodar agora, para eu ver funcionar"** — porque um agendamento que você não viu
disparar é uma promessa, e um novo usuário não tem motivo para acreditar em uma.

Uma tarefa é um *fluxo*, não um tipo novo de coisa: mesmo agendador, mesmo portão de permissão, mesmo registro
de auditoria. Numa máquina sem tela: `bento job recipes`, depois `bento job add morning-brief --topics "…"`.

---

## Três faces, um programa

O Bento roda em três lugares, e **cada recurso é construído para os três**. Esta é a primeira
pergunta feita a qualquer mudança, não a última.

| | O que é | Inicie com |
|---|---|---|
| **GUI** | uma janela (ou aba) no macOS, Windows ou Linux. Nada extra para instalar | `bento` |
| **TUI** | o SO inteiro em um terminal — para um servidor, ou um Pi sem tela por SSH | `bento tui` |
| **SUI** | o Bento **é** sua sessão Linux: ele é dono da máquina | `bento installer` |

> O comando é `bento`. `agentos` ainda funciona e sempre funcionará — está no histórico de shell das pessoas,
> em unidades systemd e em scripts, e uma renomeação que nós escolhemos não deve custar isso a elas.

---

## Veja em ação

| | |
|---|---|
| ![Chat com o agente de IA — respostas em streaming, chamadas de ferramentas e aprovações](../screenshots/chat.png) **Chat do Agente** — converse com sua máquina; respostas em streaming, cartões de ferramentas, aprovações, voz | ![App Team — subagentes, workflows e observabilidade](../screenshots/team.png) **Team** — subagentes especialistas e workflows visuais, com mistura de modelos por passo |
| ![App de documentação embutido renderizando o manual completo](../screenshots/docs.png) **Docs** — o manual completo vive dentro do SO | ![Loja de apps — apps de um clique, skills e canais MCP](../screenshots/store.png) **Store** — apps de um clique, skills e canais de ferramentas MCP |

### Várias pessoas, uma máquina

Adicione uma conta e cada pessoa recebe **sua própria casa** — seu próprio banco de dados, memória, agentes,
canais, servidores MCP e credenciais. Não uma coluna `user_id` que uma cláusula `WHERE` esquecida
vaza: seu próprio diretório, porque dois arquivos não podem vazar um no outro.

![O app de Usuários: duas contas, Ada Lovelace marcada como admin e "esta é você", Bob Kahn com um menu de função definido como Executor](../screenshots/users-two-accounts.png)

Duas funções — **executor** (tudo dentro da própria casa) e **admin** (isso, mais a
máquina). As configurações permanecem compartilhadas, então há uma chave de provedor para a máquina em vez de uma
por pessoa. Agentes e apps cruzam deliberadamente, como cópias, através de uma biblioteca compartilhada.

E é **um único login, aqui e de qualquer lugar**: uma máquina com contas é trancada por
elas, então o celular no bolso de alguém usa o mesmo nome de usuário e senha do desktop
e chega na própria casa. Nenhuma segunda frase-senha compartilhada para inventar, compartilhar ou esquecer.

![O painel de Acesso remoto lendo "Trancado pelas contas desta máquina — todos entram do celular com o mesmo nome de usuário e senha que usam aqui"](../screenshots/remote-locked-by-accounts.png)

### Você consegue ver o que ele está fazendo

![Um turno em andamento: a chamada Read finalizada manteve sua duração, a chamada Bash em execução envelhece no lugar e a linha abaixo diz qual passo e quanto tempo o turno levou](../screenshots/agent-working.png)

Um turno é em grande parte espera, e "trabalhando…" por quatro minutos não te diz nada — um modelo pensando
e uma execução que morreu silenciosamente parecem idênticos assim. Cada superfície de espera diz **no que ela está
e por quanto tempo**: a chamada em execução envelhece no lugar (`running · 2m 14s`), chamadas finalizadas mantêm
sua duração, e a linha abaixo carrega o passo e o total do turno. A mesma frase
aparece na bolha de presença e na omnibar, então é respondível a partir do desktop sem
abrir o chat.

### Ele pode construir seu próprio time — e pede antes de fazer

![Aprovando uma delegação: o cartão nomeia o agente, o modelo, o orçamento de passos e tempo, e as ferramentas e skills exatas que ele teria](../screenshots/agent-approval.png)

Quando nenhum especialista existente serve, o agente **constrói um** e delega a ele. Definir um agente
não concede nada a ele; na primeira vez em que ele é de fato usado você recebe um cartão nomeando o modelo em que ele roda,
seu orçamento, e as ferramentas e skills exatas que sua definição lhe dá — porque o consentimento a um ator
que você não consegue imaginar é consentimento só no nome. Aprovar `researcher` não é aprovar `deploy-bot`,
e a concessão é revogável em Permissões como qualquer outra. [Como funciona →](../security.md)

### Ele responde perguntas sobre si mesmo a partir do próprio manual

![O app Docs respondendo uma pergunta sobre este SO, fundamentada no manual](../screenshots/docs-ask.png)

O manual está no índice de recuperação, então "como faço para impedir um app de acessar a internet mas mantê-lo
funcionando?" é respondido a partir **destas páginas**, não da memória de um modelo sobre um projeto diferente — e
a resposta nomeia a página que usou. É recuperação agêntica em vez de uma busca única: o agente
busca, lê, e busca de novo quando a primeira passada erra.

### Janelas que se comportam como janelas

![Quatro janelas do Bento empilhadas no desktop: a que está em foco carrega um anel de destaque e a sombra completa, as demais recuam](../screenshots/windows.png)

Uma janela abre **onde você deixou** — posição e tamanho são lembrados por app — e uma janela
abrindo pela primeira vez cai em cascata por mais do que uma barra de título, então a que está embaixo continua
legível. A janela em foco carrega um anel de destaque e a sombra completa; as demais recuam. O ✦
na barra de título é o agente *dentro daquele app*: pergunte a ele sobre o que está na tela sem sair dela.

### Cinco linguagens de design, não cinco paletas

![Os cinco temas de linguagem de design embutidos: Bento, Liquid Glass, Spatial, Claymorphism, Minimalism](../screenshots/themes.png)

**Bento · Liquid Glass · Spatial · Claymorphism · Minimalism.** Cada um recorta toda a interface —
superfícies, raios, elevação, desfoque, tipografia — e traz seu próprio papel de parede. Os papéis de parede vêm como SVG:
alguns KB cada, nítidos de um celular a um painel 4K. [Mais →](../desktop.md#themes)

Vidro é a coisa mais cara que um desktop pode desenhar, e o custo se acumula a cada janela que você
abre. **Themes → Effects** mede sua máquina e o reduz apenas se precisar — cinco janelas
em Liquid Glass foram de 6,5fps para 27 (reduzido) ou 60 (desligado).

### Ele te alcança onde você já está

![O canal do WhatsApp em Configurações: os quatro campos da Cloud API, a URL de callback para colar no console da Meta, o número pareado, e se a janela de 24 horas está aberta](../screenshots/channels-whatsapp.png)

**Telegram e WhatsApp são canais nativos** — a mesma conversa, a mesma memória, as mesmas
ferramentas e os mesmos botões de aprovação que na mesa. Não uma ponte de notificações: uma resposta do seu
celular continua a conversa que você começou esta manhã.

O WhatsApp tem **dois transportes**, e eles falham em direções opostas. A Cloud API da Meta é
oficial mas precisa de uma conta de desenvolvedor e um webhook público, e fora de 24 horas desde sua última
mensagem ela não vai carregar uma resposta em texto livre de jeito nenhum — o cartão diz se aquela janela está aberta, um
envio que não pode passar diz isso e como resolver, e uma tarefa agendada salva seu relatório primeiro
para que nada se perca. O link WhatsApp Web precisa apenas de uma leitura de QR e não tem janela de 24 horas, mas é
**não oficial** e o Bento diz isso no cartão de instalação antes de qualquer download. [Configuração →](../whatsapp.md)

O Telegram também é um **console de administração**: `/agents`, `/run`, `/flows`, `/model`, `/logs`, `/perms` —
apenas para o dono, e todo comando que *faz* algo passa pelo mesmo portão de permissão e os
mesmos botões de aprovação do desktop, então nunca é uma entrada mais barata. [Comandos →](../integrations.md)

### Um desktop, todas as telas

![Bento Box AI em um celular: a tela de bloqueio, o desktop disposto para um celular, e um app como uma folha de tela cheia](../screenshots/mobile.png)

Celular, tablet, estação de trabalho — o mesmo desktop, adaptando-se. Janelas viram folhas de tela cheia, o dock
ocupa a borda inferior, popovers viram folhas. Ative o **Acesso remoto** e alcance-o do seu celular
pela sua rede, atrás de uma frase-senha; *Adicionar à Tela de Início* o transforma em um app de tela cheia.
[Acesso remoto →](../remote-access.md) · [Layout responsivo →](../desktop.md#phone-tablet-desktop)

### Ele pode *ser* o desktop, não apenas viver em um

![Uma aplicação Wayland nativa acima do desktop do Bento, com a barra de menus reservada acima dela e o dock reservado abaixo dela](../screenshots/session-native-window.png)

Faça login e obtenha o Bento como sua sessão Linux. O desktop é desenhado como uma **superfície de camada Wayland na
camada de fundo**, então janelas de aplicações nativas ficam acima dela na ordem normal de empilhamento — não porque
algo seja elevado ou rebaixado, mas porque é isso que "fundo" significa. A barra de menus e o dock
ficam em faixas **reservadas com o compositor**, o mesmo mecanismo que um painel do GNOME ou KDE usa, então um
app de tela cheia para nas bordas delas em vez de engoli-las.

![Dois terminais nativos encaixados nas metades esquerda e direita do desktop do Bento](../screenshots/session-snapped.png)

Gerenciamento completo de janelas para apps nativos: encaixe em metades e quartos, tile, flutuar, layouts, redimensionamento por
teclado, workspaces, minimizar, e um alternador Alt-Tab — com a barra de tarefas e a barra de menus acompanhando
qualquer app que esteja em foco. [A interface de sessão →](../session-ui.md)

### Instale aplicações, de dentro do Bento

![O app Applications buscando no catálogo de pacotes da máquina, com botões de instalação por resultado](../screenshots/app-store.png)

Um desktop no qual você não consegue instalar software é uma demonstração. *Applications → Get apps…* busca no próprio
catálogo da máquina — AppStream, Flatpak ou apt — e mostra o comando exato antes de rodá-lo. O Flatpak
é preferido onde existe porque uma instalação por usuário não precisa de senha alguma. O Bento não espelha
nada e não empacota nada; ele pergunta ao gerenciador de pacotes que você já tem.

### Sua tela real, no seu celular, no navegador

![O Remote Desktop do Bento aberto no navegador de um celular, mostrando a tela real da máquina com um app nativo nela e uma barra de ferramentas de teclas que um teclado de celular não tem](../screenshots/phone-remote-desktop.png)

**Acesso remoto** te envia a interface do Bento, que é HTML e viaja perfeitamente — mas um app nativo
são pixels no próprio display da máquina e nunca fez parte da página. **Remote Desktop** resolve
isso: o Bento retransmite a tela pela sua *própria* conexão autenticada, então você obtém o desktop real,
clicável, sem nenhum app VNC para instalar no celular.

O formato é o ponto — o servidor VNC fica em `127.0.0.1` e nunca chega perto da rede; o que
o protege é a frase-senha que você já usa. [Acesso remoto →](../remote-access.md)

### Automações e cantos ativos

![O app Automations com rotinas salvas e o mapa de cantos ativos, e o construtor de passos](../screenshots/automations.png)

Nomeie uma sequência uma vez — abra estes apps, troque o tema, rode este Python, chame aquela ferramenta MCP, ponha o
agente numa tarefa — e rode-a para sempre depois pela barra de comando, um canto ativo, um agendamento, ou
pedindo por ela pelo nome. [Mais →](../desktop.md#automations)

---

## Por que o Bento Box AI

- **Um desktop de verdade, não uma caixa de chat** — janelas arrastáveis, barra de tarefas, desktops virtuais, widgets,
  temas, uma paleta de comandos, e mais de 25 apps embutidos.
- **Um agente com mãos** — comandos de shell, gerenciamento de arquivos, pesquisa na web, notificações de desktop,
  tarefas agendadas, relatórios HTML e criação de apps, tudo a partir de linguagem simples.
- **Local-first e privado** — tudo pode rodar no seu hardware com o Ollama; nada sai da sua
  máquina a menos que você adicione uma chave de nuvem. Vincula-se apenas ao localhost, até você deliberadamente ativar o
  [acesso remoto](../remote-access.md) protegido por frase-senha.
- **Todo o ciclo de vida sob um só teto** — **Treinar · Testar · Operar · Construir · Publicar · Gerenciar**, ao vivo
  em uma tela (Mission Control): faça fine-tuning dos seus próprios modelos na sua GPU, submeta cada
  automodificação a um portão de testes, rode tarefas agendadas, construa apps e publique-os no GitHub.
- **Auto-extensível** — o agente constrói novos apps de UI para si (App Studio), instala skills e servidores de
  ferramentas MCP, e pode modificar o próprio código-fonte do Bento (com snapshots automáticos e uma suíte de testes que
  deve passar antes de um reinício).
- **Memória que se acumula** — memória de dois níveis, um grafo de conhecimento ao vivo e uma "alma" persistente,
  aprendida automaticamente depois de cada conversa.
- **Seguro por design** — níveis de autonomia, prompts de aprovação, políticas de permitir/negar, um sandbox de pasta
  com bubblewrap, comandos destrutivos bloqueados na raiz, e pontos de restauração de um clique.

---

## Início rápido

**Um comando, no macOS ou Linux.** Ele instala tudo — incluindo o Python, via `uv` — inicia
o Bento, e então *prova que funciona* fazendo uma pergunta ao servidor em execução antes de dizer "pronto".

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh
```

Depois abra **http://127.0.0.1:8321**, ou rode `bento setup` para os mesmos onze passos em um terminal.

Se houver um terminal para perguntar, o instalador pergunta duas coisas antes de terminar: se esta máquina
deve ser alcançável a partir dos seus outros dispositivos e — em caso afirmativo — se você entra com uma
**frase-senha** ou com uma **conta**. Numa máquina sem tela, essa primeira pergunta é a diferença entre uma
instalação que você consegue olhar e uma que não. `--yes` deliberadamente não a responde: uma porta aberta
aqui é um shell aberto.

Ele deixa um comando `bento` no seu `PATH` (em `~/.local/bin`, adicionado ao seu perfil de shell se ele não
estivesse lá — abra um novo terminal depois). `bento --help` mostra os dez comandos de que uma máquina nova precisa; `bento help --all` é o resto.

### Instalando em um endereço e porta escolhidos

Em um servidor que você acessa por SSH, `127.0.0.1:8321` significa "acessível por nada". Dê ao
instalador uma frase-senha e um endereço e ele sobe pronto, com o serviço de inicialização já
apontado para a porta certa:

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --passphrase='something long and unguessable' --bind=0.0.0.0 --port=8080
```

Aquela máquina agora responde em **todas** as interfaces na porta 8080, e pede aquela frase-senha
antes de fazer qualquer coisa. O uso local através de `127.0.0.1:8080` permanece inalterado.

O instalador diz com qual das duas ele te deixou — `AgentOS is running` apenas quando algo
está genuinamente escutando. Numa máquina sem gerenciador de serviços à mão (um contêiner, uma distro
sem systemd, SSH sem D-Bus de usuário) ele diz isso em vez disso, e `bento service start` termina o trabalho.

Uma interface em vez de todas — uma VLAN privada, um endereço Tailscale:

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --passphrase='something long and unguessable' --bind=192.168.1.20 --port=8080
```

Apenas uma porta diferente, ainda somente loopback:

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --port=8080
```

> **`-s --` não é opcional.** `curl … | sh --port=8080` entrega a flag ao `sh`, que a rejeita
> — um script encanado não recebe argumentos próprios. `-s --` significa "o resto é para o script".
> Esta é a forma mais comum de essas flags se perderem, e o erro nomeia o `sh`, então
> parece um instalador quebrado.

**Todas as flags:**

| flag | o que ela faz |
|---|---|
| `--passphrase=SECRET` | exige isto para entrar, e permite vincular fora do loopback — dada aqui, o instalador não pergunta |
| `--bind=ADDR` | qual interface escutar (padrão `0.0.0.0`); precisa de `--passphrase` |
| `--port=N` | qual porta (padrão `8321`); salva na configuração, então o serviço de inicialização a usa |
| `--yes` | responde sim a todo componente opcional — **não** a abrir a porta |
| `--no-service` | sem launcher e sem serviço de inicialização (contêineres, CI) |
| `--no-verify` | pula o passo "prova que funciona" |

### Mudando depois

Tudo acima vive em **`~/.agentos/config.json`** (ou sob `$AGENTOS_HOME`), e
`bento config` lê e escreve nele sem você ter que encontrá-lo:

```bash
bento config                       # o arquivo inteiro, segredos mascarados
bento config port                  # uma configuração
bento config port 8080             # muda ela
bento config remote.bind 0.0.0.0   # caminhos pontilhados para configurações aninhadas
bento config --path                # onde o arquivo está
bento config --edit                # abre no $EDITOR — recusa salvar JSON inválido
```

`bento remote` são as mesmas configurações com as de acessibilidade agrupadas:

```bash
bento remote --on --passphrase 'something long' --bind 0.0.0.0   # um segredo compartilhado
bento user add alice && bento remote --on --bind 0.0.0.0          # ou uma conta para cada um
bento remote --port 8080                                          # a porta
bento remote                                                      # como está agora, e quem entra
```

**Uma mudança de porta não alcança um serviço de inicialização instalado sozinha** — a unidade systemd
e o LaunchAgent a fixam no `ExecStart`. Ambos os comandos avisam quando isso se aplica:

```bash
bento service install && bento service restart
```

> **Acessível de outras máquinas é uma escolha deliberada, não um padrão.** O Bento escuta em
> `127.0.0.1` apenas até ter uma tranca — uma frase-senha, ou uma conta com a qual alguém entra —, porque o
> agente tem um shell de verdade e uma porta aberta
> aqui é um shell aberto. `--bind` sozinho é recusado por esse motivo, e também
> `bento serve --host 0.0.0.0` com o acesso remoto desligado. As duas trancas são alternativas, não camadas: assim que existe uma conta, é ela a tranca, e uma frase-senha na frente é configuração que nada lê.

**Sobre portas abaixo de 1024.** Elas são recusadas a um processo não-root no Linux, e no macOS a
recusa é por endereço — ele concede `0.0.0.0:80` e nega `127.0.0.1:80`. Então nada aqui
adivinha pelo número: `--port` tenta o bind real e, se o kernel disser não, imprime a
linha `sysctl`, a regra de redirecionamento, ou a opção de proxy que resolve. No Linux, a porta 80 geralmente
significa um comando:

```bash
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/50-agentos.conf
sudo sysctl --system
```

Rodar o servidor como root não é aconselhável — o agente tem um shell de verdade.

<details>
<summary><b>A partir de um checkout do git em vez disso</b></summary>

```bash
uv sync                 # instala dependências (ou: pip install -e .)
uv run bento            # inicia o servidor e abre o desktop no seu navegador
```
</details>

<details>
<summary><b>No Docker</b></summary>

```bash
docker build -t bento .
docker run -d --name bento -p 8321:8321 -v bento-data:/data \
  -e AGENTOS_PASSPHRASE='something long and unguessable' bento
```

Um contêiner tem que vincular `0.0.0.0` para ser acessível, então a frase-senha é obrigatória em vez de
opcional — o entrypoint recusa iniciar inacessível *ou* inseguro e diz qual. Tudo o que
seria perdido vive no volume `/data`. Construa um branch específico com
`--build-arg SOURCE=git --build-arg REF=my-branch`.
</details>

Se o **Ollama** estiver rodando, seus modelos locais são detectados automaticamente. Adicione chaves de API de nuvem em
**Settings** se você as quiser. Essa é toda a configuração.

> **Dica:** builds, chamadas de ferramentas e tarefas de múltiplos passos são bem mais confiáveis com um **modelo
> capaz de usar ferramentas** (qualquer modelo `qwen*`, ou um modelo de nuvem). Modelos locais mais fracos como `gemma` não
> chamarão ferramentas de forma confiável.

---

## Rode-o como seu desktop Linux (SUI)

```bash
uv run bento installer      # detecta sua distro, instala o que falta, adiciona à tela de login
```

Depois faça logout e escolha **Bento Box AI** na tela de login. Seu desktop existente fica intocado —
voltar é fazer logout e escolher o Ubuntu de novo.

O instalador detecta a distribuição, nomeia cada pacote que quer e por quê, e pergunta antes de
instalar qualquer coisa. Dois grupos: o motor do compositor (o sway e companhia, MIT), e a superfície de desktop
nativa (`python3-gi`, `python3-gi-cairo`, gtk-layer-shell, WebKitGTK) que permite ao desktop
ser uma superfície Wayland de verdade em vez de uma janela de navegador.

**O Bento não distribui nem redistribui nenhum deles.** O gtk-layer-shell é MIT, mas GTK, PyGObject e
WebKitGTK são LGPL, e aquilo de que este projeto *depende* permanece permissivo — então eles são pedidos, com
as licenças à vista. Sem eles a sessão ainda roda, desenhando o desktop numa janela Chromium.
[Licenciamento →](../licensing.md) · [A interface de sessão →](../session-ui.md)

Se algo no desktop se comportar mal, um comando te diz por quê:

```bash
uv run bento doctor --session   # verifica o que realmente pode desenhar NESTA máquina, e diz
```

Ele verifica o interpretador, o display do GTK, o suporte a layer-shell do compositor, e se o WebKit
consegue renderizar *e continuar renderizando* — numa janela e numa superfície de camada — e então dá um veredito. As verificações
rodam em subprocessos, porque as falhas que ele procura são aborts e segfaults, e uma verificação que
trava o doctor não consegue relatar que travou.

---

## Instale como um pacote Debian/Ubuntu (.deb)

Um `.deb` autocontido (empacota o app **e** um venv Python com todas as dependências — nenhuma rede
necessária na instalação):

```bash
./packaging/build-deb.sh                                   # → packaging/dist/agentos_<ver>_<arch>.deb
sudo dpkg -i packaging/dist/agentos_0.1.0_amd64.deb        # instala em /opt/agentos + launcher + serviço
systemctl --user enable --now agentos                      # inicia no login (por usuário)
bento app                                                  # ou inicie a partir do seu menu
```

`apt`/`dpkg` cuida das atualizações e da remoção. Ele **Recommends** `bubblewrap` (sandbox) e `xdg-utils`,
e **Suggests** `ollama`, `nodejs` e `git`. O pacote de desktop adicionalmente **Suggests** a
pilha da interface de sessão e `wayvnc`/`novnc` — sugeridos em vez de dependidos, porque o apt instala
Recommends por padrão e isso seria empacotar com um nome mais suave.

## Instale como um app de verdade (auto-início na inicialização) — a partir do código-fonte

```bash
uv run bento install      # launcher de app + um serviço em segundo plano que inicia no login/boot
```

O mecanismo nativo certo é usado automaticamente: um launcher `.desktop` mais um **serviço de usuário
systemd** no Linux (com linger, para iniciar no boot), um app bundle mais **LaunchAgents** no
macOS, um atalho no Menu Iniciar mais **entradas de Inicialização** no Windows.

Um conjunto de comandos conduz os três — você não deveria ter que saber se esta máquina
usa systemd ou launchd para controlar seu próprio agente:

```bash
bento service status       # está rodando, vai voltar no boot, a porta está respondendo
bento service start        # …stop, restart
bento service logs -f      # journalctl ou o arquivo de log, o que esta máquina usar
bento service uninstall    # remove só o serviço em segundo plano — launcher e dados ficam
bento uninstall            # remove launcher + serviço (seus dados ficam)
bento app                  # abre como uma janela de desktop sem chrome a qualquer momento
```

`bento service status` reporta o que o supervisor acredita **e** se a porta
responde, separadamente: uma unidade que está "ativa" enquanto nada escuta é um loop
de travamento, e esse é o estado que vale a pena poder ver.

---

## Modos de inicialização

| Comando | O que ele faz |
|---|---|
| `uv run bento` | inicia o servidor **e** abre o desktop no seu navegador |
| `uv run bento serve --no-browser --port 8321` | servidor sem interface (usado pelo serviço de inicialização) |
| `uv run bento app` | abre o desktop como uma janela com cara de nativa |
| `uv run bento tui` | o SO inteiro em um terminal (**TUI**) |
| `uv run bento installer` | detecta esta distro e configura a sessão Linux (**SUI**) |
| `uv run bento doctor` / `doctor --session` | verificação de ambiente / o que pode desenhar o desktop aqui |
| `uv run bento service status \| start \| stop \| restart \| logs \| uninstall` | o servidor em segundo plano, em qualquer supervisor que este SO tenha |
| `uv run bento update` / `update --apply` | verifica uma versão mais nova / puxa, sincroniza, testa e reinicia |
| `uv run bento config [key] [value]` | lê ou muda `~/.agentos/config.json` (`--edit`, `--path`) |
| `uv run bento remote --port 8080 --bind 0.0.0.0` | o endereço em que ele responde, salvo na configuração |
| `uv run bento serve --if-running open\|port\|restart\|fail` | o que fazer quando um já está rodando (padrão: perguntar) |
| `uv run bento apps search \| install \| remove` | aplicações nativas, de um terminal |
| `uv run bento remote --on --passphrase '…'` | alcance este desktop do seu celular |
| `uv run bento remote-desktop --on` | o remote desktop no navegador (tela real, apps nativos) |
| `uv run bento ask "…"` | execução única do agente no terminal (`--full`, `--model …`) |
| `uv run bento user add <nome>` | contas — a primeira adota esta máquina e é administradora |
| `uv run bento help --all` | todos os comandos; `bento --help` mostra os dez de que uma máquina nova precisa |

---

## Requisitos

- **Python ≥ 3.10** e [**uv**](https://docs.astral.sh/uv/) (ou pip).
- **Um provedor de modelo** — ou [Ollama](https://ollama.com) localmente (recomendado: um modelo
  capaz de usar ferramentas como `qwen3.5:9b`), ou uma chave de API de nuvem.

Opcionais, desbloqueiam recursos extras quando presentes — `bento installer` oferece cada um com sua licença:

- **A sessão Linux (SUI)** — `sway` e companhia, mais `python3-gi`, `python3-gi-cairo`,
  `gir1.2-gtklayershell-0.1` e `gir1.2-webkit2-4.1`. [Detalhes →](../session-ui.md)
- **wayvnc + novnc** — Remote Desktop a partir do navegador de um celular, retransmitido no loopback.
- **bubblewrap** (`bwrap`) — o **sandbox** de pasta que confina o agente e o terminal a uma pasta.
- **Node/npx** e/ou **uvx** — para rodar **servidores MCP** (Playwright, filesystem, git, …).
- **git** — para instalar **skills** a partir de repositórios.

---

## O desktop

- **Janelas** — cada app abre numa janela arrastável e redimensionável com minimizar/maximizar/fechar e
  ordenação em z. Uma **barra de tarefas** acompanha as janelas abertas; um **menu Iniciar** lança tudo.
- **Janelas que dormem** — uma janela que você não consegue ver para de fazer trabalho periódico e atualiza no
  momento em que volta. Seis apps abertos e todos minimizados foram de 25 requisições por 10s para 2.
- **Desktops virtuais** — um pager na barra de tarefas; `Ctrl+1..6` para trocar, botão direito para mover uma janela para lá.
  Widgets são por desktop, então cada um é seu próprio espaço.
- **Widgets** — fixe qualquer app como um tile ao vivo sem moldura; arraste, redimensione, e ele é restaurado na inicialização.
- **Paleta de comandos** — `Ctrl+Space` (ou `Ctrl+K`) para lançamento fuzzy de qualquer app ou ação, ou
  "Ask Aria …" para enviar direto ao agente. `Ctrl+Alt+T` abre um terminal.
- **Aparência** — papéis de parede gerados por IA com uma galeria local, uma animação de pensamento enquanto o
  agente trabalha, e voz opcional. Cole imagens direto no chat para modelos capazes de visão.

### Apps embutidos

| App | O que é |
|---|---|
| **Agent Chat** | converse com o agente; streaming, cartões de ferramentas, aprovações, voz, colar imagem |
| **Applications** | todo app de desktop instalado — inicie-os, ou instale novos |
| **Remote Desktop** | a tela real da máquina, clicável, daqui ou de um celular |
| **Host Screen** | uma imagem estática atualizável do display real, incluindo janelas de apps nativos |
| **Web** | abre URLs no seu **navegador de sistema real** (sites completos, logins, extensões) |
| **Files** | navegue pelo workspace; clique num arquivo para abri-lo no seu navegador/app host |
| **Terminal** | um shell host de verdade (xterm.js sobre um PTY), confinado à pasta do sandbox |
| **App Studio** | descreva um app em linguagem simples e o agente **o constrói ao vivo** |
| **Task Manager** | CPU/memória/disco ao vivo, processos, janelas abertas (e quais estão dormindo) |
| **Knowledge Graph** | o que o agente sabe, como um grafo dirigido por forças ao vivo |
| **Soul** | a identidade/personalidade persistente do agente (injetada a cada turno) |
| **Memory** | memória de usuário e de sessão com auto-aprendizado + recuperação semântica |
| **Profile** | tudo o que o agente sabe sobre você, em um só lugar |
| **Team** | subagentes e workflows visuais (misture modelos por passo) + observabilidade |
| **Docs** | este manual, dentro do SO |
| **Automations** | rotinas nomeadas, cantos ativos, e o construtor de passos |
| **Skills** | procedimentos reutilizáveis; instale de um repo git ou uma URL `.md` bruta |
| **MCP Servers** | conecte servidores de ferramentas externos de um catálogo |
| **Telegram** | controle o agente do seu celular; allow-list por chat |
| **Policies** | regras de sempre-permitir / sempre-negar para ferramentas e comandos |
| **Logs** | tudo o que o sistema fez (turnos, ferramentas, MCP, telegram, tarefas) |
| **Scheduler** | **tarefas** recorrentes em segundo plano |
| **Snapshots** | pontos de restauração para o SO inteiro (config, dados e código-fonte) |
| **Settings** | provedores, modelo, autonomia, voz, sandbox, nome do agente |

---

## O que o agente pode fazer

O agente (nome padrão **Aria**) tem um grande conjunto de ferramentas e pode conduzir todo o SO a partir do chat ou
do Telegram:

- **Agir na máquina** — rodar comandos de shell, ler/escrever arquivos, buscar na web, abrir apps/arquivos no
  host, notificações de desktop.
- **Entregar resultados** — `save_report` escreve um relatório HTML estilizado que aparece em Files e abre no
  seu navegador, e pode enviar um resumo ao Telegram. O agente é instruído a **terminar o trabalho** — transformar
  pesquisa em um entregável de verdade, não parar depois de uma busca.
- **Construir o SO** — `create_app` cria novos apps de UI com um ícone de desktop; `pin_widget` os põe no
  desktop; `add_mcp_server` conecta novos canais de ferramentas.
- **Crescer** — memória de dois níveis, um grafo de conhecimento, `update_soul` — mais **auto-aprendizado**: uma passada
  em segundo plano depois de cada turno extrai memórias e fatos por conta própria.
- **Automatizar** — `schedule_task` cria **tarefas** sem interface que entregam a um relatório e/ou ao Telegram.
- **Estender a si mesmo** — `read_source` / `develop_agentos` permitem que ele modifique o **próprio código-fonte** do Bento;
  ele faz um snapshot automático primeiro e verifica a sintaxe antes de escrever.

Peça em linguagem simples: *"adicione o canal MCP do github", "construa um rastreador de hábitos e fixe no desktop
2", "toda manhã reporte tendências de redes sociais no meu Telegram", "instale o inkscape".*

---

## Modelos e provedores

- **Ollama** (local) — autodescoberto; nada sai da sua máquina.
- **Anthropic**, **OpenAI**, **OpenRouter**, ou qualquer endpoint **compatível com OpenAI** (LM Studio, vLLM,
  Groq, …).
- **Geração de imagens** — modelos de imagem do Google Gemini ou da OpenAI quando uma chave está definida, fallback
  gratuito caso contrário.

`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` e `GOOGLE_API_KEY` são detectados
automaticamente. Troque de modelo em pleno voo pelo menu suspenso da janela de chat.

---

## Segurança

- **Níveis de autonomia** — Paranoid / Balanced rodam automaticamente ações somente-leitura e perguntam antes de qualquer coisa que
  modifique o sistema; Full roda tudo. Comandos destrutivos são **bloqueados na raiz** em todos os níveis.
- **Políticas** — regras de sempre-permitir / sempre-negar (com curingas `*`) comparadas contra
  `<tool> <command>`.
- **Sandbox de pasta** — com o bubblewrap, as ferramentas de shell/arquivo do agente e o Terminal ficam confinados a
  uma pasta; o resto do sistema de arquivos fica somente-leitura.
- **Snapshots** — pontos de restauração; o agente faz snapshot automático antes de editar o próprio código.
- **Privado por padrão** — vincula-se a `127.0.0.1`. O acesso remoto fica desligado até você ligá-lo com uma
  frase-senha, e instalar software é recusado de qualquer lugar que não seja a própria máquina.

---

## Telegram · MCP · Programável

**Telegram** — mande mensagem ao @BotFather, cole o token no app do Telegram, e o primeiro chat privado
se torna o dono. O agente tem todas as suas ferramentas ali; ações arriscadas enviam botões inline de Allow/Deny.

**Servidores MCP** — adicione servidores de ferramentas externos do catálogo (Playwright, filesystem, fetch, git,
GitHub, Postgres, Slack, busca, …) ou um servidor `stdio`/`http` personalizado. Suas ferramentas aparecem ao
agente como `mcp_<server>_<tool>`, e aos apps construídos via `POST /api/tool`.

**Programável** — `bento ask "…"` para execuções únicas; uma API REST (`POST /api/chat`, `GET /api/system`,
`POST /api/tool`, …); WebSockets em `/ws` (chat em streaming + aprovações) e `/ws/terminal` (PTY do host).
Os apps que você constrói rodam num iframe de mesma origem e podem chamar tudo isso.

---

## Arquitetura

```
agentos/                 # o pacote Python mantém seu nome original; veja "Sobre o nome" abaixo
├── __main__.py    # ponto de entrada da CLI: serve · app · installer · doctor · apps · remote-desktop · ask
├── agent.py       # o kernel: loop planejar → agir (ferramentas) → observar, portões de aprovação, personas
├── providers.py   # chat unificado em streaming: Ollama / Anthropic / OpenAI / OpenRouter / custom
├── tools.py       # as mãos: shell, arquivos, web, apps, relatórios, memória, KG, alma, skills, MCP
├── shellhost.py   # a SUI: o desktop como uma superfície wlr-layer-shell (GTK + WebKitGTK)
├── sessiondoctor.py # o que realmente pode desenhar o desktop nesta máquina
├── compositor.py  # IPC do sway/wlroots: janelas, workspaces, saídas, eventos ao vivo
├── appstore.py    # instalação de aplicações nativas via appstream / flatpak / apt
├── remotedesktop.py # o remote desktop no navegador, retransmitido pela conexão autenticada
├── installer.py   # configuração ciente do SO: detecta a distro, instala o que falta, pergunta antes
├── memory.py      # SQLite: conversas, memórias, tarefas, logs, KG, skills, apps
├── server.py      # FastAPI: UI do desktop, API REST, streams WebSocket, servir arquivos
└── ui/
    ├── src/       # o código-fonte do desktop — edite aqui
    └── index.html # gerado por `python -m agentos.ui.build` (não edite)
```

**O estado vive em `~/.agentos/`:** `config.json`, o banco de dados SQLite, `soul.md`, `wallpapers/`,
`snapshots/`. O diretório de trabalho do agente é `~/AgentOS/`.

### Sobre o nome

O produto é o **Bento Box AI**. O pacote Python, o diretório de dados e a unidade systemd continuam sendo
`agentos` — deliberadamente. Renomear isso quebra o serviço, a config e os scripts de toda instalação existente,
e não dá ao usuário nada que ele possa ver. Eles mudarão quando houver uma migração que valha
a pena rodar, não antes. O nome e a marca são nossos do mesmo jeito que os do Ubuntu são da Canonical: bifurque o código
livremente sob MIT, distribua-o sob seu próprio nome. [Licenciamento e marcas →](../licensing.md)

---

*O Bento Box AI é uma alternativa aberta e local-first aos assistentes de IA na nuvem: um SO agêntico, desktop com IA,
e plataforma de automação que você mesmo roda — no Linux, macOS ou Windows.*
