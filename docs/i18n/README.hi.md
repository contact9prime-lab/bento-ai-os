# Bento Box AI — एक local-first एजेंटिक ऑपरेटिंग सिस्टम

<p align="right"><sub>
<a href="../../README.md">English</a> ·
<a href="README.zh-CN.md">简体中文</a> ·
<a href="README.zh-TW.md">繁體中文</a> ·
<a href="README.ja.md">日本語</a> ·
<a href="README.ko.md">한국어</a> ·
<a href="README.es.md">Español</a> ·
<a href="README.pt-BR.md">Português&nbsp;(BR)</a> ·
<a href="README.fr.md">Français</a> ·
<a href="README.de.md">Deutsch</a> ·
<a href="README.ru.md">Русский</a> ·
<b>हिन्दी</b> ·
<a href="README.ar.md">العربية</a>
</sub></p>

**आपकी मशीन, एक दिमाग के साथ।** Bento Box AI एक self-hosted **AI डेस्कटॉप एनवायरनमेंट** है: एक पूरा
डेस्कटॉप — विंडो, ऐप, फ़ाइलें, टर्मिनल — जिसे एक **स्वायत्त AI एजेंट** चलाता है जो आपके कंप्यूटर पर
**वास्तविक कार्रवाइयाँ** करता है। पूरी प्राइवेसी के लिए [Ollama](https://ollama.com) के ज़रिए local
मॉडल इस्तेमाल करें, या क्लाउड मॉडल (Anthropic Claude, OpenAI, OpenRouter, या कोई भी OpenAI-compatible
endpoint) — हमेशा आपकी मंज़ूरी के साथ। एजेंट ब्राउज़ कर सकता है, अपने खुद के ऐप बना सकता है, जॉब शेड्यूल
कर सकता है, जो सीखता है उसे याद रख सकता है, अपना खुद का सोर्स कोड बढ़ा सकता है, और Telegram या WhatsApp
पर आप तक पहुँच सकता है।

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Platforms](https://img.shields.io/badge/platform-Linux%20·%20macOS%20·%20Windows-lightgrey)
![Local-first](https://img.shields.io/badge/AI-local--first%20·%20Ollama%20·%20cloud%20optional-5eead4)

`http://127.0.0.1:8321` पर चलता है — डिफ़ॉल्ट रूप से प्राइवेट, boot-time सर्विस के रूप में इंस्टॉल करने योग्य।

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh
```

![The Bento Box AI desktop — AI agent chat, file manager, and quick settings in a browser-based desktop environment](../screenshots/desktop.png)

**पूरा डॉक्युमेंटेशन [`docs/`](../README.md) में है** — इंस्टॉलेशन, डेस्कटॉप और हर ऐप के लिए एक
यूज़र गाइड, एजेंट और उसके टूल, ऐप बनाना, इंटीग्रेशन, API रेफ़रेंस, और
ट्रबलशूटिंग।

---

## सेटअप ग्यारह कदमों का है, और हर एक कुछ पीछे छोड़ जाता है

यह प्रोग्रेस बार वाला कोई सेटिंग्स फ़ॉर्म नहीं है। हर कदम **कुछ वास्तविक चीज़ बनाता है** — एक मॉडल
जो जवाब देता है, एक एजेंट जो मौजूद है, एक फ़्लो जो चलता है, एक शेड्यूल जो फ़ायर होता है — और आपसे कुछ
भी माँगने से पहले बताता है कि आप अंत में किसके साथ रहेंगे।

![The first-run setup screen: a rail of eleven steps down the left, and on the right "Name your agent" with the line "You will end up with: the name on the menu bar and in every reply"](../screenshots/onboarding-1-name.png)

हर कदम **प्रोब किया जाता है, कभी याद नहीं रखा जाता**: वह इसलिए टिक होता है क्योंकि मशीन के पास वह चीज़
है। एजेंट को डिलीट करें और कदम वापस todo पर चला जाता है। यही चीज़ इसे दोबारा चलाने के लिए सुरक्षित बनाती है — और
दोबारा चलाना यहाँ एक सामान्य बात है, क्योंकि **सेटअप एक ऐप भी है।** कभी भी इसे खोलें और देखें कि कोई कदम क्या
करता है, उस मशीन पर जिसे आपने महीनों पहले सेटअप किया था।

![The Setup app in a window: the eleven-step rail on the left, and the "Build a specialist" step open on the right](../screenshots/setup-app.png)

वही कैटलॉग, वही प्रोब, वही पैन — टर्मिनल में भी, जहाँ SSH पर `bento setup` ठीक वहीं से उठाता है जहाँ
ब्राउज़र ने छोड़ा था।

---

## पहली चीज़ जो यह आपसे पूछता है वह यह है कि कौन-सा काम करना है

सेटअप एक सवाल पर खत्म होता है, दरवाज़े पर नहीं: **मुझे एक काम दो।** तीन में से एक चुनें, दो सवालों के जवाब दें,
और यह मशीन आपके लिए कुछ कर रही होती है इससे पहले कि आपने एक भी ऐप खोला हो।

![The Jobs screen: three recipes — brief me every morning, watch a folder, tell me when a page changes — with the chosen one's questions and exactly what it will be allowed to do](../screenshots/jobs.png)

| | |
|---|---|
| **हर सुबह मुझे ब्रीफ़ करो** | रात भर उन चीज़ों के बारे में पढ़ता है जिन्हें आप फ़ॉलो करते हैं और एक पेज तैयार छोड़ देता है |
| **मेरे लिए एक फ़ोल्डर पर नज़र रखो** | जो कुछ *आपके चुने हुए* फ़ोल्डर में आता है उसे नोटिस करता है, पता लगाता है कि वह क्या है, और आपको बताता है |
| **जब कोई पेज बदले तो मुझे बताओ** | एक पेज चेक करता है और तभी बोलता है जब सचमुच कुछ बदला हो |

दो चीज़ें जो यह नहीं करेगा। यह खुद को ऐसी कोई चीज़ नहीं देगा जिसे आपने देखा न हो: पैनल आपके बटन दबाने से पहले
सटीक अनुमतियाँ प्रिंट करता है, उसी कोड से गणना करके जो उन्हें लिखता है —
"`~/Downloads/*` पढ़ता है, और कुछ नहीं"। और यह आप तक पहुँचने का कोई ऐसा तरीका पेश नहीं करेगा जो काम न
करे: एक unpaired Telegram उस वाक्य के साथ धुँधला दिखाया जाता है जो इसे ठीक कर देगा, न कभी छिपाया जाता है
और न कभी चुपचाप बदला जाता है।

आख़िरी बटन है **"इसे अभी चलाओ, ताकि मैं इसे काम करते देख सकूँ"** — क्योंकि एक शेड्यूल जिसे आपने फ़ायर होते
न देखा हो वह एक वादा है, और एक नए यूज़र के पास उस पर यकीन करने की कोई वजह नहीं होती।

एक जॉब एक *फ़्लो* है, कोई नई तरह की चीज़ नहीं: वही शेड्यूलर, वही अनुमति गेट, वही ऑडिट
लेजर। किसी headless बॉक्स पर: `bento job recipes`, फिर `bento job add morning-brief --topics "…"`।

---

## तीन चेहरे, एक प्रोग्राम

Bento तीन जगहों पर चलता है, और **हर फ़ीचर तीनों के लिए बनाया जाता है**। यह किसी भी बदलाव के बारे में पहला
सवाल है, आख़िरी नहीं।

| | यह क्या है | इसे इससे शुरू करें |
|---|---|---|
| **GUI** | macOS, Windows या Linux पर एक विंडो (या टैब)। इंस्टॉल करने के लिए कुछ अतिरिक्त नहीं | `bento` |
| **TUI** | पूरा OS एक टर्मिनल में — किसी सर्वर के लिए, या SSH पर एक headless Pi के लिए | `bento tui` |
| **SUI** | Bento **ही** आपका Linux सेशन है: यह मशीन का मालिक है | `bento installer` |

> कमांड `bento` है। `agentos` अभी भी काम करता है और हमेशा करेगा — यह लोगों की शेल हिस्ट्री,
> systemd यूनिट और स्क्रिप्ट में है, और हमारे द्वारा चुना गया एक rename उन्हें इसकी कीमत नहीं चुकानी चाहिए।

---

## इसे कार्य करते हुए देखें

| | |
|---|---|
| ![Chat with the AI agent — streaming replies, tool calls, and approvals](../screenshots/chat.png) **Agent Chat** — अपनी मशीन से बात करें; स्ट्रीमिंग रिप्लाई, टूल कार्ड, अप्रूवल, वॉइस | ![Team app — subagents, workflows, and observability](../screenshots/team.png) **Team** — विशेषज्ञ subagent और विज़ुअल workflow, हर स्टेप के लिए मॉडल मिक्सिंग के साथ |
| ![Built-in documentation app rendering the full manual](../screenshots/docs.png) **Docs** — पूरा मैनुअल OS के अंदर ही रहता है | ![App store — one-click apps, skills, and MCP channels](../screenshots/store.png) **Store** — एक-क्लिक ऐप, skills, और MCP टूल चैनल |

### कई लोग, एक मशीन

एक अकाउंट जोड़ें और हर व्यक्ति को **अपना खुद का घर** मिलता है — अपना डेटाबेस, मेमोरी, एजेंट,
चैनल, MCP सर्वर और क्रेडेंशियल। कोई `user_id` कॉलम नहीं जिसे एक भूला हुआ `WHERE`
क्लॉज़ लीक कर दे: उनकी अपनी डायरेक्टरी, क्योंकि दो फ़ाइलें एक-दूसरे में लीक नहीं हो सकतीं।

![The Users app: two accounts, Ada Lovelace marked admin and "this is you", Bob Kahn with a role dropdown set to Executor](../screenshots/users-two-accounts.png)

दो भूमिकाएँ — **executor** (उनके अपने घर के अंदर सब कुछ) और **admin** (वह, साथ ही
मशीन)। सेटिंग्स साझा रहती हैं, इसलिए हर व्यक्ति के लिए एक के बजाय मशीन के लिए एक provider key होती है।
एजेंट और ऐप एक साझा लाइब्रेरी के ज़रिए, कॉपी के रूप में, जानबूझकर पार जाते हैं।

और यह **एक ही sign-in है, यहाँ और कहीं से भी**: अकाउंट वाली मशीन उनके द्वारा लॉक होती है,
इसलिए किसी की जेब में मौजूद फ़ोन वही username और password इस्तेमाल करता है जो डेस्कटॉप इस्तेमाल करता है
और उनके अपने घर में उतरता है। न कोई दूसरा साझा passphrase गढ़ना, साझा करना या भूलना पड़ता है।

![The Remote access panel reading "Locked by this machine's accounts — everyone signs in from their phone with the same username and password they use here"](../screenshots/remote-locked-by-accounts.png)

### आप देख सकते हैं कि यह क्या कर रहा है

![A turn in flight: the finished Read call kept its duration, the running Bash call ages in place, and the row underneath says which step and how long the turn has taken](../screenshots/agent-working.png)

एक टर्न ज़्यादातर इंतज़ार होता है, और चार मिनट तक "working…" आपको कुछ नहीं बताता — एक सोचता हुआ मॉडल
और एक रन जो चुपचाप मर चुका है, इसके नीचे एक जैसे दिखते हैं। हर इंतज़ार करने वाली सतह बताती है कि **वह किस
काम पर है और कितनी देर से**: चल रहा कॉल जगह पर ही पुराना होता जाता है (`running · 2m 14s`), पूरे हो चुके कॉल
अपनी अवधि रखते हैं, और नीचे की पंक्ति स्टेप और टर्न का कुल समय ढोती है। वही वाक्य presence bubble और omnibar
पर दिखता है, इसलिए इसका जवाब चैट खोले बिना डेस्कटॉप से ही दिया जा सकता है।

### यह अपनी टीम खुद बना सकता है — और ऐसा करने से पहले पूछता है

![Approving a delegation: the card names the agent, the model, the step and time budget, and the exact tools and skills it would hold](../screenshots/agent-approval.png)

जब कोई मौजूदा विशेषज्ञ फ़िट नहीं बैठता, तो एजेंट **एक बनाता है** और उसे काम सौंपता है। एक एजेंट को परिभाषित
करना उसे कुछ नहीं देता; पहली बार जब वह वास्तव में इस्तेमाल किया जाता है तो आपको एक कार्ड मिलता है जो उस मॉडल का नाम
बताता है जिस पर वह चलता है, उसका बजट, और वे सटीक टूल और skills जो उसकी परिभाषा उसे देती है — क्योंकि एक ऐसे actor
के लिए सहमति जिसकी आप कल्पना नहीं कर सकते, नाम भर की सहमति है। `researcher` को अप्रूव करना `deploy-bot` को
अप्रूव करना नहीं है, और यह ग्रांट किसी भी अन्य की तरह Permissions में रद्द किया जा सकता है। [यह कैसे काम करता है →](../security.md)

### यह अपने बारे में सवालों का जवाब अपने खुद के मैनुअल से देता है

![The Docs app answering a question about this OS, grounded in the manual](../screenshots/docs-ask.png)

मैनुअल retrieval index में है, इसलिए "मैं किसी ऐप को इंटरनेट तक पहुँचने से कैसे रोकूँ पर उसे काम करता कैसे
रखूँ?" का जवाब **इन्हीं पेजों** से दिया जाता है, किसी अलग प्रोजेक्ट की मॉडल की याददाश्त से नहीं — और
जवाब उस पेज का नाम बताता है जिसका उसने इस्तेमाल किया। यह एक-शॉट लुकअप के बजाय एजेंटिक retrieval है: एजेंट
खोजता है, पढ़ता है, और जब पहला प्रयास चूक जाता है तो फिर से खोजता है।

### विंडो जो विंडो की तरह बर्ताव करती हैं

![Four Bento windows stacked on the desktop: the focused one carries an accent ring and the full shadow, the rest recede](../screenshots/windows.png)

एक विंडो वहीं खुलती है **जहाँ आपने उसे छोड़ा था** — पोज़िशन और साइज़ हर ऐप के लिए याद रखे जाते हैं — और
पहली बार खुलने वाली विंडो एक title bar से ज़्यादा cascade होती है, ताकि नीचे वाली अभी भी
पढ़ने लायक रहे। फ़ोकस्ड विंडो एक accent ring और पूरा shadow ढोती है; बाकी पीछे हट जाती हैं। title bar में ✦
उस ऐप *के अंदर* का एजेंट है: स्क्रीन पर जो है उसके बारे में उसे छोड़े बिना पूछें।

### पाँच डिज़ाइन भाषाएँ, पाँच पैलेट नहीं

![The five built-in design-language themes: Bento, Liquid Glass, Spatial, Claymorphism, Minimalism](../screenshots/themes.png)

**Bento · Liquid Glass · Spatial · Claymorphism · Minimalism.** हर एक पूरे शेल को फिर से काटती है —
सतहें, radii, elevation, blur, टाइप — और अपना खुद का wallpaper लाती है। wallpaper SVG के रूप में शिप होते हैं:
हर एक कुछ KB का, फ़ोन से 4K पैनल तक तेज़। [और →](../desktop.md#themes)

Glass एक डेस्कटॉप द्वारा खींची जा सकने वाली सबसे महँगी चीज़ है, और लागत हर विंडो के साथ बढ़ती जाती है जिसे आप
खोलते हैं। **Themes → Effects** आपकी मशीन को नापता है और तभी कम करता है जब उसे ऐसा करना ही पड़े — Liquid Glass में पाँच विंडो
6.5fps से 27 (कम किया गया) या 60 (बंद) तक गईं।

### यह आप तक वहीं पहुँचता है जहाँ आप पहले से हैं

![The WhatsApp channel in Settings: the four Cloud API fields, the callback URL to paste into Meta's console, the paired number, and whether the 24-hour window is open](../screenshots/channels-whatsapp.png)

**Telegram और WhatsApp native चैनल हैं** — वही बातचीत, वही मेमोरी, वही
टूल और वही अप्रूवल बटन जैसे डेस्क पर। कोई नोटिफ़िकेशन ब्रिज नहीं: आपके
फ़ोन से एक रिप्लाई उस थ्रेड को जारी रखता है जो आपने आज सुबह शुरू किया था।

WhatsApp के **दो transport** हैं, और वे विपरीत दिशाओं में फ़ेल होते हैं। Meta का Cloud API
आधिकारिक है पर इसे एक developer account और एक public webhook चाहिए, और आपके आख़िरी संदेश से 24 घंटे के बाहर
यह कोई free-form रिप्लाई बिल्कुल नहीं ढोएगा — कार्ड बताता है कि वह window खुली है या नहीं, एक
send जो जा नहीं सकता वह ऐसा कहता है और इसे कैसे ठीक करना है, और एक शेड्यूल्ड जॉब अपनी रिपोर्ट पहले सेव कर देता है
ताकि कुछ खोए नहीं। WhatsApp Web link को सिर्फ़ एक QR स्कैन चाहिए और इसमें कोई 24-घंटे की window नहीं है, पर यह
**अनौपचारिक** है और Bento कुछ भी डाउनलोड होने से पहले इंस्टॉल कार्ड पर ऐसा कहता है। [सेटअप →](../whatsapp.md)

Telegram एक **admin कंसोल** भी है: `/agents`, `/run`, `/flows`, `/model`, `/logs`, `/perms` —
सिर्फ़ owner के लिए, और हर कमांड जो *कुछ करता है* वह उसी अनुमति गेट और उन्हीं अप्रूवल बटन से गुज़रता है जो डेस्कटॉप
के हैं, इसलिए यह कभी अंदर आने का सस्ता रास्ता नहीं है। [कमांड →](../integrations.md)

### एक डेस्कटॉप, हर स्क्रीन

![Bento Box AI on a phone: the lock screen, the desktop laid out for a phone, and an app as a full-bleed sheet](../screenshots/mobile.png)

फ़ोन, टैबलेट, वर्कस्टेशन — वही डेस्कटॉप, ढलता हुआ। विंडो full-bleed sheet बन जाती हैं, dock
निचले किनारे तक फैलता है, popover sheet बन जाते हैं। **Remote access** चालू करें और अपने नेटवर्क पर एक passphrase
के पीछे से अपने फ़ोन से इस तक पहुँचें; *Add to Home Screen* इसे एक full-screen ऐप बना देता है।
[Remote access →](../remote-access.md) · [Responsive layout →](../desktop.md#phone-tablet-desktop)

### यह डेस्कटॉप *पर* सिर्फ़ रहने के बजाय, डेस्कटॉप *बन* सकता है

![A native Wayland application above the Bento desktop, with the menu bar reserved above it and the dock reserved below it](../screenshots/session-native-window.png)

लॉग इन करें और Bento को अपने Linux सेशन के रूप में पाएँ। डेस्कटॉप एक **background layer पर Wayland layer
surface** के रूप में खींचा जाता है, इसलिए native एप्लिकेशन विंडो सामान्य stacking order में इसके ऊपर होती हैं — इसलिए नहीं
कि कुछ ऊपर या नीचे किया जाता है, बल्कि इसलिए कि "background" का यही मतलब है। menu bar और dock
उन बैंड में बैठते हैं जो **compositor के साथ रिज़र्व** हैं, वही तंत्र जो एक GNOME या KDE पैनल इस्तेमाल करता है, इसलिए एक
full-screen ऐप उन्हें निगलने के बजाय उनके किनारों पर रुक जाता है।

![Two native terminals snapped to the left and right halves of the Bento desktop](../screenshots/session-snapped.png)

native ऐप के लिए पूरा विंडो प्रबंधन: आधे और चौथाई में snap, टाइल, फ़्लोट, लेआउट, कीबोर्ड
रीसाइज़, workspace, minimise, और एक Alt-Tab switcher — taskbar और menu bar उस ऐप को ट्रैक करते हैं जिसके पास
फ़ोकस है। [सेशन UI →](../session-ui.md)

### Bento के अंदर से ही एप्लिकेशन इंस्टॉल करें

![The Applications app searching the machine's package catalogue, with install buttons per result](../screenshots/app-store.png)

एक डेस्कटॉप जिस पर आप सॉफ़्टवेयर इंस्टॉल नहीं कर सकते, वह एक डेमो है। *Applications → Get apps…* मशीन के
अपने कैटलॉग — AppStream, Flatpak या apt — को खोजता है और चलाने से पहले आपको सटीक कमांड दिखाता है। Flatpak
को वहाँ प्राथमिकता दी जाती है जहाँ यह मौजूद है क्योंकि per-user install को कोई password नहीं चाहिए। Bento कुछ भी
मिरर नहीं करता और कुछ भी bundle नहीं करता; यह उसी package manager से पूछता है जो आपके पास पहले से है।

### आपकी असली स्क्रीन, आपके फ़ोन पर, ब्राउज़र में

![Bento's Remote Desktop open in a phone browser, showing the machine's real screen with a native app on it and a toolbar of keys a phone keyboard lacks](../screenshots/phone-remote-desktop.png)

**Remote access** आपको Bento शेल भेजता है, जो HTML है और बेहद अच्छी तरह यात्रा करता है — पर एक native ऐप
मशीन के अपने डिस्प्ले पर पिक्सेल है और वह कभी पेज का हिस्सा नहीं था। **Remote Desktop** इसे
बंद कर देता है: Bento स्क्रीन को अपने *खुद के* authenticated कनेक्शन पर रिले करता है, इसलिए आपको असली डेस्कटॉप मिलता है,
क्लिक करने योग्य, फ़ोन पर इंस्टॉल करने के लिए कोई VNC ऐप के बिना।

आकार ही मुद्दा है — VNC सर्वर `127.0.0.1` पर रहता है और कभी नेटवर्क के पास नहीं जाता; जो
इसकी रक्षा करता है वह वही passphrase है जो आप पहले से इस्तेमाल करते हैं। [Remote access →](../remote-access.md)

### Automations और hot corners

![The Automations app with saved routines and the hot-corner map, and the step builder](../screenshots/automations.png)

एक sequence को एक बार नाम दें — ये ऐप खोलो, थीम बदलो, यह Python चलाओ, वह MCP टूल कॉल करो, एजेंट को
किसी काम पर लगाओ — और उसके बाद इसे हमेशा प्रॉम्प्ट बार से, एक hot corner से, एक शेड्यूल से, या
नाम से माँगकर चलाएँ। [और →](../desktop.md#automations)

---

## Bento Box AI क्यों

- **एक असली डेस्कटॉप, कोई चैट बॉक्स नहीं** — खींचने योग्य विंडो, taskbar, virtual desktop, विजेट,
  थीम, एक command palette, और 25+ built-in ऐप।
- **हाथों वाला एक एजेंट** — शेल कमांड, फ़ाइल प्रबंधन, वेब रिसर्च, डेस्कटॉप नोटिफ़िकेशन,
  शेड्यूल्ड जॉब, HTML रिपोर्ट, और ऐप-निर्माण, सब कुछ सादी भाषा से।
- **Local-first और प्राइवेट** — Ollama के साथ सब कुछ आपके हार्डवेयर पर चल सकता है; जब तक आप कोई क्लाउड key न
  जोड़ें तब तक कुछ भी आपकी मशीन से बाहर नहीं जाता। यह सिर्फ़ localhost से बँधता है, जब तक आप जानबूझकर
  passphrase-protected [remote access](../remote-access.md) चालू न करें।
- **पूरा lifecycle एक ही छत के नीचे** — **Train · Test · Operate · Build · Ship · Manage**, एक
  स्क्रीन (Mission Control) पर जीवित: अपने GPU पर अपने खुद के मॉडल fine-tune करें, हर
  self-modification को test-gate करें, शेड्यूल्ड जॉब चलाएँ, ऐप बनाएँ, और उन्हें GitHub पर ship करें।
- **Self-extending** — एजेंट अपने लिए नए UI ऐप बनाता है (App Studio), skills और MCP
  टूल सर्वर इंस्टॉल करता है, और Bento का अपना सोर्स कोड बदल सकता है (auto-snapshots और एक test suite के साथ जो
  restart से पहले पास होना चाहिए)।
- **मेमोरी जो जुड़ती जाती है** — दो-स्तरीय मेमोरी, एक लाइव knowledge graph, और एक स्थायी "soul",
  जो हर बातचीत के बाद अपने आप सीखा जाता है।
- **डिज़ाइन से ही सुरक्षित** — autonomy स्तर, अप्रूवल प्रॉम्प्ट, allow/deny पॉलिसी, एक bubblewrap फ़ोल्डर
  sandbox, हार्ड-ब्लॉक की गई विनाशकारी कमांड, और एक-क्लिक restore points।

---

## Quickstart

**एक कमांड, macOS या Linux पर।** यह सब कुछ इंस्टॉल करता है — Python सहित, `uv` के ज़रिए — Bento
शुरू करता है, और फिर "done" कहने से पहले चल रहे सर्वर से एक सवाल पूछकर *साबित करता है कि यह काम करता है*।

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh
```

फिर **http://127.0.0.1:8321** खोलें, या टर्मिनल में उन्हीं ग्यारह कदमों के लिए `bento setup` चलाएँ।

अगर पूछने के लिए कोई टर्मिनल मौजूद है, तो installer ख़त्म होने से पहले दो चीज़ें पूछता है: क्या यह मशीन आपके
बाक़ी उपकरणों से पहुँच योग्य होनी चाहिए, और — अगर हाँ — तो आप **passphrase** से sign in करेंगे या किसी
**account** से। बिना स्क्रीन वाली मशीन पर वह पहला सवाल ही तय करता है कि install ऐसा है जिसे आप देख सकते हैं
या ऐसा जिसे नहीं। `--yes` जानबूझकर इसका जवाब नहीं देता: यहाँ एक खुला पोर्ट एक खुला शेल है।

यह आपके `PATH` पर एक `bento` कमांड छोड़ता है (`~/.local/bin` में, आपके शेल प्रोफ़ाइल में जोड़ा गया अगर यह
वहाँ नहीं था — बाद में एक नया टर्मिनल खोलें)। `bento --help` वे दस कमांड दिखाता है जो एक नई मशीन को चाहिए; बाक़ी सब `bento help --all` में हैं।

### इसे चुने हुए पते और पोर्ट पर इंस्टॉल करना

एक सर्वर पर जिस तक आप SSH के ज़रिए पहुँचते हैं, `127.0.0.1:8321` का मतलब है "किसी से भी पहुँच योग्य नहीं"। इंस्टॉलर को
एक passphrase और एक पता दें और यह तैयार होकर आता है, boot सर्विस पहले से ही सही पोर्ट पर
इशारा किए हुए:

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --passphrase='something long and unguessable' --bind=0.0.0.0 --port=8080
```

वह मशीन अब पोर्ट 8080 पर **हर** इंटरफ़ेस पर जवाब देती है, और कुछ भी करने से पहले उस passphrase
के लिए पूछती है। `127.0.0.1:8080` के ज़रिए local इस्तेमाल अपरिवर्तित रहता है।

इंस्टॉलर बताता है कि दोनों में से किसके साथ उसने आपको छोड़ा — `AgentOS is running` तभी जब कुछ
वास्तव में सुन रहा हो। ऐसे बॉक्स पर जिसके पास कोई सर्विस मैनेजर न हो (एक container, एक non-systemd
distro, बिना user D-Bus के SSH) यह इसके बजाय ऐसा कहता है, और `bento service start` काम पूरा करता है।

सबके बजाय एक इंटरफ़ेस — एक निजी VLAN, एक Tailscale पता:

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --passphrase='something long and unguessable' --bind=192.168.1.20 --port=8080
```

सिर्फ़ एक अलग पोर्ट, फिर भी सिर्फ़ loopback:

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --port=8080
```

> **`-s --` वैकल्पिक नहीं है।** `curl … | sh --port=8080` फ़्लैग को `sh` को सौंप देता है, जो इसे
> अस्वीकार करता है — एक piped स्क्रिप्ट को अपने खुद के कोई तर्क नहीं मिलते। `-s --` का मतलब है "बाकी स्क्रिप्ट के लिए है"।
> ये फ़्लैग खोने का यह सबसे आम तरीका है, और एरर `sh` का नाम लेता है, इसलिए यह
> एक टूटे हुए इंस्टॉलर जैसा पढ़ा जाता है।

**सभी फ़्लैग:**

| flag | यह क्या करता है |
|---|---|
| `--passphrase=SECRET` | sign in करने के लिए इसकी ज़रूरत हो, और loopback से बाहर binding की अनुमति दे — यहाँ दे दिया तो installer पूछता नहीं |
| `--bind=ADDR` | किस इंटरफ़ेस पर सुनना है (डिफ़ॉल्ट `0.0.0.0`); इसे `--passphrase` चाहिए |
| `--port=N` | कौन-सा पोर्ट (डिफ़ॉल्ट `8321`); config में सेव किया जाता है, इसलिए boot सर्विस इसे इस्तेमाल करती है |
| `--yes` | हर वैकल्पिक कंपोनेंट को हाँ में जवाब दें — पोर्ट खोलने को **नहीं** |
| `--no-service` | कोई launcher नहीं और कोई boot सर्विस नहीं (containers, CI) |
| `--no-verify` | "prove it works" कदम छोड़ें |

### इसे बाद में बदलना

ऊपर की हर चीज़ **`~/.agentos/config.json`** में रहती है (या `$AGENTOS_HOME` के अंतर्गत), और
`bento config` इसे पढ़ता और लिखता है बिना आपको इसे ढूँढना पड़े:

```bash
bento config                       # the whole file, secrets masked
bento config port                  # one setting
bento config port 8080             # change it
bento config remote.bind 0.0.0.0   # dotted paths for nested settings
bento config --path                # where the file is
bento config --edit                # open it in $EDITOR — refuses to save invalid JSON
```

`bento remote` वही सेटिंग्स हैं जिनमें reachability वाली सेटिंग्स एक साथ समूहबद्ध हैं:

```bash
bento remote --on --passphrase 'something long' --bind 0.0.0.0   # one shared secret
bento user add alice && bento remote --on --bind 0.0.0.0          # or an account each
bento remote --port 8080                                          # the port
bento remote                                                      # what it is now, and who signs in
```

**एक पोर्ट बदलाव अपने आप एक इंस्टॉल किए गए boot सर्विस तक नहीं पहुँचता** — systemd यूनिट
और LaunchAgent इसे `ExecStart` में पका देते हैं। दोनों कमांड आपको बताते हैं कि यह कब लागू होता है:

```bash
bento service install && bento service restart
```

> **अन्य मशीनों से पहुँच योग्य होना एक जानबूझकर लिया गया फ़ैसला है, कोई डिफ़ॉल्ट नहीं।** Bento
> सिर्फ़ `127.0.0.1` पर सुनता है जब तक इसे एक ताला न मिल जाए — एक passphrase, या एक account जिससे कोई sign in
> करता है — क्योंकि एजेंट के पास एक असली शेल है, और यहाँ एक खुला
> पोर्ट एक खुला शेल है। इसी वजह से अकेले `--bind` अस्वीकार किया जाता है, और वैसे ही
> remote access बंद होने पर `bento serve --host 0.0.0.0` भी। दोनों ताले विकल्प हैं, परतें नहीं: जैसे ही कोई account बनता है, वही ताला है, और उसके आगे रखा passphrase ऐसा config है जिसे कुछ भी नहीं पढ़ता।

**1024 से नीचे के पोर्ट के बारे में।** Linux पर उन्हें non-root process को अस्वीकार किया जाता है, और macOS पर
अस्वीकृति per-address है — यह `0.0.0.0:80` देता है और `127.0.0.1:80` को नकारता है। इसलिए यहाँ कुछ भी
संख्या से अनुमान नहीं लगाता: `--port` असली bind की कोशिश करता है और, अगर kernel ना कहता है, तो
`sysctl` लाइन, redirect नियम, या proxy विकल्प प्रिंट करता है जो इसे ठीक करता है। Linux पर, पोर्ट 80 आमतौर पर
एक कमांड का मतलब है:

```bash
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/50-agentos.conf
sudo sysctl --system
```

सर्वर को root के रूप में चलाने की सलाह नहीं दी जाती — एजेंट के पास एक असली शेल है।

<details>
<summary><b>इसके बजाय एक git checkout से</b></summary>

```bash
uv sync                 # install dependencies (or: pip install -e .)
uv run bento            # start the server and open the desktop in your browser
```
</details>

<details>
<summary><b>Docker में</b></summary>

```bash
docker build -t bento .
docker run -d --name bento -p 8321:8321 -v bento-data:/data \
  -e AGENTOS_PASSPHRASE='something long and unguessable' bento
```

एक container को बिल्कुल पहुँच योग्य होने के लिए `0.0.0.0` से बँधना पड़ता है, इसलिए passphrase वैकल्पिक के बजाय
आवश्यक है — entrypoint unreachable *या* insecure शुरू होने से इनकार करता है और आपको बताता है कि कौन-सा।
जो कुछ भी खोया जाएगा वह `/data` volume में रहता है। किसी खास branch को
`--build-arg SOURCE=git --build-arg REF=my-branch` के साथ बनाएँ।
</details>

अगर **Ollama** चल रहा है, तो आपके local मॉडल अपने आप उठा लिए जाते हैं। अगर आप उन्हें चाहते हैं तो
**Settings** के अंतर्गत क्लाउड API keys जोड़ें। बस इतना ही सेटअप है।

> **टिप:** builds, tool-calling, और multi-step टास्क एक **tool-capable
> मॉडल** (कोई भी `qwen*` मॉडल, या एक क्लाउड मॉडल) के साथ कहीं ज़्यादा भरोसेमंद होते हैं। `gemma` जैसे कमज़ोर local मॉडल
> भरोसेमंद तरीके से टूल कॉल नहीं करेंगे।

---

## इसे अपने Linux डेस्कटॉप के रूप में चलाएँ (SUI)

```bash
uv run bento installer      # detects your distro, installs what's missing, adds it to the login screen
```

फिर लॉग आउट करें और login screen पर **Bento Box AI** चुनें। आपका मौजूदा डेस्कटॉप अछूता रहता है —
वापस स्विच करना बस लॉग आउट करना और फिर से Ubuntu चुनना है।

इंस्टॉलर distribution का पता लगाता है, वह हर package नाम देता है जो वह चाहता है और क्यों, और कुछ भी
इंस्टॉल करने से पहले पूछता है। दो समूह: compositor engine (sway और साथी, MIT), और native
डेस्कटॉप surface (`python3-gi`, `python3-gi-cairo`, gtk-layer-shell, WebKitGTK) जो डेस्कटॉप को
ब्राउज़र विंडो के बजाय एक असली Wayland surface होने देता है।

**Bento इनमें से किसी को शिप या पुनर्वितरित नहीं करता।** gtk-layer-shell MIT है, पर GTK, PyGObject और
WebKitGTK LGPL हैं, और जिस पर यह प्रोजेक्ट *निर्भर* करता है वह permissive रहता है — इसलिए इन्हें माँगा जाता है, licences
सामने रखते हुए। इनके बिना भी सेशन चलता है, डेस्कटॉप को एक Chromium विंडो में खींचते हुए।
[Licensing →](../licensing.md) · [सेशन UI →](../session-ui.md)

अगर डेस्कटॉप के बारे में कुछ भी गड़बड़ करे, तो एक कमांड आपको बताता है क्यों:

```bash
uv run bento doctor --session   # probes what can actually draw on THIS machine, and says so
```

यह interpreter, GTK के डिस्प्ले, compositor के layer-shell समर्थन को चेक करता है, और क्या WebKit
render कर सकता है *और render करता रहता है* — एक विंडो में और एक layer surface पर — फिर एक फ़ैसला देता है। प्रोब
subprocess में चलते हैं, क्योंकि जिन failures की यह तलाश करता है वे abort और segfault हैं, और एक प्रोब जो
doctor को क्रैश कर देता है वह रिपोर्ट नहीं कर सकता कि वह क्रैश हुआ।

---

## एक Debian/Ubuntu package (.deb) के रूप में इंस्टॉल करें

एक self-contained `.deb` (ऐप **और** सभी dependencies वाला एक Python venv bundle करता है — इंस्टॉल पर कोई नेटवर्क
ज़रूरत नहीं):

```bash
./packaging/build-deb.sh                                   # → packaging/dist/agentos_<ver>_<arch>.deb
sudo dpkg -i packaging/dist/agentos_0.1.0_amd64.deb        # installs to /opt/agentos + launcher + service
systemctl --user enable --now agentos                      # start at login (per user)
bento app                                                  # or launch it from your menu
```

`apt`/`dpkg` अपडेट और हटाना संभालता है। यह `bubblewrap` (sandbox) और `xdg-utils` की **Recommends** करता है,
और `ollama`, `nodejs`, और `git` की **Suggests** करता है। डेस्कटॉप package इसके अतिरिक्त
session-UI stack और `wayvnc`/`novnc` की **Suggests** करता है — depend करने के बजाय suggest करता है, क्योंकि apt
डिफ़ॉल्ट रूप से Recommends इंस्टॉल करता है और वह एक नरम नाम के साथ bundling करना ही होगा।

## एक असली ऐप के रूप में इंस्टॉल करें (boot पर auto-start) — source से

```bash
uv run bento install      # app launcher + a background service that starts at login/boot
```

सही native तंत्र अपने आप इस्तेमाल किया जाता है: Linux पर एक `.desktop` launcher प्लस एक **systemd user
service** (linger के साथ, ताकि यह boot पर शुरू हो), macOS पर एक app bundle प्लस **LaunchAgents**,
Windows पर एक Start Menu shortcut प्लस **Startup entries**।

कमांड का एक सेट तीनों को चलाता है — आपको यह जानने की ज़रूरत नहीं होनी चाहिए कि यह बॉक्स
अपने खुद के एजेंट को नियंत्रित करने के लिए systemd या launchd इस्तेमाल करता है:

```bash
bento service status       # is it running, will it come back at boot, is the port answering
bento service start        # …stop, restart
bento service logs -f      # journalctl or the log file, whichever this machine uses
bento service uninstall    # remove the background service only — launcher and data stay
bento uninstall            # remove launcher + service (your data stays)
bento app                  # open as a chromeless desktop window any time
```

`bento service status` वह रिपोर्ट करता है जो supervisor मानता है **और** क्या पोर्ट
जवाब देता है, अलग-अलग: एक यूनिट जो "active" है जबकि कुछ भी नहीं सुन रहा एक crash
loop है, और वही वह स्थिति है जिसे देख पाना काम का है।

---

## Launch modes

| Command | यह क्या करता है |
|---|---|
| `uv run bento` | सर्वर शुरू करता है **और** आपके ब्राउज़र में डेस्कटॉप खोलता है |
| `uv run bento serve --no-browser --port 8321` | headless सर्वर (boot सर्विस द्वारा इस्तेमाल किया जाता है) |
| `uv run bento app` | डेस्कटॉप को एक native-feel विंडो के रूप में खोलता है |
| `uv run bento tui` | पूरा OS एक टर्मिनल में (**TUI**) |
| `uv run bento installer` | इस distro का पता लगाता है और Linux सेशन सेटअप करता है (**SUI**) |
| `uv run bento doctor` / `doctor --session` | environment जाँच / यहाँ डेस्कटॉप क्या खींच सकता है |
| `uv run bento service status \| start \| stop \| restart \| logs \| uninstall` | background सर्वर, जो भी supervisor इस OS के पास है उस पर |
| `uv run bento update` / `update --apply` | नए version के लिए जाँच / pull, sync, test और restart |
| `uv run bento config [key] [value]` | `~/.agentos/config.json` पढ़ें या बदलें (`--edit`, `--path`) |
| `uv run bento remote --port 8080 --bind 0.0.0.0` | वह पता जिस पर यह जवाब देता है, config में सेव किया गया |
| `uv run bento serve --if-running open\|port\|restart\|fail` | जब कोई पहले से चल रहा हो तो क्या करना है (डिफ़ॉल्ट: पूछो) |
| `uv run bento apps search \| install \| remove` | native एप्लिकेशन, एक टर्मिनल से |
| `uv run bento remote --on --passphrase '…'` | इस डेस्कटॉप तक अपने फ़ोन से पहुँचें |
| `uv run bento remote-desktop --on` | ब्राउज़र remote desktop (असली स्क्रीन, native ऐप) |
| `uv run bento ask "…"` | टर्मिनल में एक-शॉट एजेंट रन (`--full`, `--model …`) |
| `uv run bento user add <नाम>` | accounts — पहला वाला इस मशीन को अपना लेता है और admin होता है |
| `uv run bento help --all` | हर कमांड; `bento --help` वे दस दिखाता है जो एक नई मशीन को चाहिए |

---

## आवश्यकताएँ

- **Python ≥ 3.10** और [**uv**](https://docs.astral.sh/uv/) (या pip)।
- **एक मॉडल provider** — या तो [Ollama](https://ollama.com) local (अनुशंसित: एक tool-capable
  मॉडल जैसे `qwen3.5:9b`), या एक क्लाउड API key।

वैकल्पिक, मौजूद होने पर अतिरिक्त फ़ीचर अनलॉक करते हैं — `bento installer` हर एक को उसके licence के साथ पेश करता है:

- **Linux सेशन (SUI)** — `sway` और साथी, प्लस `python3-gi`, `python3-gi-cairo`,
  `gir1.2-gtklayershell-0.1` और `gir1.2-webkit2-4.1`। [विवरण →](../session-ui.md)
- **wayvnc + novnc** — एक फ़ोन ब्राउज़र से Remote Desktop, loopback पर रिले किया गया।
- **bubblewrap** (`bwrap`) — फ़ोल्डर **sandbox** जो एजेंट और टर्मिनल को एक फ़ोल्डर में जेल करता है।
- **Node/npx** और/या **uvx** — **MCP सर्वर** चलाने के लिए (Playwright, filesystem, git, …)।
- **git** — repositories से **skills** इंस्टॉल करने के लिए।

---

## डेस्कटॉप

- **Windows** — हर ऐप एक खींचने योग्य, रीसाइज़ करने योग्य विंडो में खुलता है जिसमें minimize/maximize/close और
  z-ordering होती है। एक **taskbar** खुली विंडो को ट्रैक करता है; एक **Start menu** सब कुछ लॉन्च करता है।
- **सोने वाली विंडो** — एक विंडो जिसे आप नहीं देख सकते वह periodic काम करना बंद कर देती है और
  वापस आते ही रिफ़्रेश करती है। छह ऐप खुले और सभी minimise, 25 requests प्रति 10s से 2 तक गए।
- **Virtual desktops** — एक taskbar pager; स्विच करने के लिए `Ctrl+1..6`, विंडो को वहाँ ले जाने के लिए right-click।
  विजेट per-desktop होते हैं, इसलिए हर एक अपना खुद का स्पेस है।
- **Widgets** — किसी भी ऐप को एक frameless लाइव टाइल के रूप में pin करें; खींचें, रीसाइज़ करें, और यह startup पर बहाल हो जाता है।
- **Command palette** — किसी भी ऐप या क्रिया के fuzzy launch के लिए `Ctrl+Space` (या `Ctrl+K`), या
  सीधे एजेंट को भेजने के लिए "Ask Aria …"। `Ctrl+Alt+T` एक टर्मिनल खोलता है।
- **Look & feel** — एक local gallery के साथ AI-generated wallpaper, एजेंट के काम करते समय एक thinking
  animation, और वैकल्पिक वॉइस। vision-capable मॉडल के लिए इमेज सीधे चैट में paste करें।

### Built-in apps

| App | यह क्या है |
|---|---|
| **Agent Chat** | एजेंट से बात करें; स्ट्रीमिंग, टूल कार्ड, अप्रूवल, वॉइस, इमेज paste |
| **Applications** | हर इंस्टॉल किया गया डेस्कटॉप ऐप — उन्हें लॉन्च करें, या नए इंस्टॉल करें |
| **Remote Desktop** | मशीन की असली स्क्रीन, क्लिक करने योग्य, यहाँ से या एक फ़ोन से |
| **Host Screen** | असली डिस्प्ले का एक रिफ़्रेश होता स्थिर चित्र, native ऐप विंडो सहित |
| **Web** | URL आपके **असली सिस्टम ब्राउज़र** में खोलता है (पूरी साइटें, logins, extensions) |
| **Files** | workspace ब्राउज़ करें; एक फ़ाइल पर क्लिक करके उसे अपने host ब्राउज़र/ऐप में खोलें |
| **Terminal** | एक असली host शेल (PTY पर xterm.js), sandbox फ़ोल्डर में जेल किया गया |
| **App Studio** | एक ऐप को सादी भाषा में बताएँ और एजेंट **उसे लाइव बनाता है** |
| **Task Manager** | लाइव CPU/memory/disk, प्रोसेस, खुली विंडो (और कौन-सी सो रही हैं) |
| **Knowledge Graph** | एजेंट क्या जानता है, एक लाइव force-directed graph के रूप में |
| **Soul** | एजेंट की स्थायी पहचान/व्यक्तित्व (हर टर्न इंजेक्ट किया गया) |
| **Memory** | auto-learn + semantic recall के साथ यूज़र और सेशन मेमोरी |
| **Profile** | एजेंट आपके बारे में जो कुछ जानता है, सब एक जगह |
| **Team** | subagents और विज़ुअल workflows (हर स्टेप पर मॉडल मिक्स करें) + observability |
| **Docs** | यह मैनुअल, OS के अंदर |
| **Automations** | नामित routines, hot corners, और step builder |
| **Skills** | पुन: प्रयोज्य प्रक्रियाएँ; एक git repo या एक raw `.md` URL से इंस्टॉल करें |
| **MCP Servers** | एक catalog से बाहरी टूल सर्वर कनेक्ट करें |
| **Telegram** | अपने फ़ोन से एजेंट को नियंत्रित करें; per-chat allow-list |
| **Policies** | टूल और कमांड के लिए always-allow / always-deny नियम |
| **Logs** | सिस्टम ने जो कुछ किया (टर्न, टूल, MCP, telegram, जॉब) |
| **Scheduler** | आवर्ती background **जॉब** |
| **Snapshots** | पूरे OS के लिए restore points (config, data, और source) |
| **Settings** | providers, मॉडल, autonomy, वॉइस, sandbox, एजेंट का नाम |

---

## एजेंट क्या कर सकता है

एजेंट (डिफ़ॉल्ट नाम **Aria**) के पास एक बड़ा टूलसेट है और वह चैट या
Telegram से पूरे OS को चला सकता है:

- **मशीन पर कार्रवाई करें** — शेल कमांड चलाएँ, फ़ाइलें पढ़ें/लिखें, वेब fetch करें, host पर ऐप/फ़ाइलें
  खोलें, डेस्कटॉप नोटिफ़िकेशन।
- **परिणाम पहुँचाएँ** — `save_report` एक styled HTML रिपोर्ट लिखता है जो Files में दिखती है और आपके
  ब्राउज़र में खुलती है, और एक summary Telegram को भेज सकता है। एजेंट को **काम पूरा करने** के लिए कहा जाता है — रिसर्च को
  एक वास्तविक deliverable में बदलना, एक search के बाद रुक न जाना।
- **OS बनाएँ** — `create_app` एक डेस्कटॉप आइकन के साथ नए UI ऐप बनाता है; `pin_widget` उन्हें
  डेस्कटॉप पर रखता है; `add_mcp_server` नए टूल चैनल कनेक्ट करता है।
- **बढ़ें** — दो-स्तरीय मेमोरी, एक knowledge graph, `update_soul` — प्लस **auto-learn**: हर टर्न के बाद एक background
  pass अपने आप memories और तथ्य निकालता है।
- **Automate करें** — `schedule_task` headless **जॉब** बनाता है जो एक रिपोर्ट और/या Telegram को deliver करते हैं।
- **खुद को बढ़ाएँ** — `read_source` / `develop_agentos` इसे Bento का **अपना सोर्स कोड** बदलने देते हैं;
  यह पहले auto-snapshot करता है और लिखने से पहले syntax-check करता है।

सादी भाषा में पूछें: *"github MCP चैनल जोड़ो", "मेरे लिए एक habit tracker बनाओ और उसे desktop
2 पर pin करो", "हर सुबह मेरे Telegram पर social-media trends रिपोर्ट करो", "inkscape इंस्टॉल करो".*

---

## Models और providers

- **Ollama** (local) — auto-discovered; कुछ भी आपकी मशीन से बाहर नहीं जाता।
- **Anthropic**, **OpenAI**, **OpenRouter**, या कोई भी **OpenAI-compatible** endpoint (LM Studio, vLLM,
  Groq, …)।
- **Image generation** — key सेट होने पर Google Gemini या OpenAI image मॉडल, अन्यथा मुफ़्त
  fallback।

`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` और `GOOGLE_API_KEY` अपने आप उठा लिए जाते हैं।
चैट विंडो के dropdown से मॉडल बीच में ही स्विच करें।

---

## सुरक्षा

- **Autonomy स्तर** — Paranoid / Balanced read-only क्रियाओं को auto-run करते हैं और सिस्टम को संशोधित करने वाली
  किसी भी चीज़ से पहले पूछते हैं; Full सब कुछ चलाता है। विनाशकारी कमांड हर स्तर पर **हार्ड-ब्लॉक** होती हैं।
- **Policies** — always-allow / always-deny नियम (`*` wildcards के साथ) जो
  `<tool> <command>` के विरुद्ध मिलाए जाते हैं।
- **फ़ोल्डर sandbox** — bubblewrap के साथ, एजेंट के शेल/फ़ाइल टूल और Terminal एक फ़ोल्डर में जेल
  किए जाते हैं; बाकी filesystem read-only होता है।
- **Snapshots** — restore points; एजेंट अपना खुद का कोड संपादित करने से पहले auto-snapshot करता है।
- **डिफ़ॉल्ट रूप से प्राइवेट** — `127.0.0.1` से बँधता है। Remote access तब तक बंद रहता है जब तक आप इसे एक
  passphrase के साथ चालू न करें, और सॉफ़्टवेयर इंस्टॉल करना मशीन खुद के अलावा कहीं से भी अस्वीकार किया जाता है।

---

## Telegram · MCP · Programmable

**Telegram** — @BotFather को संदेश करें, token को Telegram ऐप में paste करें, और पहला निजी चैट
owner बन जाता है। एजेंट के पास वहाँ अपने सभी टूल होते हैं; जोखिम भरी क्रियाएँ inline Allow/Deny बटन भेजती हैं।

**MCP सर्वर** — catalog से बाहरी टूल सर्वर जोड़ें (Playwright, filesystem, fetch, git,
GitHub, Postgres, Slack, search, …) या एक कस्टम `stdio`/`http` सर्वर। उनके टूल एजेंट को
`mcp_<server>_<tool>` के रूप में दिखते हैं, और बनाए गए ऐप को `POST /api/tool` के ज़रिए।

**Programmable** — एक-शॉट रन के लिए `bento ask "…"`; एक REST API (`POST /api/chat`, `GET /api/system`,
`POST /api/tool`, …); `/ws` पर WebSockets (स्ट्रीमिंग चैट + अप्रूवल) और `/ws/terminal` (host PTY)।
जो ऐप आप बनाते हैं वे एक same-origin iframe में चलते हैं और इस सब को कॉल कर सकते हैं।

---

## Architecture

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

**State `~/.agentos/` में रहता है:** `config.json`, SQLite डेटाबेस, `soul.md`, `wallpapers/`,
`snapshots/`। एजेंट की working directory `~/AgentOS/` है।

### नाम के बारे में

प्रोडक्ट **Bento Box AI** है। Python package, data directory और systemd यूनिट अभी भी
`agentos` हैं — जानबूझकर। इन्हें rename करना हर मौजूदा install की सर्विस, config और
स्क्रिप्ट को तोड़ देता है, और यूज़र को कुछ नहीं देता जो वे देख सकें। वे तब चलेंगे जब कोई migration चलाने लायक
होगा, उससे पहले नहीं। नाम और मार्क हमारे हैं उसी तरह जैसे Ubuntu के Canonical के हैं: कोड को MIT के तहत
आज़ादी से fork करें, इसे अपने खुद के नाम के तहत ship करें। [Licensing और trademarks →](../licensing.md)

---

*Bento Box AI क्लाउड AI असिस्टेंट का एक खुला, local-first विकल्प है: एक एजेंटिक OS, AI डेस्कटॉप,
और automation प्लेटफ़ॉर्म जिसे आप खुद चलाते हैं — Linux, macOS, या Windows पर।*
