# 语音：听和说

两个方向是**两件不同的事**，配置、依赖、失败原因都不一样：

| 方向 | 做什么 | 入口 |
|---|---|---|
| **入站** | QQ 语音条 → 文字，再转给模型 | 桥的「语音转写」+ 一条外部命令 |
| **出站** | 模型决定说一句语音 → 合成 → QQ 语音条 | 工具 `qq_voice`（本仓库补丁） |

---

## 一、入站：QQ 语音条 → 文字

上游已经把路铺好了：桥自己不带模型，只负责把音频落成文件，交给**你指定的命令**；
命令读 `{file}`、往 stdout 打一行文字就行。仓库里的 `vendor/dsh-qq-bridge/tools/asr_cli.py`
是其中一种接法（sherpa-onnx + SenseVoice）。

### 本机的装法（Python 3.14 太新，sherpa-onnx 没有 wheel）

用 `uv` 建一个 Python 3.12 的独立环境，再装依赖：

```bash
uv venv --seed --python 3.12 ~/.dsh/qq-bridge-asr/.venv
uv pip install --python ~/.dsh/qq-bridge-asr/.venv/bin/python \
  sherpa-onnx numpy edge-tts
```

模型只下 int8 的两个文件（约 230 MB），不要下那个 999 MB 的 tar.bz2：

```bash
MODEL=~/.dsh/qq-bridge-asr/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
mkdir -p "$MODEL"
curl -L -o "$MODEL/model.int8.onnx" \
  https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/model.int8.onnx
curl -L -o "$MODEL/tokens.txt" \
  https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/tokens.txt
```

在 `~/.dsh/qq-bridge-config.json` 里填（路径换成本机的）：

```json
{
  "语音转写": true,
  "语音模型目录": "/home/<user>/.dsh/qq-bridge-asr/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
  "转写命令": "\"/home/<user>/.dsh/qq-bridge-asr/.venv/bin/python\" \"/path/to/vendor/dsh-qq-bridge/tools/asr_cli.py\" \"{file}\" --模型目录 \"/home/<user>/.dsh/qq-bridge-asr/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17\"",
  "转写超时秒": 60
}
```

> `转写命令` 里**必须有 `{file}`**，桥会把落下来的音频路径替换进去。
> 命令走 `sh -c`，带空格 / 引号的路径要自己加引号。

### 落音频的两条路

`lib/host.js` 的 `语音落文件()` 先问 NapCat 的 `get_record` 要 wav（它能解 silk）；
拿不到就下载 `data.file` 里的 URL，再用本机 `ffmpeg` 转成 16 kHz 单声道 wav。
所以 `ffmpeg` 在 PATH 里就行。

### 实测

- 用 edge-tts 合成一句中文 → ffmpeg 转 16k wav → `asr_cli.py`，**1.2 秒**转完（含模型加载），
  文字基本一致（同音字偶尔会错）。
- 验收看 `~/.dsh/qq-bridge.log`：以前是 `[语音]`，现在会看到 `（语音）<转出来的字>`，
  而且模型会接着这句话回。

---

## 二、出站：文字 → QQ 语音条

上游 `tools/语音/` 那套是 **Windows only**：用 PowerShell 录**系统声音回环**
（把浏览器朗读桥念出来的声音录下来）。Linux 没有这条路，所以自己写。

### 怎么做的

1. **合成**：`tools/qq_tts.py`，用 edge-tts 把文字写成 mp3。
   它跟 `asr_cli.py` 的约定正好相反：**文字从 stdin 读**，音频写到 `--out`。
   这样桥 `spawn(解释器, [脚本, ...])` 时不用过 shell，引号 / 空格 / emoji 都不会把命令弄坏。
2. **发出去**：OneBot 的 `record` 段。**不需要自己转 silk** ——
   NapCat 4.18.38 的 `createValidSendPttElement()` 会先 `isSilk()`，
   不是 silk 就用自己的 ffmpeg 转成 `ntsilk_s16le`（`convertToNTSilkTct`）再上传。
   mp3 / wav 都能直接交，NapCat 自己转。
3. **什么时候发**：做成工具 `qq_voice`，**不自动把每条回复都念出来**。
   群里连发语音条很吵，QQ 对语音也有风控。工具描述里写死了「只在有人让你唱/念、
   或者非要用语气才到位时用」。另外三道限制：
   - 只在**被 QQ 消息叫醒的那一轮**能用（自己在 DSH 里打字不会误发）；
   - **一次回复最多一条**；
   - **整个 QQ 号 30 秒冷却**（可配 `语音冷却秒`）。
   - ⚠（`[本地补丁 2026-11-03]`）工具描述里补了一句**语音说什么**：语音**不是把正文念一遍**，
     正文说事、语音说语气（正文「行吧」→ 语音「真拿你没办法」）。在这之前模型就是原样念正文，
     用户的原话是「和发出去的文字完全一样，那样没有意义」。
   另有「偶尔主动发」的补充（`[本地补丁 2026-11-02]`）：`主动语音概率`（0–100，**默认 0**）
   打开后，每一轮**QQ 叫醒、没有图、净文字 ≤ `主动语音最多字`** 的回复按这个百分比
   **额外**念一条语音（文字照发）。它和 `qq_voice` 共用 30 秒冷却和「一轮一条」，
   刚用工具发过语音的轮次不会再额外发。
   ⚠ 这条路念的是**这一轮回复的正文**（`[本地补丁 2026-11-03]` 改成只取清洗后的第一句，
   去掉 markdown / 括号旁白 / 表情）—— 内容仍然来自正文，所以**本机设为 0（关）**：
   要主动出声就走 `qq_voice`，让模型自己写一句和正文不同的话。
   另加 `主动语音冷却秒`（默认 600）：只压「自己主动念」，被点名的语音不受它影响。
4. **发送兜底**：`file://绝对路径` → 原始绝对路径 → `base64://`，哪个先成功用哪个
   （NapCat 各版本对 `file` 的认法不完全一样）。

### 配置

| 键 | 默认 | 说明 |
|---|---|---|
| `允许发语音` | `true` | 总闸；关掉后 `qq_voice` 只回一句「闸关着」 |
| `语音音色` | `zh-CN-XiaoyiNeural` | edge-tts 音色名 |
| `语音语速` | `-4%` | edge-tts `--rate`。默认比原速慢一点 —— 原速念中文像播报 |
| `语音音调` | `+2Hz` | edge-tts `--pitch`。抬一点点更像人说话；填 `+0Hz` 回到原样 |
| `语音合成命令` | 空 | 想换别的 TTS 才填；命令按空白切参数，`{out}` 是输出文件，文字走 stdin |
| `语音冷却秒` | `30` | 两次语音之间至少隔多久 |
| `主动语音概率` | `0` | 0 = 不主动发；>0 = 按百分比额外念一条**正文**（只对短文字、无图）。本机设 0 |
| `主动语音最多字` | `60` | 超过这个长度就不主动念 |
| `主动语音冷却秒` | `600` | 只管「自己主动念」的冷却，不拖慢被点名的语音 |

### 验收（还没做完的那一步）

需要一条**真实的 QQ 消息**来验证 `record` 段：
在群里（或私聊）发一句「用语音说给我听」/「唱一句」，看她会不会调 `qq_voice`。
成功的标志：

```bash
grep '发了条语音' ~/.dsh/qq-bridge.log
```

失败会写 `发语音没成功：{retcode...}` 或 `语音合成失败：...`。

---

## 三、唱歌：DiffSinger（本地真唱）

**edge-tts 唱不了歌**：它只有整句的语速/音调，没有音符级的音高和时长。
CosyVoice 2 的论文也明确写了唱歌表现不好。真唱要上专门的 SVS —— 这里用
[DiffSinger](https://github.com/openvpi/DiffSinger) + [`diffsinger-utau`](https://github.com/bingcheng1998/diffsinger_utau)（MIT）
的推理管线，外加一个 OpenUTAU 格式的中文声库。

### 装环境

```bash
uv venv --seed --python 3.12 ~/.dsh/qq-sing/.venv
uv pip install --python ~/.dsh/qq-sing/.venv/bin/python diffsinger-utau
```

> `diffsinger-utau` 会拉 torch。推理模型是 ONNX，默认 CPU；6GB 显存的机器够用，
> 短句一般十几秒。第一次调用要加载声库，会慢一点。

### 声库

需要一个 OpenUTAU 格式的 DiffSinger 声库目录（里面有 `dsconfig.yaml`）。
本机用的是 ACG 社区声库（`aihobbyist/ACG-DiffSinger-VoiceDB`，CC-BY-NC-4.0，
**仅供个人二次创作，不可商用**）：

```bash
mkdir -p ~/.dsh/qq-sing/voicebanks
# 从 ModelScope 下某个角色的 zip，解压到 ~/.dsh/qq-sing/voicebanks/<名字>/
```

声库训练音频的版权属于对应游戏公司；不要把声库提交进仓库，也不要商用。

### 生成一首短歌

`vendor/dsh-qq-bridge/tools/qq_sing.py` 把「歌词 + 曲调」拼成 `.ds`
（歌词从 stdin 读，音频写到 `--out`），再跑 DiffSinger：

```bash
# 用曲目名（会带曲目自己的 BPM）
echo "两只老虎两只老虎跑得快" | ~/.dsh/qq-sing/.venv/bin/python \
  vendor/dsh-qq-bridge/tools/qq_sing.py \
  --voice-bank ~/.dsh/qq-sing/voicebanks/hutao \
  --out /tmp/sing.wav --song 两只老虎

# 或者直接给简谱（模型知道某首歌的谱时走这条最灵活）
echo "一闪一闪亮晶晶满天都是小星星" | ~/.dsh/qq-sing/.venv/bin/python \
  vendor/dsh-qq-bridge/tools/qq_sing.py \
  --voice-bank ~/.dsh/qq-sing/voicebanks/hutao \
  --out /tmp/sing.wav \
  --notation '1 1 5 5 6 6 5 4 4 3 3 2 2 1'
```

内置曲目：`小星星`（完整两句）/ `小星星副歌`（只有第二句）/ `两只老虎` /
`生日快乐` / `铃儿响叮当` / `找朋友` / `自由`。

**简谱写法**：`1-7`（C4-B4），高音在数字后加 `’`（如 `1’`），低音加 `,`（如 `5,`），
长音加 `-`（如 `5-`），附点加 `.`（如 `5.`），升降音用 `#4` / `b7`，`|` 和 `，` 当分隔。
音符比歌词多就截、少就循环；休止符 `0` 会被丢掉（不占音节）。

**节奏**：别把所有音都写成 1 拍 —— 句尾拖长（2 拍）、快字用半拍/四分之一拍，
听起来才有「顿挫」，不然就是「文字加音调」。内置曲目已经按这个原则改过；
《爱你》按简谱的十六分/八分音符重排。声学步数 `唱歌步数` 默认 **50**
（上游 CLI 默认；越大越细、越慢，短歌约 7～9 秒；嫌慢可以降到 20）。

**跑调 / 转音**：
- 短音（尤其音程跳进后的快音）DiffSinger 会欠冲，最狠一次到 -85 音分；
  把那个音的时值拉长（0.19s → 0.4～0.6s）就能回到 ±20 音分内。
- `qq_sing.py` 有一个实验性的 `--tune`（rubberband pitchmap 自动校音），
  默认**关** —— 实测能把音高拉回，但咬字会变差（「一定」→「一点」）。
- **一字多音的转音**已支持：`melodies.json` 里写
  `"C5:0.25+G4:0.75"`，表示这个字唱 C5 再滑到 G4；生成 `.ds` 时后续音
  `note_slur=1`。普通一个音就写 `"C5:1"`。
- ⚠ 简谱数字下面的点可能是**低八度**，也可能是**断音/节奏点**。看错八度会整句
  高/低一个八度，听起来就是「跑调」；拿不准就让人哼一遍（见上一节），别猜。

**自己加歌**：写 `~/.dsh/qq-sing/melodies.json`，格式见
`docs/qq-sing-melodies.example.json`；同名会覆盖内置曲目。加完要重启 dsh-web，
桥才会把新歌名列进工具说明。

曲目还可以写 `"lyrics"`：模型偷懒选了 `自由` / 默认小星星时，脚本会按歌词前缀
自动认歌，改用那首歌的调子。本机就是靠这个修掉「点了《爱你》，它却拿老调子糊弄」的：

```json
{
  "爱你": {
    "bpm": 80,
    "notes": ["F4:1", "F4:1", "…"],
    "lyrics": "如果你突然打了个喷嚏那一定就是我在想你"
  }
}
```

> ⚠ 2026-10-31 实测踩过：`小星星` 原来只有第一句的 7 个音，唱「满天都是小星星」时会
> 重复第一句的旋律，用户直接听出来「旋律唱错了」。现在 `小星星` 是完整 14 个音；
> `小星星副歌` 才是单独的第二句。另外，用户反馈「只有一个调」——现在模型可以按歌名
> 选曲目，或者用 `notation` 直接传这首歌的简谱，不再所有歌都套小星星。

### 找谱：让它自己上网找调子（2026-11-01）

用户点了一首不会的歌，它张嘴就是「给我个简谱」—— 用户说
**「应该会自己去网络上找调子才对」**。后来 11-01 夜里又点《无敌》，它**找到了谱**，
但抓回来的是一张**钢琴五线谱**（还没有歌词），只能承认读不了，又回头要简谱 ——
用户直接说「**现在还是没办法，他一定要简谱才能唱**」。

所以问题不是「搜不到」，是**搜回来的东西不对**。找谱这条路做成桥的工具
**`qq_find_score`**（脚本 `tools/qq_score.py`）：

```
搜狗 → 360 → 必应 搜「歌名 简谱」  →  解析 /link 那层跳转拿真地址  →  谱子站优先
    →  打开页面抠谱子图  →  验尺寸 / 验「像不像谱子」 / **剔掉五线谱**
    →  塞进下一轮消息里让模型自己看，或直接给文字谱
```

为什么用 Python 写脚本：谱子站（jianpu.cn 等）页面常见 **GBK**，Node 没有内置 GBK 编解码。

| 站点 | 能不能取到谱 | 说明 |
|---|---|---|
| 苍强曲谱 `cangqiang.com.cn` | ✅✅ | 最好：**带歌词的 C 调简谱**，数字、八度点、歌词、`♩=` 速度都清楚 |
| 歌谱简谱网 `jianpu.cn` | ✅ | 谱子在 `div#jianpu` 的 `<img>` 里；**但同一站也放钢琴五线谱**，得靠筛 |
| 虫虫钢琴 `gangqinpu.com`、弹琴吧 `tan8.com` | ❌ | 库最全、但谱子是 JS 异步加载的，HTML 里只有 logo（抠到过一张 YJ Music） |
| 「简谱库」`jp114.com` 之类 | ❌ | SEO 垃圾站：页面里塞的是图库**照片**（抠到过一张弹吉他的人物照） |
| 简谱网 / 曲谱网 / 51曲谱… | ❌ | 这台机器**直连不通**（连不上，不是 403） |

踩过的坑，都写进脚本注释了：

- **搜索会被拦**：搜狗连着搜十几次就跳 `/antispider/` 验证码页。旧代码把它当成
  「没搜到」，于是机器人跟人说「网上没有」—— 现在是**显式识别**，换 360、再换必应，
  并把真实原因带回去；搜狗被拦后 15 分钟内直接跳过它（`~/.dsh/qq-sing/sogou-blocked`）。
- **五线谱要按像素筛掉**：五线谱的谱线横贯整页，简谱只有数字底下很短的减时线。
  900px 归一化后数「半页宽以上的长横线」：苍强简谱 0~2 行、无敌钢琴五线谱 94 行，
  阈值取 20。见 `是五线谱()`。**这是这次的关键修补**。
- **还得挡「不像谱子」的图**：光验尺寸不够 —— 人物照有 500×500，照样能过。
  谱子是白底黑字、几乎无彩色：实测真谱白底 ≥0.82 / 彩色 0.00，人物照白底 ≤0.50 / 彩色 ≥0.20。
  见 `像谱子()`（需要 Pillow，装在 `~/.dsh/qq-sing/.venv` 里）。
- **Referer 不能乱给**：搜狗那个 Referer 会让图床 403（苍强的谱子图就是这么丢的），
  要按目标站自己的域名给。
- **必须验图片尺寸**：谱子站旁边全是 logo / 图标，抠 `src` 会把它们一起抠出来 ——
  实测抠回过一张 64×64 的站标。现在宽高都 < 480 的一律当 logo 丢掉。
- **图床缩略参数要剥掉**：虫虫钢琴的图带 `?x-oss-process=image/resize,h_300`。
- **同名歌很多**：搜「无敌」会拿到另一首同名的军旅合唱谱；`--song "无敌 邓超"` 才准，
  工具说明里也写了让模型先核对歌手/词曲作者。

```bash
# 看搜出来什么（不下载）
~/.dsh/qq-sing/.venv/bin/python vendor/dsh-qq-bridge/tools/qq_score.py --song "孤勇者" --list
# 找并下载谱子图
~/.dsh/qq-sing/.venv/bin/python vendor/dsh-qq-bridge/tools/qq_score.py --song "无敌 邓超"
# 这张不对，换下一个来源
~/.dsh/qq-sing/.venv/bin/python vendor/dsh-qq-bridge/tools/qq_score.py --song "无敌 邓超" --skip <上次的页面地址>
```

实测：`孤勇者` → 苍强曲谱的两页 C 调简谱（1140×1611，数字、八度点、歌词都清楚）；
`起风了`、`晴天 周杰伦` 也能取到简谱；`无敌 邓超` 网上只有钢琴五线谱，
**会自动挡掉并如实说「只找到五线谱」**（不是假装没搜到）。

**取到图之后呢**：桥把谱子图**当成一条普通消息塞回会话**（`转入一条` + 图片段，
走的就是收 QQ 图片那条路），下一轮模型就能看见这张谱；提示词要求它**只转写要唱的那一两句**
（`qq_sing` 一次最多 30 字），写成 `notation` 唱，并给 `qq_sing` 传 `save=true` ——
`qq_sing.py --save-song` 会把这次的简谱记进 `melodies.json`（带 `.bak` 备份），
**下次点同一首歌直接唱**。看不清就带 `skip` 再找一次换一张。
**它读不准就别硬编** —— 上一轮《爱你》就是照着看不清的谱猜八度，改了三版越改越不对。

### 学歌：让人哼一遍（2026-11-01）

「不同的歌要唱不同的调」这件事，卡在**调子从哪来**。模型凭记忆写简谱、或者从网上
抄一张看不清的简谱，都出过错 —— 《爱你》就是照着一张小图猜八度，改了三版越改越不对。
有把握的只有一个来源：**人的声音**。让人哼一遍，音高直接从录音里量，不用会看谱。

- 有人发一条**哼唱的语音条**，说「教你唱《X》」；
- 模型调 `qq_learn_song`（`song` = 歌名，可选 `lyrics` / `bpm`）；
- 桥把这条语音交给 `tools/qq_hum.py`，量出音高 + 时值 → 写进
  `~/.dsh/qq-sing/melodies.json`（同名覆盖，先备份 `.bak`）→ 接着 `qq_sing` 唱一遍。

`qq_hum.py` 单独也能跑：

```bash
~/.dsh/qq-sing/.venv/bin/python vendor/dsh-qq-bridge/tools/qq_hum.py \
  --in hum.wav --song 孤勇者 --lyrics 都是勇敢的 --save
# 只量不存：去掉 --save，结果以 JSON 打在 stdout
```

每一步都是踩坑踩出来的：

| 做法 | 为什么 |
|---|---|
| pyin 取音高，再做 5 帧中值滤波 | pyin 在音与音之间会冒出一两个假音高 |
| 偏离要**连续持续几帧**才认新音 | 一帧就换会把每个音前后的滑音切成假音（实测 14 个音被切成 34 个） |
| 音量坑（±150ms 内比旁边低一半）也算断点 | 「一闪一闪」这种**同音高连着两个字**，只有音量坑能把它们分开 |
| 时值按「前后两段的中点」算 | pyin 窗约 90ms，交界处两头都不认，直接量会短一截（0.6 秒量成 0.3 秒） |
| 丢掉「又短、音高又夹在前后两音中间」的段 | 那是滑过去的过渡，不是音 |
| 整体挪八度（不动音程）到 A3–A4 | 哼低了直接唱出来像大叔 |
| 段内音高标准差 > 0.45 半音就警告 | 实测哼唱 0.09～0.30、说话 0.57～0.60 —— 录进去的是说话就提醒重哼 |

实测（合成的哼唱，100 BPM 的《小星星》）：量出 14 个音，**音高和节奏全对**；
低八度哼的会先归位再量，也对；换成朗读音频会给出「听着更像说话」的警告。

> ⚠ 拿不准某首歌的八度时**别再猜**：要么让人哼一遍走这条路，要么让人给一份八度标清楚的简谱。


原理：`.ds` 里 `ph_num` 把音素切成「词」，`note_seq` 给每个词一个音高，
`note_dur` 给每个词一个时长；DiffSinger 依次预测时长、音高、方差、声学、声码器。
`tools/qq_sing.py` 负责把歌词拼音化、查 opencpop 音素表、按 `Phome` 规则分组。

### 点歌与严格模式

桥会从**这一轮 QQ 原文**里抓歌名：`唱《X》` / `唱一首X` / `来一首X` / `点一首X`。
抓到之后会**覆盖模型选的 `song`**（模型再选「自由」也没用）。然后：

- 歌在曲目表里 → 用那首歌的调子；
- 不在曲目表 → **先调 `qq_find_score` 自己去网上找谱**（见上一节）；找到数字谱就用它，
  只找到谱子图就让模型看图写 `notation`，并带 `save=true` 记进曲目表；
- 找到了但不确认是不是这首歌（同名歌）、或者什么都没找到 → 直说「这首没学会」，
  **不再拿小星星/自由随便套**。

**硬规矩：不许回头跟人要简谱**。这条写进了 `qq_sing` 和 `qq_find_score` 的工具说明、
每轮的点歌提示、以及「不认识的旋律」那句报错里。2026-11-01 它连着两次把活推回给人
（「你要能弄到 1234567 那种简谱，我立马唱」），用户就是为这个发火的。

群里**任何人**点歌都可以唱，不是只有主人/老爹；这条写在工具说明和每轮的点歌提示里。
歌名从原文里抓（`唱《X》` / `唱一首X` / `来一首X` / `点一首X`）；抓的时候会掐掉
「胜利的歌」「就唱」这类**不是歌名**的句子（2026-11-01：它们被抓成歌名之后工具找不到调子，
直接回「这首唱不出来」，用户看到的就是「点了歌它不会」）。

想让一首新歌能唱，按顺序试：

1. **它自己找**（默认路径）：`qq_find_score` 联网找简谱，模型看图转 `notation`，
   唱完 `save=true` 存下来 —— 之后这首歌就是**直接唱**了；
2. 加 `~/.dsh/qq-sing/melodies.json`（最好带 `lyrics`，能按歌词自动认歌）；
3. **让人哼一遍** → `qq_learn_song`（网上确实没有这首时才用，别当默认）；
4. 模型凭记忆写 `notation`（出错率高，只当兜底）。

### 接进 QQ

桥里的工具是 `qq_sing`（配置键 `允许唱歌` / `唱歌解释器` / `唱歌声库` / `唱歌旋律` / `唱歌步数`）。
工具参数：`text` 歌词、`song` 曲目名、`notation` 简谱、`bpm` 可选速度、
`save`（把这个 `notation` 记进 `melodies.json`，靠 `qq_sing.py --save-song`）。
模型会优先用 `notation`（这样点哪首歌就唱哪首），其次 `song` 曲目表，最后 `song="自由"`。

⚠ `save` 只在**歌名是点出来的、或模型明确传了 `song`** 时才落库（`[本地补丁 2026-11-02]`）。
以前歌名会退回 `唱歌旋律` 的默认值（小星星），照《晴天》的谱唱完却存成「小星星」，
把内置曲目覆盖成半句 —— 2026-11-02 00:57 真实发生过，已修。
它和 `qq_voice` 共用冷却和「一次回复最多一条」。歌出来后还是走 OneBot 的 `record` 段，
NapCat 会转 silk，跟普通语音没有区别。学歌的 `qq_learn_song` 只写曲目表、不发消息，
所以不吃冷却 —— 学完可以紧接着唱。

```bash
grep '唱了一句' ~/.dsh/qq-bridge.log        # 唱成功
grep '学了首歌' ~/.dsh/qq-bridge.log        # 学歌成功（带音数/音域/BPM）
grep '找谱' ~/.dsh/qq-bridge.log            # 找谱成功/失败（带页面地址）
```

---

## 四、说话也用唱歌声库的音色（F5-TTS 零样本克隆，可选）

> **本机结论（2026-10-31）**：试过，但参考音是用 DiffSinger 唱出来的（带唱腔），
> 克隆出来「不自然」，用户最终决定说话先用 edge-tts 的小艺，胡桃只唱歌。
> 要再试，必须用**真实说话**的 5～12 秒干净音频 + 逐字文本当参考。
> 下面的安装步骤保留，方便以后换参考音再跑。

DiffSinger 只能唱，不能自然朗读；如果希望**说话和唱歌同一个音色**，用 F5-TTS 的
零样本克隆：给一段参考音频 + 对应文本，它就能用那个音色说任意话。

### 参考音频

用 DiffSinger 的 `说话` 旋律（音高起伏很小）生成一段参考音，保证音色就是声库的：

```bash
mkdir -p ~/.dsh/qq-clone
printf '你好呀我是小肥鱼今天也一起玩吧' | ~/.dsh/qq-sing/.venv/bin/python \
  vendor/dsh-qq-bridge/tools/qq_sing.py \
  --voice-bank ~/.dsh/qq-sing/voicebanks/hutao \
  --out ~/.dsh/qq-clone/ref.wav --melody 说话 --bpm 150
printf '你好呀我是小肥鱼今天也一起玩吧' > ~/.dsh/qq-clone/ref.txt
```

> 也可以换成真实的人声（5～12 秒干净录音 + 逐字文本）；DiffSinger 生成的参考音
> 可能带一点唱腔，F5-TTS 会跟着学。

### 装 F5-TTS

```bash
uv venv --seed --python 3.12 ~/.dsh/qq-clone/.venv
uv pip install --python ~/.dsh/qq-clone/.venv/bin/python torch torchaudio
uv pip install --python ~/.dsh/qq-clone/.venv/bin/python f5-tts
```

> F5-TTS 的权重是 **CC-BY-NC**（非商用）。第一次调用会从 HuggingFace 下
> `F5TTS_v1_Base` + `vocos`，共约 1.4GB；之后走缓存。
> 6GB 显存够用；不够就把 `QQ_CLONE_DEVICE=cpu`（慢很多）。

### 命令行 / 接桥

`tools/qq_clone_tts.py` 读 stdin 文字，用 `~/.dsh/qq-clone/ref.wav` + `ref.txt` 出 mp3：

```bash
echo "哼，笨蛋，才不是特意说给你听的。" | \
  ~/.dsh/qq-clone/.venv/bin/python vendor/dsh-qq-bridge/tools/qq_clone_tts.py \
  --out /tmp/clone.mp3
```

接进桥不用改代码，只要把 `语音合成命令` 填成：

```
/home/<user>/.dsh/qq-clone/.venv/bin/python /path/to/vendor/dsh-qq-bridge/tools/qq_clone_tts.py --out {out}
```

并把 `语音合成超时秒` 调到 60（F5-TTS 每次起进程要加载模型）。`语音音色` 只在
这条命令留空时才给 edge-tts 用。

---

## 五、坑

- **别让她每条都发语音**。QQ 对语音有风控，群里刷语音条也很烦。工具 + 冷却 + 每轮一条
  就是为这个加的，别为了「更像真人」把这三道去掉。
- **edge-tts 要联网**。断网 / 代理坏掉时 `qq_tts.py` 会非 0 退出，桥会在日志里写
  `语音合成失败`，这一轮退回文字。
- **SenseVoice 同音字**会错（「新做」→「新座」），转进来的文字带 `（语音）` 前缀，
  模型知道这是听写的，别当成群友原话引用。
- 机器人的语音条和文字条共用 NapCat 的发送通道，没有额外风控参数可调。
